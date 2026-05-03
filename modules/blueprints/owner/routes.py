"""
blueprints/owner/routes.py
قمرة القيادة — Owner Intelligence Dashboard
السيادة المطلقة للمالك: أرباح، رقابة، موارد بشرية، API Keys، وضع العرض
"""
import hashlib
import json
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for, flash

from modules.extensions import get_db
from modules.middleware import owner_required, write_audit_log

bp = Blueprint("owner", __name__, url_prefix="/owner")


# ══════════════════════════════════════════════════════════════════════════════
#  الصفحة الرئيسية — قمرة القيادة
# ══════════════════════════════════════════════════════════════════════════════

@bp.route("/")
@owner_required
def owner_dashboard():
    """الشاشة الموحدة: صافي الأرباح + مبيعات المناديب + رواتب الموظفين"""
    db     = get_db()
    biz_id = session["business_id"]

    # ── KPIs ──────────────────────────────────────────────────────────────────
    today   = datetime.now().strftime("%Y-%m-%d")
    month   = datetime.now().strftime("%Y-%m")

    sales_today = db.execute(
        """SELECT COALESCE(SUM(total), 0) FROM invoices
           WHERE business_id=? AND invoice_type='sale'
             AND date(created_at)=?""",
        (biz_id, today)
    ).fetchone()[0]

    sales_month = db.execute(
        """SELECT COALESCE(SUM(total), 0) FROM invoices
           WHERE business_id=? AND invoice_type='sale'
             AND strftime('%Y-%m', created_at)=?""",
        (biz_id, month)
    ).fetchone()[0]

    cost_month = db.execute(
        """SELECT COALESCE(SUM(total), 0) FROM invoices
           WHERE business_id=? AND invoice_type='purchase'
             AND strftime('%Y-%m', created_at)=?""",
        (biz_id, month)
    ).fetchone()[0]

    net_profit = float(sales_month) - float(cost_month)

    # ── إحصاء الموظفين والمناديب ─────────────────────────────────────────────
    emp_count = db.execute(
        "SELECT COUNT(*) FROM employees WHERE business_id=? AND is_active=1", (biz_id,)
    ).fetchone()[0]

    agent_count = db.execute(
        "SELECT COUNT(*) FROM agents WHERE business_id=? AND is_active=1", (biz_id,)
    ).fetchone()[0]

    pending_deductions = db.execute(
        """SELECT COUNT(*) FROM shift_blind_closures
           WHERE business_id=? AND shortage_amount > 0""",
        (biz_id,)
    ).fetchone()[0]

    # ── آخر 30 يوم: مبيعات يومية ─────────────────────────────────────────────
    daily_sales = db.execute(
        """SELECT date(created_at) as day, COALESCE(SUM(total),0) as total
           FROM invoices
           WHERE business_id=? AND invoice_type='sale'
             AND created_at >= date('now','-29 days')
           GROUP BY day ORDER BY day""",
        (biz_id,)
    ).fetchall()

    # ── مبيعات المناديب (top agents) ─────────────────────────────────────────
    agent_sales = db.execute(
        """SELECT a.full_name, a.employee_code,
                  COALESCE(SUM(ac.commission_amount),0) as total_commission,
                  COUNT(ac.id) as invoice_count
           FROM agents a
           LEFT JOIN agent_commissions ac ON ac.agent_id=a.id AND ac.business_id=?
           WHERE a.business_id=? AND a.is_active=1
           GROUP BY a.id
           ORDER BY total_commission DESC LIMIT 10""",
        (biz_id, biz_id)
    ).fetchall()

    # ── إجمالي الرواتب والخصومات للشهر الحالي ────────────────────────────────
    payroll_total = db.execute(
        """SELECT COALESCE(SUM(base_salary),0) FROM employees
           WHERE business_id=? AND is_active=1""",
        (biz_id,)
    ).fetchone()[0]

    deductions_total = db.execute(
        """SELECT COALESCE(SUM(amount),0) FROM payroll_deductions
           WHERE business_id=?
             AND strftime('%Y-%m', created_at)=?""",
        (biz_id, month)
    ).fetchone()[0]

    # ── إعدادات العرض ────────────────────────────────────────────────────────
    ext = db.execute(
        "SELECT * FROM business_settings_ext WHERE business_id=?", (biz_id,)
    ).fetchone()
    display_mode = (dict(ext)["display_mode"] if ext else "pro")

    # ── آخر 10 سجلات نشاط ────────────────────────────────────────────────────
    recent_logs = db.execute(
        """SELECT actor_name, actor_role, action, entity_type, created_at
           FROM audit_logs WHERE business_id=?
           ORDER BY created_at DESC LIMIT 10""",
        (biz_id,)
    ).fetchall()

    kpis = {
        "sales_today":        float(sales_today),
        "sales_month":        float(sales_month),
        "cost_month":         float(cost_month),
        "net_profit":         net_profit,
        "emp_count":          emp_count,
        "agent_count":        agent_count,
        "pending_deductions": pending_deductions,
        "payroll_total":      float(payroll_total),
        "deductions_total":   float(deductions_total),
    }

    return render_template(
        "owner_dashboard.html",
        kpis=kpis,
        daily_sales=[dict(r) for r in daily_sales],
        agent_sales=[dict(r) for r in agent_sales],
        recent_logs=[dict(r) for r in recent_logs],
        display_mode=display_mode,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  وضع العرض — Basic / Pro Toggle
# ══════════════════════════════════════════════════════════════════════════════

@bp.route("/display-mode", methods=["POST"])
@owner_required
def toggle_display_mode():
    """تبديل وضع العرض البسيط ↔ الاحترافي"""
    db     = get_db()
    biz_id = session["business_id"]
    mode   = request.form.get("mode", "pro")
    if mode not in ("basic", "pro"):
        return jsonify({"error": "قيمة غير مقبولة"}), 400

    # إخفاء المحاسبة في الوضع البسيط
    hide_acc = 1 if mode == "basic" else 0

    db.execute(
        """INSERT INTO business_settings_ext
               (business_id, display_mode, hide_accounting, updated_at)
           VALUES (?, ?, ?, datetime('now'))
           ON CONFLICT(business_id) DO UPDATE
               SET display_mode    = excluded.display_mode,
                   hide_accounting = excluded.hide_accounting,
                   updated_at      = excluded.updated_at""",
        (biz_id, mode, hide_acc)
    )
    db.commit()

    write_audit_log(
        db, biz_id,
        action="display_mode_changed",
        entity_type="setting",
        new_value=json.dumps({"display_mode": mode})
    )

    label = "بسيط (Basic)" if mode == "basic" else "احترافي (Pro)"
    flash(f"تم تفعيل الوضع {label} بنجاح", "success")
    return redirect(url_for("owner.owner_dashboard"))


# ══════════════════════════════════════════════════════════════════════════════
#  لوحة إعدادات الرقابة
# ══════════════════════════════════════════════════════════════════════════════

@bp.route("/control-panel", methods=["POST"])
@owner_required
def update_control_panel():
    """تحديث إعدادات الرقابة: إخفاء الوحدات، الخصم التلقائي"""
    db     = get_db()
    biz_id = session["business_id"]

    hide_wf     = 1 if request.form.get("hide_workforce") else 0
    hide_agent  = 1 if request.form.get("hide_agent_portal") else 0
    auto_deduct = 1 if request.form.get("auto_deduct_deficit") else 0

    db.execute(
        """INSERT INTO business_settings_ext
               (business_id, hide_workforce, hide_agent_portal, auto_deduct_deficit, updated_at)
           VALUES (?, ?, ?, ?, datetime('now'))
           ON CONFLICT(business_id) DO UPDATE
               SET hide_workforce      = excluded.hide_workforce,
                   hide_agent_portal   = excluded.hide_agent_portal,
                   auto_deduct_deficit = excluded.auto_deduct_deficit,
                   updated_at          = excluded.updated_at""",
        (biz_id, hide_wf, hide_agent, auto_deduct)
    )
    db.commit()

    write_audit_log(db, biz_id, action="control_panel_updated", entity_type="setting")
    flash("تم حفظ إعدادات الرقابة", "success")
    return redirect(url_for("owner.owner_dashboard"))


# ══════════════════════════════════════════════════════════════════════════════
#  سجل النشاط (Audit Logs)
# ══════════════════════════════════════════════════════════════════════════════

@bp.route("/audit-logs")
@owner_required
def audit_logs():
    db     = get_db()
    biz_id = session["business_id"]
    page   = max(1, int(request.args.get("page", 1)))
    per    = 50
    offset = (page - 1) * per

    action_filter = request.args.get("action", "")
    params = [biz_id]
    where  = "WHERE al.business_id=?"
    if action_filter:
        where += " AND al.action=?"
        params.append(action_filter)

    logs = db.execute(
        f"""SELECT al.*, u.full_name as user_full_name
            FROM audit_logs al
            LEFT JOIN users u ON u.id = al.user_id
            {where}
            ORDER BY al.created_at DESC
            LIMIT ? OFFSET ?""",
        params + [per, offset]
    ).fetchall()

    total = db.execute(
        f"SELECT COUNT(*) FROM audit_logs al {where}", params
    ).fetchone()[0]

    actions = db.execute(
        "SELECT DISTINCT action FROM audit_logs WHERE business_id=? ORDER BY action",
        (biz_id,)
    ).fetchall()

    return render_template(
        "owner_audit_logs.html",
        logs=[dict(r) for r in logs],
        page=page,
        per=per,
        total=total,
        pages=(total + per - 1) // per,
        action_filter=action_filter,
        actions=[r["action"] for r in actions],
    )


# ══════════════════════════════════════════════════════════════════════════════
#  تقارير الإقفال الأعمى واعتماد الخصم
# ══════════════════════════════════════════════════════════════════════════════

@bp.route("/blind-closures")
@owner_required
def blind_closures():
    db     = get_db()
    biz_id = session["business_id"]

    closures = db.execute(
        """SELECT sbc.*, e.full_name as employee_name
           FROM shift_blind_closures sbc
           LEFT JOIN employees e ON e.id = sbc.employee_id
           WHERE sbc.business_id=?
           ORDER BY sbc.shift_date DESC, sbc.id DESC LIMIT 100""",
        (biz_id,)
    ).fetchall()

    return render_template("owner_blind_closures.html", closures=[dict(c) for c in closures])


@bp.route("/blind-closures/<int:closure_id>/approve", methods=["POST"])
@owner_required
def approve_blind_closure(closure_id: int):
    """اعتماد خصم العجز من راتب الموظف"""
    db     = get_db()
    biz_id = session["business_id"]
    user_id = session["user_id"]

    closure = db.execute(
        "SELECT * FROM shift_blind_closures WHERE id=? AND business_id=?",
        (closure_id, biz_id)
    ).fetchone()
    if not closure:
        return jsonify({"error": "إقفال غير موجود"}), 404

    deficit = float(closure["shortage_amount"] or 0)

    # تسجيل خصم الرواتب إذا كان هناك عجز
    if deficit > 0:
        db.execute(
            """INSERT INTO payroll_deductions
                   (business_id, employee_id, source_type, source_id, amount, reason)
               VALUES (?, ?, 'blind_deficit', ?, ?, ?)""",
            (biz_id, closure["employee_id"],
             closure_id,
             deficit,
             f"عجز إقفال أعمى بتاريخ {closure['shift_date']}")
        )

    db.commit()

    write_audit_log(
        db, biz_id,
        action="blind_closure_approved",
        entity_type="shift_blind_closure",
        entity_id=closure_id,
        new_value=json.dumps({"deficit": deficit, "approved_by": user_id})
    )
    return jsonify({"success": True, "deficit_deducted": deficit})


# ══════════════════════════════════════════════════════════════════════════════
#  مفاتيح API — لوحة ربط المنصات الخارجية
# ══════════════════════════════════════════════════════════════════════════════

@bp.route("/api-keys")
@owner_required
def api_keys_page():
    db     = get_db()
    biz_id = session["business_id"]

    keys = db.execute(
        """SELECT id, label, key_prefix, scopes, last_used_at, expires_at, is_active, created_at
           FROM api_keys WHERE business_id=? ORDER BY created_at DESC""",
        (biz_id,)
    ).fetchall()

    return render_template("owner_api_keys.html", api_keys=[dict(k) for k in keys])


@bp.route("/api-keys/create", methods=["POST"])
@owner_required
def create_api_key():
    """توليد مفتاح API جديد — يُعرض مرة واحدة فقط"""
    db     = get_db()
    biz_id = session["business_id"]
    user_id = session["user_id"]

    label  = request.form.get("label", "").strip()
    scopes = request.form.getlist("scopes") or ["read"]
    expires_days = request.form.get("expires_days")

    if not label:
        flash("يجب إدخال اسم/وصف للمفتاح", "error")
        return redirect(url_for("owner.api_keys_page"))

    # توليد المفتاح: jb_live_{32 حرف عشوائي}
    raw_key = "jb_live_" + secrets.token_urlsafe(32)
    prefix  = raw_key[:12]                              # أول 12 حرفاً تُعرض للمستخدم
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    expires_at = None
    if expires_days and int(expires_days) > 0:
        expires_at = (datetime.now() + timedelta(days=int(expires_days))).strftime("%Y-%m-%d %H:%M:%S")

    db.execute(
        """INSERT INTO api_keys
               (business_id, created_by, label, key_prefix, key_hash, scopes, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (biz_id, user_id, label, prefix, key_hash, json.dumps(scopes), expires_at)
    )
    db.commit()

    write_audit_log(
        db, biz_id,
        action="api_key_created",
        entity_type="api_key",
        new_value=json.dumps({"label": label, "scopes": scopes, "prefix": prefix})
    )

    # المفتاح يُعرض مرة واحدة فقط ثم يختفي
    flash(f"المفتاح الجديد (احتفظ به الآن — لن يُعرض مرة أخرى): {raw_key}", "key_reveal")
    return redirect(url_for("owner.api_keys_page"))


@bp.route("/api-keys/<int:key_id>/revoke", methods=["POST"])
@owner_required
def revoke_api_key(key_id: int):
    """إلغاء تفعيل مفتاح API"""
    db     = get_db()
    biz_id = session["business_id"]

    db.execute(
        "UPDATE api_keys SET is_active=0 WHERE id=? AND business_id=?",
        (key_id, biz_id)
    )
    db.commit()
    write_audit_log(db, biz_id, action="api_key_revoked", entity_type="api_key", entity_id=key_id)
    return jsonify({"success": True})


# ══════════════════════════════════════════════════════════════════════════════
#  إدارة الموارد البشرية والرواتب (HR Control)
# ══════════════════════════════════════════════════════════════════════════════

@bp.route("/hr")
@owner_required
def hr_panel():
    db     = get_db()
    biz_id = session["business_id"]

    employees = db.execute(
        """SELECT e.*,
                  COALESCE(SUM(pd.amount),0) as month_deductions
           FROM employees e
           LEFT JOIN payroll_deductions pd
               ON pd.employee_id=e.id
              AND pd.business_id=?
              AND strftime('%Y-%m', pd.created_at)=strftime('%Y-%m','now')
           WHERE e.business_id=? AND e.is_active=1
           GROUP BY e.id
           ORDER BY e.full_name""",
        (biz_id, biz_id)
    ).fetchall()

    agents = db.execute(
        """SELECT a.*,
                  COALESCE(SUM(ac.commission_amount),0) as pending_commission
           FROM agents a
           LEFT JOIN agent_commissions ac
               ON ac.agent_id=a.id AND ac.status != 'paid'
           WHERE a.business_id=? AND a.is_active=1
           GROUP BY a.id
           ORDER BY a.full_name""",
        (biz_id,)
    ).fetchall()

    return render_template(
        "owner_hr.html",
        employees=[dict(e) for e in employees],
        agents=[dict(a) for a in agents],
    )


@bp.route("/hr/employee/<int:emp_id>/salary", methods=["POST"])
@owner_required
def update_employee_salary(emp_id: int):
    """تعديل راتب موظف"""
    db     = get_db()
    biz_id = session["business_id"]

    new_salary = request.form.get("base_salary", type=float)
    if new_salary is None or new_salary < 0:
        return jsonify({"error": "راتب غير صحيح"}), 400

    old = db.execute(
        "SELECT base_salary FROM employees WHERE id=? AND business_id=?",
        (emp_id, biz_id)
    ).fetchone()
    if not old:
        return jsonify({"error": "موظف غير موجود"}), 404

    db.execute(
        "UPDATE employees SET base_salary=? WHERE id=? AND business_id=?",
        (new_salary, emp_id, biz_id)
    )
    db.commit()

    write_audit_log(
        db, biz_id,
        action="salary_updated",
        entity_type="employee",
        entity_id=emp_id,
        old_value=json.dumps({"base_salary": old["base_salary"]}),
        new_value=json.dumps({"base_salary": new_salary})
    )
    return jsonify({"success": True, "new_salary": new_salary})


@bp.route("/hr/agent/<int:agent_id>/commission", methods=["POST"])
@owner_required
def update_agent_commission(agent_id: int):
    """تعديل نسبة عمولة مندوب"""
    db     = get_db()
    biz_id = session["business_id"]

    rate = request.form.get("commission_rate", type=float)
    if rate is None or not (0 <= rate <= 100):
        return jsonify({"error": "نسبة عمولة غير صحيحة (0-100)"}), 400

    old = db.execute(
        "SELECT commission_rate FROM agents WHERE id=? AND business_id=?",
        (agent_id, biz_id)
    ).fetchone()
    if not old:
        return jsonify({"error": "مندوب غير موجود"}), 404

    db.execute(
        "UPDATE agents SET commission_rate=? WHERE id=? AND business_id=?",
        (rate, agent_id, biz_id)
    )
    db.commit()

    write_audit_log(
        db, biz_id,
        action="commission_rate_updated",
        entity_type="agent",
        entity_id=agent_id,
        old_value=json.dumps({"commission_rate": old["commission_rate"]}),
        new_value=json.dumps({"commission_rate": rate})
    )
    return jsonify({"success": True, "new_rate": rate})


# ══════════════════════════════════════════════════════════════════════════════
#  API: بيانات الرسوم البيانية (Charts JSON)
# ══════════════════════════════════════════════════════════════════════════════

@bp.route("/api/chart-data")
@owner_required
def chart_data():
    """JSON لرسم خرائط قمرة القيادة (مبيعات يومية + مناديب + رواتب)"""
    db     = get_db()
    biz_id = session["business_id"]

    # مبيعات آخر 30 يوم
    daily = db.execute(
        """SELECT date(created_at) as day, COALESCE(SUM(total),0) as total
           FROM invoices
           WHERE business_id=? AND invoice_type='sale'
             AND created_at >= date('now','-29 days')
           GROUP BY day ORDER BY day""",
        (biz_id,)
    ).fetchall()

    # مبيعات المناديب
    agents = db.execute(
        """SELECT a.full_name,
                  COUNT(ac.id) as invoice_count,
                  COALESCE(SUM(ac.commission_amount),0) as commission
           FROM agents a
           LEFT JOIN agent_commissions ac ON ac.agent_id=a.id
           WHERE a.business_id=? AND a.is_active=1
           GROUP BY a.id ORDER BY commission DESC LIMIT 8""",
        (biz_id,)
    ).fetchall()

    # رواتب vs خصومات (آخر 6 أشهر)
    payroll_chart = db.execute(
        """SELECT strftime('%Y-%m', pd.created_at) as month,
                  COALESCE(SUM(pd.amount),0) as deductions
           FROM payroll_deductions pd
           WHERE pd.business_id=?
             AND pd.created_at >= date('now','-6 months')
           GROUP BY month ORDER BY month""",
        (biz_id,)
    ).fetchall()

    return jsonify({
        "daily_sales": [{"day": r["day"], "total": float(r["total"])} for r in daily],
        "agent_commissions": [
            {"name": r["full_name"], "invoices": r["invoice_count"], "commission": float(r["commission"])}
            for r in agents
        ],
        "payroll_deductions": [
            {"month": r["month"], "deductions": float(r["deductions"])}
            for r in payroll_chart
        ],
    })
