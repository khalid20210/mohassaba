"""
modules/blueprints/medical/routes.py — قطاع الصحة الكامل
Patients | Appointments | Visits | Prescriptions | Insurance | Services | Reports
"""

from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, g, redirect, flash, url_for
from functools import wraps
import json

bp = Blueprint("medical", __name__, url_prefix="/medical")


# ── صلاحيات ─────────────────────────────────────────────────────────────────
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
                    flash("غير مصرح لك بالوصول لهذه الصفحة", "error")
                    return redirect("/dashboard")
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def _next_file_number(db, business_id):
    """توليد رقم ملف جديد"""
    try:
        db.execute("""
            INSERT INTO medical_file_counter (business_id, last_number)
            VALUES (?, 1)
            ON CONFLICT(business_id) DO UPDATE SET last_number = last_number + 1
        """, (business_id,))
        num = db.execute(
            "SELECT last_number FROM medical_file_counter WHERE business_id = ?",
            (business_id,)
        ).fetchone()[0]
    except Exception:
        import random
        num = random.randint(10000, 99999)
    return f"MED-{num:05d}"


# ══════════════════════════════════════════════════════════════════════════════
# PATIENTS
# ══════════════════════════════════════════════════════════════════════════════

@bp.route("/patients")
@require_perm("sales")
def list_patients():
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]

    search  = request.args.get("q", "").strip()
    page    = max(1, int(request.args.get("page", 1)))
    per_page = 25

    base = "FROM patients WHERE business_id = ?"
    params = [business_id]
    if search:
        base += " AND (patient_name LIKE ? OR patient_phone LIKE ? OR file_number LIKE ? OR national_id LIKE ?)"
        s = f"%{search}%"
        params.extend([s, s, s, s])

    total   = db.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
    patients = db.execute(
        f"SELECT * {base} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        params + [per_page, (page - 1) * per_page]
    ).fetchall()

    insurance_cos = db.execute(
        "SELECT * FROM insurance_companies WHERE business_id = ? AND is_active = 1",
        (business_id,)
    ).fetchall()

    return render_template("medical/patients_list.html",
        patients=patients, total=total, page=page,
        per_page=per_page, search=search,
        insurance_cos=insurance_cos)


@bp.route("/patients/new", methods=["POST"])
@require_perm("sales")
def add_patient():
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    d = request.form

    file_number = _next_file_number(db, business_id)

    try:
        db.execute("""
            INSERT INTO patients (
                business_id, file_number,
                patient_name, patient_phone, date_of_birth, gender,
                national_id, email, address,
                blood_type, height, weight,
                chronic_diseases, allergies,
                insurance_company_id, insurance_policy_number,
                emergency_contact, emergency_phone,
                medical_history, notes,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))
        """, (
            business_id, file_number,
            d.get("full_name", "").strip(),
            d.get("phone", "").strip(),
            d.get("dob") or None,
            d.get("gender", ""),
            d.get("national_id", "").strip(),
            d.get("email", "").strip(),
            d.get("address", "").strip(),
            d.get("blood_type", ""),
            d.get("height") or None,
            d.get("weight") or None,
            d.get("chronic_diseases", "").strip(),
            d.get("allergies", "").strip(),
            d.get("insurance_company_id") or None,
            d.get("insurance_policy_number", "").strip(),
            d.get("emergency_contact", "").strip(),
            d.get("emergency_phone", "").strip(),
            d.get("medical_history", "").strip(),
            d.get("notes", "").strip(),
        ))
        db.commit()
        flash(f"تم تسجيل المريض بنجاح — رقم الملف: {file_number}", "success")
    except Exception as e:
        flash(f"خطأ: {e}", "error")

    return redirect("/medical/patients")


