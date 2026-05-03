"""
blueprints/workforce/routes.py
بوابة الموظفين والمناديب + API-First endpoints
نظام المناديب الاحترافي الكامل — v2
"""
import json
from datetime import datetime, timedelta
from urllib.parse import quote

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from modules.extensions import check_password, get_db, hash_password
from modules.middleware import onboarding_required, require_perm
from modules.validators import (
    SCHEMA_AGENT_CREATE,
    SCHEMA_BLIND_CLOSE,
    SCHEMA_EMPLOYEE_CREATE,
    V,
    validate,
)

bp = Blueprint("workforce", __name__)

# Rate limiting for agent login
_agent_login_attempts: dict = {}
_AGENT_MAX_ATTEMPTS = 5
_AGENT_WINDOW_SEC = 300  # 5 minutes


# ─────────────────────────────────────────────────────────────
# بوابة تسجيل الدخول المستقلة للمندوب
# ─────────────────────────────────────────────────────────────
@bp.route("/agent/login", methods=["GET", "POST"])
def agent_login():
    """صفحة تسجيل الدخول المستقلة للمندوب — بدون أي auth مطلوب"""
    if session.get("agent_id"):
        return redirect(url_for("workforce.agent_portal"))

    if request.method == "POST":
        ip  = request.remote_addr or "unknown"
        now = datetime.now().timestamp()
        _agent_login_attempts.setdefault(ip, [])
        _agent_login_attempts[ip] = [t for t in _agent_login_attempts[ip] if now - t < _AGENT_WINDOW_SEC]
        if len(_agent_login_attempts[ip]) >= _AGENT_MAX_ATTEMPTS:
            error = "تم تجاوز الحد المسموح من المحاولات. انتظر 5 دقائق."
            return render_template("agent_login.html", error=error)

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            return render_template("agent_login.html", error="يرجى إدخال اسم المستخدم وكلمة المرور")

        db = get_db()
        agent = db.execute(
            """SELECT a.*, b.name AS business_name
               FROM agents a
               JOIN businesses b ON b.id = a.business_id
               WHERE a.username = ? AND a.is_active = 1""",
            (username,),
        ).fetchone()

        if not agent or not agent["password_hash"] or not check_password(agent["password_hash"], password):
            _agent_login_attempts[ip].append(now)
            return render_template("agent_login.html", error="اسم المستخدم أو كلمة المرور غير صحيحة")

        _agent_login_attempts.pop(ip, None)
        session.clear()
        session["agent_id"]      = agent["id"]
        session["agent_biz_id"]  = agent["business_id"]
        session["agent_name"]    = agent["full_name"]
        session.permanent        = True

        db.execute("UPDATE agents SET last_login=datetime('now') WHERE id=?", (agent["id"],))
        db.commit()
        return redirect(url_for("workforce.agent_portal"))

    return render_template("agent_login.html", error=None)


@bp.route("/agent/portal")
def agent_portal():
    """بوابة المندوب — تتطلب session مندوب"""
    agent_id = session.get("agent_id")
    if not agent_id:
        return redirect(url_for("workforce.agent_login"))

    db      = get_db()
    biz_id  = session["agent_biz_id"]
    agent   = db.execute(
        """SELECT a.*, b.name AS business_name
           FROM agents a
           JOIN businesses b ON b.id = a.business_id
           WHERE a.id=? AND a.business_id=? AND a.is_active=1""",
        (agent_id, biz_id),
    ).fetchone()
    if not agent:
        session.clear()
        return redirect(url_for("workforce.agent_login"))

    return render_template("agent_mobile.html", agent=dict(agent))


@bp.route("/agent/logout", methods=["POST", "GET"])
def agent_logout():
    """تسجيل خروج المندوب"""
    session.pop("agent_id",     None)
    session.pop("agent_biz_id", None)
    session.pop("agent_name",   None)
    return redirect(url_for("workforce.agent_login"))


@bp.route("/api/v1/agent/me")
def agent_api_me():
    """API — بيانات المندوب الحالي (للـ PWA)"""
    agent_id = session.get("agent_id")
    if not agent_id:
        return jsonify({"success": False, "error": "unauthorized"}), 401
    db    = get_db()
    biz   = session["agent_biz_id"]
    agent = db.execute(
        "SELECT id, full_name, phone, commission_rate, region, employee_code FROM agents WHERE id=? AND business_id=?",
        (agent_id, biz),
    ).fetchone()
    if not agent:
        return jsonify({"success": False, "error": "not found"}), 404
    return jsonify({"success": True, "agent": dict(agent)})


# ─────────────────────────────────────────────────────────────
# صفحة مناديب مستقلة للأدمن
# ─────────────────────────────────────────────────────────────
@bp.route("/agents")
@require_perm("settings")
def agents_dashboard():
    """لوحة إدارة المناديب للأدمن"""
    from datetime import date
    return render_template("agents_dashboard.html", now_date=date.today().isoformat())


@bp.route("/workforce")
@require_perm("settings")
def workforce_portal():
    """لوحة إدارة الموظفين + الإقفال الأعمى + المناديب"""
    return render_template("workforce_portal.html")


@bp.route("/agents/mobile/<int:agent_id>")
@onboarding_required
def agent_mobile_portal(agent_id: int):
    """واجهة موبايل مخصصة للمندوب"""
    db = get_db()
    biz_id = session["business_id"]
    agent = db.execute(
        """SELECT id, full_name, phone, whatsapp_number, commission_rate
           FROM agents WHERE id=? AND business_id=? AND is_active=1""",
        (agent_id, biz_id),
    ).fetchone()
    if not agent:
        return render_template("404.html"), 404
    return render_template("agent_mobile.html", agent=dict(agent))


