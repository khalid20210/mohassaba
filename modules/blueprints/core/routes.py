"""
blueprints/core/routes.py — الصفحات الأساسية: dashboard، analytics، onboarding، settings،
                             recycle_bin، reminders، backup، stub
"""
import io
import json
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from flask import (
    Blueprint, flash, g, jsonify, redirect, render_template,
    request, send_file, send_from_directory, session, url_for
)

from modules.config import (
    ALLOWED_LOGO_EXT, BASE_DIR, INDUSTRY_TYPES,
    LOGO_FOLDER, STUB_PAGES, PLATFORM_NAME, SAAS_REGION,
    FLASK_ENV, DB_PATH, HEALTH_DB_TIMEOUT_MS, IS_PROD,
    REDIS_REQUIRED, QUEUE_REQUIRED
)
from modules.extensions import (
    csrf_protect, get_db, seed_business_accounts, hash_password
)
from modules.industry_seeds import seed_industry_defaults
from modules.middleware import (
    login_required, onboarding_required, require_perm, user_has_perm,
    owner_required, write_audit_log
)
from modules.terminology import get_terms
from modules.unit_localization import ensure_unit_localization_defaults
from modules.runtime_services import (
    get_redis_client,
    queue_health_status,
    get_redis_error,
)

bp = Blueprint("core", __name__)

LOGO_FOLDER.mkdir(exist_ok=True)


def _column_exists(db, table: str, column: str) -> bool:
    """تحقق خفيف من وجود عمود قبل استخدامه في الاستعلامات الديناميكية."""
    try:
        rows = db.execute(f"PRAGMA table_info({table})").fetchall()
        return any(r[1] == column for r in rows)
    except Exception:
        return False


@bp.route("/healthz")
def healthz():
    """فحص حياة الخدمة (للمراقبة و load balancer)."""
    redis_status = "disabled"
    redis_client = get_redis_client()
    if redis_client is not None:
        try:
            redis_client.ping()
            redis_status = "ok"
        except Exception as exc:
            redis_status = f"error: {exc}"
    elif get_redis_error():
        redis_status = f"disabled: {get_redis_error()}"

    return jsonify({
        "status": "ok",
        "platform": PLATFORM_NAME,
        "region": SAAS_REGION,
        "env": FLASK_ENV,
        "redis": redis_status,
        "queue": queue_health_status(),
        "time": datetime.now().isoformat(timespec="seconds"),
    }), 200


@bp.route("/monitoring")
def monitoring_dashboard():
    """لوحة مراقبة الأداء الحية."""
    return render_template("monitoring_dashboard.html")


@bp.route("/metrics")
@owner_required
def metrics_endpoint():
    """مؤشرات الأداء للمراقبة (Prometheus-style)."""
    from modules.observability import metrics
    return jsonify({
        "metrics": metrics.get_metrics_summary(),
        "region": SAAS_REGION,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }), 200


@bp.route("/diagnostics")
@owner_required
def diagnostics():
    """معلومات التشخيص الكاملة للنظام."""
    db = get_db()
    from modules.observability import metrics
    
    try:
        db_info = {
            "path": str(DB_PATH),
            "size_kb": int(DB_PATH.stat().st_size / 1024) if DB_PATH.exists() else 0,
        }
        
        table_counts = {}
        for table in ["businesses", "users", "invoices", "products", "contacts"]:
            try:
                cnt = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                table_counts[table] = cnt
            except:
                pass
        
        return jsonify({
            "platform": PLATFORM_NAME,
            "region": SAAS_REGION,
            "env": FLASK_ENV,
            "database": db_info,
            "runtime": {
                "redis": "ok" if get_redis_client() else "disabled",
                "queue": queue_health_status(),
            },
            "tables": table_counts,
            "metrics_summary": metrics.get_metrics_summary(),
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }), 200
    except Exception as e:
        return jsonify({
            "error": str(e),
            "request_id": getattr(g, "request_id", "unknown"),
        }), 500


@bp.route("/readyz")
def readyz():
    """فحص الجاهزية: يتحقق من جودة الخدمة الكاملة."""
    db = get_db()
    started = datetime.now()
    checks = {"db": None, "tables": None, "migrations": None, "redis": None, "queue": None}
    
    try:
        db.execute("SELECT 1").fetchone()
        checks["db"] = "ok"
    except Exception as e:
        checks["db"] = str(e)
    
    try:
        tables = db.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
        checks["tables"] = f"{tables} tables"
    except Exception as e:
        checks["tables"] = str(e)
    
    try:
        migrations = db.execute(
            "SELECT COUNT(*) FROM _schema_migrations"
        ).fetchone()[0]
        checks["migrations"] = f"{migrations} applied"
    except Exception as e:
        checks["migrations"] = str(e)

    try:
        redis_client = get_redis_client()
        if redis_client is None:
            checks["redis"] = "disabled"
        else:
            redis_client.ping()
            checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = str(e)

    try:
        checks["queue"] = queue_health_status()
    except Exception as e:
        checks["queue"] = str(e)
    
    elapsed_ms = int((datetime.now() - started).total_seconds() * 1000)
    ready = checks.get("db") == "ok"

    # Redis/Queue اختيارية إلا إذا كانت مفعلة وفاشلة
    redis_state = str(checks.get("redis") or "")
    queue_state = str(checks.get("queue") or "")
    if redis_state.startswith("error"):
        ready = False
    if queue_state.startswith("error"):
        ready = False
    if REDIS_REQUIRED and redis_state == "disabled":
        ready = False
    if QUEUE_REQUIRED and queue_state == "disabled":
        ready = False

    status = 200 if ready else 503
    
    return jsonify({
        "status": "ready" if ready else "degraded",
        "checks": checks,
        "ping_ms": elapsed_ms,
        "region": SAAS_REGION,
        "env": FLASK_ENV,
    }), status


