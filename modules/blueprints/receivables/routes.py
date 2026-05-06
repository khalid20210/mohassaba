"""
blueprints/receivables/routes.py — إدارة الذمم المدينة والدائنة المتقدمة

المسارات:
  GET/POST /receivables              → قائمة الذمم
  GET      /receivables/<id>         → تفاصيل العميل
  POST     /receivables/payment      → تسجيل دفعة
  GET      /receivables/aging        → تقرير التقادم
  GET      /receivables/metrics      → مقاييس الأداء
  GET      /receivables/alerts       → التنبيهات
  POST     /receivables/write-off    → شطب دين معدوم
"""
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, session, jsonify, g, flash, redirect, url_for

from modules.extensions import get_db
from modules.middleware import require_perm, onboarding_required, write_audit_log
from modules.advanced_receivables import (
    get_contact_balance, create_receivable_transaction, record_payment,
    generate_aging_report, calculate_performance_metrics,
    write_off_bad_debt, check_credit_alerts
)

bp = Blueprint("receivables", __name__, url_prefix="/receivables")


# ════════════════════════════════════════════════════════════════════════════
# SECTION 1: قائمة الذمم
# ════════════════════════════════════════════════════════════════════════════

@bp.route("/", methods=["GET"])
@require_perm("accounting")
def list_receivables():
    """قائمة العملاء والموردين مع أرصدتهم"""
    db = get_db()
    biz_id = session["business_id"]
    
    # الفلاتر
    view_type = request.args.get("view", "receivable")  # receivable | payable | all
    status_filter = request.args.get("status", "all")   # all | open | overdue
    search_q = request.args.get("q", "").strip()
    
    # القاعدة الأساسية
    base_where = "rps.business_id=?"
    params = [biz_id]
    
    if view_type != "all":
        base_where += " AND rps.summary_type=?"
        params.append(view_type)
    
    if status_filter == "open":
        base_where += " AND rps.current_balance > 0"
    elif status_filter == "overdue":
        base_where += " AND rps.is_overdue=1"
    
    if search_q:
        base_where += " AND c.name LIKE ?"
        params.append(f"%{search_q}%")
    
    # الاستعلام الرئيسي
    rows = db.execute(
        f"""SELECT rps.id, c.id as contact_id, c.name, c.phone, c.email,
                  rps.summary_type, rps.current_balance, rps.is_overdue,
                  rps.days_overdue, rps.last_payment_date,
                  COUNT(DISTINCT CASE WHEN rpt.status='open' THEN rpt.id END) as open_count,
                  SUM(CASE WHEN rpt.status IN ('open','partial') THEN rpt.remaining_balance ELSE 0 END) as open_amount
           FROM receivables_payables_summary rps
           JOIN contacts c ON rps.contact_id=c.id
           LEFT JOIN receivables_payables_transactions rpt 
             ON rpt.business_id=? AND rpt.contact_id=c.id AND rpt.status IN ('open','partial')
           WHERE {base_where}
           GROUP BY c.id
           ORDER BY CASE WHEN rps.is_overdue=1 THEN 0 ELSE 1 END, rps.current_balance DESC""",
        [biz_id] + params
    ).fetchall()
    
    return render_template(
        "receivables/list.html",
        receivables=rows,
        view_type=view_type,
        status_filter=status_filter,
        search_q=search_q,
    )


# ════════════════════════════════════════════════════════════════════════════
# SECTION 2: تفاصيل العميل/المورد
# ════════════════════════════════════════════════════════════════════════════

@bp.route("/<int:contact_id>", methods=["GET"])
@require_perm("accounting")
def view_contact_receivables(contact_id: int):
    """عرض جميع حركات الذمة للعميل/المورد"""
    db = get_db()
    biz_id = session["business_id"]
    
    # التحقق من الاتصال
    contact = db.execute(
        "SELECT * FROM contacts WHERE id=? AND business_id=?",
        (contact_id, biz_id)
    ).fetchone()
    
    if not contact:
        return jsonify({"error": "جهة الاتصال غير موجودة"}), 404
    
    # الأرصدة
    receivable = get_contact_balance(db, biz_id, contact_id, 'receivable')
    payable = get_contact_balance(db, biz_id, contact_id, 'payable')
    
    # سياسة الائتمان
    policy = db.execute(
        """SELECT * FROM credit_policies
           WHERE business_id=? AND contact_id=?""",
        (biz_id, contact_id)
    ).fetchone()
    
    # الحركات المفتوحة
    transactions = db.execute(
        """SELECT * FROM receivables_payables_transactions
           WHERE business_id=? AND contact_id=? AND status IN ('open', 'partial')
           ORDER BY due_date ASC""",
        (biz_id, contact_id)
    ).fetchall()
    
    # التنبيهات
    alerts = db.execute(
        """SELECT * FROM receivables_alerts
           WHERE business_id=? AND contact_id=? AND status='active'
           ORDER BY triggered_at DESC""",
        (biz_id, contact_id)
    ).fetchall()
    
    return render_template(
        "receivables/contact_detail.html",
        contact=contact,
        receivable=receivable,
        payable=payable,
        policy=policy,
        transactions=transactions,
        alerts=alerts,
    )