@bp.route("/api/v1/health")
@onboarding_required
def api_v1_health():
    return jsonify(
        {
            "success": True,
            "service": "jenan-biz-api",
            "version": "v1",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
    )


@bp.route("/api/v1/openapi")
@onboarding_required
def api_v1_openapi():
    """ملخص endpoints (API-first contract)"""
    return jsonify(
        {
            "success": True,
            "version": "v1",
            "endpoints": [
                {"method": "GET", "path": "/api/v1/health"},
                {"method": "GET", "path": "/api/v1/employees"},
                {"method": "POST", "path": "/api/v1/employees"},
                {"method": "POST", "path": "/api/v1/shifts/close-blind"},
                {"method": "GET", "path": "/api/v1/agents"},
                {"method": "POST", "path": "/api/v1/agents"},
                {
                    "method": "POST",
                    "path": "/api/v1/agents/<agent_id>/assign-invoice",
                },
                {
                    "method": "GET",
                    "path": "/api/v1/agents/<agent_id>/commissions/summary",
                },
                {
                    "method": "POST",
                    "path": "/api/v1/agents/<agent_id>/whatsapp-campaign",
                },
            ],
        }
    )


@bp.route("/api/v1/employees")
@onboarding_required
def api_v1_employees_list():
    db = get_db()
    biz_id = session["business_id"]
    rows = db.execute(
        """SELECT id, full_name, phone, role_label, base_salary, is_active, created_at
           FROM employees
           WHERE business_id=?
           ORDER BY is_active DESC, id DESC""",
        (biz_id,),
    ).fetchall()
    return jsonify({"success": True, "employees": [dict(r) for r in rows]})


@bp.route("/api/v1/employees", methods=["POST"])
@onboarding_required
def api_v1_employees_create():
    payload = request.get_json(force=True) or {}
    clean, errs = validate(payload, SCHEMA_EMPLOYEE_CREATE)
    if errs:
        return jsonify({"success": False, "errors": errs}), 400

    db = get_db()
    biz_id = session["business_id"]
    try:
        db.execute(
            """INSERT INTO employees
               (business_id, full_name, phone, role_label, base_salary)
               VALUES (?,?,?,?,?)""",
            (
                biz_id,
                clean["full_name"],
                clean.get("phone"),
                clean.get("role_label") or "موظف",
                round(clean.get("base_salary") or 0, 2),
            ),
        )
        db.commit()
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": f"تعذر إنشاء الموظف: {e}"}), 400

    return jsonify({"success": True, "message": "تم إنشاء الموظف بنجاح"})


@bp.route("/api/v1/shifts/close-blind", methods=["POST"])
@onboarding_required
def api_v1_shift_close_blind():
    """
    الإقفال الأعمى:
    - النظام يستقبل expected_cash من النظام وcounted_cash من الموظف.
    - أي عجز يخلق خصم رواتب تلقائياً (pending).
    """
    payload = request.get_json(force=True) or {}
    clean, errs = validate(payload, SCHEMA_BLIND_CLOSE)
    if errs:
        return jsonify({"success": False, "errors": errs}), 400

    db = get_db()
    biz_id = session["business_id"]
    user_id = session.get("user_id")

    emp = db.execute(
        "SELECT id, full_name FROM employees WHERE id=? AND business_id=? AND is_active=1",
        (clean["employee_id"], biz_id),
    ).fetchone()
    if not emp:
        return jsonify({"success": False, "error": "الموظف غير موجود"}), 404

    expected_cash = round(clean["expected_cash"], 2)
    counted_cash = round(clean["counted_cash"], 2)
    diff = round(expected_cash - counted_cash, 2)
    shortage = diff if diff > 0 else 0.0
    overage = abs(diff) if diff < 0 else 0.0

    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            """INSERT INTO shift_blind_closures
               (business_id, employee_id, shift_date, expected_cash, counted_cash,
                shortage_amount, overage_amount, notes, closed_by)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                biz_id,
                clean["employee_id"],
                clean["shift_date"],
                expected_cash,
                counted_cash,
                shortage,
                overage,
                clean.get("notes"),
                user_id,
            ),
        )
        closure_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        deduction_id = None
        if shortage > 0:
            db.execute(
                """INSERT INTO payroll_deductions
                   (business_id, employee_id, source_type, source_id, amount, reason, status)
                   VALUES (?,?,?,?,?,?, 'pending')""",
                (
                    biz_id,
                    clean["employee_id"],
                    "shift_shortage",
                    closure_id,
                    shortage,
                    f"عجز صندوق (إقفال أعمى) بتاريخ {clean['shift_date']}",
                ),
            )
            deduction_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        db.commit()
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": f"فشل الإقفال: {e}"}), 500

    return jsonify(
        {
            "success": True,
            "closure_id": closure_id,
            "employee": emp["full_name"],
            "shortage_amount": shortage,
            "overage_amount": overage,
            "deduction_created": bool(deduction_id),
            "deduction_id": deduction_id,
            "message": "تم الإقفال الأعمى بنجاح",
        }
    )


@bp.route("/api/v1/agents")
@onboarding_required
def api_v1_agents_list():
    db = get_db()
    biz_id = session["business_id"]
    rows = db.execute(
        """SELECT id, full_name, phone, whatsapp_number, commission_rate, is_active
           FROM agents WHERE business_id=? ORDER BY is_active DESC, id DESC""",
        (biz_id,),
    ).fetchall()
    return jsonify({"success": True, "agents": [dict(r) for r in rows]})


@bp.route("/api/v1/agents/<int:agent_id>/set-credentials", methods=["POST"])
@onboarding_required
def api_agent_set_credentials(agent_id: int):
    """تعيين اسم المستخدم وكلمة المرور للمندوب من قِبل الأدمن"""
    biz_id  = session["business_id"]
    payload = request.get_json(force=True) or {}
    username = (payload.get("username") or "").strip()
    password = (payload.get("password") or "").strip()

    if not username:
        return jsonify({"success": False, "error": "اسم المستخدم مطلوب"}), 400
    if len(username) < 3:
        return jsonify({"success": False, "error": "اسم المستخدم 3 أحرف على الأقل"}), 400

    db = get_db()
    agent = db.execute(
        "SELECT id FROM agents WHERE id=? AND business_id=?", (agent_id, biz_id)
    ).fetchone()
    if not agent:
        return jsonify({"success": False, "error": "المندوب غير موجود"}), 404

    # Check username uniqueness (exclude current agent)
    conflict = db.execute(
        "SELECT id FROM agents WHERE username=? AND id != ?", (username, agent_id)
    ).fetchone()
    if conflict:
        return jsonify({"success": False, "error": "اسم المستخدم مستخدم بالفعل"}), 409

    if password:
        # Change password too
        if len(password) < 6:
            return jsonify({"success": False, "error": "كلمة المرور 6 أحرف على الأقل"}), 400
        hashed = hash_password(password)
        db.execute(
            "UPDATE agents SET username=?, password_hash=? WHERE id=? AND business_id=?",
            (username, hashed, agent_id, biz_id),
        )
    else:
        # Update username only
        db.execute(
            "UPDATE agents SET username=? WHERE id=? AND business_id=?",
            (username, agent_id, biz_id),
        )
    db.commit()
    return jsonify({"success": True, "message": "تم تحديث بيانات الدخول"})


@bp.route("/api/v1/agents/<int:agent_id>/credentials", methods=["GET"])
@onboarding_required
def api_agent_get_credentials(agent_id: int):
    """جلب اسم المستخدم للمندوب (بدون كلمة المرور)"""
    biz_id = session["business_id"]
    db     = get_db()
    row    = db.execute(
        "SELECT username, last_login FROM agents WHERE id=? AND business_id=?",
        (agent_id, biz_id),
    ).fetchone()
    if not row:
        return jsonify({"success": False}), 404
    return jsonify({
        "success":    True,
        "username":   row["username"],
        "last_login": row["last_login"],
        "has_password": bool(row["username"]),
    })


@bp.route("/api/v1/agents", methods=["POST"])
@onboarding_required
def api_v1_agents_create():
    payload = request.get_json(force=True) or {}
    clean, errs = validate(payload, SCHEMA_AGENT_CREATE)
    if errs:
        return jsonify({"success": False, "errors": errs}), 400

    db = get_db()
    biz_id = session["business_id"]
    try:
        db.execute(
            """INSERT INTO agents
               (business_id, full_name, phone, whatsapp_number, commission_rate)
               VALUES (?,?,?,?,?)""",
            (
                biz_id,
                clean["full_name"],
                clean.get("phone"),
                clean.get("whatsapp_number"),
                round(clean.get("commission_rate") or 0, 2),
            ),
        )
        db.commit()
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": f"تعذر إنشاء المندوب: {e}"}), 400

    return jsonify({"success": True, "message": "تم إنشاء المندوب بنجاح"})


@bp.route("/api/v1/agents/<int:agent_id>/assign-invoice", methods=["POST"])
@onboarding_required
def api_v1_agent_assign_invoice(agent_id: int):
    """ربط فاتورة بمندوب وإنشاء عمولة تلقائياً."""
    payload = request.get_json(force=True) or {}
    clean, errs = validate(
        payload,
        {
            "invoice_id": [V.required, V.positive_int],
            "commission_rate": [V.optional, V.num_range(0, 100)],
        },
    )
    if errs:
        return jsonify({"success": False, "errors": errs}), 400

    db = get_db()
    biz_id = session["business_id"]

    agent = db.execute(
        "SELECT id, commission_rate FROM agents WHERE id=? AND business_id=? AND is_active=1",
        (agent_id, biz_id),
    ).fetchone()
    if not agent:
        return jsonify({"success": False, "error": "المندوب غير موجود"}), 404

    inv = db.execute(
        """SELECT id, total, invoice_type, status
           FROM invoices WHERE id=? AND business_id=?""",
        (clean["invoice_id"], biz_id),
    ).fetchone()
    if not inv:
        return jsonify({"success": False, "error": "الفاتورة غير موجودة"}), 404
    if inv["invoice_type"] not in ("sale", "table") or inv["status"] not in ("paid", "partial"):
        return jsonify({"success": False, "error": "العمولة متاحة لفواتير البيع المدفوعة/الجزئية فقط"}), 400

    rate = round(clean.get("commission_rate") if clean.get("commission_rate") is not None else agent["commission_rate"], 2)
    amount = round(float(inv["total"] or 0) * rate / 100, 2)

    try:
        db.execute("BEGIN IMMEDIATE")
        # agent_invoice_links: UNIQUE(business_id, invoice_id) — استخدم INSERT OR IGNORE ثم UPDATE
        db.execute(
            """INSERT OR IGNORE INTO agent_invoice_links
               (business_id, agent_id, invoice_id, created_at)
               VALUES (?,?,?,datetime('now'))""",
            (biz_id, agent_id, clean["invoice_id"]),
        )
        db.execute(
            """UPDATE agent_invoice_links SET agent_id=?
               WHERE business_id=? AND invoice_id=?""",
            (agent_id, biz_id, clean["invoice_id"]),
        )
        # agent_commissions: استخدم INSERT OR IGNORE + UPDATE
        db.execute(
            """INSERT OR IGNORE INTO agent_commissions
               (business_id, agent_id, invoice_id, invoice_total,
                commission_rate, commission_amount, status, created_at)
               VALUES (?,?,?,?,?,?,'pending',datetime('now'))""",
            (biz_id, agent_id, clean["invoice_id"],
             round(float(inv["total"] or 0), 2), rate, amount),
        )
        db.execute(
            """UPDATE agent_commissions
               SET agent_id=?, invoice_total=?, commission_rate=?, commission_amount=?
               WHERE business_id=? AND invoice_id=? AND status='pending'""",
            (agent_id, round(float(inv["total"] or 0), 2), rate, amount,
             biz_id, clean["invoice_id"]),
        )
        db.commit()
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": f"تعذر تسجيل العمولة: {e}"}), 500

    return jsonify(
        {
            "success": True,
            "invoice_id": clean["invoice_id"],
            "agent_id": agent_id,
            "commission_rate": rate,
            "commission_amount": amount,
            "message": "تم ربط الفاتورة بالمندوب وتسجيل العمولة",
        }
    )


@bp.route("/api/v1/agents/<int:agent_id>/commissions/summary")
@onboarding_required
def api_v1_agent_commissions_summary(agent_id: int):
    db = get_db()
    biz_id = session["business_id"]
    days = request.args.get("days", "30")
    try:
        days_int = max(1, min(int(days), 365))
    except ValueError:
        days_int = 30

    since = (datetime.now() - timedelta(days=days_int)).strftime("%Y-%m-%d")

    row = db.execute(
        """SELECT
               COUNT(*) AS invoices_count,
               COALESCE(SUM(commission_amount),0) AS commissions_total,
               COALESCE(SUM(CASE WHEN status='paid' THEN commission_amount ELSE 0 END),0) AS commissions_paid,
               COALESCE(SUM(CASE WHEN status='pending' THEN commission_amount ELSE 0 END),0) AS commissions_pending
           FROM agent_commissions
           WHERE business_id=? AND agent_id=? AND DATE(created_at) >= ?""",
        (biz_id, agent_id, since),
    ).fetchone()

    recent = db.execute(
        """SELECT ac.invoice_id, ac.invoice_total, ac.commission_rate, ac.commission_amount,
                  ac.status, ac.created_at, i.invoice_number
           FROM agent_commissions ac
           LEFT JOIN invoices i ON i.id=ac.invoice_id
           WHERE ac.business_id=? AND ac.agent_id=?
           ORDER BY ac.id DESC LIMIT 25""",
        (biz_id, agent_id),
    ).fetchall()

    return jsonify(
        {
            "success": True,
            "window_days": days_int,
            "summary": dict(row) if row else {},
            "recent": [dict(r) for r in recent],
        }
    )


@bp.route("/api/v1/agents/<int:agent_id>/whatsapp-campaign", methods=["POST"])
@onboarding_required
def api_v1_agent_whatsapp_campaign(agent_id: int):
    payload = request.get_json(force=True) or {}
    clean, errs = validate(
        payload,
        {
            "message": [V.required, V.str_max(500), V.safe_text],
        },
    )
    if errs:
        return jsonify({"success": False, "errors": errs}), 400

    db = get_db()
    biz_id = session["business_id"]

    agent = db.execute(
        "SELECT id, full_name FROM agents WHERE id=? AND business_id=? AND is_active=1",
        (agent_id, biz_id),
    ).fetchone()
    if not agent:
        return jsonify({"success": False, "error": "المندوب غير موجود"}), 404

    contacts = db.execute(
        """SELECT id, name, phone FROM contacts
           WHERE business_id=? AND contact_type IN ('customer','both')
             AND phone IS NOT NULL AND TRIM(phone)<>''
           ORDER BY id DESC LIMIT 50""",
        (biz_id,),
    ).fetchall()

    links = []
    txt = quote(clean["message"])
    for c in contacts:
        phone = "".join(ch for ch in (c["phone"] or "") if ch.isdigit())
        if phone.startswith("0"):
            phone = "966" + phone[1:]
        if not phone:
            continue
        links.append(
            {
                "contact_id": c["id"],
                "contact_name": c["name"],
                "whatsapp_url": f"https://wa.me/{phone}?text={txt}",
            }
        )

    return jsonify(
        {
            "success": True,
            "agent": agent["full_name"],
            "count": len(links),
            "links": links,
        }
    )


# ═══════════════════════════════════════════════════════════════
#  تعديل / تعطيل مندوب
# ═══════════════════════════════════════════════════════════════

@bp.route("/api/v1/agents/<int:agent_id>", methods=["PUT"])
@onboarding_required
def api_v1_agent_update(agent_id: int):
    payload = request.get_json(force=True) or {}
    db = get_db()
    biz_id = session["business_id"]
    agent = db.execute(
        "SELECT id FROM agents WHERE id=? AND business_id=?", (agent_id, biz_id)
    ).fetchone()
    if not agent:
        return jsonify({"success": False, "error": "المندوب غير موجود"}), 404

    fields = []
    vals = []
    for col in ["full_name", "phone", "whatsapp_number", "commission_rate", "region", "notes"]:
        if col in payload:
            fields.append(f"{col}=?")
            vals.append(payload[col])
    if not fields:
        return jsonify({"success": False, "error": "لا توجد بيانات للتحديث"}), 400
    vals.append(agent_id)
    db.execute(f"UPDATE agents SET {','.join(fields)} WHERE id=?", vals)
    db.commit()
    return jsonify({"success": True, "message": "تم تحديث بيانات المندوب"})


@bp.route("/api/v1/agents/<int:agent_id>/toggle", methods=["POST"])
@require_perm("settings")
def api_v1_agent_toggle(agent_id: int):
    """تفعيل أو تعطيل مندوب"""
    db = get_db()
    biz_id = session["business_id"]
    row = db.execute(
        "SELECT is_active FROM agents WHERE id=? AND business_id=?", (agent_id, biz_id)
    ).fetchone()
    if not row:
        return jsonify({"success": False, "error": "المندوب غير موجود"}), 404
    new_status = 0 if row["is_active"] else 1
    db.execute("UPDATE agents SET is_active=? WHERE id=?", (new_status, agent_id))
    db.commit()
    return jsonify({"success": True, "is_active": new_status})


# ═══════════════════════════════════════════════════════════════
#  تتبع الموقع (Location Tracking)
# ═══════════════════════════════════════════════════════════════

@bp.route("/api/v1/agents/<int:agent_id>/location", methods=["POST"])
@onboarding_required
def api_v1_agent_record_location(agent_id: int):
    """تسجيل موقع المندوب (يُستدعى كل 30 دقيقة)"""
    payload = request.get_json(force=True) or {}
    lat = payload.get("latitude")
    lng = payload.get("longitude")
    if lat is None or lng is None:
        return jsonify({"success": False, "error": "latitude و longitude مطلوبان"}), 400
    db = get_db()
    biz_id = session["business_id"]
    db.execute(
        """INSERT INTO agent_locations (business_id, agent_id, latitude, longitude, accuracy, battery)
           VALUES (?,?,?,?,?,?)""",
        (biz_id, agent_id, float(lat), float(lng),
         payload.get("accuracy"), payload.get("battery")),
    )
    db.commit()
    return jsonify({"success": True, "message": "تم تسجيل الموقع"})


@bp.route("/api/v1/agents/<int:agent_id>/locations")
@require_perm("settings")
def api_v1_agent_locations(agent_id: int):
    """مسار تحركات المندوب اليوم — للأدمن"""
    db = get_db()
    biz_id = session["business_id"]
    date_filter = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    rows = db.execute(
        """SELECT latitude, longitude, accuracy, battery, recorded_at
           FROM agent_locations
           WHERE business_id=? AND agent_id=? AND DATE(recorded_at)=?
           ORDER BY recorded_at""",
        (biz_id, agent_id, date_filter),
    ).fetchall()
    return jsonify({"success": True, "date": date_filter, "points": [dict(r) for r in rows]})


@bp.route("/api/v1/agents/all-locations")
@require_perm("settings")
def api_v1_all_agents_locations():
    """آخر موقع لكل مندوب — للخريطة الرئيسية"""
    db = get_db()
    biz_id = session["business_id"]
    rows = db.execute(
        """SELECT al.agent_id, a.full_name, a.phone, al.latitude, al.longitude,
                  al.battery, al.recorded_at
           FROM agent_locations al
           JOIN agents a ON a.id=al.agent_id
           WHERE al.business_id=?
             AND al.id IN (
               SELECT MAX(id) FROM agent_locations
               WHERE business_id=? GROUP BY agent_id
             )""",
        (biz_id, biz_id),
    ).fetchall()
    return jsonify({"success": True, "agents": [dict(r) for r in rows]})


# ═══════════════════════════════════════════════════════════════
#  الحضور والانصراف
# ═══════════════════════════════════════════════════════════════

@bp.route("/api/v1/agents/<int:agent_id>/attendance/checkin", methods=["POST"])
@onboarding_required
def api_v1_agent_checkin(agent_id: int):
    payload = request.get_json(force=True) or {}
    db = get_db()
    biz_id = session["business_id"]
    today = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    existing = db.execute(
        "SELECT id, checkin_at FROM agent_attendance WHERE agent_id=? AND work_date=? AND business_id=?",
        (agent_id, today, biz_id),
    ).fetchone()
    if existing and existing["checkin_at"]:
        return jsonify({"success": False, "error": "تم تسجيل الحضور مسبقاً اليوم"}), 400

    if existing:
        db.execute(
            "UPDATE agent_attendance SET checkin_at=?, checkin_lat=?, checkin_lng=? WHERE id=?",
            (now_str, payload.get("latitude"), payload.get("longitude"), existing["id"]),
        )
    else:
        db.execute(
            """INSERT INTO agent_attendance (business_id, agent_id, work_date, checkin_at, checkin_lat, checkin_lng)
               VALUES (?,?,?,?,?,?)""",
            (biz_id, agent_id, today, now_str, payload.get("latitude"), payload.get("longitude")),
        )
    db.commit()
    return jsonify({"success": True, "checkin_at": now_str, "message": "تم تسجيل الحضور"})


@bp.route("/api/v1/agents/<int:agent_id>/attendance/checkout", methods=["POST"])
@onboarding_required
def api_v1_agent_checkout(agent_id: int):
    payload = request.get_json(force=True) or {}
    db = get_db()
    biz_id = session["business_id"]
    today = datetime.now().strftime("%Y-%m-%d")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rec = db.execute(
        "SELECT id, checkin_at FROM agent_attendance WHERE agent_id=? AND work_date=? AND business_id=?",
        (agent_id, today, biz_id),
    ).fetchone()
    if not rec or not rec["checkin_at"]:
        return jsonify({"success": False, "error": "لم يتم تسجيل الحضور بعد"}), 400

    checkin_dt = datetime.strptime(rec["checkin_at"], "%Y-%m-%d %H:%M:%S")
    total_hours = round((datetime.now() - checkin_dt).total_seconds() / 3600, 2)

    db.execute(
        """UPDATE agent_attendance
           SET checkout_at=?, checkout_lat=?, checkout_lng=?, total_hours=?, notes=?
           WHERE id=?""",
        (now_str, payload.get("latitude"), payload.get("longitude"),
         total_hours, payload.get("notes"), rec["id"]),
    )
    db.commit()
    return jsonify({
        "success": True, "checkout_at": now_str,
        "total_hours": total_hours, "message": "تم تسجيل الانصراف"
    })


@bp.route("/api/v1/agents/<int:agent_id>/attendance")
@onboarding_required
def api_v1_agent_attendance_history(agent_id: int):
    db = get_db()
    biz_id = session["business_id"]
    rows = db.execute(
        """SELECT work_date, checkin_at, checkout_at, total_hours, notes
           FROM agent_attendance
           WHERE agent_id=? AND business_id=?
           ORDER BY work_date DESC LIMIT 30""",
        (agent_id, biz_id),
    ).fetchall()
    return jsonify({"success": True, "records": [dict(r) for r in rows]})


# ═══════════════════════════════════════════════════════════════
#  بيانات منشآت العملاء (Client Profiles)
# ═══════════════════════════════════════════════════════════════

@bp.route("/api/v1/agents/<int:agent_id>/client-profiles")
@onboarding_required
def api_v1_agent_client_profiles(agent_id: int):
    db = get_db()
    biz_id = session["business_id"]
    rows = db.execute(
        """SELECT id, contact_id, company_name, manager_name, phone, region, address, notes, is_active
           FROM agent_client_profiles
           WHERE agent_id=? AND business_id=?
           ORDER BY company_name""",
        (agent_id, biz_id),
    ).fetchall()
    return jsonify({"success": True, "profiles": [dict(r) for r in rows]})


@bp.route("/api/v1/agents/<int:agent_id>/client-profiles", methods=["POST"])
@onboarding_required
def api_v1_agent_client_profiles_create(agent_id: int):
    payload = request.get_json(force=True) or {}
    if not payload.get("company_name", "").strip():
        return jsonify({"success": False, "error": "اسم المنشأة مطلوب"}), 400
    db = get_db()
    biz_id = session["business_id"]
    db.execute(
        """INSERT INTO agent_client_profiles
           (business_id, agent_id, contact_id, company_name, manager_name, phone, region, address, notes, lat, lng)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (biz_id, agent_id,
         payload.get("contact_id"),
         payload["company_name"].strip(),
         payload.get("manager_name", "").strip() or None,
         payload.get("phone", "").strip() or None,
         payload.get("region", "").strip() or None,
         payload.get("address", "").strip() or None,
         payload.get("notes", "").strip() or None,
         payload.get("lat") or None,
         payload.get("lng") or None),
    )
    db.commit()
    return jsonify({"success": True, "message": "تم إضافة المنشأة"})