# ─── Dynamic KPIs مخصصة حسب القطاع ──────────────────────────────────────────
def _get_industry_kpis(db, biz_id: int, industry_type: str, since30: str) -> dict:
    """
    يُعيد KPIs مخصصة حسب pos_mode كل قطاع.
    يُستدعى من dashboard فقط.
    """
    terms    = get_terms(industry_type)
    pos_mode = terms.get("pos_mode", "standard")
    kpis     = {}

    if pos_mode == "restaurant":
        # متوسط قيمة الطلب + أكثر الطاولات مبيعاً
        avg = db.execute("""
            SELECT ROUND(AVG(total), 2) AS avg_order,
                   COUNT(*) AS orders_count,
                   ROUND(SUM(total), 2) AS total_rev
            FROM invoices
            WHERE business_id=? AND invoice_type='table' AND status='paid'
              AND DATE(created_at) >= ?
        """, (biz_id, since30)).fetchone()
        top_tables = db.execute("""
            SELECT party_name, COUNT(*) AS visits, ROUND(SUM(total),2) AS revenue
            FROM invoices
            WHERE business_id=? AND invoice_type='table' AND status='paid'
              AND DATE(created_at) >= ?
            GROUP BY party_name ORDER BY revenue DESC LIMIT 5
        """, (biz_id, since30)).fetchall()
        top_dishes = db.execute("""
            SELECT il.description, SUM(il.quantity) AS qty, ROUND(SUM(il.total),2) AS rev
            FROM invoice_lines il
            JOIN invoices i ON i.id = il.invoice_id
            WHERE i.business_id=? AND i.invoice_type='table' AND i.status='paid'
              AND DATE(i.created_at) >= ?
            GROUP BY il.description ORDER BY qty DESC LIMIT 5
        """, (biz_id, since30)).fetchall()
        kpis["avg_order_value"]  = float(avg["avg_order"] or 0)
        kpis["orders_count"]     = int(avg["orders_count"] or 0)
        kpis["total_restaurant_rev"] = float(avg["total_rev"] or 0)
        kpis["top_tables"]       = [dict(r) for r in top_tables]
        kpis["top_dishes"]       = [dict(r) for r in top_dishes]

    elif pos_mode == "pharmacy":
        # الأدوية الأكثر صرفاً + قرب انتهاء الصلاحية
        top_drugs = db.execute("""
            SELECT il.description, SUM(il.quantity) AS qty, ROUND(SUM(il.total),2) AS rev
            FROM invoice_lines il
            JOIN invoices i ON i.id = il.invoice_id
            WHERE i.business_id=? AND i.status='paid' AND DATE(i.created_at) >= ?
            GROUP BY il.description ORDER BY qty DESC LIMIT 10
        """, (biz_id, since30)).fetchall()
        expiry_soon = []
        if _column_exists(db, "products", "expiry_date"):
            expiry_soon = db.execute("""
                SELECT name, barcode, expiry_date,
                       COALESCE((SELECT SUM(s.quantity) FROM stock s WHERE s.product_id=p.id), 0) AS qty
                FROM products p
                WHERE business_id=? AND is_active=1
                  AND expiry_date IS NOT NULL
                  AND DATE(expiry_date) <= DATE('now', '+30 days')
                  AND DATE(expiry_date) >= DATE('now')
                ORDER BY expiry_date ASC LIMIT 10
            """, (biz_id,)).fetchall()
        kpis["top_drugs"]    = [dict(r) for r in top_drugs]
        kpis["expiry_soon"]  = [dict(r) for r in expiry_soon]

    elif pos_mode == "construction":
        # الفواتير المفتوحة (ديون المشاريع) + أكبر العملاء
        open_invoices = db.execute("""
            SELECT invoice_number, party_name, total, invoice_date
            FROM invoices
            WHERE business_id=? AND status IN ('draft','pending')
              AND invoice_type = 'sale'
            ORDER BY total DESC LIMIT 10
        """, (biz_id,)).fetchall()
        top_clients = db.execute("""
            SELECT party_name,
                   COUNT(*) AS projects,
                   ROUND(SUM(total), 2) AS contracted_value,
                   ROUND(SUM(CASE WHEN status='paid' THEN total ELSE 0 END),2) AS collected
            FROM invoices
            WHERE business_id=? AND invoice_type='sale'
              AND DATE(created_at) >= ?
            GROUP BY party_name ORDER BY contracted_value DESC LIMIT 5
        """, (biz_id, since30)).fetchall()
        total_open = db.execute("""
            SELECT COALESCE(SUM(total),0) AS open_total
            FROM invoices WHERE business_id=? AND status IN ('draft','pending')
        """, (biz_id,)).fetchone()
        kpis["open_invoices"]  = [dict(r) for r in open_invoices]
        kpis["top_clients"]    = [dict(r) for r in top_clients]
        kpis["total_open_debt"]= float(total_open["open_total"] or 0)

    elif pos_mode == "wholesale":
        # أكبر موزعين + حجم الشحنات + ديون متأخرة
        top_distributors = db.execute("""
            SELECT party_name, COUNT(*) AS orders, ROUND(SUM(total),2) AS volume
            FROM invoices
            WHERE business_id=? AND invoice_type='sale' AND status='paid'
              AND DATE(created_at) >= ?
            GROUP BY party_name ORDER BY volume DESC LIMIT 5
        """, (biz_id, since30)).fetchall()
        pending_purchases = db.execute("""
            SELECT COUNT(*) AS cnt, COALESCE(SUM(total),0) AS total
            FROM invoices WHERE business_id=? AND invoice_type='purchase'
              AND status='pending'
        """, (biz_id,)).fetchone()
        # ديون الموزعين المتأخرة (تاريخ الاستحقاق تجاوز اليوم)
        overdue_debts = db.execute("""
            SELECT party_name, party_id, invoice_number, 
                   ROUND(total - COALESCE(paid_amount,0), 2) AS outstanding,
                   due_date, CAST((julianday('now') - julianday(due_date)) AS INTEGER) AS days_overdue
            FROM invoices
            WHERE business_id=? AND invoice_type='sale' AND status='pending'
              AND due_date IS NOT NULL AND DATE(due_date) < DATE('now')
            ORDER BY due_date ASC LIMIT 10
        """, (biz_id,)).fetchall()
        # أصناف منخفضة المخزون للموزعين
        low_stock_wholesale = db.execute("""
            SELECT pi.sku, ROUND(pi.current_qty, 3) AS current_qty, ROUND(pi.min_qty, 3) AS min_qty,
                   ROUND(pi.max_qty, 3) AS max_qty, p.name AS product_name
            FROM product_inventory pi
            LEFT JOIN products p ON p.id = pi.product_id AND p.business_id = pi.business_id
            WHERE pi.business_id=? AND pi.current_qty <= pi.min_qty * 1.5
            ORDER BY (pi.min_qty - pi.current_qty) DESC LIMIT 8
        """, (biz_id,)).fetchall()
        kpis["top_distributors"]    = [dict(r) for r in top_distributors]
        kpis["pending_purchase_cnt"]= int(pending_purchases["cnt"] or 0)
        kpis["pending_purchase_val"]= float(pending_purchases["total"] or 0)
        kpis["overdue_debts"]       = [dict(r) for r in overdue_debts]
        kpis["low_stock_wholesale"] = [dict(r) for r in low_stock_wholesale]

    elif pos_mode in ("workshop", "rental"):
        # الأوامر المفتوحة + أكثر الخدمات مبيعاً
        open_orders = db.execute("""
            SELECT invoice_number, party_name, total, invoice_date, status
            FROM invoices
            WHERE business_id=? AND status IN ('draft','pending')
            ORDER BY created_at DESC LIMIT 10
        """, (biz_id,)).fetchall()
        top_services = db.execute("""
            SELECT il.description, SUM(il.quantity) AS cnt, ROUND(SUM(il.total),2) AS rev
            FROM invoice_lines il
            JOIN invoices i ON i.id = il.invoice_id
            WHERE i.business_id=? AND i.status='paid' AND DATE(i.created_at) >= ?
            GROUP BY il.description ORDER BY cnt DESC LIMIT 5
        """, (biz_id, since30)).fetchall()
        kpis["open_orders"]   = [dict(r) for r in open_orders]
        kpis["top_services"]  = [dict(r) for r in top_services]

    # retail (+ standard / fashion / medical / default) → أفضل 10 منتجات + معدل دوران + أصناف بطيئة
    else:
        # أفضل 10 منتجات
        top_products = db.execute("""
            SELECT il.description, SUM(il.quantity) AS qty, ROUND(SUM(il.total),2) AS rev
            FROM invoice_lines il
            JOIN invoices i ON i.id = il.invoice_id
            WHERE i.business_id=? AND i.invoice_type='sale' AND i.status='paid'
              AND DATE(i.created_at) >= ?
            GROUP BY il.description ORDER BY rev DESC LIMIT 10
        """, (biz_id, since30)).fetchall()
        new_customers = db.execute("""
            SELECT COUNT(*) AS cnt FROM contacts
                        WHERE business_id=? AND contact_type='customer'
              AND DATE(created_at) >= ?
        """, (biz_id, since30)).fetchone()
        # أفضل المبيعات اليوم
        today_sales = db.execute("""
            SELECT il.description, SUM(il.quantity) AS qty, ROUND(SUM(il.total),2) AS rev
            FROM invoice_lines il
            JOIN invoices i ON i.id = il.invoice_id
            WHERE i.business_id=? AND i.invoice_type='sale' AND i.status='paid'
              AND DATE(i.created_at) = DATE('now')
            GROUP BY il.description ORDER BY rev DESC LIMIT 5
        """, (biz_id,)).fetchall()
        # معدل دوران المخزون (تقديري): مبيعات 30 يوم / متوسط المخزون
        avg_stock = db.execute("""
            SELECT COALESCE(SUM(current_qty), 0) AS avg_qty FROM product_inventory
            WHERE business_id=?
        """, (biz_id,)).fetchone()
        sales_30d = db.execute("""
            SELECT COALESCE(SUM(total), 0) AS total FROM invoices
            WHERE business_id=? AND invoice_type='sale' AND status='paid'
              AND DATE(created_at) >= ?
        """, (biz_id, since30)).fetchone()
        # الأصناف البطيئة (لم تُباع في 30 يوم)
        slow_moving = db.execute("""
            SELECT pr.name AS product_name, pi.sku, ROUND(pi.current_qty, 2) AS qty,
                   ROUND(pi.unit_cost * pi.current_qty, 2) AS stock_value
            FROM product_inventory pi
            JOIN products pr ON pr.id = pi.product_id
            WHERE pi.business_id=? AND pi.current_qty > 0
              AND pi.sku NOT IN (
                  SELECT DISTINCT p.barcode FROM invoice_lines il
                  JOIN invoices i ON i.id = il.invoice_id
                  JOIN products p ON p.name = il.description
                  WHERE i.business_id=? AND i.invoice_type='sale' AND i.status='paid'
                    AND DATE(i.created_at) >= ?
              )
            ORDER BY pi.current_qty DESC LIMIT 8
        """, (biz_id, biz_id, since30)).fetchall()
        kpis["top_products"]     = [dict(r) for r in top_products]
        kpis["new_customers"]    = int(new_customers["cnt"] or 0) if new_customers else 0
        kpis["today_sales"]      = [dict(r) for r in today_sales]
        kpis["slow_moving"]      = [dict(r) for r in slow_moving]
        kpis["inventory_turnover"]= float(sales_30d["total"] or 0) / float(avg_stock["avg_qty"] or 1)

    kpis["pos_mode"] = pos_mode
    kpis["industry_icon"]  = terms.get("industry_icon", "🏪")
    kpis["industry_label"] = terms.get("industry_label", "نشاط تجاري")
    return kpis


