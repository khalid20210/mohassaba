"""
modules/blueprints/contacts/routes.py — إدارة العملاء والموردين
Contacts Management: Customers, Suppliers, Customer Transactions
"""

import json
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, g, redirect, flash
from functools import wraps

bp = Blueprint("contacts", __name__, url_prefix="/contacts")


def require_perm(*perms):
    """التحقق من الصلاحيات"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not g.user or not g.business:
                return redirect("/login")
            
            user_perms = g.user.get("permissions", {})
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
        INSERT INTO activity_log (business_id, module, action, entity_id, changes_json, user_id, ip_address, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
    """, (
        g.business["id"],
        module,
        action,
        entity_id,
        json.dumps(changes) if changes else None,
        g.user.get("id"),
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
    
    # إحصائيات
    stats = db.execute("""
        SELECT 
            (SELECT COUNT(*) FROM contacts WHERE business_id = ? AND contact_type = 'customer') as total_customers,
            (SELECT COUNT(*) FROM contacts WHERE business_id = ? AND contact_type = 'supplier') as total_suppliers,
            (SELECT COALESCE(SUM(current_balance), 0) FROM contacts WHERE business_id = ? AND contact_type = 'customer') as customer_debts,
            (SELECT COALESCE(SUM(current_balance), 0) FROM contacts WHERE business_id = ? AND contact_type = 'supplier') as supplier_credits
    """, (business_id, business_id, business_id, business_id)).fetchone()
    
    # العملاء المميزين (VIP)
    vip_customers = db.execute("""
        SELECT id, name, phone, current_balance, category
        FROM contacts
        WHERE business_id = ? AND contact_type = 'customer' AND category = 'vip'
        ORDER BY current_balance DESC
        LIMIT 5
    """, (business_id,)).fetchall()
    
    # العملاء بأعلى دين
    top_debtors = db.execute("""
        SELECT id, name, phone, current_balance
        FROM contacts
        WHERE business_id = ? AND contact_type = 'customer' AND current_balance > 0
        ORDER BY current_balance DESC
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
    
    query = "SELECT * FROM contacts WHERE business_id = ? AND contact_type = 'customer'"
    params = [business_id]
    
    if search:
        query += " AND (name LIKE ? OR phone LIKE ?)"
        search_term = f"%{search}%"
        params.extend([search_term, search_term])
    
    if category and category != "all":
        query += " AND category = ?"
        params.append(category)
    
    query += " ORDER BY name ASC LIMIT ? OFFSET ?"
    params.extend([per_page, (page - 1) * per_page])
    
    customers = db.execute(query, params).fetchall()
    total = db.execute(
        "SELECT COUNT(*) FROM contacts WHERE business_id = ? AND contact_type = 'customer'",
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
        SELECT * FROM contacts
        WHERE id = ? AND business_id = ? AND contact_type = 'customer'
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
        SELECT id, number, total, created_at
        FROM invoices
        WHERE business_id = ? AND customer_id = ?
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
        
        db.execute("""
            INSERT INTO contacts (
                business_id, contact_type, name, company_name, phone, email,
                address, city, country, tax_id, credit_limit, category,
                notes, is_active, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """, (
            business_id,
            "customer",
            data.get("name"),
            data.get("company_name"),
            data.get("phone"),
            data.get("email"),
            data.get("address"),
            data.get("city"),
            data.get("country"),
            data.get("tax_id"),
            float(data.get("credit_limit", 0)),
            data.get("category", "regular"),
            data.get("notes"),
            1,
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
    
    db.execute("""
        UPDATE contacts SET
            name = ?, company_name = ?, email = ?, address = ?,
            city = ?, country = ?, tax_id = ?, credit_limit = ?,
            category = ?, notes = ?, updated_at = datetime('now')
        WHERE id = ? AND business_id = ? AND contact_type = 'customer'
    """, (
        data.get("name"),
        data.get("company_name"),
        data.get("email"),
        data.get("address"),
        data.get("city"),
        data.get("country"),
        data.get("tax_id"),
        float(data.get("credit_limit", 0)),
        data.get("category", "regular"),
        data.get("notes"),
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
    
    query = "SELECT * FROM contacts WHERE business_id = ? AND contact_type = 'supplier'"
    params = [business_id]
    
    if search:
        query += " AND (name LIKE ? OR phone LIKE ?)"
        search_term = f"%{search}%"
        params.extend([search_term, search_term])
    
    query += " ORDER BY name ASC LIMIT ? OFFSET ?"
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
                business_id, contact_type, name, company_name, phone, email,
                address, city, country, tax_id, iban, notes, is_active,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """, (
            business_id,
            "supplier",
            data.get("name"),
            data.get("company_name"),
            data.get("phone"),
            data.get("email"),
            data.get("address"),
            data.get("city"),
            data.get("country"),
            data.get("tax_id"),
            data.get("iban"),
            data.get("notes"),
            1,
        ))
        db.commit()
        
        log_activity("contacts", "add_supplier", None, {"name": data.get("name")})
        flash("تم إضافة المورد بنجاح", "success")
        return redirect("/contacts/suppliers")
    
    return render_template("contacts/supplier_form.html")


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
        "SELECT current_balance FROM contacts WHERE id = ? AND business_id = ?",
        (contact_id, business_id)
    ).fetchone()
    
    if not contact:
        return jsonify({"error": "العميل غير موجود"}), 404
    
    amount = float(data.get("amount"))
    transaction_type = data.get("transaction_type")  # payment, credit_note, etc.
    
    old_balance = contact["current_balance"]
    
    if transaction_type == "payment":
        new_balance = old_balance - amount
    elif transaction_type == "credit_note":
        new_balance = old_balance - amount
    else:
        new_balance = old_balance
    
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
    
    # تحديث الرصيد
    db.execute(
        "UPDATE contacts SET current_balance = ? WHERE id = ?",
        (new_balance, contact_id)
    )
    
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
    
    sql = "SELECT id, name, phone, category FROM contacts WHERE business_id = ? AND (name LIKE ? OR phone LIKE ?)"
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
    
    contact = db.execute(
        "SELECT current_balance, credit_limit FROM contacts WHERE id = ? AND business_id = ?",
        (customer_id, business_id)
    ).fetchone()
    
    if contact:
        return jsonify({
            "current_balance": contact["current_balance"],
            "credit_limit": contact["credit_limit"],
            "available_credit": contact["credit_limit"] - contact["current_balance"],
        })
    
    return jsonify({"error": "Contact not found"}), 404
