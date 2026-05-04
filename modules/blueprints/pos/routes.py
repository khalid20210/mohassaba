"""
blueprints/pos/routes.py — نقطة البيع (POS)
"""
import random
import sqlite3
import time
from datetime import datetime, timedelta

from flask import (
    Blueprint, g, jsonify, redirect, render_template,
    request, session, url_for
)

from modules.config import CHECKOUT_LOCK_TIMEOUT_MS, CHECKOUT_LOCK_TTL_MS, CHECKOUT_MAX_RETRIES
from modules.extensions import (
    get_db, get_account_id, next_entry_number, next_invoice_number
)
from modules.middleware import onboarding_required, require_perm, user_has_perm, write_audit_log
from modules.runtime_services import acquire_business_lock, release_business_lock
from modules.terminology import get_terms
from modules.unit_localization import get_market_packaging_terms
from modules.validators import validate, V, SCHEMA_POS_CHECKOUT
from modules.zatca_queue import enqueue_invoice

bp = Blueprint("pos", __name__)


def _table_exists(db, table_name):
    row = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    ).fetchone()
    return row is not None


def _column_exists(db, table_name, column_name):
    try:
        rows = db.execute(f"PRAGMA table_info({table_name})").fetchall()
        return any(r[1] == column_name for r in rows)
    except Exception:
        return False


def _ensure_pos_shift_tables(db):
    db.execute(
        """CREATE TABLE IF NOT EXISTS pos_shifts (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               business_id INTEGER NOT NULL,
               user_id INTEGER NOT NULL,
               opened_at TEXT NOT NULL DEFAULT (datetime('now')),
               opening_cash REAL NOT NULL DEFAULT 0,
               closed_at TEXT,
               closing_cash REAL,
               expected_cash REAL DEFAULT 0,
               sales_count INTEGER DEFAULT 0,
               sales_total REAL DEFAULT 0,
               notes TEXT,
               created_at TEXT NOT NULL DEFAULT (datetime('now'))
           )"""
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_pos_shifts_biz_user_open ON pos_shifts(business_id, user_id, closed_at)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_pos_shifts_biz_opened_at ON pos_shifts(business_id, opened_at DESC)"
    )
    if _table_exists(db, "invoices") and not _column_exists(db, "invoices", "pos_shift_id"):
        try:
            db.execute("ALTER TABLE invoices ADD COLUMN pos_shift_id INTEGER")
        except Exception:
            pass


def _active_shift(db, biz_id, user_id):
    _ensure_pos_shift_tables(db)
    return db.execute(
        """SELECT * FROM pos_shifts
           WHERE business_id=? AND user_id=? AND closed_at IS NULL
           ORDER BY id DESC LIMIT 1""",
        (biz_id, user_id)
    ).fetchone()


def _shift_sales_metrics(db, biz_id, shift_row):
    if not shift_row:
        return {
            "sales_count": 0,
            "sales_total": 0.0,
            "cash_total": 0.0,
            "bank_total": 0.0,
            "credit_total": 0.0,
            "returns_total": 0.0,
        }

    opened = shift_row["opened_at"]
    closed = shift_row["closed_at"]
    where = (
        "business_id=? AND invoice_type='sale' AND status<>'cancelled' "
        "AND datetime(created_at) >= datetime(?)"
    )
    params = [biz_id, opened]
    if closed:
        where += " AND datetime(created_at) <= datetime(?)"
        params.append(closed)

    totals = db.execute(
        f"""SELECT COUNT(*) AS sales_count,
                   COALESCE(SUM(total),0) AS sales_total,
                   COALESCE(SUM(CASE WHEN payment_method='cash' THEN total ELSE 0 END),0) AS cash_total,
                   COALESCE(SUM(CASE WHEN payment_method='bank' THEN total ELSE 0 END),0) AS bank_total,
                   COALESCE(SUM(CASE WHEN payment_method='credit' THEN total ELSE 0 END),0) AS credit_total
            FROM invoices
            WHERE {where}""",
        params
    ).fetchone()

    ret_where = (
        "business_id=? AND invoice_type='sale_return' AND status<>'cancelled' "
        "AND datetime(created_at) >= datetime(?)"
    )
    ret_params = [biz_id, opened]
    if closed:
        ret_where += " AND datetime(created_at) <= datetime(?)"
        ret_params.append(closed)
    returns_row = db.execute(
        f"SELECT COALESCE(SUM(total),0) AS returns_total FROM invoices WHERE {ret_where}",
        ret_params
    ).fetchone()

    return {
        "sales_count": int(totals["sales_count"] or 0),
        "sales_total": round(float(totals["sales_total"] or 0), 2),
        "cash_total": round(float(totals["cash_total"] or 0), 2),
        "bank_total": round(float(totals["bank_total"] or 0), 2),
        "credit_total": round(float(totals["credit_total"] or 0), 2),
        "returns_total": round(float(returns_row["returns_total"] or 0), 2),
    }


def _contact_current_balance(db, contact_id):
    last_tx = db.execute(
        "SELECT balance_after FROM customer_transactions WHERE contact_id=? ORDER BY id DESC LIMIT 1",
        (contact_id,)
    ).fetchone()
    if last_tx:
        return float(last_tx["balance_after"] or 0)

    opening = db.execute(
        "SELECT opening_balance FROM contacts WHERE id=?",
        (contact_id,)
    ).fetchone()
    return float(opening["opening_balance"] or 0) if opening else 0.0