@bp.route("/dashboard")
@onboarding_required
def dashboard():
    db     = get_db()
    biz_id = session["business_id"]

    stats = {
        "products": db.execute("SELECT COUNT(*) FROM products WHERE business_id=?", (biz_id,)).fetchone()[0],
        "contacts": db.execute("SELECT COUNT(*) FROM contacts  WHERE business_id=?", (biz_id,)).fetchone()[0],
        "journals": db.execute("SELECT COUNT(*) FROM journal_entries WHERE business_id=?", (biz_id,)).fetchone()[0],
        "accounts": db.execute("SELECT COUNT(*) FROM accounts  WHERE business_id=?", (biz_id,)).fetchone()[0],
    }

    today   = datetime.now().strftime("%Y-%m-%d")
    since7  = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    since30 = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    daily_sales = db.execute("""
        SELECT DATE(created_at) AS day, COALESCE(SUM(total),0) AS rev
        FROM invoices
        WHERE business_id=? AND invoice_type IN ('sale','table')
          AND status='paid' AND DATE(created_at) >= ?
        GROUP BY DATE(created_at) ORDER BY day
    """, (biz_id, since7)).fetchall()

    top5 = db.execute("""
        SELECT il.description, SUM(il.quantity) AS qty
        FROM invoice_lines il
        JOIN invoices i ON i.id = il.invoice_id
        WHERE i.business_id=? AND i.invoice_type IN ('sale','table')
          AND i.status='paid' AND DATE(i.created_at) >= ?
        GROUP BY il.description ORDER BY qty DESC LIMIT 5
    """, (biz_id, since30)).fetchall()

    dashboard_totals = db.execute("""
        SELECT
          COALESCE(SUM(CASE WHEN invoice_type IN ('sale','table') AND status='paid' AND DATE(invoice_date)=? THEN total ELSE 0 END),0) AS sales_today,
          COALESCE(SUM(CASE WHEN invoice_type='purchase' AND status IN ('paid','partial') AND DATE(invoice_date) >= ? THEN total ELSE 0 END),0) AS purchases_30d,
          COUNT(CASE WHEN DATE(invoice_date) >= ? THEN 1 END) AS invoices_30d
        FROM invoices
        WHERE business_id=?
    """, (today, since30, since30, biz_id)).fetchone()

    profit_today = db.execute("""
        SELECT
          COALESCE(SUM(CASE WHEN a.code='4101' THEN jel.credit ELSE 0 END),0) AS revenue_today,
          COALESCE(SUM(CASE WHEN a.code='5101' THEN jel.debit ELSE 0 END),0) AS cogs_today
        FROM journal_entry_lines jel
        JOIN journal_entries je ON je.id = jel.entry_id
        JOIN accounts a ON a.id = jel.account_id
        WHERE a.business_id=? AND DATE(je.entry_date)=?
    """, (biz_id, today)).fetchone()

    rev_exp = db.execute("""
        SELECT
          COALESCE(SUM(CASE WHEN invoice_type IN ('sale','table') AND status='paid' THEN total ELSE 0 END),0) AS revenue,
          COALESCE(SUM(CASE WHEN invoice_type='purchase'          AND status='paid' THEN total ELSE 0 END),0) AS expenses
        FROM invoices WHERE business_id=? AND DATE(created_at) >= ?
    """, (biz_id, since30)).fetchone()

    dashboard_metrics = {
        "net_profit_today": int(round(float((profit_today["revenue_today"] if profit_today else 0) - (profit_today["cogs_today"] if profit_today else 0)))),
        "sales_today": int(round(float(dashboard_totals["sales_today"] if dashboard_totals else 0))),
        "purchases_30d": int(round(float(dashboard_totals["purchases_30d"] if dashboard_totals else 0))),
        "invoices_30d": int(dashboard_totals["invoices_30d"] if dashboard_totals else 0),
    }

    last_entries = db.execute("""
        SELECT je.entry_number, je.entry_date, je.description,
               COALESCE(SUM(CASE WHEN jel.debit>0 THEN jel.debit ELSE 0 END),0) AS total_debit
        FROM journal_entries je
        LEFT JOIN journal_entry_lines jel ON jel.entry_id = je.id
        WHERE je.business_id=?
        GROUP BY je.id ORDER BY je.entry_date DESC, je.id DESC LIMIT 5
    """, (biz_id,)).fetchall()

    chart_daily  = json.dumps({"labels": [r["day"] for r in daily_sales],
                                "values": [float(r["rev"]) for r in daily_sales]}, ensure_ascii=False)
    chart_top5   = json.dumps({"labels": [r["description"] for r in top5],
                                "values": [float(r["qty"]) for r in top5]}, ensure_ascii=False)
    chart_revexp = json.dumps({"revenue": float(rev_exp["revenue"] if rev_exp else 0),
                                "expenses": float(rev_exp["expenses"] if rev_exp else 0)}, ensure_ascii=False)

    stock_alerts = []
    reorder_suggestions = []
    if user_has_perm("reports") or user_has_perm("warehouse"):
        stock_alerts = db.execute("""
            SELECT p.name AS product_name, p.barcode AS sku, p.min_stock,
                   COALESCE(SUM(s.quantity), 0) AS total_qty,
                   w.name AS warehouse_name
            FROM products p
            JOIN stock s ON s.product_id = p.id
            JOIN warehouses w ON w.id = s.warehouse_id
            WHERE p.business_id=? AND p.min_stock > 0 AND s.quantity <= p.min_stock
            GROUP BY p.id
            ORDER BY (COALESCE(SUM(s.quantity),0) - p.min_stock) ASC
            LIMIT 15
        """, (biz_id,)).fetchall()
        stock_alerts = [dict(r) for r in stock_alerts]
        
        # اقتراحات إعادة الطلب من نظام المخزون التجزئي
        reorder_suggestions = db.execute("""
            SELECT id, sku, barcode, current_qty, min_qty, max_qty
            FROM product_inventory
            WHERE business_id=? AND min_qty > 0 AND current_qty <= min_qty
            ORDER BY (min_qty - current_qty) DESC, sku ASC
            LIMIT 10
        """, (biz_id,)).fetchall()
        reorder_suggestions = [dict(r) for r in reorder_suggestions]

    # ── Dynamic KPIs مخصصة حسب قطاع المنشأة ─────────────────────────────────
    biz          = g.business
    industry_type= biz["industry_type"] if biz else "retail_other"
    industry_kpis= _get_industry_kpis(db, biz_id, industry_type, since30)

    return render_template(
        "dashboard.html",
        stats=stats,
        dashboard_metrics=dashboard_metrics,
        last_entries=[dict(r) for r in last_entries],
        chart_daily=chart_daily,
        chart_top5=chart_top5,
        chart_revexp=chart_revexp,
        stock_alerts=stock_alerts,
        reorder_suggestions=reorder_suggestions,
        industry_kpis=industry_kpis,
    )


