"""
modules/blueprints/wholesale/routes.py — قطاع الجملة
Wholesale: Orders, Pricing Lists
"""

from flask import Blueprint, render_template, request, jsonify, g, redirect, flash
from functools import wraps
import json
from datetime import datetime
from modules.extensions import safe_sql_identifier

bp = Blueprint("wholesale", __name__, url_prefix="/wholesale")


def _column_exists(db, table: str, column: str) -> bool:
    try:
        safe_table = safe_sql_identifier(table)
        rows = db.execute(f"PRAGMA table_info({safe_table})").fetchall()
        return any((r[1] if not isinstance(r, dict) else r.get("name")) == column for r in rows)
    except Exception:
        return False


def _safe_to_int(val, default=0):
    try:
        return int(val)
    except Exception:
        return default


def _safe_to_float(val, default=0.0):
    try:
        return float(val)
    except Exception:
        return default


def _current_customer_balance(db, contact_id: int) -> float:
    row = db.execute(
        "SELECT balance_after FROM customer_transactions WHERE contact_id=? ORDER BY id DESC LIMIT 1",
        (contact_id,),
    ).fetchone()
    if row:
        return _safe_to_float(row["balance_after"], 0.0)
    opening_row = db.execute(
        "SELECT COALESCE(opening_balance, 0) AS opening_balance FROM contacts WHERE id=?",
        (contact_id,),
    ).fetchone()
    return _safe_to_float(opening_row["opening_balance"], 0.0) if opening_row else 0.0


def _customer_credit_limit(db, contact_id: int) -> float:
    if not _column_exists(db, "contacts", "credit_limit"):
        return 0.0
    row = db.execute(
        "SELECT COALESCE(credit_limit, 0) AS credit_limit FROM contacts WHERE id=?",
        (contact_id,),
    ).fetchone()
    return _safe_to_float(row["credit_limit"], 0.0) if row else 0.0


def require_perm(*perms):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not g.user or not g.business:
                return redirect("/login")
            user_perms = g.user.get("permissions", {})
            if isinstance(user_perms, str):
                try:
                    user_perms = json.loads(user_perms or "{}")
                except Exception:
                    user_perms = {}
            if user_perms.get("all"):
                return f(*args, **kwargs)
            for perm in perms:
                if perm not in user_perms:
                    flash("غير مصرح لك", "error")
                    return redirect("/dashboard")
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ORDERS
@bp.route("/orders")
@require_perm("sales")
def list_orders():
    """قائمة الطلبات"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    
    status = request.args.get("status", "")
    
    query = """
        SELECT o.*, c.name AS customer_name
        FROM orders o
        LEFT JOIN contacts c ON c.id = o.customer_id
        WHERE o.business_id = ?
    """
    params = [business_id]
    
    if status:
        query += " AND order_status = ?"
        params.append(status)
    
    query += " ORDER BY order_date DESC"
    orders = db.execute(query, params).fetchall()
    
    return render_template("wholesale/orders_list.html", orders=orders)


@bp.route("/orders/new", methods=["POST"])
@require_perm("sales")
def create_order():
    """إنشاء طلب جديد"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    
    payload = request.get_json(silent=True) if request.is_json else None
    data = payload or request.form
    order_items = (payload or {}).get("items", []) if payload else []
    
    subtotal = sum(_safe_to_float(item.get("qty"), 0) * _safe_to_float(item.get("price"), 0) for item in order_items)
    tax = _safe_to_float(data.get("tax", 0), 0)
    shipping = _safe_to_float(data.get("shipping", 0), 0)
    total = subtotal + tax + shipping

    customer_id = _safe_to_int(data.get("customer_id"), 0)
    if customer_id:
        balance = _current_customer_balance(db, customer_id)
        credit_limit = _customer_credit_limit(db, customer_id)
        projected = balance + total
        if credit_limit > 0 and projected > credit_limit:
            over = projected - credit_limit
            msg = f"تجاوز سقف الائتمان: الرصيد الحالي {balance:,.2f} + الطلب {total:,.2f} > الحد {credit_limit:,.2f} (فرق {over:,.2f})"
            if request.is_json:
                return jsonify({"success": False, "error": msg}), 400
            flash(msg, "error")
            return redirect("/wholesale/orders")
    
    db.execute("""
        INSERT INTO orders (
            business_id, order_number, customer_id, order_date,
            order_items, subtotal, tax_amount, shipping_cost,
            total_amount, order_status, created_by, created_at
        ) VALUES (?, ?, ?, datetime('now'), ?, ?, ?, ?, ?, 'pending', ?, datetime('now'))
    """, (
        business_id,
        data.get("order_number"),
        customer_id or None,
        json.dumps(order_items),
        subtotal,
        tax,
        shipping,
        total,
        g.user.get("id"),
    ))
    db.commit()
    
    flash("تم إنشاء الطلب", "success")
    return redirect("/wholesale/orders")