@bp.route("/patients/<int:patient_id>")
@require_perm("sales")
def patient_detail(patient_id):
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]

    patient = db.execute(
        "SELECT * FROM patients WHERE id = ? AND business_id = ?",
        (patient_id, business_id)
    ).fetchone()
    if not patient:
        flash("المريض غير موجود", "error")
        return redirect("/medical/patients")

    appointments = db.execute("""
        SELECT a.*, d.name AS doctor_name
        FROM appointments a
        LEFT JOIN doctors d ON a.doctor_id = d.id
        WHERE a.patient_id = ? AND a.business_id = ?
        ORDER BY a.appointment_date DESC
    """, (patient_id, business_id)).fetchall()

    visits = db.execute("""
        SELECT v.*, d.name AS doctor_name
        FROM patient_visits v
        LEFT JOIN doctors d ON v.doctor_id = d.id
        WHERE v.patient_id = ? AND v.business_id = ?
        ORDER BY v.visit_date DESC
    """, (patient_id, business_id)).fetchall()

    prescriptions = db.execute("""
        SELECT * FROM prescriptions WHERE patient_id = ? AND business_id = ?
        ORDER BY created_at DESC
    """, (patient_id, business_id)).fetchall()

    insurance = None
    if patient["insurance_company_id"]:
        insurance = db.execute(
            "SELECT * FROM insurance_companies WHERE id = ?",
            (patient["insurance_company_id"],)
        ).fetchone()

    doctors = db.execute(
        "SELECT * FROM doctors WHERE business_id = ? AND is_active = 1",
        (business_id,)
    ).fetchall()

    insurance_cos = db.execute(
        "SELECT * FROM insurance_companies WHERE business_id = ? AND is_active = 1",
        (business_id,)
    ).fetchall()

    return render_template("medical/patient_detail.html",
        patient=patient, appointments=appointments,
        visits=visits, prescriptions=prescriptions,
        insurance=insurance, doctors=doctors,
        insurance_cos=insurance_cos)


@bp.route("/patients/<int:patient_id>/edit", methods=["POST"])
@require_perm("sales")
def edit_patient(patient_id):
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    d = request.form

    db.execute("""
        UPDATE patients SET
            patient_name = ?, patient_phone = ?, date_of_birth = ?,
            gender = ?, national_id = ?, email = ?, address = ?,
            blood_type = ?, height = ?, weight = ?,
            chronic_diseases = ?, allergies = ?,
            insurance_company_id = ?, insurance_policy_number = ?,
            emergency_contact = ?, emergency_phone = ?,
            medical_history = ?, notes = ?,
            updated_at = datetime('now')
        WHERE id = ? AND business_id = ?
    """, (
        d.get("full_name", "").strip(),
        d.get("phone", "").strip(),
        d.get("dob") or None,
        d.get("gender", ""),
        d.get("national_id", "").strip(),
        d.get("email", "").strip(),
        d.get("address", "").strip(),
        d.get("blood_type", ""),
        d.get("height") or None,
        d.get("weight") or None,
        d.get("chronic_diseases", "").strip(),
        d.get("allergies", "").strip(),
        d.get("insurance_company_id") or None,
        d.get("insurance_policy_number", "").strip(),
        d.get("emergency_contact", "").strip(),
        d.get("emergency_phone", "").strip(),
        d.get("medical_history", "").strip(),
        d.get("notes", "").strip(),
        patient_id, business_id
    ))
    db.commit()
    flash("تم تحديث بيانات المريض", "success")
    return redirect(f"/medical/patients/{patient_id}")


# ══════════════════════════════════════════════════════════════════════════════
# APPOINTMENTS
# ══════════════════════════════════════════════════════════════════════════════

@bp.route("/appointments")
@require_perm("sales")
def list_appointments():
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]

    status      = request.args.get("status", "")
    date_filter = request.args.get("date", "")
    doctor_id   = request.args.get("doctor_id", "")

    query = """
        SELECT a.*, p.patient_name, p.patient_phone, p.file_number,
               d.name AS doctor_name
        FROM appointments a
        JOIN patients p ON a.patient_id = p.id
        LEFT JOIN doctors d ON a.doctor_id = d.id
        WHERE a.business_id = ?
    """
    params = [business_id]

    if status:
        query += " AND a.status = ?"
        params.append(status)
    if date_filter:
        query += " AND a.appointment_date = ?"
        params.append(date_filter)
    if doctor_id:
        query += " AND a.doctor_id = ?"
        params.append(doctor_id)

    query += " ORDER BY a.appointment_date ASC, a.appointment_time ASC"
    appointments = db.execute(query, params).fetchall()

    doctors  = db.execute(
        "SELECT * FROM doctors WHERE business_id = ? AND is_active = 1",
        (business_id,)
    ).fetchall()
    patients = db.execute(
        "SELECT id, patient_name, file_number FROM patients WHERE business_id = ? ORDER BY patient_name",
        (business_id,)
    ).fetchall()

    stats = db.execute("""
        SELECT
            COUNT(*) total,
            SUM(CASE WHEN status='scheduled' THEN 1 ELSE 0 END) scheduled,
            SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) completed,
            SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END) cancelled
        FROM appointments WHERE business_id = ?
    """, (business_id,)).fetchone()

    return render_template("medical/appointments_list.html",
        appointments=appointments, doctors=doctors,
        patients=patients, stats=stats,
        status=status, date_filter=date_filter)