@bp.route("/analytics")
@require_perm("analytics")
def analytics():
    db     = get_db()
    biz_id = session["business_id"]
    period = request.args.get("period", "30")
    try:
        days = int(period)
    except ValueError:
        days = 30

    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    totals = db.execute("""
        SELECT
          COALESCE(SUM(CASE WHEN invoice_type IN ('sale','table') AND status='paid' THEN total ELSE 0 END),0) AS revenue,
          COALESCE(SUM(CASE WHEN invoice_type='purchase' AND status='paid' THEN total ELSE 0 END),0) AS purchases,
          COUNT(DISTINCT CASE WHEN invoice_type IN ('sale','table') AND status='paid' THEN id END) AS invoices_count
        FROM invoices
        WHERE business_id=? AND DATE(created_at) >= ?
    """, (biz_id, since)).fetchone()

    top_products = db.execute("""
        SELECT il.description, SUM(il.quantity) AS total_qty, SUM(il.total) AS total_rev
        FROM invoice_lines il
        JOIN invoices i ON i.id = il.invoice_id
        WHERE i.business_id=? AND i.invoice_type IN ('sale','table')
          AND i.status='paid' AND DATE(i.created_at) >= ?
        GROUP BY il.description ORDER BY total_qty DESC LIMIT 10
    """, (biz_id, since)).fetchall()

    daily = db.execute("""
        SELECT DATE(created_at) AS day, SUM(total) AS revenue
        FROM invoices
        WHERE business_id=? AND invoice_type IN ('sale','table')
          AND status='paid' AND DATE(created_at) >= ?
        GROUP BY DATE(created_at) ORDER BY day ASC
    """, (biz_id, since)).fetchall()

    by_category = db.execute("""
        SELECT p.category_name, SUM(il.total) AS total_rev
        FROM invoice_lines il
        JOIN invoices i ON i.id = il.invoice_id
                JOIN products p ON p.id = il.product_id AND p.business_id = i.business_id
        WHERE i.business_id=? AND i.invoice_type IN ('sale','table')
          AND i.status='paid' AND DATE(i.created_at) >= ?
        GROUP BY p.category_name ORDER BY total_rev DESC LIMIT 8
    """, (biz_id, since)).fetchall()

    return render_template(
        "analytics.html",
        period=str(days),
        totals=dict(totals),
        top_products=[dict(r) for r in top_products],
        chart_daily=json.dumps({"labels": [r["day"] for r in daily],
                                 "values": [float(r["revenue"]) for r in daily]}, ensure_ascii=False),
        chart_cat=json.dumps({"labels": [r["category_name"] or "غير محدد" for r in by_category],
                               "values": [float(r["total_rev"]) for r in by_category]}, ensure_ascii=False),
        chart_top=json.dumps({"labels": [r["description"] for r in top_products],
                               "values": [float(r["total_qty"]) for r in top_products]}, ensure_ascii=False),
    )


@bp.route("/onboarding", methods=["GET", "POST"])
@login_required
def onboarding():
    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard

        biz_name      = request.form.get("business_name",  "").strip()
        industry_type = request.form.get("industry_type",  "retail_other").strip()
        tax_number    = request.form.get("tax_number",      "").strip()
        city          = request.form.get("city",            "").strip()

        if not biz_name:
            flash("اسم المنشأة مطلوب", "error")
            return render_template("onboarding.html")

        valid_types = [t[0] for t in INDUSTRY_TYPES]
        if industry_type not in valid_types:
            # تطبيع أكواد الـ onboarding الجديدة إلى أنواع صالحة
            if industry_type.startswith("svc_"):
                industry_type = "services"
            elif industry_type.startswith("con_"):
                industry_type = "construction"
            elif industry_type.startswith("mfg_"):
                industry_type = "services"
            elif industry_type.startswith("hos_cafe"):
                industry_type = "food_cafe"
            elif industry_type.startswith("hos_"):
                industry_type = "food_restaurant"
            elif industry_type.startswith("hlt_"):
                industry_type = "medical"
            elif industry_type.startswith("lgx_"):
                industry_type = "services"
            elif industry_type.startswith("retail_"):
                industry_type = "retail"
            elif industry_type.startswith("wholesale_"):
                industry_type = "wholesale"
            else:
                flash("الرجاء اختيار نشاط صحيح من القائمة لإتمام التهيئة.", "error")
                return render_template("onboarding.html")

        industry_labels = {k: v for k, v in INDUSTRY_TYPES}
        industry_label = industry_labels.get(industry_type, industry_type)

        db     = get_db()
        biz_id = session["business_id"]
        country_row = db.execute("SELECT country_code FROM businesses WHERE id=?", (biz_id,)).fetchone()
        country_code = (country_row["country_code"] if country_row and country_row["country_code"] else "SA")

        try:
            db.execute(
                """UPDATE businesses
                   SET name=?, industry_type=?, tax_number=?, city=?,
                       is_active=1, updated_at=datetime('now')
                   WHERE id=?""",
                (biz_name, industry_type, tax_number, city, biz_id)
            )
            db.execute(
                "INSERT OR IGNORE INTO warehouses (business_id, name, is_default) VALUES (?,?,1)",
                (biz_id, "المستودع الرئيسي")
            )
            seed_business_accounts(db, biz_id)
            seed_summary = seed_industry_defaults(db, biz_id, industry_type)
            ensure_unit_localization_defaults(db, int(biz_id), country_code=country_code)
            db.execute(
                "INSERT OR IGNORE INTO settings (business_id, key, value) VALUES (?,?,?)",
                (biz_id, "onboarding_complete", "1")
            )
            db.commit()
        except Exception:
            db.rollback()
            flash("حدث خطأ أثناء إنشاء المنشأة — يرجى المحاولة مرة أخرى", "error")
            return render_template("onboarding.html")
        session.pop("needs_onboarding", None)
        flash(
            (
                f"تم تهيئة نشاط «{industry_label}» بنجاح: "
                f"{seed_summary.get('categories_inserted', 0)} تصنيف جديد، "
                f"{seed_summary.get('products_inserted', 0)} منتج جديد."
            ),
            "success",
        )
        flash(f"مرحباً! تم إنشاء منشأة «{biz_name}» بنجاح ✓", "success")
        return redirect(url_for("core.dashboard"))

    return render_template("onboarding.html")