@bp.route("/reports/aging")
@require_perm("reports")
def aging_report():
    """تقرير أعمار الديون 30/60/90+ لعملاء الجملة"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]

    rows = db.execute(
        """
        SELECT
            c.id AS customer_id,
            c.name AS customer_name,
            i.id AS invoice_id,
            i.invoice_number,
            i.invoice_date,
            i.due_date,
            COALESCE(i.total, 0) AS total,
            COALESCE(i.paid_amount, 0) AS paid_amount,
            (COALESCE(i.total, 0) - COALESCE(i.paid_amount, 0)) AS outstanding
        FROM invoices i
        LEFT JOIN contacts c ON c.id = i.party_id
        WHERE i.business_id = ?
          AND i.invoice_type = 'sale'
          AND i.status IN ('unpaid', 'partial')
          AND (COALESCE(i.total, 0) - COALESCE(i.paid_amount, 0)) > 0
        ORDER BY i.due_date ASC, i.id DESC
        """,
        (business_id,),
    ).fetchall()

    today = datetime.now().date()
    buckets = {"current": 0.0, "30": 0.0, "60": 0.0, "90": 0.0}
    details = []

    for r in rows:
        due_raw = r["due_date"] or r["invoice_date"]
        days_overdue = 0
        try:
            due_date = datetime.strptime(str(due_raw)[:10], "%Y-%m-%d").date()
            days_overdue = (today - due_date).days
        except Exception:
            days_overdue = 0

        amount = _safe_to_float(r["outstanding"], 0.0)
        if days_overdue <= 0:
            bucket = "current"
        elif days_overdue <= 30:
            bucket = "30"
        elif days_overdue <= 60:
            bucket = "60"
        else:
            bucket = "90"
        buckets[bucket] += amount

        details.append({
            "customer_id": r["customer_id"],
            "customer_name": r["customer_name"] or "—",
            "invoice_number": r["invoice_number"] or f"#{r['invoice_id']}",
            "due_date": str(due_raw)[:10] if due_raw else "—",
            "outstanding": amount,
            "days_overdue": max(days_overdue, 0),
            "bucket": bucket,
        })

    return render_template(
        "wholesale/aging_report.html",
        buckets=buckets,
        details=details,
        total_outstanding=round(sum(buckets.values()), 2),
    )


@bp.route("/customers/<int:customer_id>/statement")
@require_perm("sales")
def customer_statement(customer_id):
    """كشف حساب عميل تفصيلي (فواتير + حركات مدفوعات/قيود)"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]

    customer = db.execute(
        "SELECT * FROM contacts WHERE id=? AND business_id=?",
        (customer_id, business_id),
    ).fetchone()
    if not customer:
        flash("العميل غير موجود", "error")
        return redirect("/wholesale/orders")

    invoices = db.execute(
        """
        SELECT id, invoice_number, invoice_date, due_date, total, paid_amount, status,
               (COALESCE(total,0)-COALESCE(paid_amount,0)) AS outstanding
        FROM invoices
        WHERE business_id=? AND party_id=? AND invoice_type='sale'
        ORDER BY invoice_date DESC, id DESC
        """,
        (business_id, customer_id),
    ).fetchall()

    tx = db.execute(
        """
        SELECT transaction_type, amount, balance_before, balance_after, reference_type, reference_id, notes, created_at
        FROM customer_transactions
        WHERE business_id=? AND contact_id=?
        ORDER BY id DESC
        LIMIT 200
        """,
        (business_id, customer_id),
    ).fetchall()

    current_balance = _current_customer_balance(db, customer_id)
    credit_limit = _customer_credit_limit(db, customer_id)

    return render_template(
        "wholesale/customer_statement.html",
        customer=dict(customer),
        invoices=[dict(x) for x in invoices],
        transactions=[dict(x) for x in tx],
        current_balance=current_balance,
        credit_limit=credit_limit,
        available_credit=max(credit_limit - current_balance, 0) if credit_limit > 0 else 0,
    )


