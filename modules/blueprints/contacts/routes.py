"""
modules/blueprints/contacts/routes.py — إدارة العملاء والموردين
Contacts Management: Customers, Suppliers, Customer Transactions
"""

import json
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, g, redirect, flash
from functools import wraps

bp = Blueprint("contacts", __name__, url_prefix="/contacts")


def _column_exists(db, table: str, column: str) -> bool:
    try:
        rows = db.execute(f"PRAGMA table_info({table})").fetchall()
        return any((r[1] if not isinstance(r, dict) else r.get("name")) == column for r in rows)
    except Exception:
        return False


def require_perm(*perms):
    """التحقق من الصلاحيات"""
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
                    flash("غير مصرح لك بهذا الإجراء", "error")
                    return redirect("/dashboard")
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def log_activity(module, action, entity_id=None, changes=None):
    """تسجيل النشاط"""
    from modules.extensions import get_db
    
    if not g.user or not g.business:
        return
    
    db = get_db()
    db.execute("""
        INSERT INTO audit_logs (business_id, user_id, action, entity_type, entity_id, new_value, ip_address, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
    """, (
        g.business["id"],
        g.user.get("id"),
        action,
        module,
        entity_id,
        json.dumps(changes) if changes else None,
        request.remote_addr
    ))
    db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: CONTACTS DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/")