@bp.route("/appointments/new", methods=["POST"])
@require_perm("sales")
def add_appointment():
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    d = request.form

    db.execute("""
        INSERT INTO appointments (
            business_id, patient_id, doctor_id,
            appointment_date, appointment_time, appointment_type,
            reason, status, notes, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,datetime('now'))
    """, (
        business_id,
        d.get("patient_id"),
        d.get("doctor_id") or None,
        d.get("appointment_date"),
        d.get("appointment_time", ""),
        d.get("appointment_type", "كشف"),
        d.get("reason", ""),
        "scheduled",
        d.get("notes", ""),
    ))
    db.commit()
    flash("تم حجز الموعد بنجاح", "success")
    back = request.form.get("back_to", "/medical/appointments")
    return redirect(back)


@bp.route("/appointments/<int:appointment_id>", methods=["GET", "POST"])
@require_perm("sales")
def manage_appointment(appointment_id):
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]

    appointment = db.execute("""
        SELECT a.*, p.patient_name, p.file_number, p.blood_type,
               p.chronic_diseases, p.allergies, p.patient_phone,
               d.name AS doctor_name
        FROM appointments a
        JOIN patients p ON a.patient_id = p.id
        LEFT JOIN doctors d ON a.doctor_id = d.id
        WHERE a.id = ? AND a.business_id = ?
    """, (appointment_id, business_id)).fetchone()

    if not appointment:
        flash("الموعد غير موجود", "error")
        return redirect("/medical/appointments")

    if request.method == "POST":
        action = request.form.get("action", "save")
        d = request.form

        if action == "cancel":
            db.execute(
                "UPDATE appointments SET status='cancelled', updated_at=datetime('now') WHERE id=?",
                (appointment_id,)
            )
            db.commit()
            flash("تم إلغاء الموعد", "info")
            return redirect("/medical/appointments")

        db.execute("""
            INSERT INTO patient_visits (
                business_id, patient_id, visit_date, doctor_id,
                diagnosis, treatment, notes,
                vital_bp, vital_temp, vital_pulse, vital_weight,
                follow_up_date, created_at
            ) VALUES (?,?,datetime('now'),?,?,?,?,?,?,?,?,?,datetime('now'))
        """, (
            business_id,
            appointment["patient_id"],
            appointment["doctor_id"],
            d.get("diagnosis", ""),
            d.get("treatment", ""),
            d.get("notes", ""),
            d.get("vital_bp", ""),
            d.get("vital_temp") or None,
            d.get("vital_pulse") or None,
            d.get("vital_weight") or None,
            d.get("follow_up_date") or None,
        ))

        db.execute("""
            UPDATE appointments SET
                status = 'completed', visit_fee = ?,
                updated_at = datetime('now')
            WHERE id = ?
        """, (d.get("visit_fee", 0), appointment_id))

        db.execute(
            "UPDATE patients SET last_visit = date('now') WHERE id = ?",
            (appointment["patient_id"],)
        )

        prescription_items = d.get("prescription_items", "").strip()
        if prescription_items:
            db.execute("""
                INSERT INTO prescriptions (
                    business_id, appointment_id, patient_id, doctor_id,
                    prescription_items, notes, created_at
                ) VALUES (?,?,?,?,?,?,datetime('now'))
            """, (
                business_id, appointment_id,
                appointment["patient_id"], appointment["doctor_id"],
                prescription_items, d.get("rx_notes", ""),
            ))

        db.commit()
        flash("تم حفظ الزيارة الطبية بنجاح", "success")
        return redirect("/medical/appointments")

    services = db.execute(
        "SELECT * FROM medical_services WHERE business_id = ? AND is_active = 1",
        (business_id,)
    ).fetchall()

    return render_template("medical/appointment_detail.html",
        appointment=appointment, services=services)


