"""
modules/blueprints/services/routes.py — قطاع الخدمات
Services: Jobs, Contracts
"""

from flask import Blueprint, render_template, request, jsonify, g, redirect, flash
from functools import wraps

bp = Blueprint("services", __name__, url_prefix="/services")


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


# JOBS
@bp.route("/jobs")
@require_perm("sales")
def list_jobs():
    """قائمة أوامر العمل"""
    from ..middleware import get_db
    db = get_db()
    business_id = g.business["id"]
    
    status = request.args.get("status", "")
    
    query = "SELECT * FROM jobs WHERE business_id = ?"
    params = [business_id]
    
    if status:
        query += " AND job_status = ?"
        params.append(status)
    
    query += " ORDER BY scheduled_date DESC"
    jobs = db.execute(query, params).fetchall()
    
    return render_template("services/jobs_list.html", jobs=jobs)


@bp.route("/jobs/new", methods=["POST"])
@require_perm("sales")
def create_job():
    """إنشاء أمر عمل"""
    from ..middleware import get_db
    db = get_db()
    business_id = g.business["id"]
    
    data = request.form
    
    db.execute("""
        INSERT INTO jobs (
            business_id, job_number, client_id, job_type,
            description, location, scheduled_date,
            technician_id, priority, job_status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', datetime('now'))
    """, (
        business_id,
        data.get("job_number"),
        data.get("client_id"),
        data.get("type"),
        data.get("description"),
        data.get("location"),
        data.get("scheduled_date"),
        data.get("technician_id"),
        data.get("priority", "medium"),
    ))
    db.commit()
    
    flash("تم إنشاء أمر العمل", "success")
    return redirect("/services/jobs")


@bp.route("/jobs/<int:job_id>", methods=["GET", "POST"])
@require_perm("sales")
def view_job(job_id):
    """عرض تفاصيل أمر العمل"""
    from ..middleware import get_db
    db = get_db()
    business_id = g.business["id"]
    
    if request.method == "POST":
        data = request.form
        
        db.execute("""
            UPDATE jobs SET
                job_status = ?, actual_cost = ?, notes = ?
            WHERE id = ? AND business_id = ?
        """, (
            data.get("status"),
            float(data.get("cost", 0)),
            data.get("notes"),
            job_id,
            business_id,
        ))
        db.commit()
        
        flash("تم تحديث أمر العمل", "success")
        return redirect(f"/services/jobs/{job_id}")
    
    job = db.execute(
        "SELECT * FROM jobs WHERE id = ? AND business_id = ?",
        (job_id, business_id)
    ).fetchone()
    
    if not job:
        return "أمر العمل غير موجود", 404
    
    return render_template("services/job_detail.html", job=job)


# CONTRACTS
@bp.route("/contracts")
@require_perm("sales")
def list_contracts():
    """قائمة العقود"""
    from ..middleware import get_db
    db = get_db()
    business_id = g.business["id"]
    
    status = request.args.get("status", "")
    
    query = "SELECT * FROM service_contracts WHERE business_id = ?"
    params = [business_id]
    
    if status:
        query += " AND status = ?"
        params.append(status)
    
    query += " ORDER BY start_date DESC"
    contracts = db.execute(query, params).fetchall()
    
    return render_template("services/contracts_list.html", contracts=contracts)


@bp.route("/contracts/new", methods=["POST"])
@require_perm("sales")
def create_contract():
    """إنشاء عقد"""
    from ..middleware import get_db
    db = get_db()
    business_id = g.business["id"]
    
    data = request.form
    
    db.execute("""
        INSERT INTO service_contracts (
            business_id, contract_number, client_id, contract_type,
            start_date, end_date, contract_value, billing_frequency,
            service_description, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', datetime('now'))
    """, (
        business_id,
        data.get("number"),
        data.get("client_id"),
        data.get("type"),
        data.get("start_date"),
        data.get("end_date"),
        float(data.get("value", 0)),
        data.get("billing"),
        data.get("description"),
    ))
    db.commit()
    
    flash("تم إنشاء العقد", "success")
    return redirect("/services/contracts")