# PRICING LISTS
@bp.route("/pricing")
@require_perm("purchases")
def list_pricing():
    """قوائم الأسعار"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    
    lists = db.execute("""
        SELECT * FROM pricing_lists
        WHERE business_id = ?
        ORDER BY valid_from DESC
    """, (business_id,)).fetchall()
    
    return render_template("wholesale/pricing_lists.html", lists=lists)


@bp.route("/pricing/new", methods=["POST"])
@require_perm("purchases")
def create_pricing_list():
    """إنشاء قائمة أسعار"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    
    data = request.form
    pricing_items = request.get_json().get("items", []) if request.is_json else []
    
    db.execute("""
        INSERT INTO pricing_lists (
            business_id, list_name, description, valid_from,
            valid_until, pricing_items, is_active, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 1, datetime('now'))
    """, (
        business_id,
        data.get("name"),
        data.get("description"),
        data.get("valid_from"),
        data.get("valid_until"),
        json.dumps(pricing_items),
    ))
    db.commit()
    
    flash("تم إنشاء قائمة الأسعار", "success")
    return redirect("/wholesale/pricing")


# ─── ORDER ACTIONS ──────────────────────────────────────────
@bp.route("/orders/<int:order_id>")
@require_perm("sales")
def view_order(order_id):
    """تفاصيل الطلب"""
    from modules.extensions import get_db
    db = get_db()
    bid = g.business["id"]
    order = db.execute(
        "SELECT * FROM orders WHERE id=? AND business_id=?",
        (order_id, bid)
    ).fetchone()
    if not order:
        return "الطلب غير موجود", 404
    order = dict(order)
    order["status"] = order.get("order_status") or order.get("status")
    order["order_items"] = json.loads(order.get("order_items") or "[]")
    return render_template("wholesale/order_detail.html", order=order)


@bp.route("/orders/<int:order_id>/confirm", methods=["POST"])
@require_perm("sales")
def confirm_order(order_id):
    """تأكيد الطلب"""
    from modules.extensions import get_db
    db = get_db()
    db.execute(
        "UPDATE orders SET order_status='confirmed' WHERE id=? AND business_id=?",
        (order_id, g.business["id"])
    )
    db.commit()
    flash("تم تأكيد الطلب ✅", "success")
    return redirect(f"/wholesale/orders/{order_id}")


@bp.route("/orders/<int:order_id>/deliver", methods=["POST"])
@require_perm("sales")
def deliver_order(order_id):
    """تسليم الطلب"""
    from modules.extensions import get_db
    db = get_db()
    db.execute(
        "UPDATE orders SET order_status='delivered' WHERE id=? AND business_id=?",
        (order_id, g.business["id"])
    )
    db.commit()
    flash("تم تسليم الطلب 🚚", "success")
    return redirect(f"/wholesale/orders/{order_id}")


@bp.route("/orders/<int:order_id>/cancel", methods=["POST"])
@require_perm("sales")
def cancel_order(order_id):
    """إلغاء الطلب"""
    from modules.extensions import get_db
    db = get_db()
    db.execute(
        "UPDATE orders SET order_status='cancelled' WHERE id=? AND business_id=?",
        (order_id, g.business["id"])
    )
    db.commit()
    flash("تم إلغاء الطلب", "warning")
    return redirect("/wholesale/orders")


