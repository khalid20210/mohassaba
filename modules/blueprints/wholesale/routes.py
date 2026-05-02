"""
modules/blueprints/wholesale/routes.py — قطاع الجملة
Wholesale: Orders, Pricing Lists
"""

from flask import Blueprint, render_template, request, jsonify, g, redirect, flash
from functools import wraps
import json

bp = Blueprint("wholesale", __name__, url_prefix="/wholesale")


def require_perm(*perms):
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
    
    query = "SELECT * FROM orders WHERE business_id = ?"
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
    
    data = request.form
    order_items = request.get_json().get("items", []) if request.is_json else []
    
    subtotal = sum(item["qty"] * item["price"] for item in order_items)
    tax = float(data.get("tax", 0))
    shipping = float(data.get("shipping", 0))
    total = subtotal + tax + shipping
    
    db.execute("""
        INSERT INTO orders (
            business_id, order_number, customer_id, order_date,
            order_items, subtotal, tax_amount, shipping_cost,
            total_amount, order_status, created_by, created_at
        ) VALUES (?, ?, ?, datetime('now'), ?, ?, ?, ?, ?, 'pending', ?, datetime('now'))
    """, (
        business_id,
        data.get("order_number"),
        data.get("customer_id"),
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
        "UPDATE orders SET order_status='delivered', delivered_at=datetime('now') WHERE id=? AND business_id=?",
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
