"""
blueprints/workforce/routes.py
بوابة الموظفين والمناديب + API-First endpoints
"""
from datetime import datetime, timedelta
from urllib.parse import quote

from flask import Blueprint, jsonify, render_template, request, session

from modules.extensions import get_db
from modules.middleware import onboarding_required, require_perm
from modules.validators import (
    SCHEMA_AGENT_CREATE,
    SCHEMA_BLIND_CLOSE,
    SCHEMA_EMPLOYEE_CREATE,
    V,
    validate,
)

bp = Blueprint("workforce", __name__)


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
        db.execute(
            """INSERT OR REPLACE INTO agent_invoice_links
               (id, business_id, agent_id, invoice_id, created_at)
               VALUES (
                   (SELECT id FROM agent_invoice_links WHERE business_id=? AND invoice_id=?),
                   ?,?,?,datetime('now')
               )""",
            (biz_id, clean["invoice_id"], biz_id, agent_id, clean["invoice_id"]),
        )
        db.execute(
            """INSERT OR REPLACE INTO agent_commissions
               (id, business_id, agent_id, invoice_id, invoice_total, commission_rate, commission_amount, status, created_at)
               VALUES (
                   (SELECT id FROM agent_commissions WHERE business_id=? AND invoice_id=?),
                   ?,?,?,?,?,?,
                   COALESCE((SELECT status FROM agent_commissions WHERE business_id=? AND invoice_id=?), 'pending'),
                   datetime('now')
               )""",
            (
                biz_id,
                clean["invoice_id"],
                biz_id,
                agent_id,
                clean["invoice_id"],
                round(float(inv["total"] or 0), 2),
                rate,
                amount,
                biz_id,
                clean["invoice_id"],
            ),
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