# ─── PRICING ACTIONS ────────────────────────────────────────
@bp.route("/pricing/<int:list_id>")
@require_perm("purchases")
def view_pricing_list(list_id):
    """تفاصيل قائمة الأسعار"""
    from modules.extensions import get_db
    db = get_db()
    bid = g.business["id"]
    pl = db.execute(
        "SELECT * FROM pricing_lists WHERE id=? AND business_id=?",
        (list_id, bid)
    ).fetchone()
    if not pl:
        return "قائمة الأسعار غير موجودة", 404
    pl = dict(pl)
    pl["pricing_items"] = json.loads(pl.get("pricing_items") or "[]")
    return render_template("wholesale/pricing_detail.html", pricing_list=pl)


@bp.route("/pricing/<int:list_id>/toggle", methods=["POST"])
@require_perm("purchases")
def toggle_pricing_list(list_id):
    """تفعيل/تعطيل قائمة الأسعار"""
    from modules.extensions import get_db
    db = get_db()
    bid = g.business["id"]
    current = db.execute("SELECT is_active FROM pricing_lists WHERE id=? AND business_id=?", (list_id, bid)).fetchone()
    if current:
        db.execute("UPDATE pricing_lists SET is_active=? WHERE id=?", (0 if current["is_active"] else 1, list_id))
        db.commit()
    return redirect("/wholesale/pricing")


