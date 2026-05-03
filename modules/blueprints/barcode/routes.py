"""
modules/blueprints/barcode/routes.py — إدارة الباركود
Barcode Management: Generation, Printing, Scanning
"""

import json
import qrcode
from io import BytesIO
from base64 import b64encode
from flask import Blueprint, render_template, request, jsonify, g, redirect, flash, send_file
from functools import wraps

bp = Blueprint("barcode", __name__, url_prefix="/barcode")


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


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: BARCODE DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/")
@require_perm("warehouse")
def dashboard():
    """لوحة تحكم الباركود"""
    from modules.extensions import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    # الإحصائيات
    stats = db.execute("""
        SELECT 
            COUNT(*) as total_barcodes,
            (SELECT COUNT(*) FROM barcode_scans) as total_scans,
            COUNT(DISTINCT product_id) as products_with_barcode
        FROM barcodes
        WHERE business_id = ?
    """, (business_id,)).fetchone()
    
    return render_template("barcode/dashboard.html", stats=stats)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: BARCODE MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/list")
@require_perm("warehouse")
def list_barcodes():
    """قائمة الباركودات"""
    from modules.extensions import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    search = request.args.get("search", "")
    page = int(request.args.get("page", 1))
    per_page = 30
    
    query = "SELECT * FROM barcodes WHERE business_id = ?"
    params = [business_id]
    
    if search:
        query += " AND barcode_value LIKE ?"
        params.append(f"%{search}%")
    
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([per_page, (page - 1) * per_page])
    
    barcodes = db.execute(query, params).fetchall()
    total = db.execute(
        "SELECT COUNT(*) FROM barcodes WHERE business_id = ?",
        (business_id,)
    ).fetchone()[0]
    
    return render_template("barcode/list.html", **{
        "barcodes": barcodes,
        "total": total,
        "page": page,
        "search": search,
    })


@bp.route("/generate", methods=["POST"])
@require_perm("warehouse")
def generate_barcode():
    """إنشاء باركود جديد"""
    from modules.extensions import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    data = request.form
    product_id = data.get("product_id")
    barcode_format = data.get("format", "EAN13")
    quantity = int(data.get("quantity", 1))
    
    for i in range(quantity):
        # توليد رقم الباركود (يمكن تخصيص الخوارزمية)
        barcode_value = f"{business_id}{product_id}{i:06d}"
        
        # إنشاء صورة الباركود
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(barcode_value)
        qr.make(fit=True)
        img = qr.make_image()
        
        # حفظ في قاعدة البيانات
        db.execute("""
            INSERT INTO barcodes (
                business_id, product_id, barcode_value, barcode_format,
                created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, datetime('now'))
        """, (
            business_id,
            product_id,
            barcode_value,
            barcode_format,
            g.user.get("id"),
        ))
    
    db.commit()
    flash(f"تم إنشاء {quantity} باركود بنجاح", "success")
    return redirect("/barcode/list")


@bp.route("/print")
@require_perm("warehouse")
def print_barcodes():
    """طباعة الباركودات"""
    from modules.extensions import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    # تحديد الباركودات المراد طباعتها
    selected_ids = request.args.get("ids", "").split(",")
    
    if selected_ids:
        placeholders = ",".join("?" * len(selected_ids))
        query = f"SELECT * FROM barcodes WHERE id IN ({placeholders}) AND business_id = ?"
        barcodes = db.execute(query, selected_ids + [business_id]).fetchall()
        
        return render_template("barcode/print.html", barcodes=barcodes)
    
    return redirect("/barcode/list")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: BARCODE SCANNING
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/scan", methods=["GET", "POST"])
@require_perm("warehouse")
def scan():
    """صفحة المسح"""
    from modules.extensions import get_db
    
    if request.method == "POST":
        db = get_db()
        business_id = g.business["id"]
        
        data = request.get_json()
        barcode_value = data.get("barcode_value")
        action = data.get("action", "sale")
        quantity = float(data.get("quantity", 1))
        
        # البحث عن الباركود
        barcode = db.execute(
            "SELECT * FROM barcodes WHERE barcode_value = ? AND business_id = ?",
            (barcode_value, business_id)
        ).fetchone()
        
        if not barcode:
            return jsonify({"error": "الباركود غير موجود"}), 404
        
        # تسجيل المسح
        db.execute("""
            INSERT INTO barcode_scans (
                barcode_id, product_id, action, quantity, user_id, scanned_at
            ) VALUES (?, ?, ?, ?, ?, datetime('now'))
        """, (
            barcode["id"],
            barcode["product_id"],
            action,
            quantity,
            g.user.get("id"),
        ))
        
        # تحديث آخر مسح
        db.execute(
            "UPDATE barcodes SET last_scanned_at = datetime('now') WHERE id = ?",
            (barcode["id"],)
        )
        
        db.commit()
        
        return jsonify({
            "success": True,
            "product_id": barcode["product_id"],
            "barcode_value": barcode_value
        })
    
    return render_template("barcode/scan.html")


@bp.route("/api/barcode/<barcode_value>")
def api_get_barcode(barcode_value):
    """API: الحصول على معلومات الباركود"""
    from modules.extensions import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    barcode = db.execute("""
        SELECT b.*, p.name as product_name FROM barcodes b
        LEFT JOIN products p ON b.product_id = p.id
        WHERE b.barcode_value = ? AND b.business_id = ?
    """, (barcode_value, business_id)).fetchone()
    
    if barcode:
        return jsonify(dict(barcode))
    
    return jsonify({"error": "Barcode not found"}), 404


@bp.route("/api/scan", methods=["POST"])
def api_scan():
    """API: تسجيل مسح (من الأجهزة المحمولة أو الكاشيرات)"""
    from modules.extensions import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    data = request.get_json()
    barcode_value = data.get("barcode")
    
    barcode = db.execute(
        "SELECT * FROM barcodes WHERE barcode_value = ? AND business_id = ?",
        (barcode_value, business_id)
    ).fetchone()
    
    if not barcode:
        return jsonify({"error": "Barcode not found"}), 404
    
    # تسجيل المسح
    db.execute("""
        INSERT INTO barcode_scans (
            barcode_id, product_id, action, quantity, user_id, scanned_at
        ) VALUES (?, ?, ?, ?, ?, datetime('now'))
    """, (
        barcode["id"],
        barcode["product_id"],
        data.get("action", "scan"),
        float(data.get("quantity", 1)),
        g.user.get("id"),
    ))
    
    db.commit()
    
    return jsonify({"success": True})
