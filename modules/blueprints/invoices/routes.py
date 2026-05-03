"""
blueprints/invoices/routes.py — إدارة الفواتير الموحدة
صفحة قائمة الفواتير الشاملة: مبيعات + مشتريات مع فلاتر + أمان كامل
"""
import json
from datetime import datetime

from flask import (
    Blueprint, flash, g, jsonify, redirect,
    render_template, request, session, url_for
)

from modules.extensions import get_db
from modules.middleware import onboarding_required, require_perm, user_has_perm, write_audit_log

bp = Blueprint("invoices", __name__, url_prefix="/invoices")

# ──────────────────────────────────────────────────────────────────────────────

@bp.route("/")
@require_perm("sales")
def list_invoices():
    """قائمة الفواتير الموحدة (مبيعات + مشتريات) مع فلاتر متقدمة"""
    db     = get_db()
    biz_id = session["business_id"]

    # ── معاملات البحث والفلترة (مع التحقق من صحة المدخلات) ──────────────────
    inv_type  = request.args.get("type", "")
    status    = request.args.get("status", "")
    date_from = request.args.get("from", "")
    date_to   = request.args.get("to", "")
    q         = request.args.get("q", "").strip()[:100]  # حد أقصى 100 حرف
    page      = max(1, min(int(request.args.get("page", 1)), 9999))
    per_page  = 25

    # التحقق من صحة تواريخ الفلترة
    try:
        if date_from:
            datetime.strptime(date_from, "%Y-%m-%d")
        if date_to:
            datetime.strptime(date_to, "%Y-%m-%d")
    except ValueError:
        date_from = date_to = ""

    # التحقق من صحة نوع الفاتورة والحالة
    valid_types   = {"sale", "purchase", "table", "return", ""}
    valid_status  = {"draft", "pending", "paid", "partial", "cancelled", ""}
    if inv_type not in valid_types:
        inv_type = ""
    if status not in valid_status:
        status = ""

    # ── بناء الاستعلام مع RLS إلزامي ─────────────────────────────────────────
    conditions = ["i.business_id = ?"]
    params     = [biz_id]

    if inv_type:
        conditions.append("i.invoice_type = ?")
        params.append(inv_type)
    if status:
        conditions.append("i.status = ?")
        params.append(status)
    if date_from:
        conditions.append("DATE(i.invoice_date) >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("DATE(i.invoice_date) <= ?")
        params.append(date_to)
    if q:
        conditions.append(
            "(i.invoice_number LIKE ? OR i.party_name LIKE ?)"
        )
        term = f"%{q}%"
        params.extend([term, term])

    where = "WHERE " + " AND ".join(conditions)

    total = db.execute(
        f"SELECT COUNT(*) FROM invoices i {where}", params
    ).fetchone()[0]

    offset  = (page - 1) * per_page
    invoices = db.execute(
        f"""SELECT i.id, i.invoice_number, i.invoice_type, i.invoice_date,
                   i.party_name, i.subtotal, i.tax_amount, i.total,
                   i.status, i.notes,
                   i.cancel_reason, i.cancelled_at,
                   u.full_name AS created_by_name
            FROM invoices i
            LEFT JOIN users u ON u.id = i.created_by
            {where}
            ORDER BY i.id DESC
            LIMIT ? OFFSET ?""",
        params + [per_page, offset]
    ).fetchall()

    # ── إحصائيات سريعة ───────────────────────────────────────────────────────
    stats = db.execute(
        """SELECT
             COUNT(*)                                           AS total_count,
             COALESCE(SUM(CASE WHEN status='paid'   THEN total ELSE 0 END), 0) AS paid_total,
             COALESCE(SUM(CASE WHEN status IN ('draft','pending') THEN total ELSE 0 END), 0) AS pending_total,
             COUNT(CASE WHEN status='cancelled' THEN 1 END)    AS cancelled_count
           FROM invoices
           WHERE business_id=?""",
        (biz_id,)
    ).fetchone()

    total_pages = max(1, (total + per_page - 1) // per_page)

    return render_template(
        "invoices/list.html",
        invoices=[dict(r) for r in invoices],
        total=total,
        page=page,
        total_pages=total_pages,
        per_page=per_page,
        stats=dict(stats),
        # فلاتر محفوظة للواجهة
        filter_type=inv_type,
        filter_status=status,
        filter_from=date_from,
        filter_to=date_to,
        filter_q=q,
    )


@bp.route("/<int:inv_id>")
@require_perm("sales")
def view_invoice(inv_id: int):
    """عرض تفاصيل فاتورة واحدة مع سطورها"""
    db     = get_db()
    biz_id = session["business_id"]

    # RLS: تحقق أن الفاتورة تعود لهذه المنشأة
    inv = db.execute(
        "SELECT * FROM invoices WHERE id=? AND business_id=?", (inv_id, biz_id)
    ).fetchone()
    if not inv:
        flash("الفاتورة غير موجودة أو لا تملك صلاحية الوصول إليها", "error")
        return redirect(url_for("invoices.list_invoices"))

    lines = db.execute(
        """SELECT il.*, p.name AS product_name
           FROM invoice_lines il
           LEFT JOIN products p ON p.id = il.product_id
           WHERE il.invoice_id=? ORDER BY il.line_order""",
        (inv_id,)
    ).fetchall()

    # سجل التدقيق
    audit = db.execute(
        """SELECT actor_name, actor_role, action, old_value, new_value, created_at
           FROM audit_logs
           WHERE entity_type='invoice' AND entity_id=? AND business_id=?
           ORDER BY created_at DESC LIMIT 20""",
        (inv_id, biz_id)
    ).fetchall()

    return render_template(
        "invoices/view.html",
        inv=dict(inv),
        lines=[dict(r) for r in lines],
        audit=[dict(r) for r in audit],
    )


@bp.route("/<int:inv_id>/mark-paid", methods=["POST"])
@require_perm("sales")
def mark_paid(inv_id: int):
    """تحديث حالة الفاتورة إلى مدفوعة"""
    db     = get_db()
    biz_id = session["business_id"]

    inv = db.execute(
        "SELECT id, status, invoice_number FROM invoices WHERE id=? AND business_id=?",
        (inv_id, biz_id)
    ).fetchone()
    if not inv:
        return jsonify({"success": False, "error": "الفاتورة غير موجودة"}), 404

    if inv["status"] == "cancelled":
        return jsonify({"success": False, "error": "لا يمكن تحديث فاتورة ملغية"}), 400

    old_status = inv["status"]
    db.execute(
        "UPDATE invoices SET status='paid' WHERE id=? AND business_id=?",
        (inv_id, biz_id)
    )
    db.commit()

    write_audit_log(
        db, biz_id,
        action="invoice_marked_paid",
        entity_type="invoice",
        entity_id=inv_id,
        old_value=json.dumps({"status": old_status}),
        new_value=json.dumps({"status": "paid"}),
    )
    return jsonify({"success": True, "invoice_number": inv["invoice_number"]})


@bp.route("/<int:inv_id>/cancel", methods=["POST"])
@require_perm("sales")
def cancel_invoice(inv_id: int):
    """إلغاء فاتورة مع سبب إلزامي"""
    db     = get_db()
    biz_id = session["business_id"]

    reason = request.form.get("reason", "").strip()[:500]
    if not reason:
        flash("يجب إدخال سبب الإلغاء", "error")
        return redirect(url_for("invoices.view_invoice", inv_id=inv_id))

    inv = db.execute(
        "SELECT id, status, invoice_number FROM invoices WHERE id=? AND business_id=?",
        (inv_id, biz_id)
    ).fetchone()
    if not inv:
        flash("الفاتورة غير موجودة", "error")
        return redirect(url_for("invoices.list_invoices"))

    if inv["status"] == "cancelled":
        flash("الفاتورة ملغية مسبقاً", "warning")
        return redirect(url_for("invoices.view_invoice", inv_id=inv_id))

    old_status = inv["status"]
    now        = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    db.execute(
        """UPDATE invoices
           SET status='cancelled', cancel_reason=?, cancelled_at=?, cancelled_by=?
           WHERE id=? AND business_id=?""",
        (reason, now, session.get("user_id"), inv_id, biz_id)
    )
    db.commit()

    write_audit_log(
        db, biz_id,
        action="invoice_cancelled",
        entity_type="invoice",
        entity_id=inv_id,
        old_value=json.dumps({"status": old_status}),
        new_value=json.dumps({"status": "cancelled", "reason": reason}),
    )
    flash(f"تم إلغاء الفاتورة {inv['invoice_number']} بنجاح", "success")
    return redirect(url_for("invoices.view_invoice", inv_id=inv_id))


@bp.route("/api/stats")
@require_perm("sales")
def api_stats():
    """API: إحصائيات الفواتير الشهرية"""
    db     = get_db()
    biz_id = session["business_id"]

    month = request.args.get("month", datetime.now().strftime("%Y-%m"))
    # تحقق من صيغة الشهر
    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError:
        month = datetime.now().strftime("%Y-%m")

    rows = db.execute(
        """SELECT invoice_type,
                  COUNT(*)                                          AS count,
                  COALESCE(SUM(CASE WHEN status='paid' THEN total ELSE 0 END), 0) AS paid,
                  COALESCE(SUM(tax_amount), 0)                     AS vat
           FROM invoices
           WHERE business_id=? AND strftime('%Y-%m', invoice_date)=?
           GROUP BY invoice_type""",
        (biz_id, month)
    ).fetchall()

    return jsonify({
        "month":   month,
        "summary": [dict(r) for r in rows],
    })
