"""
blueprints/core/routes.py — الصفحات الأساسية: dashboard، analytics، onboarding، settings، stub
"""
import json
import secrets
from datetime import datetime, timedelta

from flask import (
    Blueprint, flash, g, jsonify, redirect, render_template,
    request, send_from_directory, session, url_for
)

from modules.config import (
    ALLOWED_LOGO_EXT, BASE_DIR, INDUSTRY_TYPES,
    LOGO_FOLDER, STUB_PAGES
)
from modules.extensions import (
    csrf_protect, get_db, seed_business_accounts, hash_password
)
from modules.middleware import (
    login_required, onboarding_required, require_perm, user_has_perm,
    owner_required
)
from modules.terminology import get_terms

bp = Blueprint("core", __name__)

LOGO_FOLDER.mkdir(exist_ok=True)


def _column_exists(db, table: str, column: str) -> bool:
    """تحقق خفيف من وجود عمود قبل استخدامه في الاستعلامات الديناميكية."""
    try:
        rows = db.execute(f"PRAGMA table_info({table})").fetchall()
        return any(r[1] == column for r in rows)
    except Exception:
        return False


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
        # أكبر موزعين + حجم الشحنات
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
        kpis["top_distributors"]    = [dict(r) for r in top_distributors]
        kpis["pending_purchase_cnt"]= int(pending_purchases["cnt"] or 0)
        kpis["pending_purchase_val"]= float(pending_purchases["total"] or 0)

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

    # standard / fashion / medical / default → أفضل 10 منتجات + إجمالي العملاء
    else:
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
        kpis["top_products"]   = [dict(r) for r in top_products]
        kpis["new_customers"]  = int(new_customers["cnt"] or 0) if new_customers else 0

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
            industry_type = "retail_other"

        db     = get_db()
        biz_id = session["business_id"]

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
        flash(f"مرحباً! تم إنشاء منشأة «{biz_name}» بنجاح ✓", "success")
        return redirect(url_for("core.dashboard"))

    return render_template("onboarding.html")


@bp.route("/settings", methods=["GET", "POST"])
@require_perm("settings")
def settings():
    db     = get_db()
    biz_id = session["business_id"]

    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard

        name       = request.form.get("business_name",  "").strip()
        tax_number = request.form.get("tax_number",     "").strip()
        phone      = request.form.get("phone",          "").strip()
        email      = request.form.get("email",          "").strip()
        address    = request.form.get("address",        "").strip()
        city       = request.form.get("city",           "").strip()
        cr_number  = request.form.get("cr_number",      "").strip()
        currency   = request.form.get("currency",       "SAR")
        inv_prefix = request.form.get("invoice_prefix", "INV").strip()

        if not name:
            flash("اسم المنشأة مطلوب", "error")
            return redirect(url_for("core.settings"))

        logo_path = None
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



@bp.route("/sw.js")
def service_worker():
    resp = send_from_directory(str(BASE_DIR / "static"), "sw.js")
    resp.headers["Content-Type"]  = "application/javascript"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@bp.route("/<page>")
@onboarding_required
def stub_page(page):
    if page not in STUB_PAGES:
        return render_template("404.html"), 404
    return render_template("stub_page.html", page_name=page)