@require_perm("contacts")
def dashboard():
    """لوحة تحكم جهات الاتصال"""
    from modules.extensions import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    # إحصائيات — الرصيد الحالي = آخر balance_after في المعاملات، أو opening_balance
    stats = db.execute("""
        SELECT
            (SELECT COUNT(*) FROM contacts WHERE business_id = ? AND contact_type = 'customer' AND is_active = 1) as total_customers,
            (SELECT COUNT(*) FROM contacts WHERE business_id = ? AND contact_type = 'supplier' AND is_active = 1) as total_suppliers,
            (SELECT COALESCE(SUM(
                COALESCE((SELECT balance_after FROM customer_transactions WHERE contact_id = c.id ORDER BY id DESC LIMIT 1), c.opening_balance, 0)
            ), 0) FROM contacts c WHERE c.business_id = ? AND c.contact_type = 'customer') as total_receivables,
            (SELECT COALESCE(SUM(
                COALESCE((SELECT balance_after FROM customer_transactions WHERE contact_id = c.id ORDER BY id DESC LIMIT 1), c.opening_balance, 0)
            ), 0) FROM contacts c WHERE c.business_id = ? AND c.contact_type = 'supplier') as total_payables
    """, (business_id, business_id, business_id, business_id)).fetchone()

    # العملاء بأعلى رصيد (كبار العملاء)
    vip_customers = db.execute("""
        SELECT c.id, c.name, c.phone,
            COALESCE((SELECT balance_after FROM customer_transactions WHERE contact_id = c.id ORDER BY id DESC LIMIT 1), c.opening_balance, 0) as balance
        FROM contacts c
        WHERE c.business_id = ? AND c.contact_type = 'customer' AND c.is_active = 1
        ORDER BY balance DESC
        LIMIT 5
    """, (business_id,)).fetchall()

    # العملاء بأعلى دين مستحق
    top_debtors = db.execute("""
        SELECT c.id, c.name, c.phone,
            COALESCE((SELECT balance_after FROM customer_transactions WHERE contact_id = c.id ORDER BY id DESC LIMIT 1), c.opening_balance, 0) as balance,
            0 as credit_limit
        FROM contacts c
        WHERE c.business_id = ? AND c.contact_type = 'customer' AND c.is_active = 1
            AND COALESCE((SELECT balance_after FROM customer_transactions WHERE contact_id = c.id ORDER BY id DESC LIMIT 1), c.opening_balance, 0) > 0
        ORDER BY balance DESC
        LIMIT 5
    """, (business_id,)).fetchall()
    
    # آخر المعاملات
    recent_transactions = db.execute("""
        SELECT ct.*, c.name FROM customer_transactions ct
        JOIN contacts c ON ct.contact_id = c.id
        WHERE ct.business_id = ?
        ORDER BY ct.created_at DESC
        LIMIT 10
    """, (business_id,)).fetchall()
    
    return render_template("contacts/dashboard.html", **{
        "stats": stats,
        "vip_customers": vip_customers,
        "top_debtors": top_debtors,
        "recent_transactions": recent_transactions,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: CUSTOMERS
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/customers")
@require_perm("contacts")
def list_customers():
    """قائمة العملاء"""
    from modules.extensions import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    # فلاتر
    search = request.args.get("search", "")
    category = request.args.get("category", "")  # all, retail, wholesale, vip
    page = int(request.args.get("page", 1))
    per_page = 20
    
    query = """SELECT c.*,
        COALESCE((SELECT balance_after FROM customer_transactions WHERE contact_id = c.id ORDER BY id DESC LIMIT 1), c.opening_balance, 0) as balance
        FROM contacts c WHERE c.business_id = ? AND c.contact_type = 'customer' AND c.is_active = 1"""
    params = [business_id]
    
    if search:
        query += " AND (c.name LIKE ? OR c.phone LIKE ?)"
        search_term = f"%{search}%"
        params.extend([search_term, search_term])
    
    query += " ORDER BY c.name ASC LIMIT ? OFFSET ?"
    params.extend([per_page, (page - 1) * per_page])
    
    customers = db.execute(query, params).fetchall()
    total = db.execute(
        "SELECT COUNT(*) FROM contacts WHERE business_id = ? AND contact_type = 'customer' AND is_active = 1",
        (business_id,)
    ).fetchone()[0]
    
    return render_template("contacts/customers_list.html", **{
        "customers": customers,
        "total": total,
        "page": page,
        "per_page": per_page,
        "search": search,
        "category": category,
    })


@bp.route("/customers/<int:customer_id>")
@require_perm("contacts")
def view_customer(customer_id):
    """عرض تفاصيل العميل"""
    from modules.extensions import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    customer = db.execute("""
        SELECT c.*,
            COALESCE((SELECT balance_after FROM customer_transactions WHERE contact_id = c.id ORDER BY id DESC LIMIT 1), c.opening_balance, 0) as balance
        FROM contacts c
        WHERE c.id = ? AND c.business_id = ? AND c.contact_type = 'customer'
    """, (customer_id, business_id)).fetchone()
    
    if not customer:
        flash("العميل غير موجود", "error")
        return redirect("/contacts/customers")
    
    # معاملات العميل
    transactions = db.execute("""
        SELECT * FROM customer_transactions
        WHERE contact_id = ?
        ORDER BY created_at DESC
        LIMIT 50
    """, (customer_id,)).fetchall()
    
    # الفواتير
    invoices = db.execute("""
        SELECT id, invoice_number, total, created_at
        FROM invoices
        WHERE business_id = ? AND party_id = ? AND invoice_type IN ('sale', 'sale_return')
        ORDER BY created_at DESC
        LIMIT 10
    """, (business_id, customer_id)).fetchall()
    
    return render_template("contacts/customer_detail.html", **{
        "customer": customer,
        "transactions": transactions,
        "invoices": invoices,
    })


@bp.route("/customers/new", methods=["GET", "POST"])
@require_perm("contacts")
def add_customer():
    """إضافة عميل جديد"""
    from modules.extensions import get_db
    
    if request.method == "POST":
        db = get_db()
        business_id = g.business["id"]
        
        data = request.form
        
        has_credit_limit = _column_exists(db, "contacts", "credit_limit")
        if has_credit_limit:
            db.execute("""
                INSERT INTO contacts (
                    business_id, contact_type, name, name_en, phone, email,
                    address, tax_number, opening_balance, credit_limit, is_active, created_at
                ) VALUES (?, 'customer', ?, ?, ?, ?, ?, ?, ?, ?, 1, datetime('now'))
            """, (
                business_id,
                data.get("name"),
                data.get("name_en", ""),
                data.get("phone", ""),
                data.get("email", ""),
                data.get("address", ""),
                data.get("tax_number", ""),
                float(data.get("opening_balance") or 0),
                float(data.get("credit_limit") or 0),
            ))
        else:
            db.execute("""
                INSERT INTO contacts (
                    business_id, contact_type, name, name_en, phone, email,
                    address, tax_number, opening_balance, is_active, created_at
                ) VALUES (?, 'customer', ?, ?, ?, ?, ?, ?, ?, 1, datetime('now'))
            """, (
                business_id,
                data.get("name"),
                data.get("name_en", ""),
                data.get("phone", ""),
                data.get("email", ""),
                data.get("address", ""),
                data.get("tax_number", ""),
                float(data.get("opening_balance") or 0),
            ))
        db.commit()
        
        log_activity("contacts", "add_customer", None, {"name": data.get("name")})
        flash("تم إضافة العميل بنجاح", "success")
        return redirect("/contacts/customers")
    
    return render_template("contacts/customer_form.html")


@bp.route("/customers/<int:customer_id>/edit", methods=["POST"])
@require_perm("contacts")
def edit_customer(customer_id):
    """تعديل بيانات العميل"""
    from modules.extensions import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    data = request.form
    
    has_credit_input = data.get("credit_limit") not in (None, "")
    if _column_exists(db, "contacts", "credit_limit") and has_credit_input:
        db.execute("""
            UPDATE contacts SET
                name = ?, name_en = ?, phone = ?, email = ?, address = ?, tax_number = ?, credit_limit = ?
            WHERE id = ? AND business_id = ? AND contact_type = 'customer'
        """, (
            data.get("name"),
            data.get("name_en", ""),
            data.get("phone", ""),
            data.get("email", ""),
            data.get("address", ""),
            data.get("tax_number", ""),
            float(data.get("credit_limit") or 0),
            customer_id,
            business_id,
        ))
    else:
        db.execute("""
            UPDATE contacts SET
                name = ?, name_en = ?, phone = ?, email = ?, address = ?, tax_number = ?
            WHERE id = ? AND business_id = ? AND contact_type = 'customer'
        """, (
            data.get("name"),
            data.get("name_en", ""),
            data.get("phone", ""),
            data.get("email", ""),
            data.get("address", ""),
            data.get("tax_number", ""),
            customer_id,
            business_id,
        ))
    db.commit()
    
    log_activity("contacts", "edit_customer", customer_id)
    flash("تم تحديث بيانات العميل", "success")
    return redirect(f"/contacts/customers/{customer_id}")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: SUPPLIERS
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/suppliers")
@require_perm("contacts")
def list_suppliers():
    """قائمة الموردين"""
    from modules.extensions import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    search = request.args.get("search", "")
    page = int(request.args.get("page", 1))
    per_page = 20
    
    query = """SELECT c.*,
        COALESCE((SELECT balance_after FROM customer_transactions WHERE contact_id = c.id ORDER BY id DESC LIMIT 1), c.opening_balance, 0) as balance
        FROM contacts c WHERE c.business_id = ? AND c.contact_type = 'supplier' AND c.is_active = 1"""
    params = [business_id]
    
    if search:
        query += " AND (c.name LIKE ? OR c.phone LIKE ?)"
        search_term = f"%{search}%"
        params.extend([search_term, search_term])
    
    query += " ORDER BY c.name ASC LIMIT ? OFFSET ?"
    params.extend([per_page, (page - 1) * per_page])
    
    suppliers = db.execute(query, params).fetchall()
    total = db.execute(
        "SELECT COUNT(*) FROM contacts WHERE business_id = ? AND contact_type = 'supplier'",
        (business_id,)
    ).fetchone()[0]
    
    return render_template("contacts/suppliers_list.html", **{
        "suppliers": suppliers,
        "total": total,
        "page": page,
        "per_page": per_page,
        "search": search,
    })


@bp.route("/suppliers/new", methods=["GET", "POST"])
@require_perm("contacts")
def add_supplier():
    """إضافة مورد جديد"""
    from modules.extensions import get_db
    
    if request.method == "POST":
        db = get_db()
        business_id = g.business["id"]
        
        data = request.form
        
        db.execute("""
            INSERT INTO contacts (
                business_id, contact_type, name, name_en, phone, email,
                address, tax_number, opening_balance, is_active, created_at
            ) VALUES (?, 'supplier', ?, ?, ?, ?, ?, ?, ?, 1, datetime('now'))
        """, (
            business_id,
            data.get("name"),
            data.get("name_en", ""),
            data.get("phone", ""),
            data.get("email", ""),
            data.get("address", ""),
            data.get("tax_number", ""),
            float(data.get("opening_balance") or 0),
        ))
        db.commit()
        
        log_activity("contacts", "add_supplier", None, {"name": data.get("name")})
        flash("تم إضافة المورد بنجاح", "success")
        return redirect("/contacts/suppliers")
    
    return render_template("contacts/supplier_form.html")


@bp.route("/suppliers/<int:supplier_id>")
@require_perm("contacts")
def view_supplier(supplier_id):
    """عرض تفاصيل المورد"""
    from modules.extensions import get_db

    db = get_db()
    business_id = g.business["id"]

    supplier = db.execute("""
        SELECT c.*,
            COALESCE((SELECT balance_after FROM customer_transactions WHERE contact_id = c.id ORDER BY id DESC LIMIT 1), c.opening_balance, 0) as balance
        FROM contacts c
        WHERE c.id = ? AND c.business_id = ? AND c.contact_type = 'supplier'
    """, (supplier_id, business_id)).fetchone()

    if not supplier:
        flash("المورد غير موجود", "error")
        return redirect("/contacts/suppliers")

    transactions = db.execute("""
        SELECT * FROM customer_transactions
        WHERE contact_id = ?
        ORDER BY created_at DESC
        LIMIT 50
    """, (supplier_id,)).fetchall()

    invoices = db.execute("""
        SELECT id, invoice_number, total, created_at
        FROM invoices
        WHERE business_id = ? AND party_id = ? AND invoice_type IN ('purchase', 'purchase_return')
        ORDER BY created_at DESC
        LIMIT 10
    """, (business_id, supplier_id)).fetchall()

    return render_template("contacts/customer_detail.html", **{
        "customer": supplier,
        "transactions": transactions,
        "invoices": invoices,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4: CUSTOMER TRANSACTIONS
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/transactions/<int:customer_id>")
@require_perm("contacts")
def customer_transactions(customer_id):
    """معاملات العميل المفصلة"""
    from modules.extensions import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    customer = db.execute(
        "SELECT * FROM contacts WHERE id = ? AND business_id = ?",
        (customer_id, business_id)
    ).fetchone()
    
    if not customer:
        return "العميل غير موجود", 404
    
    page = int(request.args.get("page", 1))
    per_page = 30
    
    transactions = db.execute("""
        SELECT * FROM customer_transactions
        WHERE contact_id = ?
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
    """, (customer_id, per_page, (page - 1) * per_page)).fetchall()
    
    total = db.execute(
        "SELECT COUNT(*) FROM customer_transactions WHERE contact_id = ?",
        (customer_id,)
    ).fetchone()[0]
    
    return render_template("contacts/transactions.html", **{
        "customer": customer,
        "transactions": transactions,
        "total": total,
        "page": page,
        "per_page": per_page,
    })


@bp.route("/transactions/add", methods=["POST"])
@require_perm("contacts")
def add_transaction():
    """تسجيل معاملة يدوية"""
    from modules.extensions import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    data = request.form
    contact_id = int(data.get("contact_id"))
    
    contact = db.execute(
        "SELECT id FROM contacts WHERE id = ? AND business_id = ?",
        (contact_id, business_id)
    ).fetchone()
    
    if not contact:
        return jsonify({"error": "العميل غير موجود"}), 404
    
    amount = float(data.get("amount"))
    transaction_type = data.get("transaction_type")  # payment, credit_note, etc.
    
    # احسب الرصيد الحالي من آخر معاملة
    last_tx = db.execute(
        "SELECT balance_after FROM customer_transactions WHERE contact_id = ? ORDER BY id DESC LIMIT 1",
        (contact_id,)
    ).fetchone()
    
    opening = db.execute(
        "SELECT opening_balance FROM contacts WHERE id = ?", (contact_id,)
    ).fetchone()
    
    old_balance = last_tx["balance_after"] if last_tx else (opening["opening_balance"] or 0)
    
    if transaction_type in ("payment", "credit_note"):
        new_balance = old_balance - amount
    else:
        new_balance = old_balance + amount
    
    # تسجيل المعاملة
    db.execute("""
        INSERT INTO customer_transactions (
            business_id, contact_id, transaction_type, amount,
            balance_before, balance_after, notes, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
    """, (
        business_id,
        contact_id,
        transaction_type,
        amount,
        old_balance,
        new_balance,
        data.get("notes"),
    ))
    
    db.commit()
    
    log_activity("contacts", f"transaction_{transaction_type}", contact_id, {"amount": amount})
    flash("تم تسجيل المعاملة بنجاح", "success")
    
    return redirect(f"/contacts/transactions/{contact_id}")


# API endpoints
@bp.route("/api/search")
def api_search():
    """API: البحث عن جهات الاتصال"""
    from modules.extensions import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    query = request.args.get("q", "")
    contact_type = request.args.get("type", "customer")  # customer, supplier, all
    
    search_term = f"%{query}%"
    
    sql = "SELECT id, name, phone FROM contacts WHERE business_id = ? AND (name LIKE ? OR phone LIKE ?)"
    params = [business_id, search_term, search_term]
    
    if contact_type != "all":
        sql += " AND contact_type = ?"
        params.append(contact_type)
    
    sql += " LIMIT 10"
    
    results = db.execute(sql, params).fetchall()
    
    return jsonify([dict(r) for r in results])


@bp.route("/api/balance/<int:customer_id>")
def api_balance(customer_id):
    """API: الحصول على رصيد العميل"""
    from modules.extensions import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    last_tx = db.execute(
        "SELECT balance_after FROM customer_transactions WHERE contact_id = ? ORDER BY id DESC LIMIT 1",
        (customer_id,)
    ).fetchone()
    if _column_exists(db, "contacts", "credit_limit"):
        opening = db.execute(
            "SELECT opening_balance, COALESCE(credit_limit, 0) AS credit_limit FROM contacts WHERE id = ? AND business_id = ?",
            (customer_id, business_id)
        ).fetchone()
    else:
        opening = db.execute(
            "SELECT opening_balance, 0 AS credit_limit FROM contacts WHERE id = ? AND business_id = ?",
            (customer_id, business_id)
        ).fetchone()
    
    if opening:
        current_balance = last_tx["balance_after"] if last_tx else (opening["opening_balance"] or 0)
        credit_limit = opening["credit_limit"] or 0
        available_credit = max((credit_limit or 0) - (current_balance or 0), 0)
        return jsonify({
            "current_balance": current_balance,
            "credit_limit": credit_limit,
            "available_credit": available_credit,
        })
    
    return jsonify({"error": "Contact not found"}), 404
