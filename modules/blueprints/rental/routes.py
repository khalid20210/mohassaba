"""
modules/blueprints/rental/routes.py — قطاع تأجير السيارات
Car Rental: Fleet, Contracts, Maintenance
"""

from flask import Blueprint, render_template, request, jsonify, g, redirect, flash
from functools import wraps
import json

bp = Blueprint("rental", __name__, url_prefix="/rental")


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


# FLEET
@bp.route("/fleet")
@require_perm("sales")
def list_fleet():
    """قائمة السيارات"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    
    status = request.args.get("status", "")
    
    query = "SELECT * FROM fleet_vehicles WHERE business_id = ?"
    params = [business_id]
    
    if status:
        query += " AND status = ?"
        params.append(status)
    
    query += " ORDER BY vehicle_name ASC"
    vehicles = db.execute(query, params).fetchall()
    
    return render_template("rental/fleet_list.html", vehicles=vehicles)


@bp.route("/fleet/new", methods=["POST"])
@require_perm("sales")
def add_vehicle():
    """إضافة سيارة جديدة"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    
    data = request.form
    
    db.execute("""
        INSERT INTO fleet_vehicles (
            business_id, vehicle_name, plate_number, vin, vehicle_type,
            make, model, year, purchase_date, purchase_cost,
            rental_rate_daily, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'available', datetime('now'), datetime('now'))
    """, (
        business_id,
        data.get("name"),
        data.get("plate"),
        data.get("vin"),
        data.get("type"),
        data.get("make"),
        data.get("model"),
        data.get("year"),
        data.get("purchase_date"),
        float(data.get("cost", 0)),
        float(data.get("rate_daily", 0)),
    ))
    db.commit()
    
    flash("تم إضافة السيارة", "success")
    return redirect("/rental/fleet")


# CONTRACTS
@bp.route("/contracts")
@require_perm("sales")
def list_contracts():
    """قائمة عقود الإيجار"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    
    query = """
        SELECT rc.*, fv.vehicle_name, c.name as renter_name
        FROM rental_contracts rc
        JOIN fleet_vehicles fv ON rc.vehicle_id = fv.id
        LEFT JOIN contacts c ON rc.renter_id = c.id
        WHERE rc.business_id = ?
        ORDER BY rc.rental_start_date DESC
    """
    contracts = db.execute(query, (business_id,)).fetchall()
    
    return render_template("rental/contracts_list.html", contracts=contracts)


@bp.route("/contracts/new", methods=["POST"])
@require_perm("sales")
def create_contract():
    """إنشاء عقد إيجار"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    
    data = request.form
    daily_rate = float(data.get("daily_rate", 0))
    
    db.execute("""
        INSERT INTO rental_contracts (
            business_id, vehicle_id, renter_id, rental_start_date,
            rental_type, daily_rate, total_amount, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', datetime('now'))
    """, (
        business_id,
        data.get("vehicle_id"),
        data.get("renter_id"),
        data.get("start_date"),
        data.get("rental_type"),
        daily_rate,
        daily_rate * int(data.get("days", 1)),
    ))
    db.commit()
    
    # تحديث حالة السيارة
    db.execute(
        "UPDATE fleet_vehicles SET status = 'rented' WHERE id = ?",
        (data.get("vehicle_id"),)
    )
    db.commit()
    
    flash("تم إنشاء العقد", "success")
    return redirect("/rental/contracts")


@bp.route("/contracts/<int:contract_id>")
@require_perm("sales")
def view_contract(contract_id):
    """تفاصيل عقد الإيجار"""
    from modules.extensions import get_db
    db = get_db()
    bid = g.business["id"]
    contract = db.execute("""
        SELECT rc.*, fv.vehicle_name, fv.plate_number, c.name as renter_name, c.phone as renter_phone
        FROM rental_contracts rc
        JOIN fleet_vehicles fv ON rc.vehicle_id = fv.id
        LEFT JOIN contacts c ON rc.renter_id = c.id
        WHERE rc.id=? AND rc.business_id=?
    """, (contract_id, bid)).fetchone()
    if not contract:
        return "العقد غير موجود", 404
    return render_template("rental/contract_detail.html", contract=contract)


@bp.route("/contracts/<int:contract_id>/close", methods=["POST"])
@require_perm("sales")
def close_contract(contract_id):
    """إنهاء عقد الإيجار وإعادة السيارة"""
    from modules.extensions import get_db
    db = get_db()
    bid = g.business["id"]
    contract = db.execute(
        "SELECT vehicle_id FROM rental_contracts WHERE id=? AND business_id=?",
        (contract_id, bid)
    ).fetchone()
    if contract:
        db.execute(
            "UPDATE rental_contracts SET status='closed', rental_end_date=date('now') WHERE id=?",
            (contract_id,)
        )
        db.execute(
            "UPDATE fleet_vehicles SET status='available' WHERE id=?",
            (contract["vehicle_id"],)
        )
        db.commit()
    flash("تم إنهاء عقد الإيجار وإعادة السيارة ✅", "success")
    return redirect("/rental/contracts")


