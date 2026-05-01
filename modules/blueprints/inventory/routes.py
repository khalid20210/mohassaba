"""
modules/blueprints/inventory/routes.py — إدارة المخزون الشاملة
Inventory Management System: Products, Stock Tracking, Alerts, Barcode Integration
"""

import json
import sqlite3
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, jsonify, g, redirect, flash
from functools import wraps

bp = Blueprint("inventory", __name__, url_prefix="/inventory")


def require_perm(*perms):
    """Decorator: التحقق من الصلاحيات"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not g.user or not g.business:
                return redirect("/login")
            
            user_perms = g.user.get("permissions", {})
            # إذا كان المستخدم مالك (all=true) يُسمح له بكل شيء
            if user_perms.get("all"):
                return f(*args, **kwargs)
            
            # وإلا، تحقق من الصلاحيات المطلوبة
            for perm in perms:
                if perm not in user_perms:
                    flash("غير مصرح لك بهذا الإجراء", "error")
                    return redirect("/dashboard")
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def log_activity(module, action, entity_id=None, changes=None):
    """تسجيل النشاط في activity_log"""
    from ..middleware import get_db
    
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
# SECTION 1: INVENTORY DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/")
@require_perm("warehouse")
def dashboard():
    """لوحة تحكم المخزون — ملخص شامل"""
    from ..middleware import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    # إحصائيات عامة
    stats = db.execute("""
        SELECT 
            COUNT(*) as total_products,
            COALESCE(SUM(current_qty), 0) as total_units,
            COALESCE(SUM(current_qty * unit_cost), 0) as total_value
        FROM product_inventory
        WHERE business_id = ?
    """, (business_id,)).fetchone()
    
    # الأصناف منخفضة المخزون
    low_stock = db.execute("""
        SELECT id, sku, current_qty, min_qty, unit_price
        FROM product_inventory
        WHERE business_id = ? AND current_qty <= min_qty
        LIMIT 10
    """, (business_id,)).fetchall()
    
    # الأصناف التي تقارب انتهاء الصلاحية
    expiry_soon = db.execute("""
        SELECT id, sku, expiry_date, current_qty
        FROM product_inventory
        WHERE business_id = ? AND expiry_date IS NOT NULL
        AND expiry_date BETWEEN datetime('now') AND datetime('now', '+30 days')
        ORDER BY expiry_date ASC
        LIMIT 5
    """, (business_id,)).fetchall()
    
    # أعلى الأصناف مبيعاً (في آخر 30 يوم)
    top_sellers = db.execute("""
        SELECT pi.id, pi.sku, SUM(im.quantity) as sold_qty
        FROM product_inventory pi
        LEFT JOIN inventory_movements im ON pi.id = im.product_id
        WHERE pi.business_id = ? AND im.movement_type = 'sale'
        AND im.created_at >= datetime('now', '-30 days')
        GROUP BY pi.id
        ORDER BY sold_qty DESC
        LIMIT 5
    """, (business_id,)).fetchall()
    
    # التنبيهات النشطة
    alerts = db.execute("""
        SELECT id, alert_type, alert_message, created_at
        FROM stock_alerts
        WHERE business_id = ? AND is_resolved = 0
        ORDER BY created_at DESC
        LIMIT 5
    """, (business_id,)).fetchall()
    
    return render_template("inventory/dashboard.html", **{
        "stats": stats,
        "low_stock": low_stock,
        "expiry_soon": expiry_soon,
        "top_sellers": top_sellers,
        "alerts": alerts,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: PRODUCT INVENTORY MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/products")
@require_perm("warehouse")
def list_products():
    """قائمة جميع الأصناف مع فلاتر"""
    from ..middleware import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    # فلاتر
    search = request.args.get("search", "")
    category = request.args.get("category", "")
    status = request.args.get("status", "")  # 'all', 'low_stock', 'overstock', 'expiring'
    page = int(request.args.get("page", 1))
    per_page = 20
    
    # بناء الـ Query
    query = "SELECT * FROM product_inventory WHERE business_id = ?"
    params = [business_id]
    
    if search:
        query += " AND (sku LIKE ? OR location LIKE ?)"
        search_term = f"%{search}%"
        params.extend([search_term, search_term])
    
    if status == "low_stock":
        query += " AND current_qty <= min_qty"
    elif status == "overstock":
        query += " AND current_qty >= max_qty"
    elif status == "expiring":
        query += " AND expiry_date IS NOT NULL AND expiry_date <= datetime('now', '+30 days')"
    
    query += " ORDER BY sku ASC LIMIT ? OFFSET ?"
    params.extend([per_page, (page - 1) * per_page])
    
    products = db.execute(query, params).fetchall()
    total = db.execute(
        "SELECT COUNT(*) FROM product_inventory WHERE business_id = ?",
        (business_id,)
    ).fetchone()[0]
    
    return render_template("inventory/products_list.html", **{
        "products": products,
        "total": total,
        "page": page,
        "per_page": per_page,
        "search": search,
        "status": status,
    })


@bp.route("/products/<int:product_id>")
@require_perm("warehouse")
def view_product(product_id):
    """عرض تفاصيل الصنف"""
    from ..middleware import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    product = db.execute("""
        SELECT * FROM product_inventory
        WHERE id = ? AND business_id = ?
    """, (product_id, business_id)).fetchone()
    
    if not product:
        flash("الصنف غير موجود", "error")
        return redirect("/inventory/products")
    
    # حركات هذا الصنف (آخر 20)
    movements = db.execute("""
        SELECT * FROM inventory_movements
        WHERE product_id = ?
        ORDER BY created_at DESC
        LIMIT 20
    """, (product_id,)).fetchall()
    
    # سجل المسح (للأصناف بها باركود)
    scans = db.execute("""
        SELECT * FROM barcode_scans
        WHERE product_id = ?
        ORDER BY scanned_at DESC
        LIMIT 10
    """, (product_id,)).fetchall()
    
    return render_template("inventory/product_detail.html", **{
        "product": product,
        "movements": movements,
        "scans": scans,
    })


@bp.route("/products/new", methods=["GET", "POST"])
@require_perm("warehouse")
def add_product():
    """إضافة صنف جديد"""
    from ..middleware import get_db
    
    if request.method == "POST":
        db = get_db()
        business_id = g.business["id"]
        
        data = request.form
        
        db.execute("""
            INSERT INTO product_inventory (
                business_id, sku, barcode, current_qty, min_qty, max_qty,
                unit_cost, unit_price, location, supplier_id, notes, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """, (
            business_id,
            data.get("sku"),
            data.get("barcode"),
            float(data.get("current_qty", 0)),
            float(data.get("min_qty", 10)),
            float(data.get("max_qty", 1000)),
            float(data.get("unit_cost", 0)),
            float(data.get("unit_price", 0)),
            data.get("location"),
            data.get("supplier_id") or None,
            data.get("notes"),
        ))
        db.commit()
        
        log_activity("inventory", "add_product", data.get("sku"))
        flash("تم إضافة الصنف بنجاح", "success")
        return redirect("/inventory/products")
    
    return render_template("inventory/product_form.html")


@bp.route("/products/<int:product_id>/edit", methods=["POST"])
@require_perm("warehouse")
def edit_product(product_id):
    """تعديل بيانات الصنف"""
    from ..middleware import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    data = request.form
    
    db.execute("""
        UPDATE product_inventory SET
            min_qty = ?, max_qty = ?, unit_price = ?, location = ?,
            supplier_id = ?, notes = ?, updated_at = datetime('now')
        WHERE id = ? AND business_id = ?
    """, (
        float(data.get("min_qty", 10)),
        float(data.get("max_qty", 1000)),
        float(data.get("unit_price", 0)),
        data.get("location"),
        data.get("supplier_id") or None,
        data.get("notes"),
        product_id,
        business_id,
    ))
    db.commit()
    
    log_activity("inventory", "edit_product", product_id)
    flash("تم تحديث بيانات الصنف", "success")
    return redirect(f"/inventory/products/{product_id}")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: STOCK MOVEMENTS
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/movements")
@require_perm("warehouse")
def list_movements():
    """سجل حركات المخزون"""
    from ..middleware import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    page = int(request.args.get("page", 1))
    per_page = 30
    
    movements = db.execute("""
        SELECT im.*, pi.sku FROM inventory_movements im
        LEFT JOIN product_inventory pi ON im.product_id = pi.id
        WHERE im.business_id = ?
        ORDER BY im.created_at DESC
        LIMIT ? OFFSET ?
    """, (business_id, per_page, (page - 1) * per_page)).fetchall()
    
    total = db.execute(
        "SELECT COUNT(*) FROM inventory_movements WHERE business_id = ?",
        (business_id,)
    ).fetchone()[0]
    
    return render_template("inventory/movements_list.html", **{
        "movements": movements,
        "total": total,
        "page": page,
        "per_page": per_page,
    })


@bp.route("/movements/add", methods=["POST"])
@require_perm("warehouse")
def add_movement():
    """تسجيل حركة مخزون يدوية"""
    from ..middleware import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    data = request.form
    product_id = int(data.get("product_id"))
    quantity = float(data.get("quantity"))
    movement_type = data.get("movement_type")  # adjustment, damage, transfer, etc.
    
    # تحديث الكمية
    product = db.execute(
        "SELECT current_qty FROM product_inventory WHERE id = ? AND business_id = ?",
        (product_id, business_id)
    ).fetchone()
    
    if not product:
        return jsonify({"error": "الصنف غير موجود"}), 404
    
    if movement_type == "adjustment":
        new_qty = product["current_qty"] + quantity
    else:
        new_qty = product["current_qty"] - quantity
    
    if new_qty < 0:
        return jsonify({"error": "الكمية المطلوبة تتجاوز المخزون المتاح"}), 400
    
    # تسجيل الحركة
    db.execute("""
        INSERT INTO inventory_movements (
            business_id, product_id, movement_type, quantity, reason,
            performed_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
    """, (
        business_id,
        product_id,
        movement_type,
        quantity,
        data.get("reason"),
        g.user.get("id"),
    ))
    
    # تحديث الكمية
    db.execute(
        "UPDATE product_inventory SET current_qty = ? WHERE id = ?",
        (new_qty, product_id)
    )
    
    db.commit()
    
    log_activity("inventory", f"movement_{movement_type}", product_id, {"quantity": quantity})
    return jsonify({"success": True, "new_qty": new_qty})


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4: STOCK ALERTS
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/alerts")
@require_perm("warehouse")
def view_alerts():
    """عرض جميع التنبيهات"""
    from ..middleware import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    show_resolved = request.args.get("show_resolved", "0") == "1"
    
    query = "SELECT * FROM stock_alerts WHERE business_id = ?"
    params = [business_id]
    
    if not show_resolved:
        query += " AND is_resolved = 0"
    
    query += " ORDER BY created_at DESC"
    
    alerts = db.execute(query, params).fetchall()
    
    return render_template("inventory/alerts.html", **{
        "alerts": alerts,
        "show_resolved": show_resolved,
    })


@bp.route("/alerts/<int:alert_id>/resolve", methods=["POST"])
@require_perm("warehouse")
def resolve_alert(alert_id):
    """تصنيف التنبيه كمحلول"""
    from ..middleware import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    db.execute("""
        UPDATE stock_alerts
        SET is_resolved = 1, resolved_at = datetime('now')
        WHERE id = ? AND business_id = ?
    """, (alert_id, business_id))
    db.commit()
    
    log_activity("inventory", "resolve_alert", alert_id)
    return jsonify({"success": True})


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5: STOCK COUNTING & PHYSICAL INVENTORY
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/stock-count")
@require_perm("warehouse")
def stock_count():
    """صفحة الجرد الدوري (عد المخزون الفعلي)"""
    from ..middleware import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    products = db.execute("""
        SELECT id, sku, current_qty, unit_price
        FROM product_inventory
        WHERE business_id = ?
        ORDER BY sku ASC
    """, (business_id,)).fetchall()
    
    return render_template("inventory/stock_count.html", **{
        "products": products,
    })


@bp.route("/stock-count/submit", methods=["POST"])
@require_perm("warehouse")
def submit_stock_count():
    """حفظ نتائج الجرد"""
    from ..middleware import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    data = request.get_json()
    counted_items = data.get("items", [])
    
    total_difference = 0
    
    for item in counted_items:
        product_id = item["product_id"]
        physical_qty = float(item["physical_qty"])
        
        product = db.execute(
            "SELECT current_qty FROM product_inventory WHERE id = ? AND business_id = ?",
            (product_id, business_id)
        ).fetchone()
        
        if product:
            system_qty = product["current_qty"]
            difference = physical_qty - system_qty
            total_difference += abs(difference)
            
            if difference != 0:
                # تسجيل التفاوت
                db.execute("""
                    INSERT INTO inventory_movements (
                        business_id, product_id, movement_type, quantity,
                        reason, performed_by, created_at
                    ) VALUES (?, ?, 'adjustment', ?, 'stock_count_difference', ?, datetime('now'))
                """, (business_id, product_id, difference, g.user.get("id")))
                
                # تحديث الكمية
                db.execute(
                    "UPDATE product_inventory SET current_qty = ?, last_stock_check = datetime('now') WHERE id = ?",
                    (physical_qty, product_id)
                )
    
    db.commit()
    
    log_activity("inventory", "stock_count_completed", None, {
        "total_items": len(counted_items),
        "total_difference": total_difference
    })
    
    return jsonify({"success": True, "total_difference": total_difference})


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6: REPORTS
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/reports")
@require_perm("warehouse")
def reports():
    """تقارير المخزون"""
    from ..middleware import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    report_type = request.args.get("type", "inventory_value")
    
    if report_type == "inventory_value":
        # قيمة المخزون الإجمالية
        data = db.execute("""
            SELECT 
                SUM(current_qty * unit_cost) as total_cost,
                SUM(current_qty * unit_price) as total_retail_value,
                COUNT(*) as total_items
            FROM product_inventory
            WHERE business_id = ?
        """, (business_id,)).fetchone()
        
        return render_template("inventory/report_value.html", data=data)
    
    elif report_type == "aging":
        # الأصناف البطيئة (لم تُبع منذ 90 يوم)
        aging_products = db.execute("""
            SELECT pi.sku, pi.current_qty, MAX(im.created_at) as last_movement
            FROM product_inventory pi
            LEFT JOIN inventory_movements im ON pi.id = im.product_id AND im.movement_type = 'sale'
            WHERE pi.business_id = ?
            GROUP BY pi.id
            HAVING last_movement IS NULL OR last_movement < datetime('now', '-90 days')
            ORDER BY last_movement DESC
        """, (business_id,)).fetchall()
        
        return render_template("inventory/report_aging.html", products=aging_products)
    
    return render_template("inventory/reports.html")


# API endpoints
@bp.route("/api/stock/<int:product_id>")
def api_stock(product_id):
    """API: الحصول على الكمية المتاحة"""
    from ..middleware import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    product = db.execute(
        "SELECT current_qty, sku FROM product_inventory WHERE id = ? AND business_id = ?",
        (product_id, business_id)
    ).fetchone()
    
    if product:
        return jsonify({
            "available_qty": product["current_qty"],
            "sku": product["sku"]
        })
    
    return jsonify({"error": "Product not found"}), 404