@bp.route("/settings", methods=["GET", "POST"])
@require_perm("settings")
def settings():
    db     = get_db()
    biz_id = session["business_id"]
    can_edit_business = bool(user_has_perm("all") or user_has_perm("business_profile_edit"))
    can_skip_reason   = bool(user_has_perm("all") or user_has_perm("business_profile_reason_optional"))

    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard

        if not can_edit_business:
            flash("ليس لديك صلاحية تعديل بيانات المنشأة", "error")
            return redirect(url_for("core.settings"))

        name       = request.form.get("business_name",  "").strip()
        tax_number = request.form.get("tax_number",     "").strip()
        phone      = request.form.get("phone",          "").strip()
        email      = request.form.get("email",          "").strip()
        address    = request.form.get("address",        "").strip()
        city       = request.form.get("city",           "").strip()
        cr_number  = request.form.get("cr_number",      "").strip()
        currency   = request.form.get("currency",       "SAR")
        inv_prefix = request.form.get("invoice_prefix", "INV").strip()
        change_reason = request.form.get("change_reason", "").strip()

        if (not can_skip_reason) and (not change_reason):
            flash("سبب التعديل إلزامي حسب الصلاحيات", "error")
            return redirect(url_for("core.settings"))

        if not name:
            flash("اسم المنشأة مطلوب", "error")
            return redirect(url_for("core.settings"))

        logo_path = None
        old_biz = db.execute("SELECT * FROM businesses WHERE id=?", (biz_id,)).fetchone()
        old_inv_prefix = db.execute(
            "SELECT value FROM settings WHERE business_id=? AND key='invoice_prefix_sale'",
            (biz_id,)
        ).fetchone()

        if "logo" in request.files:
            logo_file = request.files["logo"]
            if logo_file and logo_file.filename:
                ext = logo_file.filename.rsplit(".", 1)[-1].lower()
                if ext in ALLOWED_LOGO_EXT:
                    safe_name = f"logo_{biz_id}.{ext}"
                    logo_file.save(LOGO_FOLDER / safe_name)
                    logo_path = f"/static/logos/{safe_name}"

        if logo_path:
            try:
                db.execute(
                    """UPDATE businesses
                       SET name=?, tax_number=?, phone=?, email=?, address=?, city=?,
                           cr_number=?, currency=?, logo_path=?, updated_at=datetime('now')
                       WHERE id=?""",
                    (name, tax_number, phone, email, address, city,
                     cr_number, currency, logo_path, biz_id)
                )
                db.execute(
                    "INSERT OR REPLACE INTO settings (business_id, key, value) VALUES (?,?,?)",
                    (biz_id, "invoice_prefix_sale", inv_prefix or "INV")
                )
                new_biz = db.execute("SELECT * FROM businesses WHERE id=?", (biz_id,)).fetchone()
                write_audit_log(
                    db, biz_id, "business_profile_updated",
                    entity_type="business", entity_id=biz_id,
                    old_value=json.dumps({
                        "business": dict(old_biz) if old_biz else {},
                        "invoice_prefix": (old_inv_prefix["value"] if old_inv_prefix else "INV"),
                    }, ensure_ascii=False),
                    new_value=json.dumps({
                        "reason": change_reason,
                        "business": dict(new_biz) if new_biz else {},
                        "invoice_prefix": (inv_prefix or "INV"),
                    }, ensure_ascii=False)
                )
                db.commit()
            except Exception:
                db.rollback()
                flash("حدث خطأ أثناء حفظ الإعدادات", "error")
                return redirect(url_for("core.settings"))
        else:
            try:
                db.execute(
                    """UPDATE businesses
                       SET name=?, tax_number=?, phone=?, email=?, address=?, city=?,
                           cr_number=?, currency=?, updated_at=datetime('now')
                       WHERE id=?""",
                    (name, tax_number, phone, email, address, city,
                     cr_number, currency, biz_id)
                )
                db.execute(
                    "INSERT OR REPLACE INTO settings (business_id, key, value) VALUES (?,?,?)",
                    (biz_id, "invoice_prefix_sale", inv_prefix or "INV")
                )
                new_biz = db.execute("SELECT * FROM businesses WHERE id=?", (biz_id,)).fetchone()
                write_audit_log(
                    db, biz_id, "business_profile_updated",
                    entity_type="business", entity_id=biz_id,
                    old_value=json.dumps({
                        "business": dict(old_biz) if old_biz else {},
                        "invoice_prefix": (old_inv_prefix["value"] if old_inv_prefix else "INV"),
                    }, ensure_ascii=False),
                    new_value=json.dumps({
                        "reason": change_reason,
                        "business": dict(new_biz) if new_biz else {},
                        "invoice_prefix": (inv_prefix or "INV"),
                    }, ensure_ascii=False)
                )
                db.commit()
            except Exception:
                db.rollback()
                flash("حدث خطأ أثناء حفظ الإعدادات", "error")
                return redirect(url_for("core.settings"))
        g.business = db.execute("SELECT * FROM businesses WHERE id=?", (biz_id,)).fetchone()
        flash("✅ تم حفظ الإعدادات بنجاح", "success")
        return redirect(url_for("core.settings"))

    biz        = db.execute("SELECT * FROM businesses WHERE id=?", (biz_id,)).fetchone()
    inv_prefix = db.execute(
        "SELECT value FROM settings WHERE business_id=? AND key='invoice_prefix_sale'",
        (biz_id,)
    ).fetchone()

    return render_template(
        "settings.html",
        biz=dict(biz) if biz else {},
        inv_prefix=inv_prefix["value"] if inv_prefix else "INV",
        can_edit_business=can_edit_business,
        can_skip_reason=can_skip_reason,
    )


@bp.route("/offline")
def offline():
    return render_template("offline.html")


# ─── Team Management ──────────────────────────────────────────────────────────

# الصلاحيات المتاحة في النظام مع تسمياتها
PERM_LABELS = {
    "sales":      "المبيعات والفواتير",
    "purchases":  "المشتريات",
    "warehouse":  "المخزون والباركود",
    "contacts":   "العملاء والموردين",
    "pos":        "نقطة البيع",
    "accounting": "المحاسبة والقيود",
    "reports":    "التقارير",
    "analytics":  "تحليل المبيعات",
    "settings":   "الإعدادات",
    "invoice_edit":            "تعديل الفواتير بعد الحفظ",
    "invoice_cancel":          "إلغاء الفواتير",
    "invoice_delete":          "حذف الفواتير (المسودات فقط)",
    "invoice_reason_optional": "السماح بدون سبب (تعديل/حذف/إلغاء)",
    "business_profile_edit":            "تعديل بيانات المنشأة",
    "business_profile_reason_optional": "السماح بدون سبب (تعديل بيانات المنشأة)",
}


@bp.route("/team")
@owner_required
def team():
    db     = get_db()
    biz_id = session["business_id"]
    roles  = db.execute(
        "SELECT * FROM roles WHERE business_id=? ORDER BY name", (biz_id,)
    ).fetchall()
    members = db.execute(
        """SELECT u.id, u.full_name, u.username, u.phone, u.is_active,
                  u.last_login, r.name AS role_name, r.permissions AS role_perms
           FROM users u
           LEFT JOIN roles r ON r.id = u.role_id
           WHERE u.business_id=?
           ORDER BY u.full_name""",
        (biz_id,)
    ).fetchall()
    return render_template(
        "team.html",
        roles=[dict(r) for r in roles],
        members=[dict(m) for m in members],
        perm_labels=PERM_LABELS,
        csrf_token=session.get("csrf_token", ""),
    )


# ── API: قائمة الأعضاء ────────────────────────────────────────────────────────
@bp.route("/api/v1/team", methods=["GET"])
@owner_required
def api_team_list():
    db     = get_db()
    biz_id = session["business_id"]
    rows = db.execute(
        """SELECT u.id, u.full_name, u.username, u.phone, u.is_active,
                  u.last_login, r.id AS role_id, r.name AS role_name,
                  r.permissions AS role_perms
           FROM users u
           LEFT JOIN roles r ON r.id = u.role_id
           WHERE u.business_id=?
           ORDER BY u.full_name""",
        (biz_id,)
    ).fetchall()
    return jsonify([dict(r) for r in rows])


# ── API: إضافة عضو جديد ───────────────────────────────────────────────────────
@bp.route("/api/v1/team", methods=["POST"])
@owner_required
def api_team_add():
    db     = get_db()
    biz_id = session["business_id"]
    data   = request.get_json(silent=True) or {}

    full_name = (data.get("full_name") or "").strip()
    username  = (data.get("username")  or "").strip()
    password  = (data.get("password")  or "").strip()
    phone     = (data.get("phone")     or "").strip()
    role_id   = data.get("role_id")

    if not full_name or not username or not password:
        return jsonify({"error": "الاسم واسم المستخدم وكلمة المرور مطلوبة"}), 400
    if len(password) < 6:
        return jsonify({"error": "كلمة المرور يجب أن تكون 6 أحرف على الأقل"}), 400

    existing = db.execute(
        "SELECT id FROM users WHERE business_id=? AND username=?", (biz_id, username)
    ).fetchone()
    if existing:
        return jsonify({"error": "اسم المستخدم موجود مسبقاً"}), 409

    # التحقق أن role_id تابع لنفس المنشأة
    if role_id:
        role_row = db.execute(
            "SELECT id FROM roles WHERE id=? AND business_id=?", (role_id, biz_id)
        ).fetchone()
        if not role_row:
            role_id = None

    # إذا لم يُعطَ role_id، ننشئ دوراً مؤقتاً بدون صلاحيات
    if not role_id:
        db.execute(
            "INSERT INTO roles (business_id, name, permissions) VALUES (?,?,?)",
            (biz_id, f"دور {full_name}", "{}")
        )
        db.commit()
        role_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    pw_hash = hash_password(password)
    try:
        db.execute(
            """INSERT INTO users (business_id, role_id, username, full_name, phone, password_hash)
               VALUES (?,?,?,?,?,?)""",
            (biz_id, role_id, username, full_name, phone, pw_hash)
        )
        db.commit()
        new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        return jsonify({"success": True, "id": new_id})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500