@bp.route("/fleet/<int:vehicle_id>")
@require_perm("sales")
def view_vehicle(vehicle_id):
    """تفاصيل السيارة"""
    from modules.extensions import get_db
    db = get_db()
    bid = g.business["id"]
    vehicle = db.execute(
        "SELECT * FROM fleet_vehicles WHERE id=? AND business_id=?",
        (vehicle_id, bid)
    ).fetchone()
    if not vehicle:
        return "السيارة غير موجودة", 404
    contracts = db.execute(
        "SELECT * FROM rental_contracts WHERE vehicle_id=? ORDER BY rental_start_date DESC LIMIT 10",
        (vehicle_id,)
    ).fetchall()
    maintenance = db.execute(
        "SELECT * FROM maintenance_records WHERE vehicle_id=? ORDER BY service_date DESC LIMIT 10",
        (vehicle_id,)
    ).fetchall()
    return render_template("rental/vehicle_detail.html", vehicle=vehicle, contracts=contracts, maintenance=maintenance)


@bp.route("/fleet/<int:vehicle_id>/update", methods=["POST"])
@require_perm("sales")
def update_vehicle(vehicle_id):
    """تحديث بيانات السيارة"""
    from modules.extensions import get_db
    db = get_db()
    data = request.form
    db.execute("""
        UPDATE fleet_vehicles SET
            rental_rate_daily=?, status=?, notes=?
        WHERE id=? AND business_id=?
    """, (
        float(data.get("rate_daily", 0)),
        data.get("status", "available"),
        data.get("notes", ""),
        vehicle_id, g.business["id"]
    ))
    db.commit()
    flash("تم تحديث بيانات السيارة", "success")
    return redirect(f"/rental/fleet/{vehicle_id}")


# ─── API ────────────────────────────────────────────────────
@bp.route("/api/fleet/available")
def api_available_fleet():
    """API: السيارات المتاحة"""
    from modules.extensions import get_db
    db = get_db()
    bid = g.business["id"]
    vehicles = db.execute(
        "SELECT id, vehicle_name, plate_number, rental_rate_daily FROM fleet_vehicles WHERE business_id=? AND status='available'",
        (bid,)
    ).fetchall()
    return jsonify([dict(v) for v in vehicles])


@bp.route("/api/stats")
@require_perm("sales")
def api_rental_stats():
    """إحصائيات الأسطول"""
    from modules.extensions import get_db
    db = get_db()
    bid = g.business["id"]
    total = db.execute("SELECT COUNT(*) FROM fleet_vehicles WHERE business_id=?", (bid,)).fetchone()[0]
    rented = db.execute("SELECT COUNT(*) FROM fleet_vehicles WHERE business_id=? AND status='rented'", (bid,)).fetchone()[0]
    maint = db.execute("SELECT COUNT(*) FROM fleet_vehicles WHERE business_id=? AND status='maintenance'", (bid,)).fetchone()[0]
    revenue = db.execute(
        "SELECT COALESCE(SUM(total_amount),0) FROM rental_contracts WHERE business_id=? AND strftime('%Y-%m',rental_start_date)=strftime('%Y-%m','now')",
        (bid,)
    ).fetchone()[0]
    return jsonify({"total": total, "rented": rented, "maintenance": maint, "available": total-rented-maint, "monthly_revenue": revenue})
@bp.route("/maintenance")
@require_perm("sales")
def list_maintenance():
    """سجل الصيانة"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    
    query = """
        SELECT mr.*, fv.vehicle_name
        FROM maintenance_records mr
        JOIN fleet_vehicles fv ON mr.vehicle_id = fv.id
        WHERE mr.business_id = ?
        ORDER BY mr.service_date DESC
    """
    records = db.execute(query, (business_id,)).fetchall()
    
    return render_template("rental/maintenance_list.html", records=records)


@bp.route("/maintenance/new", methods=["POST"])
@require_perm("sales")
def add_maintenance():
    """تسجيل صيانة"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    
    data = request.form
    
    db.execute("""
        INSERT INTO maintenance_records (
            business_id, vehicle_id, maintenance_type, description,
            cost, service_provider, service_date, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
    """, (
        business_id,
        data.get("vehicle_id"),
        data.get("type"),
        data.get("description"),
        float(data.get("cost", 0)),
        data.get("provider"),
    ))
    db.commit()
    
    flash("تم تسجيل الصيانة", "success")
    return redirect("/rental/maintenance")