def _append_customer_tx(db, biz_id, contact_id, transaction_type, amount, note, reference_id):
    old_balance = _contact_current_balance(db, contact_id)
    if transaction_type in ("payment", "credit_note", "return"):
        new_balance = old_balance - amount
    else:
        new_balance = old_balance + amount

    db.execute(
        """INSERT INTO customer_transactions
           (business_id, contact_id, transaction_type, reference_type, reference_id,
            amount, balance_before, balance_after, notes)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            biz_id,
            contact_id,
            transaction_type,
            "invoice",
            reference_id,
            amount,
            old_balance,
            new_balance,
            note,
        )
    )

# ── POS UI config per pos_mode ────────────────────────────────────────────────
_POS_MODE_CONFIG = {
    "standard": {
        "show_images":        False,
        "show_tables":        False,
        "show_expiry":        False,
        "show_serial":        False,
        "show_variant":       False,
        "search_by_barcode":  True,
        "quick_add_barcode":  True,
        "kitchen_screen":     False,
        "primary_search":     "barcode",
    },
    "restaurant": {
        "show_images":        True,
        "show_tables":        True,
        "show_expiry":        False,
        "show_serial":        False,
        "show_variant":       False,
        "search_by_barcode":  False,
        "quick_add_barcode":  False,
        "kitchen_screen":     True,
        "primary_search":     "name",
    },
    "pharmacy": {
        "show_images":        False,
        "show_tables":        False,
        "show_expiry":        True,   # تاريخ الصلاحية ← أولوية الصيدلية
        "show_serial":        True,   # رقم التشغيلة
        "show_variant":       False,
        "search_by_barcode":  True,
        "quick_add_barcode":  True,
        "kitchen_screen":     False,
        "primary_search":     "barcode",
    },
    "fashion": {
        "show_images":        True,
        "show_tables":        False,
        "show_expiry":        False,
        "show_serial":        False,
        "show_variant":       True,   # مقاس / لون
        "search_by_barcode":  True,
        "quick_add_barcode":  False,
        "kitchen_screen":     False,
        "primary_search":     "name",
    },
    "wholesale": {
        "show_images":        False,
        "show_tables":        False,
        "show_expiry":        False,
        "show_serial":        False,
        "show_variant":       False,
        "search_by_barcode":  True,
        "quick_add_barcode":  True,
        "kitchen_screen":     False,
        "primary_search":     "barcode",
        "show_qty_tiers":     True,   # تسعير الكميات
    },
    "workshop": {
        "show_images":        False,
        "show_tables":        False,
        "show_expiry":        False,
        "show_serial":        True,   # رقم اللوحة
        "show_variant":       False,
        "search_by_barcode":  False,
        "quick_add_barcode":  False,
        "kitchen_screen":     False,
        "primary_search":     "name",
        "show_work_order":    True,
    },
    "construction": {
        "show_images":        False,
        "show_tables":        False,
        "show_expiry":        False,
        "show_serial":        False,
        "show_variant":       False,
        "search_by_barcode":  False,
        "quick_add_barcode":  False,
        "kitchen_screen":     False,
        "primary_search":     "name",
        "show_project":       True,
    },
    "rental": {
        "show_images":        True,
        "show_tables":        False,
        "show_expiry":        False,
        "show_serial":        True,   # رقم اللوحة
        "show_variant":       False,
        "search_by_barcode":  False,
        "quick_add_barcode":  False,
        "kitchen_screen":     False,
        "primary_search":     "name",
        "show_date_range":    True,
    },
    "medical": {
        "show_images":        False,
        "show_tables":        False,
        "show_expiry":        False,
        "show_serial":        False,
        "show_variant":       False,
        "search_by_barcode":  False,
        "quick_add_barcode":  False,
        "kitchen_screen":     False,
        "primary_search":     "name",
        "show_patient_id":    True,
    },
}


def _resolve_quantity_policy(industry_type: str, pos_mode: str) -> dict:
    """سياسة الكمية في POS حسب نوع النشاط لتقليل الأخطاء والتعقيد."""
    if industry_type.startswith("wholesale_") or pos_mode == "wholesale":
        policy = {
            "qty_step": 1,
            "qty_min": 1,
            "qty_decimals": 0,
            "unit_examples": ["كرتون", "صندوق", "باليت", "دستة", "ربطة"],
            "variant_examples": [],
        }
        if industry_type.startswith("wholesale_fashion_"):
            policy["variant_examples"] = ["S", "M", "L", "XL", "XXL"]
        return policy

    if (
        industry_type.startswith("retail_fnb_")
        or industry_type in {"retail_fnb_supermarket", "retail_fnb_butcher", "retail_fnb_produce", "retail_fnb_roaster"}
    ):
        return {
            "qty_step": 0.25,
            "qty_min": 0.25,
            "qty_decimals": 3,
            "unit_examples": ["كيلو", "نصف كيلو", "ربع كيلو", "جرام"],
            "variant_examples": [],
        }

    if industry_type.startswith("retail_fashion_") or pos_mode == "fashion":
        return {
            "qty_step": 1,
            "qty_min": 1,
            "qty_decimals": 0,
            "unit_examples": ["قطعة", "طقم", "زوج"],
            "variant_examples": ["XS", "S", "M", "L", "XL", "XXL"],
        }

    return {
        "qty_step": 1,
        "qty_min": 1,
        "qty_decimals": 0,
        "unit_examples": ["قطعة", "علبة", "عبوة"],
        "variant_examples": [],
    }


@bp.route("/pos")
@require_perm("pos")
def pos():
    db             = get_db()
    biz_id         = session["business_id"]
    user_branch_id = g.user["branch_id"] if g.user else None

    warehouses = db.execute(
        "SELECT id, name FROM warehouses WHERE business_id=? AND is_active=1 ORDER BY is_default DESC",
        (biz_id,)
    ).fetchall()

    if user_branch_id:
        warehouses = [w for w in warehouses if w["id"] == user_branch_id]

    categories = db.execute(
        "SELECT DISTINCT category_name FROM products WHERE business_id=? AND is_active=1 AND category_name IS NOT NULL ORDER BY category_name",
        (biz_id,)
    ).fetchall()

    # ── تحديد واجهة POS حسب قطاع المنشأة ─────────────────────────────────────
    biz           = g.business
    industry_type = biz["industry_type"] if biz else "retail_other"
    barcode_only_flow = (
        industry_type == "retail"
        or industry_type.startswith("retail_")
    )
    terms         = get_terms(industry_type)
    pos_mode      = terms.get("pos_mode", "standard")
    qty_policy    = _resolve_quantity_policy(industry_type, pos_mode)
    country_code  = ((g.country_profile or {}).get("country_code") or "SA").upper()
    wholesale_packaging_terms = (
        get_market_packaging_terms(country_code, language="ar")
        if pos_mode == "wholesale"
        else []
    )
    ui_config     = {**_POS_MODE_CONFIG.get(pos_mode, _POS_MODE_CONFIG["standard"]), **{
        "pos_mode":        pos_mode,
        "country_code":    country_code,
        "industry_icon":   terms.get("industry_icon", "🏪"),
        "industry_label":  terms.get("industry_label", "نشاط تجاري"),
        "pos_search_hint": (
            "مرر/اكتب الباركود ثم اضغط Enter"
            if barcode_only_flow
            else terms.get("pos_search_hint", "ابحث بالاسم أو الباركود...")
        ),
        "pos_quick_label": terms.get("pos_quick_label", "بيع سريع"),
        "enforce_barcode_only": barcode_only_flow,
        "wholesale_packaging_terms": wholesale_packaging_terms,
        "qty_step":        qty_policy["qty_step"],
        "qty_min":         qty_policy["qty_min"],
        "qty_decimals":    qty_policy["qty_decimals"],
        "unit_examples":   qty_policy["unit_examples"],
        "variant_examples":qty_policy["variant_examples"],
        "T_product":       terms.get("product", "منتج"),
        "T_customer":      terms.get("customer", "عميل"),
        "T_seller":        terms.get("seller", "بائع"),
        "T_invoice":       terms.get("invoice", "فاتورة"),
        "T_order":         terms.get("order", "طلب"),
        "T_new_sale":      terms.get("new_sale", "بيع جديد"),
        "T_expiry":        terms.get("expiry", "تاريخ الانتهاء"),
        "T_serial":        terms.get("serial", "الرقم التسلسلي"),
        "T_variant":       terms.get("variant", "نوع / مقاس"),
        "T_work_order":    terms.get("work_order", "أمر عمل"),
        "T_unit":          terms.get("unit", "وحدة"),
    }}

    return render_template(
        "pos.html",
        warehouses=[dict(w) for w in warehouses],
        categories=[r["category_name"] for r in categories],
        user_branch_id=user_branch_id,
        ui_config=ui_config,
    )


@bp.route("/api/pos/config")
@onboarding_required
def api_pos_config():
    """
    يُعيد كامل إعدادات واجهة POS بصيغة JSON.
    يستخدمه الـ JavaScript لتكييف الواجهة ديناميكياً.
    """
    biz           = g.business
    industry_type = biz["industry_type"] if biz else "retail_other"
    barcode_only_flow = (
        industry_type == "retail"
        or industry_type.startswith("retail_")
    )
    terms         = get_terms(industry_type)
    pos_mode      = terms.get("pos_mode", "standard")
    qty_policy    = _resolve_quantity_policy(industry_type, pos_mode)
    country_code  = ((g.country_profile or {}).get("country_code") or "SA").upper()
    wholesale_packaging_terms = (
        get_market_packaging_terms(country_code, language="ar")
        if pos_mode == "wholesale"
        else []
    )
    config        = {**_POS_MODE_CONFIG.get(pos_mode, _POS_MODE_CONFIG["standard"])}
    config.update({
        "pos_mode":        pos_mode,
        "country_code":    country_code,
        "industry_type":   industry_type,
        "industry_icon":   terms.get("industry_icon", "🏪"),
        "industry_label":  terms.get("industry_label", "نشاط تجاري"),
        "pos_search_hint": (
            "مرر/اكتب الباركود ثم اضغط Enter"
            if barcode_only_flow
            else terms.get("pos_search_hint", "ابحث بالاسم أو الباركود...")
        ),
        "pos_quick_label": terms.get("pos_quick_label", "بيع سريع"),
        "enforce_barcode_only": barcode_only_flow,
        "wholesale_packaging_terms": wholesale_packaging_terms,
        "qty_step":        qty_policy["qty_step"],
        "qty_min":         qty_policy["qty_min"],
        "qty_decimals":    qty_policy["qty_decimals"],
        "unit_examples":   qty_policy["unit_examples"],
        "variant_examples":qty_policy["variant_examples"],
        "labels": {
            "product":    terms.get("product", "منتج"),
            "customer":   terms.get("customer", "عميل"),
            "seller":     terms.get("seller", "بائع"),
            "invoice":    terms.get("invoice", "فاتورة"),
            "order":      terms.get("order", "طلب"),
            "new_sale":   terms.get("new_sale", "بيع جديد"),
            "expiry":     terms.get("expiry", "تاريخ الانتهاء"),
            "serial":     terms.get("serial", "الرقم التسلسلي"),
            "variant":    terms.get("variant", "نوع / مقاس"),
            "work_order": terms.get("work_order", "أمر عمل"),
            "unit":       terms.get("unit", "وحدة"),
            "quantity":   terms.get("quantity", "الكمية"),
            "price":      terms.get("price", "السعر"),
            "total":      terms.get("total", "الإجمالي"),
        },
    })
    return jsonify({"success": True, "config": config})


@bp.route("/api/pos/search")
@onboarding_required
def api_pos_search():
    biz_id         = session["business_id"]
    db             = get_db()
    user_branch_id = g.user["branch_id"] if g.user else None

    q            = request.args.get("q", "").strip()
    category     = request.args.get("category", "").strip()
    warehouse_id = request.args.get("warehouse_id", "")
    biz           = g.business
    industry_type = biz["industry_type"] if biz else "retail_other"
    barcode_only_flow = (
        industry_type == "retail"
        or industry_type.startswith("retail_")
    )

    # في التجزئة فقط: لا نظهر أي منتجات إلا عند البحث بالباركود
    if barcode_only_flow and not q:
        return jsonify({"products": []})

    # الكاشير لا يمكنه اختيار مستودع آخر
    if user_branch_id:
        warehouse_id = str(user_branch_id)

    where  = "WHERE p.business_id=? AND p.is_active=1 AND p.is_pos=1"
    params = [biz_id]

    weighted_barcode = None
    if barcode_only_flow and q.isdigit() and len(q) == 13 and q.startswith("2"):
        weighted_barcode = {
            "item_code": q[1:6],
            "weight_qty": float(int(q[6:11])) / 1000.0,
        }

    if q:
        if barcode_only_flow:
            if weighted_barcode:
                where += " AND (p.barcode=? OR p.barcode LIKE ? OR p.barcode LIKE ?)"
                params += [
                    weighted_barcode["item_code"],
                    f"{weighted_barcode['item_code']}%",
                    f"%{weighted_barcode['item_code']}",
                ]
            else:
                where += " AND p.barcode=?"
                params.append(q)
        else:
            where  += " AND (p.name LIKE ? OR p.barcode LIKE ?)"
            params += [f"%{q}%", f"%{q}%"]
    if category and not barcode_only_flow:
        where  += " AND p.category_name=?"
        params.append(category)

    stock_join = ""
    if warehouse_id:
        try:
            wh_id = int(warehouse_id)
            stock_join = f"LEFT JOIN stock s ON s.product_id=p.id AND s.warehouse_id={wh_id}"
        except ValueError:
            stock_join = ""
    else:
        stock_join = "LEFT JOIN stock s ON s.product_id=p.id"

    products = db.execute(
        f"""SELECT p.id, p.name, p.barcode, p.sale_price, p.category_name,
                   0 AS tax_rate, COALESCE(s.quantity, 0) AS stock_qty
            FROM products p {stock_join}
            {where}
            ORDER BY p.name LIMIT 100""",
        params
    ).fetchall()

    payload = [dict(p) for p in products]
    if weighted_barcode and len(payload) == 1:
        payload[0]["weighted_qty"] = round(weighted_barcode["weight_qty"], 3)

    return jsonify({"products": payload})


@bp.route("/api/pos/shift/current")
@onboarding_required
def api_pos_shift_current():
    db = get_db()
    biz_id = session["business_id"]
    user_id = session["user_id"]

    shift = _active_shift(db, biz_id, user_id)
    if not shift:
        return jsonify({"success": True, "open": False, "shift": None})

    metrics = _shift_sales_metrics(db, biz_id, shift)
    out = dict(shift)
    out.update(metrics)
    return jsonify({"success": True, "open": True, "shift": out})


@bp.route("/api/pos/shift/open", methods=["POST"])
@onboarding_required
def api_pos_shift_open():
    db = get_db()
    biz_id = session["business_id"]
    user_id = session["user_id"]
    payload = request.get_json(silent=True) or {}

    current = _active_shift(db, biz_id, user_id)
    if current:
        return jsonify({"success": False, "error": "يوجد وردية مفتوحة بالفعل"}), 400

    try:
        opening_cash = float(payload.get("opening_cash", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "رصيد بداية الوردية غير صالح"}), 400
    if opening_cash < 0:
        return jsonify({"success": False, "error": "رصيد البداية لا يمكن أن يكون سالباً"}), 400

    _ensure_pos_shift_tables(db)
    db.execute(
        """INSERT INTO pos_shifts (business_id, user_id, opening_cash, notes)
           VALUES (?,?,?,?)""",
        (biz_id, user_id, opening_cash, (payload.get("notes") or "").strip()[:250])
    )
    shift_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()

    return jsonify({"success": True, "shift_id": shift_id, "message": "تم فتح الوردية"})


@bp.route("/api/pos/shift/x-report")
@onboarding_required
def api_pos_shift_x_report():
    db = get_db()
    biz_id = session["business_id"]
    user_id = session["user_id"]

    shift = _active_shift(db, biz_id, user_id)
    if not shift:
        return jsonify({"success": False, "error": "لا توجد وردية مفتوحة"}), 400

    metrics = _shift_sales_metrics(db, biz_id, shift)
    return jsonify({
        "success": True,
        "report_type": "X",
        "shift": {
            "id": shift["id"],
            "opened_at": shift["opened_at"],
            "opening_cash": float(shift["opening_cash"] or 0),
            **metrics,
            "expected_drawer": round(float(shift["opening_cash"] or 0) + metrics["cash_total"] - metrics["returns_total"], 2),
        },
    })


@bp.route("/api/pos/shift/close", methods=["POST"])
@onboarding_required
def api_pos_shift_close():
    db = get_db()
    biz_id = session["business_id"]
    user_id = session["user_id"]
    payload = request.get_json(silent=True) or {}

    shift = _active_shift(db, biz_id, user_id)
    if not shift:
        return jsonify({"success": False, "error": "لا توجد وردية مفتوحة لإغلاقها"}), 400

    metrics = _shift_sales_metrics(db, biz_id, shift)
    expected_cash = round(float(shift["opening_cash"] or 0) + metrics["cash_total"] - metrics["returns_total"], 2)

    try:
        closing_cash = float(payload.get("closing_cash", expected_cash))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "رصيد الإغلاق غير صالح"}), 400
    if closing_cash < 0:
        return jsonify({"success": False, "error": "رصيد الإغلاق لا يمكن أن يكون سالباً"}), 400

    notes = (payload.get("notes") or "").strip()[:250]
    db.execute(
        """UPDATE pos_shifts
           SET closed_at=datetime('now'), closing_cash=?, expected_cash=?,
               sales_count=?, sales_total=?, notes=CASE WHEN ?='' THEN notes ELSE ? END
           WHERE id=? AND business_id=?""",
        (
            closing_cash,
            expected_cash,
            metrics["sales_count"],
            metrics["sales_total"],
            notes,
            notes,
            shift["id"],
            biz_id,
        )
    )
    db.commit()

    difference = round(closing_cash - expected_cash, 2)
    return jsonify({
        "success": True,
        "report_type": "Z",
        "shift": {
            "id": shift["id"],
            "opened_at": shift["opened_at"],
            "closed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "opening_cash": float(shift["opening_cash"] or 0),
            "closing_cash": closing_cash,
            "expected_cash": expected_cash,
            "difference": difference,
            **metrics,
        },
        "message": "تم إغلاق الوردية بنجاح",
    })


@bp.route("/api/pos/reports/daily")
@onboarding_required
def api_pos_daily_report():
    db = get_db()
    biz_id = session["business_id"]
    selected = (request.args.get("date") or datetime.now().strftime("%Y-%m-%d")).strip()

    inv = db.execute(
        """SELECT COUNT(*) AS total_invoices,
                  COALESCE(SUM(total),0) AS gross_sales,
                  COALESCE(SUM(CASE WHEN payment_method='cash' THEN total ELSE 0 END),0) AS cash_sales,
                  COALESCE(SUM(CASE WHEN payment_method='bank' THEN total ELSE 0 END),0) AS bank_sales,
                  COALESCE(SUM(CASE WHEN payment_method='credit' THEN total ELSE 0 END),0) AS credit_sales
           FROM invoices
           WHERE business_id=? AND invoice_type='sale' AND status<>'cancelled'
             AND date(invoice_date)=date(?)""",
        (biz_id, selected)
    ).fetchone()

    returns_row = db.execute(
        """SELECT COALESCE(SUM(total),0) AS returns_total
           FROM invoices
           WHERE business_id=? AND invoice_type='sale_return' AND status<>'cancelled'
             AND date(invoice_date)=date(?)""",
        (biz_id, selected)
    ).fetchone()

    top_items = db.execute(
        """SELECT il.product_id,
                  COALESCE(NULLIF(TRIM(il.description),''), p.name, '—') AS name,
                  ROUND(COALESCE(SUM(il.quantity),0),3) AS qty,
                  ROUND(COALESCE(SUM(il.total),0),2) AS amount
           FROM invoice_lines il
           JOIN invoices i ON i.id=il.invoice_id
           LEFT JOIN products p ON p.id=il.product_id
           WHERE i.business_id=? AND i.invoice_type='sale' AND i.status<>'cancelled'
             AND date(i.invoice_date)=date(?)
           GROUP BY il.product_id, name
           ORDER BY qty DESC, amount DESC
           LIMIT 10""",
        (biz_id, selected)
    ).fetchall()

    return jsonify({
        "success": True,
        "date": selected,
        "summary": {
            "total_invoices": int(inv["total_invoices"] or 0),
            "gross_sales": round(float(inv["gross_sales"] or 0), 2),
            "returns_total": round(float(returns_row["returns_total"] or 0), 2),
            "net_sales": round(float(inv["gross_sales"] or 0) - float(returns_row["returns_total"] or 0), 2),
            "cash_sales": round(float(inv["cash_sales"] or 0), 2),
            "bank_sales": round(float(inv["bank_sales"] or 0), 2),
            "credit_sales": round(float(inv["credit_sales"] or 0), 2),
        },
        "top_items": [dict(r) for r in top_items],
    })


@bp.route("/api/pos/checkout", methods=["POST"])
@onboarding_required
def api_pos_checkout():
    """
    إتمام عملية البيع:
    1. حفظ الفاتورة وبنودها
    2. خصم الكميات من المخزون + تسجيل حركة
    3. قيد مبيعات: د/الصندوق — ك/إيرادات + ك/ضريبة
    4. قيد تكلفة: د/COGS — ك/مخزون
    """
    data    = request.get_json(force=True) or {}
    biz_id  = session["business_id"]
    user_id = session["user_id"]
    db      = get_db()

    # ── Validate top-level request ─────────────────────────────────────────
    top, errs = validate(data, SCHEMA_POS_CHECKOUT)
    if errs:
        return jsonify({"success": False, "errors": errs}), 400

    items          = top["items"]
    payment_method = top["payment_method"]
    customer_id    = data.get("customer_id")

    debit_acc_code = "1201" if payment_method == "credit" else ("1102" if payment_method == "bank" else "1101")
    cash_acc_id  = get_account_id(db, biz_id, debit_acc_code)
    sales_acc_id = get_account_id(db, biz_id, "4101")
    tax_acc_id   = get_account_id(db, biz_id, "2102")
    cogs_acc_id  = get_account_id(db, biz_id, "5101")
    inv_acc_id   = get_account_id(db, biz_id, "1104")

    if not all([cash_acc_id, sales_acc_id, cogs_acc_id, inv_acc_id]):
        return jsonify({"success": False, "error": "شجرة الحسابات غير مكتملة"}), 400

    customer = None
    if payment_method == "credit":
        try:
            cid = int(customer_id)
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "البيع الآجل يتطلب اختيار عميل صحيح"}), 400

        customer = db.execute(
            """SELECT id, name FROM contacts
               WHERE id=? AND business_id=? AND is_active=1
                 AND contact_type IN ('customer','both')""",
            (cid, biz_id)
        ).fetchone()
        if not customer:
            return jsonify({"success": False, "error": "العميل غير موجود أو غير صالح للبيع الآجل"}), 400

    user_branch_id = g.user["branch_id"] if g.user else None
    requested_wh   = data.get("warehouse_id")

    if user_branch_id:
        wh = db.execute(
            "SELECT id FROM warehouses WHERE id=? AND business_id=? AND is_active=1",
            (user_branch_id, biz_id)
        ).fetchone()
    elif requested_wh:
        wh = db.execute(
            "SELECT id FROM warehouses WHERE id=? AND business_id=? AND is_active=1",
            (int(requested_wh), biz_id)
        ).fetchone()
    else:
        wh = db.execute(
            "SELECT id FROM warehouses WHERE business_id=? AND is_default=1 LIMIT 1", (biz_id,)
        ).fetchone()
    if not wh:
        wh = db.execute("SELECT id FROM warehouses WHERE business_id=? LIMIT 1", (biz_id,)).fetchone()
    warehouse_id = wh["id"] if wh else None

    # ── جلب نسبة الضريبة من إعدادات المنشأة (لا نثق بالـ client) ──────────
    biz_tax_row = db.execute(
        "SELECT rate FROM tax_settings WHERE business_id=? AND is_active=1 ORDER BY id LIMIT 1",
        (biz_id,)
    ).fetchone()
    biz_tax_rate = float(biz_tax_row["rate"]) if biz_tax_row else 0.0

    # هل المستخدم لديه صلاحية تعديل السعر؟
    can_edit_price = user_has_perm("edit_price")

    today = datetime.now().strftime("%Y-%m-%d")
    now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subtotal = tax_total = cogs_total = 0.0
    validated = []

    for item in items:
        try:
            product_id     = int(item["product_id"])
            qty            = float(item["quantity"])
            client_price   = float(item.get("unit_price", 0))
        except (KeyError, ValueError, TypeError):
            return jsonify({"success": False, "error": "بيانات البنود غير صالحة"}), 400

        if qty <= 0:
            return jsonify({"success": False, "error": "الكمية يجب أن تكون موجبة"}), 400

        product = db.execute(
            "SELECT * FROM products WHERE id=? AND business_id=? AND is_active=1",
            (product_id, biz_id)
        ).fetchone()
        if not product:
            return jsonify({"success": False, "error": f"المنتج ID={product_id} غير موجود"}), 400

        # السعر الأساسي من قاعدة البيانات دائماً
        db_price   = float(product["sale_price"] or 0)
        # السماح بتعديل السعر فقط لمن يملك الصلاحية، وعدم السماح بسعر أعلى من الأساسي
        if can_edit_price and client_price >= 0:
            unit_price = client_price
        else:
            unit_price = db_price

        if unit_price < 0:
            return jsonify({"success": False, "error": "السعر لا يمكن أن يكون سالباً"}), 400

        # الضريبة دائماً من إعدادات المنشأة
        tax_rate = biz_tax_rate

        line_sub  = round(qty * unit_price, 4)
        line_tax  = round(line_sub * tax_rate / 100, 4)
        line_tot  = round(line_sub + line_tax, 4)
        line_cost = round(qty * float(product["purchase_price"] or 0), 4)

        subtotal   += line_sub
        tax_total  += line_tax
        cogs_total += line_cost

        validated.append({
            "product_id":     product_id,
            "description":    product["name"],
            "quantity":       qty,
            "unit_price":     unit_price,
            "tax_rate":       tax_rate,
            "tax_amount":     line_tax,
            "total":          line_tot,
            "purchase_price": float(product["purchase_price"] or 0),
        })

    subtotal    = round(subtotal,    2)
    tax_total   = round(tax_total,   2)
    grand_total = round(subtotal + tax_total, 2)
    cogs_total  = round(cogs_total,  2)

    # ── قراءة الـ shift قبل الـ lock (لتقليص نافذة BEGIN IMMEDIATE) ─────────
    shift = _active_shift(db, biz_id, user_id)
    pos_shift_id = shift["id"] if shift else None

    # ── Per-business write lock ────────────────────────────────────────────────
    # كل شركة لها lock مستقل ← كاشيري 500 شركة لا ينتظرون بعضهم
    _lock_token = acquire_business_lock(
        biz_id,
        timeout_ms=CHECKOUT_LOCK_TIMEOUT_MS,
        ttl_ms=CHECKOUT_LOCK_TTL_MS,
    )
    if _lock_token is None:
        return jsonify({
            "success": False,
            "error": "الكاشير مشغول جداً، أعد المحاولة بعد لحظة",
        }), 503

    try:
        # Retry loop على BEGIN IMMEDIATE مع exponential backoff لـ SQLITE_BUSY
        for _attempt in range(CHECKOUT_MAX_RETRIES):
            try:
                db.execute("BEGIN IMMEDIATE")
                break
            except sqlite3.OperationalError as _busy_err:
                if "database is locked" in str(_busy_err) and _attempt < CHECKOUT_MAX_RETRIES - 1:
                    time.sleep(0.030 * (2 ** _attempt) + random.uniform(0, 0.015))
                    continue
                return jsonify({"success": False, "error": "قاعدة البيانات مشغولة، أعد المحاولة بعد لحظة"}), 503

        inv_number  = next_invoice_number(db, biz_id)
        je_sale_num = next_entry_number(db, biz_id)

        db.execute(
            """INSERT INTO invoices
               (business_id, invoice_number, invoice_type, invoice_date,
            subtotal, tax_amount, total, paid_amount, status, warehouse_id, created_by,
            payment_method, party_id, party_name, pos_shift_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (biz_id, inv_number, "sale", today,
             subtotal, tax_total, grand_total,
             (0 if payment_method == "credit" else grand_total),
             ("partial" if payment_method == "credit" else "paid"),
             warehouse_id,
             user_id,
             payment_method,
             (customer["id"] if customer else None),
             (customer["name"] if customer else None),
             pos_shift_id)
        )
        invoice_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        for idx, item in enumerate(validated):
            db.execute(
                """INSERT INTO invoice_lines
                   (invoice_id, product_id, description, quantity, unit_price,
                    tax_rate, tax_amount, total, line_order)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (invoice_id, item["product_id"], item["description"],
                 item["quantity"], item["unit_price"],
                 item["tax_rate"], item["tax_amount"], item["total"], idx + 1)
            )
            if warehouse_id:
                db.execute(
                    "INSERT OR IGNORE INTO stock (business_id,product_id,warehouse_id,quantity,avg_cost) VALUES (?,?,?,0,0)",
                    (biz_id, item["product_id"], warehouse_id)
                )
                # فحص المخزون قبل الخصم لمنع القيم السالبة
                if product_row := db.execute(
                    "SELECT quantity FROM stock WHERE product_id=? AND warehouse_id=?",
                    (item["product_id"], warehouse_id)
                ).fetchone():
                    if float(product_row["quantity"]) < item["quantity"]:
                        db.execute("ROLLBACK")
                        return jsonify({
                            "success": False,
                            "error": f"المخزون غير كافٍ للمنتج: {item['description']} (المتاح: {product_row['quantity']:.2f})"
                        }), 400
                db.execute(
                    "UPDATE stock SET quantity=quantity-?,last_updated=? WHERE product_id=? AND warehouse_id=?",
                    (item["quantity"], now, item["product_id"], warehouse_id)
                )
                db.execute(
                    """INSERT INTO stock_movements
                       (business_id,product_id,warehouse_id,movement_type,
                        quantity,unit_cost,reference_type,reference_id,created_by)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (biz_id, item["product_id"], warehouse_id, "sale",
                     -item["quantity"], item["purchase_price"], "invoice", invoice_id, user_id)
                )

        db.execute(
            """INSERT INTO journal_entries
               (business_id,entry_number,entry_date,description,
                reference_type,reference_id,total_debit,total_credit,is_posted,created_by)
               VALUES (?,?,?,?,?,?,?,?,1,?)""",
            (biz_id, je_sale_num, today,
             f"قيد مبيعات نقدية — فاتورة {inv_number}",
             "invoice", invoice_id, grand_total, grand_total, user_id)
        )
        je_sale_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        if payment_method == "cash":
            cash_label = "نقدية مقبوضة"
        elif payment_method == "bank":
            cash_label = "تحويل بنكي"
        else:
            cash_label = "ذمم مدينة — عميل"
        db.execute(
            "INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
            (je_sale_id, cash_acc_id, cash_label, grand_total, 0, 1)
        )
        db.execute(
            "INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
            (je_sale_id, sales_acc_id, f"إيرادات مبيعات — {inv_number}", 0, subtotal, 2)
        )
        if tax_total > 0 and tax_acc_id:
            db.execute(
                "INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
                (je_sale_id, tax_acc_id, "ضريبة القيمة المضافة", 0, tax_total, 3)
            )

        db.execute("UPDATE invoices SET journal_entry_id=? WHERE id=?", (je_sale_id, invoice_id))

        if customer and payment_method == "credit" and _table_exists(db, "customer_transactions"):
            _append_customer_tx(
                db,
                biz_id,
                int(customer["id"]),
                "sale",
                grand_total,
                f"بيع آجل من POS — فاتورة {inv_number}",
                invoice_id,
            )

        if cogs_total > 0:
            je_cogs_num = next_entry_number(db, biz_id)
            db.execute(
                """INSERT INTO journal_entries
                   (business_id,entry_number,entry_date,description,
                    reference_type,reference_id,total_debit,total_credit,is_posted,created_by)
                   VALUES (?,?,?,?,?,?,?,?,1,?)""",
                (biz_id, je_cogs_num, today,
                 f"قيد تكلفة البضاعة المباعة — فاتورة {inv_number}",
                 "invoice", invoice_id, cogs_total, cogs_total, user_id)
            )
            je_cogs_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.execute(
                "INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
                (je_cogs_id, cogs_acc_id, "تكلفة البضاعة المباعة", cogs_total, 0, 1)
            )
            db.execute(
                "INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
                (je_cogs_id, inv_acc_id, "إقفال مخزون مباع", 0, cogs_total, 2)
            )

        db.commit()

        # ── ZATCA: أضف الفاتورة لقائمة الإرسال ─────────────────────────────
        try:
            enqueue_invoice(
                db, biz_id, invoice_id, inv_number,
                {"total": grand_total, "tax": tax_total, "items_count": len(validated)}
            )
        except Exception:
            pass  # ZATCA failure must never block the sale

        # ── Audit Trail ──────────────────────────────────────────────────────
        import json as _json
        write_audit_log(
            db, biz_id, "pos_sale",
            entity_type="invoice", entity_id=invoice_id,
            new_value=_json.dumps({
                "invoice_number": inv_number,
                "total": grand_total,
                "tax": tax_total,
                "payment_method": payment_method,
                "items_count": len(validated),
            }, ensure_ascii=False)
        )

        return jsonify({
            "success":        True,
            "invoice_number": inv_number,
            "invoice_id":     invoice_id,
            "total":          grand_total,
            "payment_method": payment_method,
            "message":        f"تمت عملية البيع بنجاح — فاتورة {inv_number}",
        })

    except Exception as e:
        db.rollback()
        import logging
        logging.getLogger(__name__).error(f"POS checkout error: {e}")
        return jsonify({"success": False, "error": "حدث خطأ أثناء حفظ الفاتورة"}), 500
    finally:
        release_business_lock(biz_id, _lock_token)


# ═══════════════════════════════════════════════════════════════
#  تعليق الفواتير / Suspend Sale
# ═══════════════════════════════════════════════════════════════

def _ensure_suspended_sales_table(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS suspended_sales (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            label       TEXT,
            customer_id INTEGER,
            customer_name TEXT,
            items_json  TEXT DEFAULT '[]',
            subtotal    REAL DEFAULT 0,
            suspended_by INTEGER,
            suspended_at TEXT DEFAULT (datetime('now'))
        )
    """)
    db.commit()


@bp.route("/api/pos/suspend", methods=["POST"])
@onboarding_required
def api_pos_suspend():
    """تعليق فاتورة POS الحالية مؤقتاً"""
    db = get_db()
    biz_id  = session["business_id"]
    user_id = session["user_id"]
    data    = request.get_json(silent=True) or {}

    items = data.get("items", [])
    if not items:
        return jsonify({"success": False, "error": "لا توجد عناصر لتعليقها"}), 400

    _ensure_suspended_sales_table(db)

    label         = (data.get("label") or "").strip() or f"معلقة {datetime.now().strftime('%H:%M')}"
    customer_id   = data.get("customer_id")
    customer_name = (data.get("customer_name") or "").strip()
    subtotal      = sum(
        float(i.get("unit_price", 0)) * float(i.get("quantity", 1))
        for i in items
    )

    db.execute("""
        INSERT INTO suspended_sales
            (business_id, label, customer_id, customer_name, items_json, subtotal, suspended_by)
        VALUES (?,?,?,?,?,?,?)
    """, (
        biz_id, label, customer_id, customer_name,
        json.dumps(items, ensure_ascii=False), round(subtotal, 2), user_id,
    ))
    db.commit()
    suspended_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    return jsonify({
        "success": True,
        "suspended_id": suspended_id,
        "label": label,
        "message": f"تم تعليق الفاتورة: {label}",
    })


@bp.route("/api/pos/suspended")
@onboarding_required
def api_pos_suspended_list():
    """قائمة الفواتير المعلقة"""
    db = get_db()
    biz_id = session["business_id"]
    _ensure_suspended_sales_table(db)

    rows = db.execute(
        """SELECT id, label, customer_name, subtotal, suspended_at, items_json
           FROM suspended_sales WHERE business_id=? ORDER BY suspended_at DESC""",
        (biz_id,)
    ).fetchall()

    suspended = []
    for r in rows:
        item_count = 0
        try:
            item_count = len(json.loads(r["items_json"] or "[]"))
        except Exception:
            item_count = 0
        suspended.append({
            "id": r["id"],
            "label": r["label"],
            "customer_name": r["customer_name"],
            "subtotal": r["subtotal"],
            "suspended_at": r["suspended_at"],
            "items_count": item_count,
        })

    return jsonify({
        "success": True,
        "count": len(suspended),
        "suspended": suspended,
    })


@bp.route("/api/pos/suspended/<int:sale_id>/restore", methods=["POST"])
@onboarding_required
def api_pos_suspended_restore(sale_id):
    """استعادة فاتورة معلقة"""
    db = get_db()
    biz_id = session["business_id"]
    _ensure_suspended_sales_table(db)

    row = db.execute(
        "SELECT * FROM suspended_sales WHERE id=? AND business_id=?",
        (sale_id, biz_id)
    ).fetchone()

    if not row:
        return jsonify({"success": False, "error": "الفاتورة المعلقة غير موجودة"}), 404

    items = json.loads(row["items_json"] or "[]")
    db.execute("DELETE FROM suspended_sales WHERE id=?", (sale_id,))
    db.commit()

    return jsonify({
        "success": True,
        "label": row["label"],
        "customer_id": row["customer_id"],
        "customer_name": row["customer_name"],
        "items": items,
        "subtotal": row["subtotal"],
    })


@bp.route("/api/pos/suspended/<int:sale_id>", methods=["DELETE"])
@onboarding_required
def api_pos_suspended_delete(sale_id):
    """حذف فاتورة معلقة نهائياً"""
    db = get_db()
    biz_id = session["business_id"]
    _ensure_suspended_sales_table(db)

    db.execute(
        "DELETE FROM suspended_sales WHERE id=? AND business_id=?",
        (sale_id, biz_id)
    )
    db.commit()
    return jsonify({"success": True, "message": "تم حذف الفاتورة المعلقة"})