# ── API: تعديل بيانات عضو ────────────────────────────────────────────────────
@bp.route("/api/v1/team/<int:user_id>", methods=["PUT"])
@owner_required
def api_team_update(user_id: int):
    db     = get_db()
    biz_id = session["business_id"]

    row = db.execute(
        "SELECT id FROM users WHERE id=? AND business_id=?", (user_id, biz_id)
    ).fetchone()
    if not row:
        return jsonify({"error": "المستخدم غير موجود"}), 404

    data      = request.get_json(silent=True) or {}
    full_name = (data.get("full_name") or "").strip()
    phone     = (data.get("phone")     or "").strip()
    role_id   = data.get("role_id")
    is_active = int(bool(data.get("is_active", True)))
    new_pw    = (data.get("password") or "").strip()

    if not full_name:
        return jsonify({"error": "الاسم مطلوب"}), 400

    if role_id:
        role_row = db.execute(
            "SELECT id FROM roles WHERE id=? AND business_id=?", (role_id, biz_id)
        ).fetchone()
        if not role_row:
            role_id = None

    if new_pw:
        if len(new_pw) < 6:
            return jsonify({"error": "كلمة المرور يجب أن تكون 6 أحرف على الأقل"}), 400
        pw_hash = hash_password(new_pw)
        db.execute(
            "UPDATE users SET full_name=?, phone=?, role_id=?, is_active=?, password_hash=? WHERE id=?",
            (full_name, phone, role_id, is_active, pw_hash, user_id)
        )
    else:
        db.execute(
            "UPDATE users SET full_name=?, phone=?, role_id=?, is_active=? WHERE id=?",
            (full_name, phone, role_id, is_active, user_id)
        )
    db.commit()
    return jsonify({"success": True})


# ── API: تغيير صلاحيات مستخدم مباشرة (بدون تغيير الدور) ──────────────────────
@bp.route("/api/v1/team/<int:user_id>/permissions", methods=["POST"])
@owner_required
def api_team_user_perms(user_id: int):
    db     = get_db()
    biz_id = session["business_id"]

    row = db.execute(
        "SELECT u.role_id FROM users u WHERE u.id=? AND u.business_id=?",
        (user_id, biz_id)
    ).fetchone()
    if not row:
        return jsonify({"error": "المستخدم غير موجود"}), 404

    data    = request.get_json(silent=True) or {}
    perms   = {k: bool(v) for k, v in data.items() if k in PERM_LABELS}
    perms_j = json.dumps(perms, ensure_ascii=False)

    role_id = row["role_id"]
    if role_id:
        # تحديث الدور مباشرة إذا كان له دور خاص
        db.execute(
            "UPDATE roles SET permissions=? WHERE id=? AND business_id=?",
            (perms_j, role_id, biz_id)
        )
    else:
        # إنشاء دور جديد خاص بهذا المستخدم
        db.execute(
            "INSERT INTO roles (business_id, name, permissions) VALUES (?,?,?)",
            (biz_id, f"دور مخصص #{user_id}", perms_j)
        )
        db.commit()
        new_role_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("UPDATE users SET role_id=? WHERE id=?", (new_role_id, user_id))
    db.commit()
    return jsonify({"success": True, "permissions": perms})