# ════════════════════════════════════════════════════════════════════════════
# SECTION 3: تسجيل الدفعات
# ════════════════════════════════════════════════════════════════════════════

@bp.route("/payment/record", methods=["POST"])
@onboarding_required
def record_payment_handler():
    """تسجيل دفعة جديدة"""
    db = get_db()
    biz_id = session["business_id"]
    
    data = request.get_json(force=True) or {}
    contact_id = data.get("contact_id")
    amount = float(data.get("amount", 0))
    reference = data.get("reference_number", "")
    notes = data.get("notes", "")
    
    if not contact_id or amount <= 0:
        return jsonify({"success": False, "error": "معلومات غير صحيحة"}), 400
    
    try:
        payment_id, remaining = record_payment(
            db, biz_id, contact_id, amount, reference, notes
        )
        db.commit()
        
        return jsonify({
            "success": True,
            "payment_id": payment_id,
            "remaining": remaining,
            "message": "تم تسجيل الدفعة بنجاح",
        })
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


# ════════════════════════════════════════════════════════════════════════════
# SECTION 4: تقارير التقادم
# ════════════════════════════════════════════════════════════════════════════

@bp.route("/aging-report", methods=["GET"])
@require_perm("reports")
def aging_report():
    """تقرير التقادم (Aging Report)"""
    db = get_db()
    biz_id = session["business_id"]
    
    # توليد التقرير
    aging = generate_aging_report(db, biz_id, 'receivable')
    
    # حفظ في قاعدة البيانات (Snapshot)
    db.execute(
        """INSERT INTO aging_snapshot
           (business_id, report_type, snapshot_date,
            current_0_to_30, overdue_31_to_60, overdue_61_to_90, overdue_over_90, total_balance)
           VALUES (?,?,?,?,?,?,?,?)""",
        (biz_id, 'receivable', aging['report_date'],
         aging['aging']['0-30']['amount'],
         aging['aging']['31-60']['amount'],
         aging['aging']['61-90']['amount'],
         aging['aging']['90+']['amount'],
         aging['grand_total'])
    )
    db.commit()
    
    return render_template(
        "receivables/aging_report.html",
        report=aging,
    )


# ════════════════════════════════════════════════════════════════════════════
# SECTION 5: مقاييس الأداء
# ════════════════════════════════════════════════════════════════════════════