@bp.route("/api/orders/<int:order_id>")
def api_get_order(order_id):
    """API: الحصول على تفاصيل الطلب"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    
    order = db.execute(
        "SELECT * FROM orders WHERE id = ? AND business_id = ?",
        (order_id, business_id)
    ).fetchone()
    
    if order:
        order_dict = dict(order)
        order_dict["order_items"] = json.loads(order_dict.get("order_items", "[]"))
        return jsonify(order_dict)
    
    return jsonify({"error": "Order not found"}), 404


# ═══════════════════════════════════════════════════════════════
#  تحويل طلب → فاتورة رسمية
# ═══════════════════════════════════════════════════════════════

@bp.route("/orders/<int:order_id>/to-invoice", methods=["POST"])
@require_perm("sales")
def order_to_invoice(order_id):
    """تحويل طلب مؤكد إلى فاتورة بيع رسمية مع قيد محاسبي."""
    from modules.extensions import get_db, next_invoice_number
    db = get_db()
    business_id = g.business["id"]

    order = db.execute(
        "SELECT * FROM orders WHERE id=? AND business_id=?",
        (order_id, business_id)
    ).fetchone()
    if not order:
        flash("الطلب غير موجود", "error")
        return redirect("/wholesale/orders")

    order = dict(order)
    if order["order_status"] not in ("confirmed", "pending"):
        flash("يجب أن يكون الطلب مؤكداً أو معلقاً لتحويله", "error")
        return redirect(f"/wholesale/orders/{order_id}")

    # التحقق من عدم وجود فاتورة مرتبطة مسبقاً
    existing = db.execute(
        "SELECT id FROM invoices WHERE business_id=? AND notes LIKE ?",
        (business_id, f"%order_ref:{order_id}%")
    ).fetchone()
    if existing:
        flash(f"تم تحويل هذا الطلب مسبقاً — الفاتورة #{existing['id']}", "warning")
        return redirect(f"/invoices/{existing['id']}")

    items = json.loads(order.get("order_items") or "[]")
    customer_id = order.get("customer_id")

    # اسم العميل
    customer = None
    if customer_id:
        customer = db.execute("SELECT name FROM contacts WHERE id=?", (customer_id,)).fetchone()

    inv_number = next_invoice_number(db, business_id, "sale")
    due_date_str = request.form.get("due_date", "")

    inv_id = db.execute("""
        INSERT INTO invoices
            (business_id, invoice_number, invoice_type, invoice_date, due_date,
             party_id, party_name, subtotal, tax_amount, total, paid_amount,
             status, notes, created_by, created_at)
        VALUES (?, ?, 'sale', DATE('now'), ?,
                ?, ?, ?, ?, ?, 0,
                'pending', ?, ?, datetime('now'))
    """, (
        business_id, inv_number,
        due_date_str or None,
        customer_id or None,
        customer["name"] if customer else order.get("customer_name", ""),
        _safe_to_float(order.get("subtotal"), 0),
        _safe_to_float(order.get("tax_amount"), 0),
        _safe_to_float(order.get("total_amount"), 0),
        f"محوّلة من طلب #{order_id} | order_ref:{order_id}",
        g.user.get("id"),
    )).lastrowid

    # سطور الفاتورة من عناصر الطلب
    for item in items:
        qty   = _safe_to_float(item.get("qty"), 1)
        price = _safe_to_float(item.get("price"), 0)
        db.execute("""
            INSERT INTO invoice_lines
                (invoice_id, description, quantity, unit_price, total, created_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
        """, (inv_id, item.get("name", "—"), qty, price, qty * price))

    # تحديث حالة الطلب → invoiced
    db.execute(
        "UPDATE orders SET order_status='invoiced' WHERE id=? AND business_id=?",
        (order_id, business_id)
    )
    db.commit()

    flash(f"✓ تم إنشاء الفاتورة {inv_number} بنجاح", "success")
    return redirect(f"/invoices/{inv_id}")


# ═══════════════════════════════════════════════════════════════
#  ديون الموزعين المتأخرة
# ═══════════════════════════════════════════════════════════════

@bp.route("/customers/overdue")
@require_perm("sales")
def customers_overdue():
    """قائمة الموزعين بديون متأخرة مع تفاصيل الفواتير."""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]

    # ديون حسب الموزع
    overdue_by_customer = db.execute("""
        SELECT
            c.id AS customer_id,
            c.name AS customer_name,
            c.phone,
            COUNT(i.id) AS invoice_count,
            ROUND(SUM(i.total - COALESCE(i.paid_amount, 0)), 2) AS total_outstanding,
            MIN(i.due_date) AS oldest_due,
            CAST((julianday('now') - julianday(MIN(i.due_date))) AS INTEGER) AS max_days_overdue
        FROM invoices i
        JOIN contacts c ON c.id = i.party_id
        WHERE i.business_id=? AND i.invoice_type='sale'
          AND i.status IN ('unpaid', 'partial', 'pending')
          AND (i.total - COALESCE(i.paid_amount, 0)) > 0
          AND i.due_date IS NOT NULL
          AND DATE(i.due_date) < DATE('now')
        GROUP BY c.id
        ORDER BY total_outstanding DESC
    """, (business_id,)).fetchall()

    # تفاصيل الفواتير المتأخرة
    overdue_invoices = db.execute("""
        SELECT
            i.id, i.invoice_number, i.invoice_date, i.due_date,
            ROUND(i.total - COALESCE(i.paid_amount, 0), 2) AS outstanding,
            CAST((julianday('now') - julianday(i.due_date)) AS INTEGER) AS days_overdue,
            c.name AS customer_name, c.id AS customer_id
        FROM invoices i
        JOIN contacts c ON c.id = i.party_id
        WHERE i.business_id=? AND i.invoice_type='sale'
          AND i.status IN ('unpaid', 'partial', 'pending')
          AND (i.total - COALESCE(i.paid_amount, 0)) > 0
          AND i.due_date IS NOT NULL
          AND DATE(i.due_date) < DATE('now')
        ORDER BY i.due_date ASC
    """, (business_id,)).fetchall()

    total_overdue = sum(r["total_outstanding"] for r in overdue_by_customer)

    return render_template(
        "wholesale/customers_overdue.html",
        overdue_by_customer=[dict(r) for r in overdue_by_customer],
        overdue_invoices=[dict(r) for r in overdue_invoices],
        total_overdue=round(total_overdue, 2),
    )


# ═══════════════════════════════════════════════════════════════
#  عروض الأسعار (Quotes)
# ═══════════════════════════════════════════════════════════════

def _ensure_quotes_table(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS quotes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            quote_number TEXT NOT NULL,
            customer_id  INTEGER,
            customer_name TEXT,
            quote_date   TEXT DEFAULT (DATE('now')),
            expiry_date  TEXT,
            status       TEXT DEFAULT 'draft',
            subtotal     REAL DEFAULT 0,
            tax_amount   REAL DEFAULT 0,
            total_amount REAL DEFAULT 0,
            notes        TEXT,
            items_json   TEXT DEFAULT '[]',
            created_by   INTEGER,
            created_at   TEXT DEFAULT (datetime('now'))
        )
    """)
    db.commit()


