"""
modules/blueprints/services/routes.py — قطاع الخدمات
Services: Jobs, Contracts
"""

from flask import Blueprint, render_template, request, jsonify, g, redirect, flash
from functools import wraps
import json

bp = Blueprint("services", __name__, url_prefix="/services")


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


# JOBS
@bp.route("/jobs")
@require_perm("sales")
def list_jobs():
    """قائمة أوامر العمل"""
    from modules.extensions import get_db
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


@bp.route("/jobs/new", methods=["GET", "POST"])
@require_perm("sales")
def create_job():
    """إنشاء أمر عمل"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    
    if request.method == "GET":
        return redirect("/services/jobs?open_new=1")
    
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
    from modules.extensions import get_db
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
    from modules.extensions import get_db
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


@bp.route("/contracts/new", methods=["GET", "POST"])
@require_perm("sales")
def create_contract():
    """إنشاء عقد"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]

    if request.method == "GET":
        return redirect("/services/contracts?open_new=1")

    data = request.form

    # توليد رقم العقد تلقائياً
    cnt = db.execute(
        "SELECT COUNT(*)+1 AS n FROM service_contracts WHERE business_id=?",
        (business_id,)
    ).fetchone()
    contract_number = data.get("number") or f"SVC-{(cnt['n'] if cnt else 1):05d}"

    db.execute("""
        INSERT INTO service_contracts (
            business_id, contract_number, client_id, contract_type,
            start_date, end_date, contract_value, billing_frequency,
            service_description, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', datetime('now'))
    """, (
        business_id,
        contract_number,
        data.get("client_id"),
        data.get("type"),
        data.get("start_date"),
        data.get("end_date"),
        float(data.get("value", 0) or 0),
        data.get("billing"),
        data.get("description"),
    ))
    db.commit()

    flash("تم إنشاء العقد", "success")
    return redirect("/services/contracts")


# ─── JOBS ACTIONS ───────────────────────────────────────────
@bp.route("/jobs/<int:job_id>/start", methods=["POST"])
@require_perm("sales")
def start_job(job_id):
    """بدء تنفيذ أمر العمل"""
    from modules.extensions import get_db
    db = get_db()
    db.execute(
        "UPDATE jobs SET job_status='in_progress' WHERE id=? AND business_id=?",
        (job_id, g.business["id"])
    )
    db.commit()
    flash("تم بدء التنفيذ", "success")
    return redirect(f"/services/jobs/{job_id}")


@bp.route("/jobs/<int:job_id>/complete", methods=["POST"])
@require_perm("sales")
def complete_job(job_id):
    """إغلاق أمر العمل كمنجز"""
    from modules.extensions import get_db
    db = get_db()
    actual_cost = request.form.get("actual_cost", 0)
    notes = request.form.get("notes", "")
    db.execute(
        "UPDATE jobs SET job_status='completed', actual_cost=?, notes=? WHERE id=? AND business_id=?",
        (float(actual_cost), notes, job_id, g.business["id"])
    )
    db.commit()
    flash("تم إغلاق أمر العمل كمنجز ✅", "success")
    return redirect(f"/services/jobs/{job_id}")


@bp.route("/jobs/<int:job_id>/cancel", methods=["POST"])
@require_perm("sales")
def cancel_job(job_id):
    """إلغاء أمر العمل"""
    from modules.extensions import get_db
    db = get_db()
    db.execute(
        "UPDATE jobs SET job_status='cancelled' WHERE id=? AND business_id=?",
        (job_id, g.business["id"])
    )
    db.commit()
    flash("تم إلغاء أمر العمل", "warning")
    return redirect("/services/jobs")


@bp.route("/jobs/<int:job_id>/update", methods=["POST"])
@require_perm("sales")
def update_job(job_id):
    """تحديث بيانات أمر العمل"""
    from modules.extensions import get_db
    db = get_db()
    data = request.form
    db.execute("""
        UPDATE jobs SET
            technician_id=?, actual_cost=?, notes=?, scheduled_date=?
        WHERE id=? AND business_id=?
    """, (
        data.get("technician_id") or None,
        float(data.get("actual_cost") or 0),
        data.get("notes", ""),
        data.get("scheduled_date") or None,
        job_id, g.business["id"]
    ))
    db.commit()
    flash("تم تحديث أمر العمل", "success")
    return redirect(f"/services/jobs/{job_id}")


# ─── CONTRACTS ACTIONS ───────────────────────────────────────
@bp.route("/contracts/<int:contract_id>")
@require_perm("sales")
def view_contract(contract_id):
    """عرض تفاصيل عقد"""
    from modules.extensions import get_db
    db = get_db()
    contract = db.execute(
        "SELECT * FROM service_contracts WHERE id=? AND business_id=?",
        (contract_id, g.business["id"])
    ).fetchone()
    if not contract:
        return "العقد غير موجود", 404
    return render_template("services/contract_detail.html", contract=contract)


@bp.route("/contracts/<int:contract_id>/renew", methods=["POST"])
@require_perm("sales")
def renew_contract(contract_id):
    """تجديد عقد"""
    from modules.extensions import get_db
    db = get_db()
    data = request.form
    db.execute("""
        UPDATE service_contracts SET end_date=?, contract_value=?, status='active' WHERE id=? AND business_id=?
    """, (data.get("end_date"), float(data.get("value", 0)), contract_id, g.business["id"]))
    db.commit()
    flash("تم تجديد العقد ✅", "success")
    return redirect(f"/services/contracts/{contract_id}")


@bp.route("/contracts/<int:contract_id>/cancel", methods=["POST"])
@require_perm("sales")
def cancel_contract(contract_id):
    """إلغاء عقد"""
    from modules.extensions import get_db
    db = get_db()
    db.execute(
        "UPDATE service_contracts SET status='cancelled' WHERE id=? AND business_id=?",
        (contract_id, g.business["id"])
    )
    db.commit()
    flash("تم إلغاء العقد", "warning")
    return redirect("/services/contracts")


# ─── API ─────────────────────────────────────────────────────
@bp.route("/api/jobs/stats")
@require_perm("sales")
def api_jobs_stats():
    """إحصائيات أوامر العمل"""
    from modules.extensions import get_db
    db = get_db()
    bid = g.business["id"]
    rows = db.execute("""
        SELECT job_status, COUNT(*) as cnt FROM jobs WHERE business_id=? GROUP BY job_status
    """, (bid,)).fetchall()
    return jsonify({r["job_status"]: r["cnt"] for r in rows})


@bp.route("/api/contracts/expiring")
@require_perm("sales")
def api_expiring_contracts():
    """عقود توشك على الانتهاء (30 يوم)"""
    from modules.extensions import get_db
    db = get_db()
    bid = g.business["id"]
    rows = db.execute("""
        SELECT * FROM service_contracts
        WHERE business_id=? AND status='active'
        AND end_date BETWEEN date('now') AND date('now','+30 days')
        ORDER BY end_date ASC
    """, (bid,)).fetchall()
    return jsonify([dict(r) for r in rows])