@bp.route("/metrics", methods=["GET"])
@require_perm("reports")
def performance_metrics():
    """مقاييس الأداء (DSO, DPO, Collection Rate)"""
    db = get_db()
    biz_id = session["business_id"]
    
    # الفترة الزمنية
    period_end = request.args.get("to", datetime.now().strftime("%Y-%m-%d"))
    period_start = request.args.get("from", (datetime.strptime(period_end, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d"))
    
    # حساب المقاييس
    metrics = calculate_performance_metrics(db, biz_id, period_start, period_end)
    
    # حفظ المقاييس
    db.execute(
        """INSERT INTO receivables_performance_metrics
           (business_id, dso, collection_rate, total_receivables,
            total_overdue, bad_debt_percentage, period_start, period_end)
           VALUES (?,?,?,?,?,?,?,?)""",
        (biz_id, metrics['dso'], metrics['collection_rate'],
         metrics['open_receivables'], 0, metrics['bad_debt_percentage'],
         period_start, period_end)
    )
    db.commit()
    
    return render_template(
        "receivables/metrics.html",
        metrics=metrics,
    )


# ════════════════════════════════════════════════════════════════════════════
# SECTION 6: التنبيهات
# ════════════════════════════════════════════════════════════════════════════

@bp.route("/alerts", methods=["GET"])
@require_perm("accounting")
def view_alerts():
    """عرض جميع التنبيهات الائتمانية"""
    db = get_db()
    biz_id = session["business_id"]
    
    # فحص التنبيهات
    alerts = check_credit_alerts(db, biz_id)
    
    return render_template(
        "receivables/alerts.html",
        alerts=alerts,
    )


# ════════════════════════════════════════════════════════════════════════════
# SECTION 7: شطب الديون المعدومة
# ════════════════════════════════════════════════════════════════════════════

@bp.route("/write-off", methods=["POST"])
@require_perm("accounting")
def write_off_handler():
    """شطب دين معدوم"""
    db = get_db()
    biz_id = session["business_id"]
    user_id = session["user_id"]

    user_perms = {}
    try:
        user_perms = g.user.get("permissions", {}) if g.user else {}
        if isinstance(user_perms, str):
            import json

            user_perms = json.loads(user_perms or "{}")
    except Exception:
        user_perms = {}
    if not bool(user_perms.get("all")):
        return jsonify({"success": False, "error": "شطب الديون محصور بمدير النظام فقط"}), 403
    
    data = request.get_json(force=True) or {}
    transaction_id = data.get("transaction_id")
    amount = float(data.get("amount", 0))
    reason = data.get("reason", "")
    
    if not transaction_id or amount <= 0 or not reason:
        return jsonify({"success": False, "error": "معلومات ناقصة"}), 400
    
    try:
        # الحساب الافتراضي للديون المعدومة
        expense_account_id = db.execute(
            """SELECT id FROM accounts WHERE business_id=? AND code='9501'""",
            (biz_id,)
        ).fetchone()['id'] or None
        
        if not expense_account_id:
            return jsonify({"success": False, "error": "حساب المصروف غير موجود"}), 400
        
        write_off_id = write_off_bad_debt(
            db, biz_id, transaction_id, amount, reason, expense_account_id, user_id
        )
        write_audit_log(
            db,
            biz_id,
            action="bad_debt_write_off",
            entity_type="receivables",
            entity_id=int(transaction_id),
            new_value=(
                f"write_off_id={write_off_id};amount={amount};reason={reason};by={user_id}"
            ),
        )
        db.commit()
        
        flash("تم شطب الدين المعدوم بنجاح", "success")
        return jsonify({"success": True, "write_off_id": write_off_id})
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


# ════════════════════════════════════════════════════════════════════════════
# API ENDPOINTS
# ════════════════════════════════════════════════════════════════════════════

@bp.route("/api/balance/<int:contact_id>", methods=["GET"])
@onboarding_required
def api_get_balance(contact_id: int):
    """API: الحصول على رصيد العميل"""
    db = get_db()
    biz_id = session["business_id"]
    
    receivable = get_contact_balance(db, biz_id, contact_id, 'receivable')
    payable = get_contact_balance(db, biz_id, contact_id, 'payable')
    
    return jsonify({
        "success": True,
        "receivable": receivable,
        "payable": payable,
    })


@bp.route("/api/create-transaction", methods=["POST"])
@onboarding_required
def api_create_transaction():
    """API: إنشاء حركة ذمة (عادة من الفاتورة)"""
    db = get_db()
    biz_id = session["business_id"]
    
    data = request.get_json(force=True) or {}
    contact_id = data.get("contact_id")
    amount = float(data.get("amount", 0))
    invoice_number = data.get("invoice_number", "")
    trans_type = data.get("type", "invoice")
    due_date = data.get("due_date")
    
    try:
        trans_id = create_receivable_transaction(
            db, biz_id, contact_id, trans_type, amount, invoice_number, due_date
        )
        db.commit()
        
        return jsonify({
            "success": True,
            "transaction_id": trans_id,
        })
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/api/transactions/<int:contact_id>", methods=["GET"])
@onboarding_required
def api_list_transactions(contact_id: int):
    """API: قائمة حركات العميل"""
    db = get_db()
    biz_id = session["business_id"]
    
    transactions = db.execute(
        """SELECT * FROM receivables_payables_transactions
           WHERE business_id=? AND contact_id=?
           ORDER BY transaction_date DESC""",
        (biz_id, contact_id)
    ).fetchall()
    
    return jsonify({
        "success": True,
        "transactions": [dict(t) for t in transactions],
    })