def _next_quote_number(db, business_id):
    row = db.execute(
        "SELECT COUNT(*) AS cnt FROM quotes WHERE business_id=?", (business_id,)
    ).fetchone()
    n = (row["cnt"] or 0) + 1
    return f"QT-{n:05d}"


@bp.route("/quotes")
@require_perm("sales")
def list_quotes():
    """قائمة عروض الأسعار"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    _ensure_quotes_table(db)

    status_filter = request.args.get("status", "")
    q = """
        SELECT qt.*, c.name AS cname
        FROM quotes qt
        LEFT JOIN contacts c ON c.id = qt.customer_id
        WHERE qt.business_id = ?
    """
    params = [business_id]
    if status_filter:
        q += " AND qt.status = ?"
        params.append(status_filter)
    q += " ORDER BY qt.created_at DESC"
    quotes = db.execute(q, params).fetchall()

    return render_template(
        "wholesale/quotes_list.html",
        quotes=[dict(r) for r in quotes],
        status_filter=status_filter,
    )


@bp.route("/quotes/new", methods=["GET", "POST"])
@require_perm("sales")
def create_quote():
    """إنشاء عرض سعر جديد"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    _ensure_quotes_table(db)

    if request.method == "GET":
        customers = db.execute(
            "SELECT id, name FROM contacts WHERE business_id=? AND contact_type='customer' AND is_active=1 ORDER BY name",
            (business_id,)
        ).fetchall()
        products = db.execute(
            "SELECT id, name, sale_price, barcode FROM products WHERE business_id=? AND is_active=1 ORDER BY name",
            (business_id,)
        ).fetchall()
        return render_template(
            "wholesale/quote_form.html",
            customers=[dict(c) for c in customers],
            products=[dict(p) for p in products],
        )

    # POST — حفظ العرض
    data = request.get_json(silent=True) or request.form
    customer_id   = _safe_to_int(data.get("customer_id"), 0) or None
    customer_name = (data.get("customer_name") or "").strip()
    expiry_date   = (data.get("expiry_date") or "").strip() or None
    notes         = (data.get("notes") or "").strip()
    items_raw     = data.get("items") or "[]"
    if not isinstance(items_raw, str):
        items_raw = json.dumps(items_raw, ensure_ascii=False)

    try:
        items = json.loads(items_raw)
    except Exception:
        items = []

    subtotal = sum(_safe_to_float(i.get("price"), 0) * _safe_to_float(i.get("qty"), 1) for i in items)
    tax_pct  = _safe_to_float(data.get("tax_pct"), 15)
    tax_amt  = round(subtotal * tax_pct / 100, 2)
    total    = round(subtotal + tax_amt, 2)

    if customer_id:
        c = db.execute("SELECT name FROM contacts WHERE id=? AND business_id=?", (customer_id, business_id)).fetchone()
        if c:
            customer_name = c["name"]

    q_number = _next_quote_number(db, business_id)
    db.execute("""
        INSERT INTO quotes (business_id, quote_number, customer_id, customer_name,
            expiry_date, subtotal, tax_amount, total_amount, notes, items_json, created_by)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (business_id, q_number, customer_id, customer_name,
          expiry_date, subtotal, tax_amt, total, notes, items_raw, g.user.get("id")))
    db.commit()
    quote_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    if request.is_json:
        return jsonify({"success": True, "quote_id": quote_id, "quote_number": q_number})
    flash(f"تم إنشاء عرض السعر {q_number}", "success")
    return redirect(f"/wholesale/quotes/{quote_id}")


@bp.route("/quotes/<int:quote_id>")
@require_perm("sales")
def view_quote(quote_id):
    """تفاصيل عرض سعر"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    _ensure_quotes_table(db)

    quote = db.execute(
        "SELECT * FROM quotes WHERE id=? AND business_id=?", (quote_id, business_id)
    ).fetchone()
    if not quote:
        flash("عرض السعر غير موجود", "error")
        return redirect("/wholesale/quotes")

    items = json.loads(quote["items_json"] or "[]")
    return render_template(
        "wholesale/quote_detail.html",
        quote=dict(quote),
        items=items,
    )


@bp.route("/quotes/<int:quote_id>/to-order", methods=["POST"])
@require_perm("sales")
def quote_to_order(quote_id):
    """تحويل عرض سعر إلى طلب جملة"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    _ensure_quotes_table(db)

    quote = db.execute(
        "SELECT * FROM quotes WHERE id=? AND business_id=?", (quote_id, business_id)
    ).fetchone()
    if not quote:
        flash("عرض السعر غير موجود", "error")
        return redirect("/wholesale/quotes")
    if quote["status"] in ("converted", "cancelled"):
        flash("هذا العرض محوّل أو ملغى", "warning")
        return redirect(f"/wholesale/quotes/{quote_id}")

    # إنشاء الطلب
    from modules.extensions import next_invoice_number
    order_num = next_invoice_number(db, business_id, "sale")
    items = json.loads(quote["items_json"] or "[]")

    order_id = db.execute("""
        INSERT INTO orders (business_id, order_number, customer_id, customer_name,
            order_date, order_status, subtotal, tax_amount, total_amount, notes, order_items, created_by)
        VALUES (?,?,?,?,DATE('now'),'pending',?,?,?,?,?,?)
    """, (
        business_id, order_num,
        quote["customer_id"], quote["customer_name"],
        _safe_to_float(quote["subtotal"]),
        _safe_to_float(quote["tax_amount"]),
        _safe_to_float(quote["total_amount"]),
        f"محوّل من عرض سعر #{quote['quote_number']}",
        quote["items_json"],
        g.user.get("id"),
    )).lastrowid

    db.execute("UPDATE quotes SET status='converted' WHERE id=?", (quote_id,))
    db.commit()

    flash(f"تم تحويل العرض إلى طلب #{order_num}", "success")
    return redirect(f"/wholesale/orders/{order_id}")


@bp.route("/quotes/<int:quote_id>/cancel", methods=["POST"])
@require_perm("sales")
def cancel_quote(quote_id):
    """إلغاء عرض سعر"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    _ensure_quotes_table(db)
    db.execute(
        "UPDATE quotes SET status='cancelled' WHERE id=? AND business_id=?",
        (quote_id, business_id)
    )
    db.commit()
    flash("تم إلغاء عرض السعر", "info")
    return redirect("/wholesale/quotes")


# ═══════════════════════════════════════════════════════════════
#  سندات القبض (Receipt Vouchers)
# ═══════════════════════════════════════════════════════════════

def _ensure_receipts_table(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS receipt_vouchers (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id   INTEGER NOT NULL,
            voucher_number TEXT NOT NULL,
            contact_id    INTEGER,
            contact_name  TEXT,
            amount        REAL NOT NULL,
            payment_method TEXT DEFAULT 'cash',
            cheque_number TEXT,
            bank_name     TEXT,
            receipt_date  TEXT DEFAULT (DATE('now')),
            notes         TEXT,
            created_by    INTEGER,
            created_at    TEXT DEFAULT (datetime('now'))
        )
    """)
    db.commit()


def _next_voucher_number(db, business_id):
    row = db.execute(
        "SELECT COUNT(*) AS cnt FROM receipt_vouchers WHERE business_id=?", (business_id,)
    ).fetchone()
    n = (row["cnt"] or 0) + 1
    return f"RV-{n:05d}"


@bp.route("/receipts")
@require_perm("sales")
def list_receipts():
    """قائمة سندات القبض"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    _ensure_receipts_table(db)

    date_from = request.args.get("from", "")
    date_to   = request.args.get("to", "")

    q = "SELECT * FROM receipt_vouchers WHERE business_id=?"
    params = [business_id]
    if date_from:
        q += " AND receipt_date >= ?"; params.append(date_from)
    if date_to:
        q += " AND receipt_date <= ?"; params.append(date_to)
    q += " ORDER BY created_at DESC"

    vouchers = db.execute(q, params).fetchall()
    total = sum(r["amount"] for r in vouchers)

    return render_template(
        "wholesale/receipts_list.html",
        vouchers=[dict(r) for r in vouchers],
        date_from=date_from,
        date_to=date_to,
        total=round(total, 2),
    )


@bp.route("/receipts/new", methods=["GET", "POST"])
@require_perm("sales")
def create_receipt():
    """إنشاء سند قبض جديد"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    _ensure_receipts_table(db)

    if request.method == "GET":
        customers = db.execute(
            "SELECT id, name FROM contacts WHERE business_id=? AND contact_type='customer' AND is_active=1 ORDER BY name",
            (business_id,)
        ).fetchall()
        from datetime import datetime as _dt
        return render_template(
            "wholesale/receipt_form.html",
            customers=[dict(c) for c in customers],
            today=_dt.now().strftime("%Y-%m-%d"),
        )

    data           = request.form
    contact_id     = _safe_to_int(data.get("contact_id"), 0) or None
    contact_name   = (data.get("contact_name") or "").strip()
    amount         = _safe_to_float(data.get("amount"), 0)
    payment_method = (data.get("payment_method") or "cash").strip()
    cheque_number  = (data.get("cheque_number") or "").strip() or None
    bank_name      = (data.get("bank_name") or "").strip() or None
    receipt_date   = (data.get("receipt_date") or "").strip() or None
    notes          = (data.get("notes") or "").strip()

    if amount <= 0:
        flash("المبلغ يجب أن يكون أكبر من صفر", "error")
        return redirect("/wholesale/receipts/new")

    if contact_id:
        c = db.execute("SELECT name FROM contacts WHERE id=? AND business_id=?", (contact_id, business_id)).fetchone()
        if c:
            contact_name = c["name"]

    v_number = _next_voucher_number(db, business_id)
    db.execute("""
        INSERT INTO receipt_vouchers
            (business_id, voucher_number, contact_id, contact_name, amount,
             payment_method, cheque_number, bank_name, receipt_date, notes, created_by)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (
        business_id, v_number, contact_id, contact_name, amount,
        payment_method, cheque_number, bank_name, receipt_date, notes, g.user.get("id"),
    ))

    # تسجيل في customer_transactions إذا كان العميل معروفاً
    if contact_id:
        prev = db.execute(
            "SELECT balance_after FROM customer_transactions WHERE contact_id=? ORDER BY id DESC LIMIT 1",
            (contact_id,)
        ).fetchone()
        prev_bal = _safe_to_float(prev["balance_after"] if prev else 0, 0)
        new_bal  = round(prev_bal - amount, 2)  # القبض يقلّل الرصيد
        db.execute("""
            INSERT INTO customer_transactions
                (business_id, contact_id, transaction_type, amount, balance_after,
                 reference_type, notes, created_at)
            VALUES (?,?,'receipt',?,?,?,'receipt',?)
        """, (business_id, contact_id, amount, new_bal, v_number,
              datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    db.commit()
    flash(f"تم إنشاء سند القبض {v_number} بنجاح", "success")
    return redirect("/wholesale/receipts")