@bp.route("/api/v1/agents/<int:agent_id>/client-profiles/<int:profile_id>", methods=["PUT"])
@onboarding_required
def api_v1_agent_client_profile_update(agent_id: int, profile_id: int):
    payload = request.get_json(force=True) or {}
    db = get_db()
    biz_id = session["business_id"]
    fields, vals = [], []
    for col in ["company_name", "manager_name", "phone", "region", "address", "notes", "lat", "lng"]:
        if col in payload:
            fields.append(f"{col}=?")
            vals.append(payload[col])
    if not fields:
        return jsonify({"success": False, "error": "لا توجد بيانات"}), 400
    vals += [profile_id, agent_id, biz_id]
    db.execute(
        f"UPDATE agent_client_profiles SET {','.join(fields)},updated_at=datetime('now') WHERE id=? AND agent_id=? AND business_id=?",
        vals,
    )
    db.commit()
    return jsonify({"success": True, "message": "تم التحديث"})


# ═══════════════════════════════════════════════════════════════
#  سجل مشتريات العميل + آخر فاتورة
# ═══════════════════════════════════════════════════════════════

@bp.route("/api/v1/agents/<int:agent_id>/customers/<int:contact_id>/history")
@onboarding_required
def api_v1_customer_history(agent_id: int, contact_id: int):
    db = get_db()
    biz_id = session["business_id"]

    contact = db.execute(
        """SELECT c.id, c.name, c.phone,
                  cp.company_name, cp.manager_name, cp.region, cp.address,
                  cp.lat, cp.lng
           FROM contacts c
           LEFT JOIN agent_client_profiles cp
             ON cp.contact_id=c.id AND cp.agent_id=? AND cp.business_id=?
           WHERE c.id=? AND c.business_id=?""",
        (agent_id, biz_id, contact_id, biz_id),
    ).fetchone()
    if not contact:
        return jsonify({"success": False, "error": "العميل غير موجود"}), 404

    invoices = db.execute(
        """SELECT id, invoice_number, invoice_date, total, status, invoice_type
           FROM invoices
           WHERE business_id=? AND party_id=?
           ORDER BY id DESC LIMIT 20""",
        (biz_id, contact_id),
    ).fetchall()

    last_inv = invoices[0] if invoices else None
    total_spend = db.execute(
        """SELECT COALESCE(SUM(total),0) AS s FROM invoices
           WHERE business_id=? AND party_id=? AND status IN ('paid','partial')""",
        (biz_id, contact_id),
    ).fetchone()["s"]

    visits = db.execute(
        """SELECT visit_type, outcome, notes, visited_at
           FROM agent_visits
           WHERE business_id=? AND agent_id=? AND contact_id=?
           ORDER BY visited_at DESC LIMIT 10""",
        (biz_id, agent_id, contact_id),
    ).fetchall()

    return jsonify({
        "success": True,
        "contact": dict(contact),
        "total_spend": round(float(total_spend), 2),
        "last_invoice": dict(last_inv) if last_inv else None,
        "invoices": [dict(i) for i in invoices],
        "visits": [dict(v) for v in visits],
    })