@bp.route("/appointments/<int:appointment_id>/status", methods=["POST"])
@require_perm("sales")
def update_appointment_status(appointment_id):
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    status = request.form.get("status")
    db.execute(
        "UPDATE appointments SET status=?, updated_at=datetime('now') WHERE id=? AND business_id=?",
        (status, appointment_id, business_id)
    )
    db.commit()
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════════════════
# INSURANCE COMPANIES
# ══════════════════════════════════════════════════════════════════════════════

@bp.route("/insurance")
@require_perm("sales")
def list_insurance():
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]

    companies = db.execute("""
        SELECT ic.*, COUNT(p.id) AS patients_count
        FROM insurance_companies ic
        LEFT JOIN patients p ON p.insurance_company_id = ic.id
        WHERE ic.business_id = ?
        GROUP BY ic.id ORDER BY ic.name
    """, (business_id,)).fetchall()

    return render_template("medical/insurance_list.html", companies=companies)


@bp.route("/insurance/new", methods=["POST"])
@require_perm("sales")
def add_insurance():
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    d = request.form

    db.execute("""
        INSERT INTO insurance_companies (
            business_id, name, name_en, contract_number,
            coverage_percent, max_coverage,
            contact_name, contact_phone, contact_email,
            address, notes, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
    """, (
        business_id,
        d.get("name", "").strip(), d.get("name_en", "").strip(),
        d.get("contract_number", "").strip(),
        d.get("coverage_percent", 80), d.get("max_coverage", 0),
        d.get("contact_name", "").strip(), d.get("contact_phone", "").strip(),
        d.get("contact_email", "").strip(),
        d.get("address", "").strip(), d.get("notes", "").strip(),
    ))
    db.commit()
    flash("تم إضافة شركة التأمين", "success")
    return redirect("/medical/insurance")


@bp.route("/insurance/<int:company_id>/toggle", methods=["POST"])
@require_perm("sales")
def toggle_insurance(company_id):
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    db.execute(
        "UPDATE insurance_companies SET is_active=1-is_active WHERE id=? AND business_id=?",
        (company_id, business_id)
    )
    db.commit()
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════════════════
# DOCTORS
# ══════════════════════════════════════════════════════════════════════════════

@bp.route("/doctors")
@require_perm("sales")
def list_doctors():
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]

    doctors = db.execute("""
        SELECT d.*, COUNT(a.id) AS appointments_count
        FROM doctors d
        LEFT JOIN appointments a ON a.doctor_id = d.id
        WHERE d.business_id = ?
        GROUP BY d.id ORDER BY d.name
    """, (business_id,)).fetchall()

    return render_template("medical/doctors_list.html", doctors=doctors)


@bp.route("/doctors/new", methods=["POST"])
@require_perm("sales")
def add_doctor():
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    d = request.form

    db.execute("""
        INSERT INTO doctors (business_id, name, specialty, license_number, phone, email, created_at)
        VALUES (?,?,?,?,?,?,datetime('now'))
    """, (
        business_id,
        d.get("name", "").strip(), d.get("specialty", "").strip(),
        d.get("license_number", "").strip(),
        d.get("phone", "").strip(), d.get("email", "").strip(),
    ))
    db.commit()
    flash("تم إضافة الطبيب", "success")
    return redirect("/medical/doctors")


@bp.route("/doctors/<int:doctor_id>/toggle", methods=["POST"])
@require_perm("sales")
def toggle_doctor(doctor_id):
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    db.execute(
        "UPDATE doctors SET is_active=1-is_active WHERE id=? AND business_id=?",
        (doctor_id, business_id)
    )
    db.commit()
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════════════════════════
# MEDICAL SERVICES
# ══════════════════════════════════════════════════════════════════════════════

@bp.route("/services")
@require_perm("sales")
def list_services():
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]

    services = db.execute(
        "SELECT * FROM medical_services WHERE business_id = ? ORDER BY category, name",
        (business_id,)
    ).fetchall()

    return render_template("medical/services_list.html", services=services)


@bp.route("/services/new", methods=["POST"])
@require_perm("sales")
def add_service():
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]
    d = request.form

    db.execute("""
        INSERT INTO medical_services (
            business_id, service_code, name, category,
            price, insurance_price, duration_min, notes, created_at
        ) VALUES (?,?,?,?,?,?,?,?,datetime('now'))
    """, (
        business_id,
        d.get("service_code", "").strip(), d.get("name", "").strip(),
        d.get("category", "").strip(),
        d.get("price", 0), d.get("insurance_price", 0),
        d.get("duration_min", 30), d.get("notes", "").strip(),
    ))
    db.commit()
    flash("تم إضافة الخدمة", "success")
    return redirect("/medical/services")


