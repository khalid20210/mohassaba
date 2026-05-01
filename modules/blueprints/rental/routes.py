"""
modules/blueprints/rental/routes.py — قطاع تأجير السيارات
Car Rental: Fleet, Contracts, Maintenance
"""

from flask import Blueprint, render_template, request, jsonify, g, redirect, flash
from functools import wraps

bp = Blueprint("rental", __name__, url_prefix="/rental")


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


# FLEET
@bp.route("/fleet")
@require_perm("sales")
def list_fleet():
    """قائمة السيارات"""
    from ..middleware import get_db
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
    from ..middleware import get_db
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
    from ..middleware import get_db
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
    from ..middleware import get_db
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


# MAINTENANCE
@bp.route("/maintenance")
@require_perm("sales")
def list_maintenance():
    """سجل الصيانة"""
    from ..middleware import get_db
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
    from ..middleware import get_db
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