# ═══════════════════════════════════════════════════════════════
#  إصدار فاتورة من المندوب + إرسال واتساب
# ═══════════════════════════════════════════════════════════════

@bp.route("/api/v1/agents/<int:agent_id>/invoices", methods=["POST"])
@onboarding_required
def api_v1_agent_create_invoice(agent_id: int):
    """إصدار فاتورة من المندوب مع مزامنة المخزون + ربط عمولة تلقائي"""
    payload = request.get_json(force=True) or {}
    items = payload.get("items", [])
    if not items:
        return jsonify({"success": False, "error": "الفاتورة لا تحتوي على منتجات"}), 400
    if not payload.get("contact_id") and not payload.get("client_name"):
        return jsonify({"success": False, "error": "اسم العميل أو contact_id مطلوب"}), 400

    db = get_db()
    biz_id = session["business_id"]

    # احتساب المجموع
    total = 0.0
    for item in items:
        qty = float(item.get("qty", 1))
        price = float(item.get("price", 0))
        total += qty * price

    tax_rate = float(
        (db.execute("SELECT tax_rate FROM tax_settings WHERE business_id=? LIMIT 1",
                    (biz_id,)).fetchone() or {"tax_rate": 0})["tax_rate"]
    )
    tax_amount = round(total * tax_rate / 100, 2)
    grand_total = round(total + tax_amount, 2)

    # رقم الفاتورة
    count = db.execute("SELECT COUNT(*) FROM invoices WHERE business_id=?", (biz_id,)).fetchone()[0]
    inv_number = f"AGT-{agent_id:03d}-{count+1:05d}"
    today = datetime.now().strftime("%Y-%m-%d")

    try:
        db.execute("BEGIN IMMEDIATE")

        # إنشاء الفاتورة
        db.execute(
            """INSERT INTO invoices
               (business_id, party_id, invoice_number, invoice_date, invoice_type,
                subtotal, tax_amount, total, status, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (biz_id, payload.get("contact_id"), inv_number, today, "sale",
             round(total, 2), tax_amount, grand_total,
             "draft", payload.get("notes", f"فاتورة مندوب #{agent_id}")),
        )
        inv_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # أسطر الفاتورة + خصم المخزون
        for item in items:
            product_id = item.get("product_id")
            qty = float(item.get("qty", 1))
            price = float(item.get("price", 0))
            line_total = round(qty * price, 2)

            db.execute(
                """INSERT INTO invoice_lines (invoice_id, product_id, description, quantity, unit_price, total)
                   VALUES (?,?,?,?,?,?)""",
                (inv_id, product_id, item.get("description", ""), qty, price, line_total),
            )

            # خصم من المخزون إذا كان المنتج مرتبطاً
            if product_id:
                db.execute(
                    """UPDATE stock SET quantity = MAX(0, quantity - ?)
                       WHERE product_id=? AND business_id=?""",
                    (qty, product_id, biz_id),
                )
                db.execute(
                    """INSERT INTO inventory_movements
                       (business_id, product_id, movement_type, quantity, reference_type, reference_id, reason)
                       VALUES (?,?,?,?,?,?,?)""",
                    (biz_id, product_id, "out", qty, "invoice", inv_id,
                     f"مبيعات مندوب #{agent_id}"),
                )

        # ربط عمولة تلقائياً
        agent_row = db.execute(
            "SELECT commission_rate FROM agents WHERE id=? AND business_id=?",
            (agent_id, biz_id),
        ).fetchone()
        if agent_row and float(agent_row["commission_rate"] or 0) > 0:
            rate = float(agent_row["commission_rate"])
            comm_amount = round(grand_total * rate / 100, 2)
            db.execute(
                """INSERT INTO agent_commissions
                   (business_id, agent_id, invoice_id, invoice_total, commission_rate, commission_amount, status)
                   VALUES (?,?,?,?,?,?,'pending')""",
                (biz_id, agent_id, inv_id, grand_total, rate, comm_amount),
            )
            db.execute(
                """INSERT OR IGNORE INTO agent_invoice_links (business_id, agent_id, invoice_id)
                   VALUES (?,?,?)""",
                (biz_id, agent_id, inv_id),
            )

        db.commit()

    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": f"فشل إنشاء الفاتورة: {e}"}), 500

    # رابط واتساب لإرسال الفاتورة
    contact_phone = None
    if payload.get("contact_id"):
        c = db.execute("SELECT phone FROM contacts WHERE id=?", (payload["contact_id"],)).fetchone()
        if c:
            contact_phone = c["phone"]
    if not contact_phone:
        contact_phone = payload.get("client_phone", "")

    wa_url = None
    if contact_phone:
        phone = "".join(ch for ch in contact_phone if ch.isdigit())
        if phone.startswith("0"):
            phone = "966" + phone[1:]
        msg = (f"السلام عليكم 🌿\n"
               f"فاتورتكم رقم {inv_number}\n"
               f"الإجمالي: {grand_total:,.2f} ر.س\n"
               f"شكراً لتعاملكم معنا ✨")
        wa_url = f"https://wa.me/{phone}?text={quote(msg)}"

    return jsonify({
        "success": True,
        "invoice_id": inv_id,
        "invoice_number": inv_number,
        "grand_total": grand_total,
        "whatsapp_url": wa_url,
        "message": "تم إنشاء الفاتورة بنجاح",
    })


# ═══════════════════════════════════════════════════════════════
#  مزامنة أوفلاين (Offline Sync Queue)
# ═══════════════════════════════════════════════════════════════

def _get_agent_biz(agent_id: int) -> tuple:
    """يُعيد (db, biz_id) مع دعم كلا النوعين من الجلسة: admin أو agent"""
    db = get_db()
    if session.get("agent_id") == agent_id:
        return db, session["agent_biz_id"]
    if session.get("business_id"):
        return db, session["business_id"]
    return db, None


@bp.route("/api/v1/agents/<int:agent_id>/sync", methods=["POST"])
def api_v1_agent_sync(agent_id: int):
    """مزامنة الطلبات المحفوظة أوفلاين — يعالجها فعلياً: فواتير، زيارات، تحصيل، حضور، موقع"""
    db, biz_id = _get_agent_biz(agent_id)
    if not biz_id:
        return jsonify({"success": False, "error": "unauthorized"}), 401

    payload = request.get_json(force=True) or {}
    queue   = payload.get("queue", [])
    if not queue:
        return jsonify({"success": True, "processed": 0})

    results   = []
    processed = 0
    from urllib.parse import quote as _quote

    for item in queue:
        action      = item.get("action_type", "")
        p           = item.get("payload", {})
        local_id    = item.get("local_id")

        # تسجيل في جدول المزامنة
        db.execute(
            """INSERT INTO agent_sync_queue (business_id, agent_id, action_type, payload_json, status)
               VALUES (?,?,?,?,'processing')""",
            (biz_id, agent_id, action, json.dumps(p, ensure_ascii=False)),
        )
        sq_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        try:
            # ─── إنشاء فاتورة ──────────────────────────────────────────
            if action == "create_invoice":
                items    = p.get("items", [])
                if not items:
                    raise ValueError("لا توجد أصناف في الفاتورة")
                now_str  = datetime.now().isoformat(timespec="seconds")
                inv_num  = f"AGT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{agent_id}"
                grand    = sum(float(i.get("qty",1))*float(i.get("unit_price",0)) for i in items)

                db.execute(
                    """INSERT INTO invoices
                       (business_id, invoice_number, invoice_date, due_date, status,
                        party_id, notes, subtotal, tax_amount, total, invoice_type)
                       VALUES (?,?,date('now'),date('now','+30 days'),'unpaid',?,?,?,0,?,'sale')""",
                    (biz_id, inv_num,
                     p.get("contact_id") or None,
                     (p.get("client_name","") + " - " + p.get("notes","")).strip(" -") or None,
                     grand, grand),
                )
                inv_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

                for i in items:
                    qty   = float(i.get("qty",1))
                    price = float(i.get("unit_price",0))
                    db.execute(
                        """INSERT INTO invoice_lines (invoice_id, product_id, description, quantity, unit_price, total)
                           VALUES (?,?,?,?,?,?)""",
                        (inv_id, i.get("product_id"), i.get("description","").strip() or None,
                         qty, price, round(qty*price,2)),
                    )
                    if i.get("product_id"):
                        db.execute(
                            """UPDATE stock SET quantity = MAX(0, quantity - ?)
                               WHERE product_id=? AND business_id=?""",
                            (qty, i["product_id"], biz_id),
                        )
                        db.execute(
                            """INSERT INTO inventory_movements
                               (business_id, product_id, movement_type, quantity, reference_type, reference_id, reason)
                               VALUES (?,?,'sale',?,?,'invoice',?)""",
                            (biz_id, i["product_id"], qty, "invoice", inv_id,
                             f"مبيعات مندوب #{agent_id} — أوفلاين"),
                        )

                # عمولة
                ag = db.execute("SELECT commission_rate FROM agents WHERE id=? AND business_id=?",
                                (agent_id, biz_id)).fetchone()
                if ag and float(ag["commission_rate"] or 0) > 0:
                    rate  = float(ag["commission_rate"])
                    comm  = round(grand * rate / 100, 2)
                    db.execute(
                        """INSERT INTO agent_commissions
                           (business_id, agent_id, invoice_id, invoice_total, commission_rate, commission_amount, status)
                           VALUES (?,?,?,?,?,?,'pending')""",
                        (biz_id, agent_id, inv_id, grand, rate, comm),
                    )
                db.execute(
                    "INSERT OR IGNORE INTO agent_invoice_links (business_id, agent_id, invoice_id) VALUES (?,?,?)",
                    (biz_id, agent_id, inv_id),
                )
                results.append({"local_id": local_id, "status": "done",
                                 "invoice_id": inv_id, "invoice_number": inv_num})

            # ─── تسجيل زيارة ──────────────────────────────────────────
            elif action == "log_visit":
                db.execute(
                    """INSERT INTO agent_visits
                       (business_id, agent_id, contact_id, client_profile_id, visit_type,
                        outcome, notes, rejection_reason, lat, lng)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (biz_id, agent_id,
                     p.get("contact_id"), p.get("client_profile_id"),
                     p.get("visit_type","visit"), p.get("outcome","neutral"),
                     p.get("notes","").strip() or None,
                     p.get("rejection_reason","").strip() or None,
                     p.get("lat"), p.get("lng")),
                )
                results.append({"local_id": local_id, "status": "done"})

            # ─── تحصيل دفعة ───────────────────────────────────────────
            elif action == "collect_payment":
                amt = float(p.get("amount",0))
                if amt <= 0:
                    raise ValueError("مبلغ التحصيل غير صالح")
                db.execute(
                    """INSERT INTO agent_collections
                       (business_id, agent_id, contact_id, invoice_id, amount,
                        payment_method, notes, collected_at, confirmed)
                       VALUES (?,?,?,?,?,?,?,datetime('now'),0)""",
                    (biz_id, agent_id,
                     p.get("contact_id"), p.get("invoice_id"),
                     amt, p.get("payment_method","cash"),
                     p.get("notes","").strip() or None),
                )
                results.append({"local_id": local_id, "status": "done"})

            # ─── تسجيل حضور ───────────────────────────────────────────
            elif action == "checkin":
                today = datetime.now().strftime("%Y-%m-%d")
                existing = db.execute(
                    "SELECT id FROM agent_attendance WHERE agent_id=? AND work_date=?",
                    (agent_id, today),
                ).fetchone()
                if not existing:
                    db.execute(
                        """INSERT INTO agent_attendance
                           (business_id, agent_id, work_date, checkin_at, checkin_lat, checkin_lng)
                           VALUES (?,?,?,datetime('now'),?,?)""",
                        (biz_id, agent_id, today,
                         p.get("lat"), p.get("lng")),
                    )
                results.append({"local_id": local_id, "status": "done"})

            # ─── تسجيل انصراف ─────────────────────────────────────────
            elif action == "checkout":
                rec = db.execute(
                    "SELECT id, checkin_at FROM agent_attendance WHERE agent_id=? AND work_date=date('now')",
                    (agent_id,),
                ).fetchone()
                if rec:
                    now_ts = datetime.now()
                    ci     = datetime.fromisoformat(rec["checkin_at"].replace("Z",""))
                    hours  = round((now_ts - ci).total_seconds() / 3600, 2)
                    db.execute(
                        """UPDATE agent_attendance
                           SET checkout_at=datetime('now'), checkout_lat=?, checkout_lng=?, total_hours=?
                           WHERE id=?""",
                        (p.get("lat"), p.get("lng"), hours, rec["id"]),
                    )
                results.append({"local_id": local_id, "status": "done"})

            # ─── موقع GPS ─────────────────────────────────────────────
            elif action == "log_location":
                db.execute(
                    """INSERT INTO agent_locations
                       (business_id, agent_id, latitude, longitude, accuracy, battery, recorded_at)
                       VALUES (?,?,?,?,?,?,datetime('now'))""",
                    (biz_id, agent_id,
                     p.get("lat"), p.get("lng"),
                     p.get("accuracy"), p.get("battery")),
                )
                results.append({"local_id": local_id, "status": "done"})

            # ─── إضافة عميل ───────────────────────────────────────────
            elif action == "add_client":
                db.execute(
                    """INSERT INTO agent_client_profiles
                       (business_id, agent_id, company_name, manager_name, phone, region, address, notes, lat, lng, is_active)
                       VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
                    (biz_id, agent_id,
                     p.get("company_name","").strip(),
                     p.get("manager_name","").strip() or None,
                     p.get("phone","").strip() or None,
                     p.get("region","").strip() or None,
                     p.get("address","").strip() or None,
                     p.get("notes","").strip() or None,
                     p.get("lat") or None,
                     p.get("lng") or None),
                )
                results.append({"local_id": local_id, "status": "done"})

            # ─── طلب مسودة ────────────────────────────────────────────
            elif action == "draft_order":
                db.execute(
                    """INSERT INTO agent_draft_orders
                       (business_id, agent_id, contact_id, client_name, items_json, total, notes, status)
                       VALUES (?,?,?,?,?,?,?,'pending')""",
                    (biz_id, agent_id,
                     p.get("contact_id"),
                     p.get("client_name","").strip() or None,
                     json.dumps(p.get("items",[]), ensure_ascii=False),
                     float(p.get("total",0)),
                     p.get("notes","").strip() or None),
                )
                results.append({"local_id": local_id, "status": "done"})

            else:
                results.append({"local_id": local_id, "status": "skipped", "reason": f"action '{action}' unknown"})

            db.execute(
                "UPDATE agent_sync_queue SET status='done', synced_at=datetime('now') WHERE id=?",
                (sq_id,),
            )
            processed += 1

        except Exception as exc:
            db.execute(
                "UPDATE agent_sync_queue SET status='failed', error_msg=? WHERE id=?",
                (str(exc), sq_id),
            )
            results.append({"local_id": local_id, "status": "failed", "error": str(exc)})

    db.commit()
    return jsonify({"success": True, "processed": processed, "results": results})


# ═══════════════════════════════════════════════════════════════
#  كاتالوج المنتجات (للمندوب — يعمل أوفلاين)
# ═══════════════════════════════════════════════════════════════

@bp.route("/api/v1/agents/<int:agent_id>/products")
def api_v1_agent_products(agent_id: int):
    """جلب كاتالوج المنتجات مع المخزون — للحفظ أوفلاين"""
    db, biz_id = _get_agent_biz(agent_id)
    if not biz_id:
        return jsonify({"success": False, "error": "unauthorized"}), 401
    rows = db.execute(
        """SELECT p.id, p.name, p.barcode, p.sale_price,
                  p.category_name,
                  COALESCE(s.quantity, 0) AS stock_qty
           FROM products p
           LEFT JOIN stock s ON s.product_id=p.id AND s.business_id=p.business_id
           WHERE p.business_id=? AND p.is_active=1
           ORDER BY p.category_name, p.name""",
        (biz_id,),
    ).fetchall()
    return jsonify({
        "success": True,
        "products": [dict(r) for r in rows],
        "cached_at": datetime.now().isoformat(timespec="seconds"),
    })


# ═══════════════════════════════════════════════════════════════
#  سجل الزيارات والمكالمات
# ═══════════════════════════════════════════════════════════════

@bp.route("/api/v1/agents/<int:agent_id>/visits", methods=["POST"])
@onboarding_required
def api_v1_agent_visit_create(agent_id: int):
    payload = request.get_json(force=True) or {}
    db = get_db()
    biz_id = session["business_id"]
    db.execute(
        """INSERT INTO agent_visits
           (business_id, agent_id, contact_id, client_profile_id, visit_type,
            outcome, notes, rejection_reason, lat, lng)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (biz_id, agent_id,
         payload.get("contact_id"),
         payload.get("client_profile_id"),
         payload.get("visit_type", "visit"),
         payload.get("outcome", "neutral"),
         payload.get("notes", "").strip() or None,
         payload.get("rejection_reason", "").strip() or None,
         payload.get("lat"), payload.get("lng")),
    )
    db.commit()
    return jsonify({"success": True, "message": "تم تسجيل الزيارة"})


