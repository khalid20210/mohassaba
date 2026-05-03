"""
modules/blueprints/medical/routes.py — خدمات القطاع الطبي
Medical Sector: Patients, Appointments, Prescriptions, Visits
"""

from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, g, redirect, flash
from functools import wraps
import json

bp = Blueprint("medical", __name__, url_prefix="/medical")


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


# PATIENTS
@bp.route("/patients")
@require_perm("sales")
def list_patients():
    """قائمة المرضى"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    
    search = request.args.get("search", "")
    page = int(request.args.get("page", 1))
    per_page = 20
    
    query = "SELECT * FROM patients WHERE business_id = ?"
    params = [business_id]
    
    if search:
        query += " AND (patient_name LIKE ? OR patient_phone LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])
    
    query += " ORDER BY patient_name ASC LIMIT ? OFFSET ?"
    params.extend([per_page, (page-1)*per_page])
    
    patients = db.execute(query, params).fetchall()
    total = db.execute(
        "SELECT COUNT(*) FROM patients WHERE business_id = ?",
        (business_id,)
    ).fetchone()[0]
    
    return render_template("medical/patients_list.html", **{
        "patients": patients,
        "total": total,
        "page": page,
    })


@bp.route("/patients/new", methods=["POST"])
@require_perm("sales")
def add_patient():
    """إضافة مريض جديد"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    
    data = request.form
    
    db.execute("""
        INSERT INTO patients (
            business_id, patient_name, patient_phone, date_of_birth,
            gender, national_id, email, address, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
    """, (
        business_id,
        data.get("name"),
        data.get("phone"),
        data.get("dob"),
        data.get("gender"),
        data.get("national_id"),
        data.get("email"),
        data.get("address"),
    ))
    db.commit()
    
    flash("تم إضافة المريض", "success")
    return redirect("/medical/patients")


# APPOINTMENTS
@bp.route("/appointments")
@require_perm("sales")
def list_appointments():
    """قائمة المواعيد"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    
    status = request.args.get("status", "scheduled")
    
    query = """
        SELECT a.*, p.patient_name FROM appointments a
        JOIN patients p ON a.patient_id = p.id
        WHERE a.business_id = ?
    """
    params = [business_id]
    
    if status != "all":
        query += " AND a.status = ?"
        params.append(status)
    
    query += " ORDER BY a.appointment_date ASC"
    
    appointments = db.execute(query, params).fetchall()
    
    return render_template("medical/appointments_list.html", **{
        "appointments": appointments,
        "status": status,
    })


@bp.route("/appointments/<int:appointment_id>", methods=["GET", "POST"])
@require_perm("sales")
def manage_appointment(appointment_id):
    """إدارة موعد - التشخيص والعلاج والوصفات"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    
    if request.method == "POST":
        data = request.form
        
        # حفظ الزيارة
        db.execute("""
            INSERT INTO patient_visits (
                business_id, patient_id, visit_date, doctor_id,
                diagnosis, treatment, notes
            ) VALUES (?, ?, datetime('now'), ?, ?, ?, ?)
        """, (
            business_id,
            data.get("patient_id"),
            g.user.get("id"),
            data.get("diagnosis"),
            data.get("treatment"),
            data.get("notes"),
        ))
        
        # تحديث حالة الموعد
        db.execute(
            "UPDATE appointments SET status = 'completed' WHERE id = ?",
            (appointment_id,)
        )
        
        db.commit()
        flash("تم حفظ الزيارة", "success")
        return redirect("/medical/appointments")
    
    appointment = db.execute(
        "SELECT * FROM appointments WHERE id = ? AND business_id = ?",
        (appointment_id, business_id)
    ).fetchone()
    
    if not appointment:
        return "غير موجود", 404
    
    return render_template("medical/appointment_detail.html", appointment=appointment)