# ── API: الأدوار ──────────────────────────────────────────────────────────────
@bp.route("/api/v1/roles", methods=["GET"])
@owner_required
def api_roles_list():
    db     = get_db()
    biz_id = session["business_id"]
    rows   = db.execute(
        "SELECT id, name, permissions, is_system FROM roles WHERE business_id=? ORDER BY name",
        (biz_id,)
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.route("/api/v1/roles", methods=["POST"])
@owner_required
def api_roles_create():
    db     = get_db()
    biz_id = session["business_id"]
    data   = request.get_json(silent=True) or {}
    name   = (data.get("name") or "").strip()
    perms  = {k: bool(v) for k, v in data.items() if k in PERM_LABELS}
    if not name:
        return jsonify({"error": "اسم الدور مطلوب"}), 400
    try:
        db.execute(
            "INSERT INTO roles (business_id, name, permissions) VALUES (?,?,?)",
            (biz_id, name, json.dumps(perms, ensure_ascii=False))
        )
        db.commit()
        new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        return jsonify({"success": True, "id": new_id, "name": name, "permissions": perms})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500


@bp.route("/api/v1/roles/<int:role_id>", methods=["PUT"])
@owner_required
def api_roles_update(role_id: int):
    db     = get_db()
    biz_id = session["business_id"]
    row    = db.execute(
        "SELECT id, is_system FROM roles WHERE id=? AND business_id=?", (role_id, biz_id)
    ).fetchone()
    if not row:
        return jsonify({"error": "الدور غير موجود"}), 404

    data  = request.get_json(silent=True) or {}
    name  = (data.get("name") or "").strip()
    perms = {k: bool(v) for k, v in data.items() if k in PERM_LABELS}
    if not name:
        return jsonify({"error": "اسم الدور مطلوب"}), 400
    db.execute(
        "UPDATE roles SET name=?, permissions=? WHERE id=?",
        (name, json.dumps(perms, ensure_ascii=False), role_id)
    )
    db.commit()
    return jsonify({"success": True})


@bp.route("/api/v1/roles/<int:role_id>", methods=["DELETE"])
@owner_required
def api_roles_delete(role_id: int):
    db     = get_db()
    biz_id = session["business_id"]
    row    = db.execute(
        "SELECT id, is_system FROM roles WHERE id=? AND business_id=?", (role_id, biz_id)
    ).fetchone()
    if not row:
        return jsonify({"error": "الدور غير موجود"}), 404
    if row["is_system"]:
        return jsonify({"error": "لا يمكن حذف أدوار النظام"}), 403
    # تحديث المستخدمين المرتبطين بهذا الدور
    db.execute("UPDATE users SET role_id=NULL WHERE role_id=? AND business_id=?", (role_id, biz_id))
    db.execute("DELETE FROM roles WHERE id=?", (role_id,))
    db.commit()
    return jsonify({"success": True})



# ═══════════════════════════════════════════════════════════════════════════════
# ─── سلة المهملات (Recycle Bin) ─────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

def _table_exists(db, table: str) -> bool:
    row = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


@bp.route("/recycle-bin")
@owner_required
def recycle_bin():
    return render_template("recycle_bin.html")


@bp.route("/api/v1/recycle-bin")
@owner_required
def api_recycle_list():
    db     = get_db()
    biz_id = session["business_id"]
    if not _table_exists(db, "recycle_bin"):
        return jsonify({"items": [], "total": 0})

    entity_type = request.args.get("type",  "")
    page        = max(1, int(request.args.get("page", 1)))
    per_page    = 25

    conditions = ["business_id=?", "restored_at IS NULL"]
    params     = [biz_id]
    if entity_type:
        conditions.append("entity_type=?")
        params.append(entity_type)

    where = " AND ".join(conditions)
    where_join = where.replace("business_id", "rb.business_id").replace("restored_at", "rb.restored_at")
    total = db.execute(f"SELECT COUNT(*) FROM recycle_bin WHERE {where}", params).fetchone()[0]
    rows  = db.execute(
        f"""SELECT rb.*, u.full_name AS deleted_by_name
            FROM recycle_bin rb
            LEFT JOIN users u ON u.id = rb.deleted_by
            WHERE {where_join}
            ORDER BY rb.deleted_at DESC
            LIMIT ? OFFSET ?""",
        params + [per_page, (page - 1) * per_page]
    ).fetchall()

    return jsonify({
        "total": total,
        "page":  page,
        "pages": max(1, (total + per_page - 1) // per_page),
        "items": [dict(r) for r in rows],
    })


@bp.route("/api/v1/recycle-bin/<int:item_id>/restore", methods=["POST"])
@owner_required
def api_recycle_restore(item_id: int):
    db     = get_db()
    biz_id = session["business_id"]
    if not _table_exists(db, "recycle_bin"):
        return jsonify({"error": "سلة المهملات غير مهيأة — نفّذ migration 011"}), 500

    row = db.execute(
        "SELECT * FROM recycle_bin WHERE id=? AND business_id=? AND restored_at IS NULL",
        (item_id, biz_id)
    ).fetchone()
    if not row:
        return jsonify({"error": "السجل غير موجود أو تم استرجاعه مسبقاً"}), 404

    user_id = session["user_id"]
    now     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # نحاول استعادة السجل — حالياً نعلّمه "مُستَرجَع" فقط
    # الاستعادة الفعلية تعتمد على entity_type وتحتاج منطقاً خاصاً
    try:
        db.execute(
            "UPDATE recycle_bin SET restored_at=?, restored_by=? WHERE id=?",
            (now, user_id, item_id)
        )
        write_audit_log(
            db, biz_id, "recycle_bin_restore",
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            old_value=None,
            new_value=json.dumps({"item_id": item_id, "label": row["entity_label"]}, ensure_ascii=False),
        )
        db.commit()
        return jsonify({"success": True, "message": f"تم استرجاع {row['entity_label'] or row['entity_type']}"})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500


@bp.route("/api/v1/recycle-bin/<int:item_id>", methods=["DELETE"])
@owner_required
def api_recycle_delete_permanent(item_id: int):
    db     = get_db()
    biz_id = session["business_id"]
    if not _table_exists(db, "recycle_bin"):
        return jsonify({"error": "سلة المهملات غير مهيأة"}), 500

    row = db.execute(
        "SELECT * FROM recycle_bin WHERE id=? AND business_id=?", (item_id, biz_id)
    ).fetchone()
    if not row:
        return jsonify({"error": "السجل غير موجود"}), 404

    try:
        write_audit_log(
            db, biz_id, "recycle_bin_permanent_delete",
            entity_type=row["entity_type"],
            entity_id=row["entity_id"],
            old_value=row["entity_data"],
            new_value=None,
        )
        db.execute("DELETE FROM recycle_bin WHERE id=?", (item_id,))
        db.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════════
# ─── نظام التنبيهات والالتزامات (Reminders) ─────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

REMINDER_TYPES = {
    "tax":              ("📋", "إقرار ضريبي"),
    "insurance":        ("🏥", "تأمين صحي / تجاري"),
    "social_insurance": ("👥", "تأمينات اجتماعية"),
    "installment":      ("💳", "قسط تمويل"),
    "license":          ("📄", "ترخيص / سجل تجاري"),
    "custom":           ("🔔", "تذكير مخصص"),
}


@bp.route("/reminders")
@owner_required
def reminders_page():
    return render_template("reminders.html", reminder_types=REMINDER_TYPES)


@bp.route("/api/v1/reminders")
@owner_required
def api_reminders_list():
    db     = get_db()
    biz_id = session["business_id"]
    if not _table_exists(db, "reminders"):
        return jsonify({"reminders": [], "total": 0})

    show_dismissed = request.args.get("dismissed", "0") == "1"
    page      = max(1, int(request.args.get("page", 1)))
    per_page  = 50

    cond   = "business_id=? AND is_active=1"
    params = [biz_id]
    if not show_dismissed:
        cond += " AND is_dismissed=0"

    total = db.execute(f"SELECT COUNT(*) FROM reminders WHERE {cond}", params).fetchone()[0]
    rows  = db.execute(
        f"SELECT * FROM reminders WHERE {cond} ORDER BY due_date ASC LIMIT ? OFFSET ?",
        params + [per_page, (page - 1) * per_page]
    ).fetchall()
    return jsonify({
        "total":     total,
        "reminders": [dict(r) for r in rows],
    })


@bp.route("/api/v1/reminders/upcoming")
@owner_required
def api_reminders_upcoming():
    """للـ Dashboard — التنبيهات القادمة خلال 30 يوماً"""
    db     = get_db()
    biz_id = session["business_id"]
    if not _table_exists(db, "reminders"):
        return jsonify([])

    in_30 = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    today = datetime.now().strftime("%Y-%m-%d")
    rows  = db.execute(
        """SELECT id, title, reminder_type, due_date, amount,
                  CAST((julianday(due_date) - julianday(?)) AS INTEGER) AS days_left
           FROM reminders
           WHERE business_id=? AND is_active=1 AND is_dismissed=0
             AND due_date >= ? AND due_date <= ?
           ORDER BY due_date ASC
           LIMIT 10""",
        (today, biz_id, today, in_30)
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.route("/api/v1/reminders", methods=["POST"])
@owner_required
def api_reminders_create():
    db     = get_db()
    biz_id = session["business_id"]
    if not _table_exists(db, "reminders"):
        return jsonify({"error": "جدول التنبيهات غير مهيأ — نفّذ migration 011"}), 500

    data     = request.get_json(silent=True) or {}
    title    = (data.get("title")    or "").strip()
    rtype    = (data.get("reminder_type") or "custom").strip()
    due_date = (data.get("due_date") or "").strip()
    amount   = data.get("amount")
    notes    = (data.get("notes")    or "").strip()
    is_recurring    = int(bool(data.get("is_recurring",    False)))
    recurrence_days = data.get("recurrence_days")

    if not title or not due_date:
        return jsonify({"error": "العنوان والتاريخ مطلوبان"}), 400

    if rtype not in REMINDER_TYPES:
        rtype = "custom"

    try:
        db.execute(
            """INSERT INTO reminders
               (business_id, title, reminder_type, due_date, amount, notes,
                is_recurring, recurrence_days, created_by)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (biz_id, title, rtype, due_date, amount, notes,
             is_recurring, recurrence_days, session["user_id"])
        )
        db.commit()
        new_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        return jsonify({"success": True, "id": new_id})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500


@bp.route("/api/v1/reminders/<int:rid>", methods=["PUT"])
@owner_required
def api_reminders_update(rid: int):
    db     = get_db()
    biz_id = session["business_id"]
    row    = db.execute(
        "SELECT id FROM reminders WHERE id=? AND business_id=?", (rid, biz_id)
    ).fetchone()
    if not row:
        return jsonify({"error": "التنبيه غير موجود"}), 404

    data     = request.get_json(silent=True) or {}
    title    = (data.get("title")    or "").strip()
    rtype    = (data.get("reminder_type") or "custom").strip()
    due_date = (data.get("due_date") or "").strip()
    amount   = data.get("amount")
    notes    = (data.get("notes")    or "").strip()
    is_recurring    = int(bool(data.get("is_recurring", False)))
    recurrence_days = data.get("recurrence_days")

    if not title or not due_date:
        return jsonify({"error": "العنوان والتاريخ مطلوبان"}), 400

    db.execute(
        """UPDATE reminders
           SET title=?, reminder_type=?, due_date=?, amount=?, notes=?,
               is_recurring=?, recurrence_days=?
           WHERE id=?""",
        (title, rtype, due_date, amount, notes, is_recurring, recurrence_days, rid)
    )
    db.commit()
    return jsonify({"success": True})


@bp.route("/api/v1/reminders/<int:rid>/dismiss", methods=["POST"])
@owner_required
def api_reminders_dismiss(rid: int):
    db     = get_db()
    biz_id = session["business_id"]
    row    = db.execute(
        "SELECT id, title, is_recurring, recurrence_days, due_date FROM reminders WHERE id=? AND business_id=?",
        (rid, biz_id)
    ).fetchone()
    if not row:
        return jsonify({"error": "التنبيه غير موجود"}), 404

    if row["is_recurring"] and row["recurrence_days"]:
        # إنشاء التنبيه التالي تلقائياً
        old_due  = datetime.strptime(row["due_date"], "%Y-%m-%d")
        next_due = (old_due + timedelta(days=row["recurrence_days"])).strftime("%Y-%m-%d")
        db.execute(
            """INSERT INTO reminders
               (business_id, title, reminder_type, due_date, amount, notes,
                is_recurring, recurrence_days, created_by)
               SELECT business_id, title, reminder_type, ?, amount, notes,
                      is_recurring, recurrence_days, created_by
               FROM reminders WHERE id=?""",
            (next_due, rid)
        )

    db.execute("UPDATE reminders SET is_dismissed=1 WHERE id=?", (rid,))
    db.commit()
    return jsonify({"success": True})


@bp.route("/api/v1/reminders/<int:rid>", methods=["DELETE"])
@owner_required
def api_reminders_delete(rid: int):
    db     = get_db()
    biz_id = session["business_id"]
    row    = db.execute(
        "SELECT id FROM reminders WHERE id=? AND business_id=?", (rid, biz_id)
    ).fetchone()
    if not row:
        return jsonify({"error": "التنبيه غير موجود"}), 404

    db.execute("UPDATE reminders SET is_active=0 WHERE id=?", (rid,))
    db.commit()
    return jsonify({"success": True})


# ═══════════════════════════════════════════════════════════════════════════════
# ─── محرك النسخ الاحتياطية (Backup Engine) ──────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/backup")
@owner_required
def backup_page():
    db     = get_db()
    biz_id = session["business_id"]
    logs   = []
    if _table_exists(db, "backup_logs"):
        logs = db.execute(
            """SELECT bl.*, u.full_name AS created_by_name
               FROM backup_logs bl
               LEFT JOIN users u ON u.id = bl.created_by
               WHERE bl.business_id=?
               ORDER BY bl.created_at DESC LIMIT 20""",
            (biz_id,)
        ).fetchall()
        logs = [dict(r) for r in logs]
    return render_template("backup.html", backup_logs=logs)


@bp.route("/api/v1/backup/download")
@owner_required
def api_backup_download():
    """تحميل نسخة JSON شاملة لبيانات المنشأة"""
    db     = get_db()
    biz_id = session["business_id"]

    # الجداول المشمولة في النسخة الاحتياطية
    tables_to_backup = [
        "businesses", "users", "roles", "settings",
        "products", "product_categories", "warehouses", "stock", "stock_movements",
        "contacts", "invoices", "invoice_lines",
        "accounts", "journal_entries", "journal_entry_lines",
        "tax_settings", "reminders",
    ]

    backup_data: dict = {
        "__meta__": {
            "version":     "jenan-biz-v2.0",
            "business_id": biz_id,
            "created_at":  datetime.now().isoformat(),
            "tables":      tables_to_backup,
        }
    }
    total_rows = 0
    for table in tables_to_backup:
        try:
            if table == "businesses":
                rows = db.execute("SELECT * FROM businesses WHERE id=?", (biz_id,)).fetchall()
            elif table in ("users", "roles", "settings",
                           "products", "product_categories", "warehouses",
                           "contacts", "accounts", "tax_settings", "reminders"):
                rows = db.execute(
                    f"SELECT * FROM {table} WHERE business_id=?", (biz_id,)
                ).fetchall()
            elif table == "stock":
                rows = db.execute(
                    """SELECT s.* FROM stock s
                       JOIN warehouses w ON w.id=s.warehouse_id
                       WHERE w.business_id=?""",
                    (biz_id,)
                ).fetchall()
            elif table == "stock_movements":
                rows = db.execute(
                    "SELECT * FROM stock_movements WHERE business_id=?", (biz_id,)
                ).fetchall()
            elif table == "invoices":
                rows = db.execute(
                    "SELECT * FROM invoices WHERE business_id=?", (biz_id,)
                ).fetchall()
            elif table == "invoice_lines":
                rows = db.execute(
                    """SELECT il.* FROM invoice_lines il
                       JOIN invoices i ON i.id=il.invoice_id
                       WHERE i.business_id=?""",
                    (biz_id,)
                ).fetchall()
            elif table == "journal_entries":
                rows = db.execute(
                    "SELECT * FROM journal_entries WHERE business_id=?", (biz_id,)
                ).fetchall()
            elif table == "journal_entry_lines":
                rows = db.execute(
                    """SELECT jel.* FROM journal_entry_lines jel
                       JOIN journal_entries je ON je.id=jel.entry_id
                       WHERE je.business_id=?""",
                    (biz_id,)
                ).fetchall()
            else:
                rows = []
            backup_data[table] = [dict(r) for r in rows]
            total_rows += len(rows)
        except Exception:
            backup_data[table] = []

    json_bytes = json.dumps(backup_data, ensure_ascii=False, indent=2).encode("utf-8")

    # ── تشفير اختياري بـ AES-256-GCM ─────────────────────────────────────────
    encrypt_password = request.args.get("password", "").strip()
    do_encrypt       = bool(encrypt_password)
    mimetype         = "application/json"
    ext              = "json"

    if do_encrypt:
        from modules.extensions import encrypt_backup
        json_bytes = encrypt_backup(json_bytes, encrypt_password)
        mimetype   = "application/octet-stream"
        ext        = "enc"

    file_size = len(json_bytes) // 1024

    # تسجيل في backup_logs
    try:
        if _table_exists(db, "backup_logs"):
            db.execute(
                """INSERT INTO backup_logs
                   (business_id, backup_type, format, file_size_kb, tables_included, created_by)
                   VALUES (?,?,?,?,?,?)""",
                (biz_id, "manual", "encrypted_json" if do_encrypt else "json",
                 file_size, json.dumps(tables_to_backup), session["user_id"])
            )
            db.commit()
    except Exception:
        pass

    filename = (
        f"jenan_biz_backup_{biz_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"
    )
    return send_file(
        io.BytesIO(json_bytes),
        mimetype=mimetype,
        as_attachment=True,
        download_name=filename,
    )


@bp.route("/sw.js")
def service_worker():
    resp = send_from_directory(BASE_DIR / "static", "sw.js")
    resp.headers["Content-Type"]  = "application/javascript"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@bp.route("/privacy-policy")
def privacy_policy_page():
    return render_template("legal/privacy_policy.html")


@bp.route("/terms-of-use")
def terms_of_use_page():
    return render_template("legal/terms_of_use.html")


@bp.route("/<page>")
@onboarding_required
def stub_page(page):
    if page not in STUB_PAGES:
        return render_template("404.html"), 404
    return render_template("stub_page.html", page_name=page)


# ═══════════════════════════════════════════════════════════════
#  Audit Trail — سجل العمليات
# ═══════════════════════════════════════════════════════════════

@bp.route("/audit-log")
@owner_required
def audit_log_page():
    return render_template("audit_log.html")


@bp.route("/api/v1/audit-log")
@owner_required
def api_audit_log():
    db     = get_db()
    biz_id = session["business_id"]

    action_filter = request.args.get("action", "")
    user_filter   = request.args.get("user",   "")
    date_from     = request.args.get("from",   "")
    date_to       = request.args.get("to",     "")
    page          = max(1, int(request.args.get("page", 1)))
    per_page      = 50

    conditions = ["business_id=?"]
    params     = [biz_id]

    if action_filter:
        conditions.append("action=?")
        params.append(action_filter)
    if user_filter:
        conditions.append("actor_name LIKE ?")
        params.append(f"%{user_filter}%")
    if date_from:
        conditions.append("created_at >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("created_at <= ?")
        params.append(date_to + " 23:59:59")

    where = " AND ".join(conditions)
    total = db.execute(f"SELECT COUNT(*) FROM audit_logs WHERE {where}", params).fetchone()[0]
    rows  = db.execute(
        f"SELECT * FROM audit_logs WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [per_page, (page - 1) * per_page]
    ).fetchall()

    return jsonify({
        "total":   total,
        "page":    page,
        "pages":   (total + per_page - 1) // per_page,
        "logs":    [dict(r) for r in rows],
    })