@bp.route("/api/v1/agents/<int:agent_id>/visits")
@onboarding_required
def api_v1_agent_visits_list(agent_id: int):
    db = get_db()
    biz_id = session["business_id"]
    rows = db.execute(
        """SELECT av.id, av.visit_type, av.outcome, av.notes, av.rejection_reason,
                  av.visited_at, c.name AS contact_name
           FROM agent_visits av
           LEFT JOIN contacts c ON c.id=av.contact_id
           WHERE av.agent_id=? AND av.business_id=?
           ORDER BY av.visited_at DESC LIMIT 50""",
        (agent_id, biz_id),
    ).fetchall()
    return jsonify({"success": True, "visits": [dict(r) for r in rows]})


# ═══════════════════════════════════════════════════════════════
#  طلبات مسودة (Draft Orders)
# ═══════════════════════════════════════════════════════════════

@bp.route("/api/v1/agents/<int:agent_id>/draft-orders", methods=["POST"])
@onboarding_required
def api_v1_agent_draft_order_create(agent_id: int):
    payload = request.get_json(force=True) or {}
    items = payload.get("items", [])
    total = sum(float(i.get("qty", 1)) * float(i.get("price", 0)) for i in items)
    db = get_db()
    biz_id = session["business_id"]
    db.execute(
        """INSERT INTO agent_draft_orders
           (business_id, agent_id, contact_id, client_name, items_json, total, notes)
           VALUES (?,?,?,?,?,?,?)""",
        (biz_id, agent_id,
         payload.get("contact_id"),
         payload.get("client_name", "").strip() or None,
         json.dumps(items, ensure_ascii=False),
         round(total, 2),
         payload.get("notes", "").strip() or None),
    )
    db.commit()
    return jsonify({"success": True, "message": "تم حفظ الطلب كمسودة"})