# ══════════════════════════════════════════════════════════════════════════════
# PRESCRIPTIONS
# ══════════════════════════════════════════════════════════════════════════════

@bp.route("/prescriptions/<int:patient_id>")
@require_perm("sales")
def patient_prescriptions(patient_id):
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]

    patient = db.execute(
        "SELECT * FROM patients WHERE id = ? AND business_id = ?",
        (patient_id, business_id)
    ).fetchone()
    if not patient:
        return redirect("/medical/patients")

    prescriptions = db.execute("""
        SELECT pr.*, d.name AS doctor_name
        FROM prescriptions pr
        LEFT JOIN doctors d ON pr.doctor_id = d.id
        WHERE pr.patient_id = ? AND pr.business_id = ?
        ORDER BY pr.created_at DESC
    """, (patient_id, business_id)).fetchall()

    return render_template("medical/prescriptions_list.html",
        prescriptions=prescriptions, patient=patient)


# ══════════════════════════════════════════════════════════════════════════════
# REPORTS
# ══════════════════════════════════════════════════════════════════════════════

@bp.route("/reports")
@require_perm("sales")
def reports():
    from modules.extensions import get_db
    db = get_db()
    business_id = g.business["id"]

    stats = {
        "total_patients":      db.execute("SELECT COUNT(*) FROM patients WHERE business_id=?", (business_id,)).fetchone()[0],
        "total_appointments":  db.execute("SELECT COUNT(*) FROM appointments WHERE business_id=?", (business_id,)).fetchone()[0],
        "completed_visits":    db.execute("SELECT COUNT(*) FROM appointments WHERE business_id=? AND status='completed'", (business_id,)).fetchone()[0],
        "total_doctors":       db.execute("SELECT COUNT(*) FROM doctors WHERE business_id=? AND is_active=1", (business_id,)).fetchone()[0],
        "insurance_patients":  db.execute("SELECT COUNT(*) FROM patients WHERE business_id=? AND insurance_company_id IS NOT NULL", (business_id,)).fetchone()[0],
        "total_prescriptions": db.execute("SELECT COUNT(*) FROM prescriptions WHERE business_id=?", (business_id,)).fetchone()[0],
        "new_patients_month":  db.execute("SELECT COUNT(*) FROM patients WHERE business_id=? AND strftime('%Y-%m',created_at)=strftime('%Y-%m','now')", (business_id,)).fetchone()[0],
        "today_appointments":  db.execute("SELECT COUNT(*) FROM appointments WHERE business_id=? AND appointment_date=date('now')", (business_id,)).fetchone()[0],
    }

    by_doctor = db.execute("""
        SELECT d.name, COUNT(a.id) cnt FROM appointments a
        JOIN doctors d ON a.doctor_id = d.id
        WHERE a.business_id = ? GROUP BY d.id ORDER BY cnt DESC LIMIT 10
    """, (business_id,)).fetchall()

    by_insurance = db.execute("""
        SELECT ic.name, COUNT(p.id) cnt FROM patients p
        JOIN insurance_companies ic ON p.insurance_company_id = ic.id
        WHERE p.business_id = ? GROUP BY ic.id ORDER BY cnt DESC
    """, (business_id,)).fetchall()

    recent_patients = db.execute(
        "SELECT * FROM patients WHERE business_id=? ORDER BY created_at DESC LIMIT 10",
        (business_id,)
    ).fetchall()

    upcoming = db.execute("""
        SELECT a.*, p.patient_name, d.name AS doctor_name
        FROM appointments a JOIN patients p ON a.patient_id=p.id
        LEFT JOIN doctors d ON a.doctor_id=d.id
        WHERE a.business_id=? AND a.appointment_date>=date('now') AND a.status='scheduled'
        ORDER BY a.appointment_date ASC, a.appointment_time ASC LIMIT 15
    """, (business_id,)).fetchall()

    return render_template("medical/reports.html",
        stats=stats, by_doctor=by_doctor, by_insurance=by_insurance,
        recent_patients=recent_patients, upcoming=upcoming)