# PRESCRIPTIONS
@bp.route("/prescriptions/<int:patient_id>")
@require_perm("sales")
def patient_prescriptions(patient_id):
    """وصفات المريض"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    
    prescriptions = db.execute("""
        SELECT * FROM prescriptions
        WHERE patient_id = ? AND business_id = ?
        ORDER BY created_at DESC
    """, (patient_id, business_id)).fetchall()
    
    return render_template("medical/prescriptions_list.html", prescriptions=prescriptions)


@bp.route("/api/patient/<int:patient_id>")
def api_get_patient(patient_id):
    """API: الحصول على بيانات المريض"""
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    
    patient = db.execute(
        "SELECT * FROM patients WHERE id = ? AND business_id = ?",
        (patient_id, business_id)
    ).fetchone()
    
    if patient:
        return jsonify(dict(patient))
    return jsonify({"error": "Patient not found"}), 404


# ─── PATIENT DETAIL & EDIT ──────────────────────────────────
@bp.route("/patients/<int:patient_id>")
@require_perm("sales")
def view_patient(patient_id):
    """ملف المريض الكامل"""
    from modules.extensions import get_db
    db = get_db()
    bid = g.business["id"]
    patient = db.execute(
        "SELECT * FROM patients WHERE id=? AND business_id=?",
        (patient_id, bid)
    ).fetchone()
    if not patient:
        return "المريض غير موجود", 404
    appointments = db.execute(
        "SELECT * FROM appointments WHERE patient_id=? AND business_id=? ORDER BY appointment_date DESC LIMIT 20",
        (patient_id, bid)
    ).fetchall()
    prescriptions = db.execute(
        "SELECT * FROM prescriptions WHERE patient_id=? AND business_id=? ORDER BY created_at DESC LIMIT 10",
        (patient_id, bid)
    ).fetchall()
    return render_template("medical/patient_detail.html",
        patient=patient, appointments=appointments, prescriptions=prescriptions)


@bp.route("/patients/<int:patient_id>/edit", methods=["POST"])
@require_perm("sales")
def edit_patient(patient_id):
    """تعديل بيانات المريض"""
    from modules.extensions import get_db
    db = get_db()
    data = request.form
    db.execute("""
        UPDATE patients SET
            patient_name=?, patient_phone=?, date_of_birth=?,
            gender=?, national_id=?, email=?, address=?, updated_at=datetime('now')
        WHERE id=? AND business_id=?
    """, (
        data.get("name"), data.get("phone"), data.get("dob"),
        data.get("gender"), data.get("national_id"),
        data.get("email"), data.get("address"),
        patient_id, g.business["id"]
    ))
    db.commit()
    flash("تم تحديث بيانات المريض ✅", "success")
    return redirect(f"/medical/patients/{patient_id}")


# ─── APPOINTMENT ACTIONS ────────────────────────────────────
@bp.route("/appointments/new", methods=["POST"])
@require_perm("sales")
def create_appointment():
    """حجز موعد جديد"""
    from modules.extensions import get_db
    db = get_db()
    data = request.form
    bid = g.business["id"]
    db.execute("""
        INSERT INTO appointments (
            business_id, patient_id, appointment_date, appointment_time,
            doctor_name, appointment_type, status, notes, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'scheduled', ?, datetime('now'))
    """, (
        bid,
        data.get("patient_id"),
        data.get("date"),
        data.get("time"),
        data.get("doctor"),
        data.get("type", "consultation"),
        data.get("notes", ""),
    ))
    db.commit()
    flash("تم حجز الموعد ✅", "success")
    return redirect("/medical/appointments")


@bp.route("/appointments/<int:appt_id>/cancel", methods=["POST"])
@require_perm("sales")
def cancel_appointment(appt_id):
    """إلغاء موعد"""
    from modules.extensions import get_db
    db = get_db()
    db.execute(
        "UPDATE appointments SET status='cancelled' WHERE id=? AND business_id=?",
        (appt_id, g.business["id"])
    )
    db.commit()
    flash("تم إلغاء الموعد", "warning")
    return redirect("/medical/appointments")


# ─── PRESCRIPTIONS ──────────────────────────────────────────
@bp.route("/prescriptions/<int:patient_id>/new", methods=["POST"])
@require_perm("sales")
def add_prescription(patient_id):
    """إضافة وصفة طبية"""
    from modules.extensions import get_db
    db = get_db()
    data = request.form
    bid = g.business["id"]
    db.execute("""
        INSERT INTO prescriptions (
            business_id, patient_id, doctor_name, diagnosis,
            medications, notes, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
    """, (
        bid, patient_id,
        data.get("doctor"),
        data.get("diagnosis"),
        data.get("medications"),
        data.get("notes", ""),
    ))
    db.commit()
    flash("تم حفظ الوصفة الطبية ✅", "success")
    return redirect(f"/medical/patients/{patient_id}")


# ─── API ────────────────────────────────────────────────────
@bp.route("/api/stats")
@require_perm("sales")
def api_medical_stats():
    """إحصائيات يومية"""
    from modules.extensions import get_db
    db = get_db()
    bid = g.business["id"]
    today = datetime.today().strftime('%Y-%m-%d')
    today_appts = db.execute(
        "SELECT COUNT(*) FROM appointments WHERE business_id=? AND date(appointment_date)=?",
        (bid, today)
    ).fetchone()[0]
    total_patients = db.execute("SELECT COUNT(*) FROM patients WHERE business_id=?", (bid,)).fetchone()[0]
    pending = db.execute(
        "SELECT COUNT(*) FROM appointments WHERE business_id=? AND status='scheduled' AND appointment_date>=?",
        (bid, today)
    ).fetchone()[0]
    return jsonify({"today_appointments": today_appts, "total_patients": total_patients, "pending_appointments": pending})