@bp.route("/api/v1/agents/<int:agent_id>/draft-orders")
@onboarding_required
def api_v1_agent_draft_orders_list(agent_id: int):
    db = get_db()
    biz_id = session["business_id"]
    rows = db.execute(
        """SELECT id, contact_id, client_name, items_json, total, status, notes, created_at
           FROM agent_draft_orders
           WHERE agent_id=? AND business_id=? AND status='pending'
           ORDER BY id DESC""",
        (agent_id, biz_id),
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["items"] = json.loads(d["items_json"] or "[]")
        result.append(d)
    return jsonify({"success": True, "orders": result})


@bp.route("/api/v1/agents/draft-orders/<int:order_id>/approve", methods=["POST"])
@require_perm("settings")
def api_v1_draft_order_approve(order_id: int):
    """أدمن يوافق على طلب المندوب ويحوّله لفاتورة"""
    db = get_db()
    biz_id = session["business_id"]
    order = db.execute(
        "SELECT * FROM agent_draft_orders WHERE id=? AND business_id=? AND status='pending'",
        (order_id, biz_id),
    ).fetchone()
    if not order:
        return jsonify({"success": False, "error": "الطلب غير موجود"}), 404
    db.execute(
        "UPDATE agent_draft_orders SET status='approved', updated_at=datetime('now') WHERE id=?",
        (order_id,),
    )
    db.commit()
    return jsonify({"success": True, "message": "تمت الموافقة على الطلب"})


# ═══════════════════════════════════════════════════════════════
#  تحصيل دفعات من العملاء بالميدان
# ═══════════════════════════════════════════════════════════════

@bp.route("/api/v1/agents/<int:agent_id>/collect-payment", methods=["POST"])
@onboarding_required
def api_v1_agent_collect_payment(agent_id: int):
    payload = request.get_json(force=True) or {}
    amount = payload.get("amount")
    if not amount or float(amount) <= 0:
        return jsonify({"success": False, "error": "المبلغ مطلوب وأكبر من صفر"}), 400
    db = get_db()
    biz_id = session["business_id"]
    db.execute(
        """INSERT INTO agent_collections
           (business_id, agent_id, contact_id, invoice_id, amount, payment_method, notes)
           VALUES (?,?,?,?,?,?,?)""",
        (biz_id, agent_id,
         payload.get("contact_id"),
         payload.get("invoice_id"),
         round(float(amount), 2),
         payload.get("payment_method", "cash"),
         payload.get("notes", "").strip() or None),
    )
    db.commit()
    return jsonify({"success": True, "message": "تم تسجيل التحصيل — في انتظار تأكيد الأدمن"})


@bp.route("/api/v1/agents/collections")
@require_perm("settings")
def api_v1_agent_collections_list():
    """قائمة التحصيلات المعلقة — للأدمن"""
    db = get_db()
    biz_id = session["business_id"]
    rows = db.execute(
        """SELECT ac.id, ac.agent_id, a.full_name AS agent_name,
                  ac.contact_id, c.name AS contact_name,
                  ac.invoice_id, ac.amount, ac.payment_method,
                  ac.notes, ac.collected_at, ac.confirmed
           FROM agent_collections ac
           JOIN agents a ON a.id=ac.agent_id
           LEFT JOIN contacts c ON c.id=ac.contact_id
           WHERE ac.business_id=?
           ORDER BY ac.id DESC LIMIT 100""",
        (biz_id,),
    ).fetchall()
    return jsonify({"success": True, "collections": [dict(r) for r in rows]})


@bp.route("/api/v1/agents/collections/<int:col_id>/confirm", methods=["POST"])
@require_perm("settings")
def api_v1_collection_confirm(col_id: int):
    db = get_db()
    biz_id = session["business_id"]
    user_id = session.get("user_id")
    col = db.execute(
        "SELECT id, invoice_id, amount, confirmed FROM agent_collections WHERE id=? AND business_id=?",
        (col_id, biz_id),
    ).fetchone()
    if not col:
        return jsonify({"success": False, "error": "السجل غير موجود"}), 404
    if col["confirmed"]:
        return jsonify({"success": False, "error": "تم التأكيد مسبقاً"}), 400
    db.execute(
        """UPDATE agent_collections
           SET confirmed=1, confirmed_by=?, confirmed_at=datetime('now')
           WHERE id=?""",
        (user_id, col_id),
    )
    db.commit()
    return jsonify({"success": True, "message": "تم تأكيد التحصيل"})


# ═══════════════════════════════════════════════════════════════
#  الأهداف الشهرية
# ═══════════════════════════════════════════════════════════════

@bp.route("/api/v1/agents/<int:agent_id>/targets")
@onboarding_required
def api_v1_agent_targets(agent_id: int):
    db = get_db()
    biz_id = session["business_id"]
    month = request.args.get("month", datetime.now().strftime("%Y-%m"))

    target = db.execute(
        "SELECT * FROM agent_targets WHERE agent_id=? AND business_id=? AND target_month=?",
        (agent_id, biz_id, month),
    ).fetchone()

    achieved = db.execute(
        """SELECT COALESCE(SUM(i.total),0) AS s
           FROM agent_invoice_links ail
           JOIN invoices i ON i.id=ail.invoice_id
           WHERE ail.agent_id=? AND ail.business_id=?
             AND strftime('%Y-%m', i.invoice_date)=?
             AND i.status IN ('paid','partial')""",
        (agent_id, biz_id, month),
    ).fetchone()["s"]

    target_amount = float(target["target_amount"] if target else 0)
    achieved_amount = round(float(achieved), 2)
    pct = round(achieved_amount / target_amount * 100, 1) if target_amount > 0 else 0

    return jsonify({
        "success": True,
        "month": month,
        "target_amount": target_amount,
        "achieved_amount": achieved_amount,
        "achievement_pct": pct,
        "bonus_amount": float(target["bonus_amount"]) if target else 0,
        "bonus_threshold": float(target["bonus_threshold"]) if target else 0,
    })


@bp.route("/api/v1/agents/<int:agent_id>/targets", methods=["POST"])
@require_perm("settings")
def api_v1_agent_target_set(agent_id: int):
    payload = request.get_json(force=True) or {}
    month = payload.get("month", datetime.now().strftime("%Y-%m"))
    target_amount = float(payload.get("target_amount", 0))
    db = get_db()
    biz_id = session["business_id"]
    db.execute(
        """INSERT INTO agent_targets (business_id, agent_id, target_month, target_amount, bonus_amount, bonus_threshold, notes)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(business_id, agent_id, target_month)
           DO UPDATE SET target_amount=excluded.target_amount,
              bonus_amount=excluded.bonus_amount,
              bonus_threshold=excluded.bonus_threshold,
              notes=excluded.notes""",
        (biz_id, agent_id, month, target_amount,
         float(payload.get("bonus_amount", 0)),
         float(payload.get("bonus_threshold", 0)),
         payload.get("notes")),
    )
    db.commit()
    return jsonify({"success": True, "message": "تم تحديد الهدف"})


# ═══════════════════════════════════════════════════════════════
#  إرسال عروض للعملاء عبر واتساب (مع رسالة مخصصة)
# ═══════════════════════════════════════════════════════════════

@bp.route("/api/v1/agents/<int:agent_id>/send-offer", methods=["POST"])
@onboarding_required
def api_v1_agent_send_offer(agent_id: int):
    payload = request.get_json(force=True) or {}
    message = (payload.get("message") or "").strip()
    contact_ids = payload.get("contact_ids", [])  # قائمة محددة أو كل العملاء
    if not message:
        return jsonify({"success": False, "error": "نص العرض مطلوب"}), 400

    db = get_db()
    biz_id = session["business_id"]

    if contact_ids:
        placeholders = ",".join("?" * len(contact_ids))
        contacts = db.execute(
            f"SELECT id, name, phone FROM contacts WHERE id IN ({placeholders}) AND business_id=?",
            list(contact_ids) + [biz_id],
        ).fetchall()
    else:
        contacts = db.execute(
            """SELECT id, name, phone FROM contacts
               WHERE business_id=? AND contact_type IN ('customer','both')
               AND phone IS NOT NULL AND TRIM(phone)<>''
               ORDER BY id DESC LIMIT 100""",
            (biz_id,),
        ).fetchall()

    txt = quote(message)
    links = []
    for c in contacts:
        phone = "".join(ch for ch in (c["phone"] or "") if ch.isdigit())
        if phone.startswith("0"):
            phone = "966" + phone[1:]
        if not phone:
            continue
        links.append({
            "contact_id": c["id"],
            "contact_name": c["name"],
            "whatsapp_url": f"https://wa.me/{phone}?text={txt}",
        })

    return jsonify({
        "success": True,
        "count": len(links),
        "links": links,
    })


# ═══════════════════════════════════════════════════════════════
#  تذكيرات ذكية — عملاء لم تتم زيارتهم منذ X يوم
# ═══════════════════════════════════════════════════════════════

@bp.route("/api/v1/agents/<int:agent_id>/reminders")
@onboarding_required
def api_v1_agent_reminders(agent_id: int):
    db = get_db()
    biz_id = session["business_id"]
    days = int(request.args.get("days", 30))
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    # عملاء لم يُزاروا منذ X يوم (أو لم يُزاروا قط)
    rows = db.execute(
        """SELECT c.id, c.name, c.phone,
                  MAX(av.visited_at) AS last_visit,
                  CAST(julianday('now') - julianday(COALESCE(MAX(av.visited_at), c.created_at)) AS INTEGER) AS days_since
           FROM contacts c
           LEFT JOIN agent_visits av ON av.contact_id=c.id AND av.agent_id=? AND av.business_id=?
           WHERE c.business_id=? AND c.contact_type IN ('customer','both')
           GROUP BY c.id
           HAVING COALESCE(MAX(av.visited_at), '1970-01-01') < ?
           ORDER BY days_since DESC
           LIMIT 20""",
        (agent_id, biz_id, biz_id, since),
    ).fetchall()

    return jsonify({
        "success": True,
        "days_threshold": days,
        "reminders": [dict(r) for r in rows],
    })


# ═══════════════════════════════════════════════════════════════
#  تقرير مقارنة المناديب — للأدمن
# ═══════════════════════════════════════════════════════════════

@bp.route("/api/v1/agents/performance")
@require_perm("settings")
def api_v1_agents_performance():
    """مقارنة أداء جميع المناديب للشهر الحالي"""
    db = get_db()
    biz_id = session["business_id"]
    month = request.args.get("month", datetime.now().strftime("%Y-%m"))

    rows = db.execute(
        """SELECT a.id, a.full_name, a.commission_rate,
                  COUNT(DISTINCT ail.invoice_id) AS invoices_count,
                  COALESCE(SUM(i.total),0) AS sales_total,
                  COALESCE(SUM(ac_comm.commission_amount),0) AS commissions_total,
                  COUNT(DISTINCT av.id) AS visits_count,
                  at2.target_amount,
                  CASE WHEN at2.target_amount > 0
                    THEN ROUND(COALESCE(SUM(i.total),0) / at2.target_amount * 100, 1)
                    ELSE 0 END AS achievement_pct
           FROM agents a
           LEFT JOIN agent_invoice_links ail ON ail.agent_id=a.id AND ail.business_id=a.business_id
           LEFT JOIN invoices i ON i.id=ail.invoice_id
               AND strftime('%Y-%m', i.invoice_date)=?
               AND i.status IN ('paid','partial')
           LEFT JOIN agent_commissions ac_comm ON ac_comm.agent_id=a.id
               AND ac_comm.business_id=a.business_id
               AND strftime('%Y-%m', ac_comm.created_at)=?
           LEFT JOIN agent_visits av ON av.agent_id=a.id
               AND av.business_id=a.business_id
               AND strftime('%Y-%m', av.visited_at)=?
           LEFT JOIN agent_targets at2 ON at2.agent_id=a.id
               AND at2.business_id=a.business_id
               AND at2.target_month=?
           WHERE a.business_id=? AND a.is_active=1
           GROUP BY a.id
           ORDER BY sales_total DESC""",
        (month, month, month, month, biz_id),
    ).fetchall()

    return jsonify({
        "success": True,
        "month": month,
        "agents": [dict(r) for r in rows],
    })


# ═══════════════════════════════════════════════════════════════
#  إعدادات المندوبين العامة (الأدمن)
# ═══════════════════════════════════════════════════════════════

@bp.route("/api/v1/agent-settings", methods=["GET", "POST"])
@require_perm("settings")
def api_agent_settings():
    """GET: جلب الإعدادات — POST: حفظ الإعدادات"""
    db     = get_db()
    biz_id = session["business_id"]

    if request.method == "GET":
        row = db.execute(
            "SELECT * FROM business_settings_ext WHERE business_id=?", (biz_id,)
        ).fetchone()
        defaults = {
            "agent_location_interval": 30,
            "agent_reminder_days":     30,
            "agent_can_discount":      0,
            "agent_can_edit_price":    0,
            "agent_can_view_cost":     0,
            "agent_can_collect":       1,
            "agent_can_add_client":    1,
            "agent_can_create_draft":  1,
            "agent_can_send_offer":    1,
            "agent_max_discount_pct":  0.0,
        }
        if row:
            data = dict(row)
            for k, v in defaults.items():
                if data.get(k) is None:
                    data[k] = v
        else:
            data = defaults
        return jsonify({"success": True, "settings": data})

    # POST — حفظ
    payload = request.get_json(force=True) or {}

    allowed_int  = ["agent_location_interval", "agent_reminder_days",
                    "agent_can_discount", "agent_can_edit_price",
                    "agent_can_view_cost", "agent_can_collect",
                    "agent_can_add_client", "agent_can_create_draft",
                    "agent_can_send_offer"]
    allowed_real = ["agent_max_discount_pct"]

    fields, vals = [], []
    for k in allowed_int:
        if k in payload:
            fields.append(f"{k}=?")
            vals.append(int(payload[k]))
    for k in allowed_real:
        if k in payload:
            fields.append(f"{k}=?")
            vals.append(float(payload[k]))

    if not fields:
        return jsonify({"success": False, "error": "لا توجد بيانات"}), 400

    vals.append(biz_id)
    # upsert
    db.execute(
        f"""INSERT INTO business_settings_ext (business_id, updated_at)
            VALUES (?, datetime('now'))
            ON CONFLICT(business_id) DO UPDATE SET updated_at=datetime('now')""",
        (biz_id,)
    )
    db.execute(
        f"UPDATE business_settings_ext SET {', '.join(fields)}, updated_at=datetime('now') WHERE business_id=?",
        vals
    )
    db.commit()
    return jsonify({"success": True, "message": "تم حفظ الإعدادات"})


# ═══════════════════════════════════════════════════════════════
#  صلاحيات مندوب بعينه (override فوق الإعدادات العامة)
# ═══════════════════════════════════════════════════════════════

@bp.route("/api/v1/agents/<int:agent_id>/permissions", methods=["GET", "POST"])
@require_perm("settings")
def api_agent_permissions(agent_id: int):
    """GET: جلب صلاحيات مندوب — POST: حفظ/تعديل"""
    db     = get_db()
    biz_id = session["business_id"]

    agent = db.execute(
        "SELECT * FROM agents WHERE id=? AND business_id=?", (agent_id, biz_id)
    ).fetchone()
    if not agent:
        return jsonify({"success": False, "error": "المندوب غير موجود"}), 404

    # جلب الإعدادات العامة كـ fallback
    ext = db.execute(
        "SELECT * FROM business_settings_ext WHERE business_id=?", (biz_id,)
    ).fetchone()
    ext_d = dict(ext) if ext else {}

    perm_map = {
        "perm_discount":    ("agent_can_discount",    0),
        "perm_edit_price":  ("agent_can_edit_price",  0),
        "perm_view_cost":   ("agent_can_view_cost",   0),
        "perm_collect":     ("agent_can_collect",     1),
        "perm_add_client":  ("agent_can_add_client",  1),
        "perm_create_draft":("agent_can_create_draft",1),
        "perm_send_offer":  ("agent_can_send_offer",  1),
        "max_discount_pct": ("agent_max_discount_pct",0.0),
    }

    if request.method == "GET":
        a = dict(agent)
        perms = {}
        for col, (global_col, default) in perm_map.items():
            # NULL = يرث من العام، أي قيمة أخرى = override
            individual = a.get(col)
            effective  = individual if individual is not None else ext_d.get(global_col, default)
            perms[col] = {
                "individual": individual,
                "effective":  effective,
                "inherited":  individual is None,
            }
        return jsonify({"success": True, "agent_id": agent_id, "permissions": perms})

    # POST
    payload = request.get_json(force=True) or {}
    fields, vals = [], []
    for col in ["perm_discount","perm_edit_price","perm_view_cost",
                "perm_collect","perm_add_client","perm_create_draft","perm_send_offer"]:
        if col in payload:
            v = payload[col]
            fields.append(f"{col}=?")
            vals.append(None if v is None else int(v))
    if "max_discount_pct" in payload:
        v = payload["max_discount_pct"]
        fields.append("max_discount_pct=?")
        vals.append(None if v is None else float(v))

    if not fields:
        return jsonify({"success": False, "error": "لا توجد بيانات"}), 400

    vals += [agent_id, biz_id]
    db.execute(
        f"UPDATE agents SET {', '.join(fields)}, updated_at=datetime('now') WHERE id=? AND business_id=?",
        vals
    )
    db.commit()
    return jsonify({"success": True, "message": "تم حفظ صلاحيات المندوب"})


# ═══════════════════════════════════════════════════════════════
#  endpoint للمندوب: جلب إعداداته الفعلية (مدمجة عام + فردي)
# ═══════════════════════════════════════════════════════════════

@bp.route("/api/v1/agent/settings")
def api_agent_my_settings():
    """المندوب يجلب إعداداته (يدعم session المندوب)"""
    # يدعم session المندوب المستقل
    if "agent_id" in session:
        agent_id = session["agent_id"]
        biz_id   = session["agent_biz_id"]
    elif "user_id" in session:
        # للأدمن أو التجربة
        agent_id = request.args.get("agent_id", type=int)
        biz_id   = session.get("business_id")
        if not agent_id:
            return jsonify({"success": False, "error": "agent_id مطلوب"}), 400
    else:
        return jsonify({"success": False, "error": "غير مصرح"}), 401

    db = get_db()
    agent = db.execute(
        "SELECT * FROM agents WHERE id=? AND business_id=?", (agent_id, biz_id)
    ).fetchone()
    if not agent:
        return jsonify({"success": False, "error": "المندوب غير موجود"}), 404

    ext = db.execute(
        "SELECT * FROM business_settings_ext WHERE business_id=?", (biz_id,)
    ).fetchone()
    ext_d = dict(ext) if ext else {}

    a = dict(agent)
    # القيم الافتراضية
    defaults = {
        "agent_location_interval": 30,
        "agent_reminder_days":     30,
        "agent_can_discount":      0,
        "agent_can_edit_price":    0,
        "agent_can_view_cost":     0,
        "agent_can_collect":       1,
        "agent_can_add_client":    1,
        "agent_can_create_draft":  1,
        "agent_can_send_offer":    1,
        "agent_max_discount_pct":  0.0,
    }
    perm_map = {
        "can_discount":    ("perm_discount",    "agent_can_discount",    0),
        "can_edit_price":  ("perm_edit_price",  "agent_can_edit_price",  0),
        "can_view_cost":   ("perm_view_cost",   "agent_can_view_cost",   0),
        "can_collect":     ("perm_collect",     "agent_can_collect",     1),
        "can_add_client":  ("perm_add_client",  "agent_can_add_client",  1),
        "can_create_draft":("perm_create_draft","agent_can_create_draft",1),
        "can_send_offer":  ("perm_send_offer",  "agent_can_send_offer",  1),
        "max_discount_pct":("max_discount_pct", "agent_max_discount_pct",0.0),
    }
    perms = {}
    for key, (ind_col, global_col, default) in perm_map.items():
        ind = a.get(ind_col)
        perms[key] = ind if ind is not None else ext_d.get(global_col, defaults.get(global_col, default))

    return jsonify({
        "success": True,
        "location_interval": ext_d.get("agent_location_interval", 30),
        "reminder_days":     ext_d.get("agent_reminder_days", 30),
        "permissions": perms,
    })


# ═══════════════════════════════════════════════════════════════════════════════
#  مزامنة الإعصار — Sync Storm Endpoints (v2 — لامتزامن)
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/api/v2/agents/<int:agent_id>/sync/batch", methods=["POST"])
def api_v2_agent_sync_batch(agent_id: int):
    """
    يقبل حزمة من الطلبات المعلقة أوفلاين ويضعها في الطابور فوراً (202 Accepted).
    لا يعالج أي شيء — العالج هو الـ Worker الخلفي.

    Body: { "queue": [ { "local_id": "x", "action_type": "create_invoice",
                          "payload": {...} }, ... ] }
    Response: { "accepted": N, "rejected_dup": M, "queue_tip": id }
    """
    from modules.sync_engine import enqueue_batch

    db, biz_id = _get_agent_biz(agent_id)
    if not biz_id:
        return jsonify({"success": False, "error": "unauthorized"}), 401

    payload = request.get_json(force=True, silent=True) or {}
    items   = payload.get("queue", [])

    if not items:
        return jsonify({"success": True, "accepted": 0, "rejected_dup": 0, "queue_tip": 0})

    result = enqueue_batch(db, biz_id, agent_id, items)

    if result.get("error") == "rate_limit":
        return jsonify({
            "success":     False,
            "error":       "rate_limit",
            "retry_after": result.get("retry_after", 30),
            "message":     "تجاوزت الحد المسموح من طلبات المزامنة. أعد المحاولة بعد 30 ثانية.",
        }), 429

    return jsonify({"success": True, **result}), 202


@bp.route("/api/v2/agents/<int:agent_id>/sync/status", methods=["GET"])
def api_v2_agent_sync_status(agent_id: int):
    """
    حالة الطابور للمندوب — يُستخدم لـ polling من التطبيق.
    Response: { pending, processing, done, failed, conflicts, conflict_details }
    """
    from modules.sync_engine import get_queue_status

    db, biz_id = _get_agent_biz(agent_id)
    if not biz_id:
        return jsonify({"success": False, "error": "unauthorized"}), 401

    return jsonify({"success": True, **get_queue_status(db, biz_id, agent_id)})
