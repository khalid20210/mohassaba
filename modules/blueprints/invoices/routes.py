"""
blueprints/invoices/routes.py — إدارة الفواتير الموحدة
صفحة قائمة الفواتير الشاملة: مبيعات + مشتريات مع فلاتر + أمان كامل
"""
import json
from datetime import datetime, timedelta

from flask import (
    Blueprint, flash, g, jsonify, redirect,
    render_template, request, session, url_for
)

from modules.extensions import get_db, next_invoice_number, csrf_protect
from modules.middleware import onboarding_required, require_perm, user_has_perm, write_audit_log
from modules.security_hardening import register_security_incident

bp = Blueprint("invoices", __name__, url_prefix="/invoices")


def _setting_bool(db, business_id: int, key: str, default: bool = False) -> bool:
    row = db.execute(
        "SELECT value FROM settings WHERE business_id=? AND key=? LIMIT 1",
        (business_id, key),
    ).fetchone()
    if not row or row["value"] is None:
        return default
    raw = str(row["value"]).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _setting_int(db, business_id: int, key: str, default: int) -> int:
    row = db.execute(
        "SELECT value FROM settings WHERE business_id=? AND key=? LIMIT 1",
        (business_id, key),
    ).fetchone()
    if not row or row["value"] is None:
        return default
    try:
        return int(float(str(row["value"]).strip()))
    except Exception:
        return default


def _ensure_invoice_cancel_requests_table(db):
    db.execute(
        """CREATE TABLE IF NOT EXISTS invoice_cancel_requests (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               business_id INTEGER NOT NULL,
               invoice_id INTEGER NOT NULL,
               requested_by INTEGER,
               reason TEXT NOT NULL,
               evidence_ref TEXT,
               status TEXT NOT NULL DEFAULT 'pending',
               review_note TEXT,
               reviewed_by INTEGER,
               reviewed_at TEXT,
               created_at TEXT NOT NULL DEFAULT (datetime('now'))
           )"""
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_inv_cancel_req_invoice ON invoice_cancel_requests(business_id, invoice_id, status, created_at DESC)"
    )


def _apply_invoice_cancellation(db, biz_id: int, inv, actor_user_id: int, reason: str, evidence_ref: str):
    old_status = inv["status"]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        """UPDATE invoices
           SET status='cancelled', cancel_reason=?, cancelled_at=?, cancelled_by=?
           WHERE id=? AND business_id=?""",
        (reason, now, actor_user_id, inv["id"], biz_id)
    )
    write_audit_log(
        db, biz_id,
        action="invoice_cancelled",
        entity_type="invoice",
        entity_id=inv["id"],
        old_value=json.dumps({"status": old_status}),
        new_value=json.dumps({
            "status": "cancelled",
            "reason": reason,
            "is_paid_invoice": ((inv["status"] in {"paid", "partial"}) or float(inv["paid_amount"] or 0) > 0),
            "evidence_ref": evidence_ref,
        }, ensure_ascii=False),
    )

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
        can_manage_cancel_requests=bool(user_has_perm("all")),
        # فلاتر محفوظة للواجهة
        filter_type=inv_type,
        filter_status=status,
        filter_from=date_from,
        filter_to=date_to,
        filter_q=q,
    )


@bp.route("/new", methods=["GET", "POST"])
@require_perm("sales")
def new_invoice():
    """إصدار فاتورة مبيعات جديدة — يعمل لجميع أنواع الأنشطة."""
    db     = get_db()
    biz_id = session["business_id"]

    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard

        # ── استخراج بيانات الفاتورة ──────────────────────────────────────────
        party_name     = request.form.get("party_name", "").strip()[:200]
        client_vat     = request.form.get("client_vat", "").strip()[:20]
        payment_method = request.form.get("payment_method", "cash")
        due_date       = request.form.get("due_date", "").strip() or None
        notes          = request.form.get("notes", "").strip()[:1000]
        inv_status     = request.form.get("status", "pending")
        apply_vat      = request.form.get("apply_vat") == "1"

        # التحقق من الحقول المطلوبة
        if not party_name:
            flash("يجب إدخال اسم العميل", "error")
            return redirect(url_for("invoices.new_invoice"))

        valid_statuses = {"draft", "pending", "paid"}
        if inv_status not in valid_statuses:
            inv_status = "pending"
        valid_methods = {"cash", "bank", "credit", "card"}
        if payment_method not in valid_methods:
            payment_method = "cash"

        # ── أسطر الفاتورة ────────────────────────────────────────────────────
        descs  = request.form.getlist("desc[]")
        qtys   = request.form.getlist("qty[]")
        prices = request.form.getlist("price[]")
        discs  = request.form.getlist("disc[]")

        lines = []
        subtotal = 0.0
        for i, desc in enumerate(descs):
            desc = desc.strip()[:500]
            if not desc:
                continue
            try:
                qty   = max(0.0, float(qtys[i]))
                price = max(0.0, float(prices[i]))
                disc  = min(100.0, max(0.0, float(discs[i] if i < len(discs) else 0)))
            except (ValueError, IndexError):
                continue
            line_total = qty * price * (1 - disc / 100)
            subtotal  += line_total
            lines.append({"desc": desc, "qty": qty, "price": price,
                           "disc": disc, "total": line_total})

        if not lines:
            flash("يجب إضافة سطر واحد على الأقل في الفاتورة", "error")
            return redirect(url_for("invoices.new_invoice"))

        tax_amount = round(subtotal * 0.15, 2) if apply_vat else 0.0
        total      = round(subtotal + tax_amount, 2)
        subtotal   = round(subtotal, 2)

        # ── رقم الفاتورة التلقائي ────────────────────────────────────────────
        inv_number = next_invoice_number(db, biz_id)

        # ── حفظ الفاتورة في قاعدة البيانات ──────────────────────────────────
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        inv_id = db.execute(
            """INSERT INTO invoices
               (business_id, invoice_number, invoice_type, invoice_date, due_date,
                party_name, subtotal, tax_amount, total, paid_amount,
                payment_method, status, notes, created_by, created_at)
               VALUES (?, ?, 'sale', DATE('now'), ?,
                       ?, ?, ?, ?, 0,
                       ?, ?, ?, ?, ?)""",
            (
                biz_id, inv_number, due_date,
                party_name, subtotal, tax_amount, total,
                payment_method, inv_status,
                (f"الرقم الضريبي للعميل: {client_vat}\n" if client_vat else "") + notes,
                session.get("user_id"), now,
            )
        ).lastrowid

        # ── حفظ أسطر الفاتورة ────────────────────────────────────────────────
        for idx, line in enumerate(lines, start=1):
            db.execute(
                """INSERT INTO invoice_lines
                   (invoice_id, description, quantity, unit_price, total, line_order)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (inv_id, line["desc"], line["qty"], line["price"], line["total"], idx)
            )

        db.commit()

        write_audit_log(
            db, biz_id,
            action="invoice_created",
            entity_type="invoice",
            entity_id=inv_id,
            new_value=json.dumps({"invoice_number": inv_number, "total": total,
                                  "status": inv_status}, ensure_ascii=False),
        )

        flash(f"✅ تم إصدار الفاتورة {inv_number} بنجاح", "success")
        return redirect(url_for("invoices.view_invoice", inv_id=inv_id))

    # ── GET: عرض نموذج الإنشاء ───────────────────────────────────────────────
    customers = db.execute(
        "SELECT name FROM contacts WHERE business_id=? AND contact_type IN ('customer','both') ORDER BY name",
        (biz_id,)
    ).fetchall()

    products = db.execute(
        """SELECT p.id, p.name, p.barcode, p.category_name,
                  pi.sku, pi.unit_price AS sell_price, pi.current_qty
           FROM products p
           LEFT JOIN product_inventory pi ON pi.product_id = p.id AND pi.business_id = p.business_id
           WHERE p.business_id=? AND p.is_active=1
           ORDER BY p.name""",
        (biz_id,)
    ).fetchall()

    # الرقم الضريبي للمنشأة من جدول businesses
    biz_row = db.execute(
        "SELECT tax_number FROM businesses WHERE id=?", (biz_id,)
    ).fetchone()
    biz_vat = (biz_row["tax_number"] or "") if biz_row else ""

    return render_template(
        "invoices/new.html",
        customers=customers,
        products=products,
        biz_vat=biz_vat,
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

    _ensure_invoice_cancel_requests_table(db)
    cancel_requests = db.execute(
        """SELECT r.id, r.reason, r.evidence_ref, r.status, r.review_note,
                  r.created_at, r.reviewed_at,
                  ru.full_name AS requested_by_name,
                  vu.full_name AS reviewed_by_name
           FROM invoice_cancel_requests r
           LEFT JOIN users ru ON ru.id = r.requested_by
           LEFT JOIN users vu ON vu.id = r.reviewed_by
           WHERE r.business_id=? AND r.invoice_id=?
           ORDER BY r.id DESC LIMIT 10""",
        (biz_id, inv_id)
    ).fetchall()

    return render_template(
        "invoices/view.html",
        inv=dict(inv),
        lines=[dict(r) for r in lines],
        audit=[dict(r) for r in audit],
        cancel_requests=[dict(r) for r in cancel_requests],
        can_approve_cancel=bool(user_has_perm("all")),
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
    actor_user_id = session.get("user_id")

    reason = request.form.get("reason", "").strip()[:500]
    if not reason:
        flash("يجب إدخال سبب الإلغاء", "error")
        return redirect(url_for("invoices.view_invoice", inv_id=inv_id))
    if len(reason) < 10:
        flash("سبب الإلغاء قصير جداً. اكتب سبباً واضحاً (10 أحرف على الأقل)", "error")
        return redirect(url_for("invoices.view_invoice", inv_id=inv_id))

    inv = db.execute(
        """SELECT id, status, invoice_number, total, paid_amount, payment_method, created_at
           FROM invoices WHERE id=? AND business_id=?""",
        (inv_id, biz_id)
    ).fetchone()
    if not inv:
        flash("الفاتورة غير موجودة", "error")
        return redirect(url_for("invoices.list_invoices"))

    if inv["status"] == "cancelled":
        flash("الفاتورة ملغية مسبقاً", "warning")
        return redirect(url_for("invoices.view_invoice", inv_id=inv_id))

    is_paid_invoice = (inv["status"] in {"paid", "partial"}) or float(inv["paid_amount"] or 0) > 0
    require_evidence_for_paid_cancel = _setting_bool(
        db, biz_id, "invoice_cancel_paid_requires_evidence", default=True
    )
    paid_cancel_grace_minutes = max(0, _setting_int(db, biz_id, "invoice_cancel_paid_grace_minutes", 15))
    evidence_ref = (request.form.get("evidence_ref") or "").strip()[:120]

    # إلغاء فاتورة مدفوعة لغير المدير يتحول إلى طلب اعتماد رسمي بدل الرفض المباشر.
    if is_paid_invoice and not user_has_perm("all"):
        _ensure_invoice_cancel_requests_table(db)
        pending = db.execute(
            """SELECT id FROM invoice_cancel_requests
               WHERE business_id=? AND invoice_id=? AND status='pending'
               ORDER BY id DESC LIMIT 1""",
            (biz_id, inv_id),
        ).fetchone()
        if pending:
            flash("يوجد طلب إلغاء قيد المراجعة لهذه الفاتورة", "warning")
            return redirect(url_for("invoices.view_invoice", inv_id=inv_id))

        created_raw = inv["created_at"] or ""
        within_grace = False
        try:
            inv_created = datetime.strptime(str(created_raw)[:19], "%Y-%m-%d %H:%M:%S")
            within_grace = datetime.now() <= (inv_created + timedelta(minutes=paid_cancel_grace_minutes))
        except Exception:
            within_grace = False

        db.execute(
            """INSERT INTO invoice_cancel_requests
               (business_id, invoice_id, requested_by, reason, evidence_ref, status)
               VALUES (?,?,?,?,?,'pending')""",
            (biz_id, inv_id, actor_user_id, reason, evidence_ref),
        )
        req_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        write_audit_log(
            db, biz_id,
            action="invoice_cancel_requested",
            entity_type="invoice",
            entity_id=inv_id,
            new_value=json.dumps({
                "request_id": req_id,
                "reason": reason,
                "evidence_ref": evidence_ref,
                "within_grace_window": within_grace,
                "grace_minutes": paid_cancel_grace_minutes,
            }, ensure_ascii=False),
        )
        register_security_incident(
            db,
            biz_id,
            "paid_invoice_cancel_request_submitted",
            payload={
                "request_id": req_id,
                "invoice_id": inv_id,
                "invoice_number": inv["invoice_number"],
                "status": inv["status"],
                "total": float(inv["total"] or 0),
                "attempted_by": actor_user_id,
                "within_grace_window": within_grace,
            },
            severity=("medium" if within_grace else "high"),
            agent_id=actor_user_id,
        )
        db.commit()
        flash("تم رفع طلب إلغاء الفاتورة المدفوعة إلى المدير للمراجعة", "success")
        return redirect(url_for("invoices.view_invoice", inv_id=inv_id))

    if is_paid_invoice and require_evidence_for_paid_cancel and len(evidence_ref) < 6:
        flash("مرجع الإثبات مطلوب لإلغاء فاتورة مدفوعة", "error")
        return redirect(url_for("invoices.view_invoice", inv_id=inv_id))

    _apply_invoice_cancellation(db, biz_id, inv, actor_user_id, reason, evidence_ref)
    if is_paid_invoice:
        register_security_incident(
            db,
            biz_id,
            "paid_invoice_cancelled",
            payload={
                "invoice_id": inv_id,
                "invoice_number": inv["invoice_number"],
                "cancelled_by": actor_user_id,
                "evidence_ref": evidence_ref,
                "reason": reason,
            },
            severity="high",
            agent_id=actor_user_id,
        )

    db.commit()
    flash(f"تم إلغاء الفاتورة {inv['invoice_number']} بنجاح", "success")
    return redirect(url_for("invoices.view_invoice", inv_id=inv_id))


@bp.route("/<int:inv_id>/cancel-requests/<int:req_id>/approve", methods=["POST"])
@require_perm("sales")
def approve_cancel_request(inv_id: int, req_id: int):
    db = get_db()
    biz_id = session["business_id"]
    reviewer_id = session.get("user_id")

    guard = csrf_protect()
    if guard:
        return guard
    if not user_has_perm("all"):
        flash("اعتماد طلب الإلغاء متاح للمدير فقط", "error")
        return redirect(url_for("invoices.view_invoice", inv_id=inv_id))

    _ensure_invoice_cancel_requests_table(db)
    req = db.execute(
        """SELECT * FROM invoice_cancel_requests
           WHERE id=? AND business_id=? AND invoice_id=? AND status='pending'""",
        (req_id, biz_id, inv_id),
    ).fetchone()
    if not req:
        flash("طلب الإلغاء غير موجود أو تمت معالجته", "warning")
        return redirect(url_for("invoices.view_invoice", inv_id=inv_id))

    inv = db.execute(
        """SELECT id, status, invoice_number, total, paid_amount, payment_method, created_at
           FROM invoices WHERE id=? AND business_id=?""",
        (inv_id, biz_id),
    ).fetchone()
    if not inv:
        flash("الفاتورة غير موجودة", "error")
        return redirect(url_for("invoices.list_invoices"))
    if inv["status"] == "cancelled":
        flash("الفاتورة ملغية مسبقاً", "warning")
        return redirect(url_for("invoices.view_invoice", inv_id=inv_id))

    review_note = (request.form.get("review_note") or "").strip()[:500]
    _apply_invoice_cancellation(db, biz_id, inv, reviewer_id, req["reason"], req["evidence_ref"] or "")
    db.execute(
        """UPDATE invoice_cancel_requests
           SET status='approved', review_note=?, reviewed_by=?, reviewed_at=datetime('now')
           WHERE id=? AND business_id=?""",
        (review_note, reviewer_id, req_id, biz_id),
    )

    write_audit_log(
        db, biz_id,
        action="invoice_cancel_request_approved",
        entity_type="invoice",
        entity_id=inv_id,
        new_value=json.dumps({
            "request_id": req_id,
            "review_note": review_note,
            "reason": req["reason"],
            "evidence_ref": req["evidence_ref"],
        }, ensure_ascii=False),
    )
    db.commit()
    flash("تم اعتماد طلب الإلغاء وتنفيذ الإلغاء بنجاح", "success")
    return redirect(url_for("invoices.view_invoice", inv_id=inv_id))


@bp.route("/<int:inv_id>/cancel-requests/<int:req_id>/reject", methods=["POST"])
@require_perm("sales")
def reject_cancel_request(inv_id: int, req_id: int):
    db = get_db()
    biz_id = session["business_id"]
    reviewer_id = session.get("user_id")

    guard = csrf_protect()
    if guard:
        return guard
    if not user_has_perm("all"):
        flash("رفض طلب الإلغاء متاح للمدير فقط", "error")
        return redirect(url_for("invoices.view_invoice", inv_id=inv_id))

    _ensure_invoice_cancel_requests_table(db)
    req = db.execute(
        """SELECT * FROM invoice_cancel_requests
           WHERE id=? AND business_id=? AND invoice_id=? AND status='pending'""",
        (req_id, biz_id, inv_id),
    ).fetchone()
    if not req:
        flash("طلب الإلغاء غير موجود أو تمت معالجته", "warning")
        return redirect(url_for("invoices.view_invoice", inv_id=inv_id))

    review_note = (request.form.get("review_note") or "").strip()[:500]
    db.execute(
        """UPDATE invoice_cancel_requests
           SET status='rejected', review_note=?, reviewed_by=?, reviewed_at=datetime('now')
           WHERE id=? AND business_id=?""",
        (review_note, reviewer_id, req_id, biz_id),
    )
    write_audit_log(
        db, biz_id,
        action="invoice_cancel_request_rejected",
        entity_type="invoice",
        entity_id=inv_id,
        new_value=json.dumps({
            "request_id": req_id,
            "review_note": review_note,
            "reason": req["reason"],
            "evidence_ref": req["evidence_ref"],
        }, ensure_ascii=False),
    )
    register_security_incident(
        db,
        biz_id,
        "paid_invoice_cancel_request_rejected",
        payload={
            "request_id": req_id,
            "invoice_id": inv_id,
            "reviewed_by": reviewer_id,
            "review_note": review_note,
        },
        severity="medium",
        agent_id=reviewer_id,
    )
    db.commit()
    flash("تم رفض طلب الإلغاء", "success")
    return redirect(url_for("invoices.view_invoice", inv_id=inv_id))


@bp.route("/cancel-requests/pending")
@require_perm("sales")
def pending_cancel_requests_page():
    db = get_db()
    biz_id = session["business_id"]
    user_id = session.get("user_id")
    if not user_has_perm("all"):
        flash("هذه الصفحة متاحة للمدير فقط", "error")
        return redirect(url_for("invoices.list_invoices"))

    _ensure_invoice_cancel_requests_table(db)

    q = (request.args.get("q") or "").strip()[:100]
    priority = (request.args.get("priority") or "").strip().lower()
    sla_status = (request.args.get("sla_status") or "").strip().lower()
    requester = (request.args.get("requester") or "").strip()
    min_total_raw = (request.args.get("min_total") or "").strip()

    min_total = None
    if min_total_raw:
        try:
            min_total = max(0.0, float(min_total_raw))
        except Exception:
            min_total = None

    high_amount = max(0, _setting_int(db, biz_id, "invoice_cancel_request_high_amount", 5000))
    critical_amount = max(high_amount, _setting_int(db, biz_id, "invoice_cancel_request_critical_amount", 20000))
    high_age = max(1, _setting_int(db, biz_id, "invoice_cancel_request_high_age_hours", 6))
    critical_age = max(high_age, _setting_int(db, biz_id, "invoice_cancel_request_critical_age_hours", 24))
    sla_critical_hours = max(1, _setting_int(db, biz_id, "invoice_cancel_request_sla_critical_hours", 2))
    sla_high_hours = max(sla_critical_hours, _setting_int(db, biz_id, "invoice_cancel_request_sla_high_hours", 8))
    sla_normal_hours = max(sla_high_hours, _setting_int(db, biz_id, "invoice_cancel_request_sla_normal_hours", 24))

    priority_expr = (
        f"CASE "
        f"WHEN (i.total >= {critical_amount} OR ((julianday('now') - julianday(r.created_at)) * 24.0) >= {critical_age}) THEN 'critical' "
        f"WHEN (i.total >= {high_amount} OR ((julianday('now') - julianday(r.created_at)) * 24.0) >= {high_age}) THEN 'high' "
        f"ELSE 'normal' END"
    )
    age_hours_expr = "((julianday('now') - julianday(r.created_at)) * 24.0)"
    sla_expr = (
        f"CASE "
        f"WHEN (({priority_expr})='critical' AND {age_hours_expr} >= {sla_critical_hours}) "
        f"  OR (({priority_expr})='high' AND {age_hours_expr} >= {sla_high_hours}) "
        f"  OR (({priority_expr})='normal' AND {age_hours_expr} >= {sla_normal_hours}) THEN 'breached' "
        f"WHEN (({priority_expr})='critical' AND {age_hours_expr} >= {max(0.1, sla_critical_hours * 0.75)}) "
        f"  OR (({priority_expr})='high' AND {age_hours_expr} >= {max(0.1, sla_high_hours * 0.75)}) "
        f"  OR (({priority_expr})='normal' AND {age_hours_expr} >= {max(0.1, sla_normal_hours * 0.75)}) THEN 'warning' "
        f"ELSE 'on_track' END"
    )

    conditions = ["r.business_id=?", "r.status='pending'"]
    params = [biz_id]

    if q:
        like = f"%{q}%"
        conditions.append("(i.invoice_number LIKE ? OR r.reason LIKE ? OR COALESCE(r.evidence_ref,'') LIKE ?)")
        params.extend([like, like, like])

    if min_total is not None:
        conditions.append("i.total >= ?")
        params.append(min_total)

    if requester == "me":
        conditions.append("r.requested_by = ?")
        params.append(user_id)
    elif requester:
        try:
            requester_id = int(requester)
            conditions.append("r.requested_by = ?")
            params.append(requester_id)
        except Exception:
            requester = ""

    if priority in {"normal", "high", "critical"}:
        conditions.append(f"({priority_expr}) = ?")
        params.append(priority)
    else:
        priority = ""

    if sla_status in {"breached", "warning", "on_track"}:
        conditions.append(f"({sla_expr}) = ?")
        params.append(sla_status)
    else:
        sla_status = ""

    where = " AND ".join(conditions)

    rows = db.execute(
        f"""SELECT r.id, r.invoice_id, r.reason, r.evidence_ref, r.status, r.created_at,
                  i.invoice_number, i.invoice_date, i.total, i.status AS invoice_status,
                  ru.full_name AS requested_by_name,
                ROUND({age_hours_expr}, 1) AS age_hours,
                {priority_expr} AS priority,
                {sla_expr} AS sla_status
           FROM invoice_cancel_requests r
           JOIN invoices i ON i.id = r.invoice_id AND i.business_id = r.business_id
           LEFT JOIN users ru ON ru.id = r.requested_by
           WHERE {where}
                     ORDER BY
                         CASE {priority_expr}
                             WHEN 'critical' THEN 3
                             WHEN 'high' THEN 2
                             ELSE 1
                         END DESC,
                         datetime(r.created_at) ASC,
                         r.id DESC""",
        params,
    ).fetchall()

    requesters = db.execute(
        """SELECT u.id, u.full_name, COUNT(*) AS req_count
           FROM invoice_cancel_requests r
           JOIN users u ON u.id = r.requested_by
           WHERE r.business_id=? AND r.status='pending'
           GROUP BY u.id, u.full_name
           ORDER BY req_count DESC, u.full_name ASC""",
        (biz_id,),
    ).fetchall()

    summary = {
        "critical": 0, "high": 0, "normal": 0,
        "breached": 0, "warning": 0, "on_track": 0,
    }
    for row in rows:
        lvl = (row["priority"] or "normal").lower()
        if lvl in summary:
            summary[lvl] += 1
        sla_lvl = (row["sla_status"] or "on_track").lower()
        if sla_lvl in summary:
            summary[sla_lvl] += 1

    return render_template(
        "invoices/cancel_requests.html",
        requests=[dict(r) for r in rows],
        requesters=[dict(r) for r in requesters],
        filter_q=q,
        filter_priority=priority,
        filter_sla_status=sla_status,
        filter_requester=requester,
        filter_min_total=("" if min_total is None else str(min_total)),
        summary=summary,
        sla_thresholds={
            "critical": sla_critical_hours,
            "high": sla_high_hours,
            "normal": sla_normal_hours,
        },
    )


@bp.route("/cancel-requests/bulk-review", methods=["POST"])
@require_perm("sales")
def bulk_review_cancel_requests():
    db = get_db()
    biz_id = session["business_id"]
    reviewer_id = session.get("user_id")

    guard = csrf_protect()
    if guard:
        return guard
    if not user_has_perm("all"):
        flash("المراجعة الجماعية متاحة للمدير فقط", "error")
        return redirect(url_for("invoices.pending_cancel_requests_page"))

    action = (request.form.get("action") or "").strip().lower()
    if action not in {"approve", "reject"}:
        flash("إجراء جماعي غير صالح", "error")
        return redirect(url_for("invoices.pending_cancel_requests_page"))

    review_note = (request.form.get("review_note") or "").strip()[:500]
    raw_ids = request.form.getlist("request_ids")
    request_ids = []
    seen = set()
    for raw in raw_ids:
        try:
            rid = int(raw)
        except Exception:
            continue
        if rid <= 0 or rid in seen:
            continue
        seen.add(rid)
        request_ids.append(rid)

    if not request_ids:
        flash("حدد طلبًا واحدًا على الأقل", "warning")
        return redirect(url_for("invoices.pending_cancel_requests_page"))

    if len(request_ids) > 200:
        flash("الحد الأقصى للمراجعة الجماعية هو 200 طلب في العملية الواحدة", "warning")
        return redirect(url_for("invoices.pending_cancel_requests_page"))

    _ensure_invoice_cancel_requests_table(db)
    placeholders = ",".join(["?"] * len(request_ids))
    rows = db.execute(
        f"""SELECT r.id, r.invoice_id, r.reason, r.evidence_ref,
                  i.status AS invoice_status, i.invoice_number, i.total, i.paid_amount
           FROM invoice_cancel_requests r
           LEFT JOIN invoices i
             ON i.id = r.invoice_id AND i.business_id = r.business_id
           WHERE r.business_id=? AND r.status='pending' AND r.id IN ({placeholders})""",
        [biz_id] + request_ids,
    ).fetchall()

    approved_count = 0
    rejected_count = 0
    skipped_count = 0

    try:
        for row in rows:
            req_id = int(row["id"])
            inv_id = int(row["invoice_id"])
            inv_status = row["invoice_status"]

            if not inv_status:
                skipped_count += 1
                continue

            if action == "approve":
                if inv_status == "cancelled":
                    skipped_count += 1
                    continue

                inv = {
                    "id": inv_id,
                    "status": inv_status,
                    "paid_amount": float(row["paid_amount"] or 0),
                }
                _apply_invoice_cancellation(
                    db,
                    biz_id,
                    inv,
                    reviewer_id,
                    row["reason"],
                    row["evidence_ref"] or "",
                )
                db.execute(
                    """UPDATE invoice_cancel_requests
                       SET status='approved', review_note=?, reviewed_by=?, reviewed_at=datetime('now')
                       WHERE id=? AND business_id=?""",
                    (review_note, reviewer_id, req_id, biz_id),
                )
                write_audit_log(
                    db, biz_id,
                    action="invoice_cancel_request_approved",
                    entity_type="invoice",
                    entity_id=inv_id,
                    new_value=json.dumps({
                        "request_id": req_id,
                        "mode": "bulk",
                        "review_note": review_note,
                        "reason": row["reason"],
                        "evidence_ref": row["evidence_ref"],
                    }, ensure_ascii=False),
                )
                approved_count += 1
            else:
                db.execute(
                    """UPDATE invoice_cancel_requests
                       SET status='rejected', review_note=?, reviewed_by=?, reviewed_at=datetime('now')
                       WHERE id=? AND business_id=?""",
                    (review_note, reviewer_id, req_id, biz_id),
                )
                write_audit_log(
                    db, biz_id,
                    action="invoice_cancel_request_rejected",
                    entity_type="invoice",
                    entity_id=inv_id,
                    new_value=json.dumps({
                        "request_id": req_id,
                        "mode": "bulk",
                        "review_note": review_note,
                        "reason": row["reason"],
                        "evidence_ref": row["evidence_ref"],
                    }, ensure_ascii=False),
                )
                register_security_incident(
                    db,
                    biz_id,
                    "paid_invoice_cancel_request_rejected",
                    payload={
                        "request_id": req_id,
                        "invoice_id": inv_id,
                        "reviewed_by": reviewer_id,
                        "review_note": review_note,
                        "mode": "bulk",
                    },
                    severity="medium",
                    agent_id=reviewer_id,
                )
                rejected_count += 1

        db.commit()
    except Exception:
        db.rollback()
        flash("تعذر تنفيذ المراجعة الجماعية حالياً", "error")
        return redirect(url_for("invoices.pending_cancel_requests_page"))

    if action == "approve":
        flash(f"تم اعتماد {approved_count} طلب. تم تجاوز {skipped_count} طلب.", "success")
    else:
        flash(f"تم رفض {rejected_count} طلب. تم تجاوز {skipped_count} طلب.", "success")
    return redirect(url_for("invoices.pending_cancel_requests_page"))


@bp.route("/cancel-requests/report/daily")
@require_perm("sales")
def cancel_requests_daily_report_page():
    db = get_db()
    biz_id = session["business_id"]
    if not user_has_perm("all"):
        flash("تقرير الطلبات متاح للمدير فقط", "error")
        return redirect(url_for("invoices.list_invoices"))

    _ensure_invoice_cancel_requests_table(db)

    selected_date = (request.args.get("date") or datetime.now().strftime("%Y-%m-%d")).strip()
    try:
        datetime.strptime(selected_date, "%Y-%m-%d")
    except ValueError:
        selected_date = datetime.now().strftime("%Y-%m-%d")

    high_amount = max(0, _setting_int(db, biz_id, "invoice_cancel_request_high_amount", 5000))
    critical_amount = max(high_amount, _setting_int(db, biz_id, "invoice_cancel_request_critical_amount", 20000))
    high_age = max(1, _setting_int(db, biz_id, "invoice_cancel_request_high_age_hours", 6))
    critical_age = max(high_age, _setting_int(db, biz_id, "invoice_cancel_request_critical_age_hours", 24))
    sla_critical_hours = max(1, _setting_int(db, biz_id, "invoice_cancel_request_sla_critical_hours", 2))
    sla_high_hours = max(sla_critical_hours, _setting_int(db, biz_id, "invoice_cancel_request_sla_high_hours", 8))
    sla_normal_hours = max(sla_high_hours, _setting_int(db, biz_id, "invoice_cancel_request_sla_normal_hours", 24))

    priority_expr = (
        f"CASE "
        f"WHEN (i.total >= {critical_amount} OR ((julianday('now') - julianday(r.created_at)) * 24.0) >= {critical_age}) THEN 'critical' "
        f"WHEN (i.total >= {high_amount} OR ((julianday('now') - julianday(r.created_at)) * 24.0) >= {high_age}) THEN 'high' "
        f"ELSE 'normal' END"
    )
    age_hours_expr = "((julianday('now') - julianday(r.created_at)) * 24.0)"
    sla_expr = (
        f"CASE "
        f"WHEN (({priority_expr})='critical' AND {age_hours_expr} >= {sla_critical_hours}) "
        f"  OR (({priority_expr})='high' AND {age_hours_expr} >= {sla_high_hours}) "
        f"  OR (({priority_expr})='normal' AND {age_hours_expr} >= {sla_normal_hours}) THEN 'breached' "
        f"WHEN (({priority_expr})='critical' AND {age_hours_expr} >= {max(0.1, sla_critical_hours * 0.75)}) "
        f"  OR (({priority_expr})='high' AND {age_hours_expr} >= {max(0.1, sla_high_hours * 0.75)}) "
        f"  OR (({priority_expr})='normal' AND {age_hours_expr} >= {max(0.1, sla_normal_hours * 0.75)}) THEN 'warning' "
        f"ELSE 'on_track' END"
    )

    summary_row = db.execute(
        f"""SELECT
               COUNT(*) AS total_count,
               SUM(CASE WHEN r.status='pending' THEN 1 ELSE 0 END) AS pending_count,
               SUM(CASE WHEN r.status='approved' THEN 1 ELSE 0 END) AS approved_count,
               SUM(CASE WHEN r.status='rejected' THEN 1 ELSE 0 END) AS rejected_count,
               SUM(CASE WHEN ({priority_expr})='critical' THEN 1 ELSE 0 END) AS critical_count,
               SUM(CASE WHEN ({priority_expr})='high' THEN 1 ELSE 0 END) AS high_count,
               SUM(CASE WHEN ({priority_expr})='normal' THEN 1 ELSE 0 END) AS normal_count,
            SUM(CASE WHEN ({sla_expr})='breached' THEN 1 ELSE 0 END) AS sla_breached_count,
            SUM(CASE WHEN ({sla_expr})='warning' THEN 1 ELSE 0 END) AS sla_warning_count,
            SUM(CASE WHEN ({sla_expr})='on_track' THEN 1 ELSE 0 END) AS sla_on_track_count,
            SUM(CASE WHEN r.status='pending' AND ({sla_expr})='breached' THEN 1 ELSE 0 END) AS pending_sla_breached_count,
            ROUND(AVG(CASE WHEN r.status IN ('approved','rejected') AND r.reviewed_at IS NOT NULL
                        THEN ((julianday(r.reviewed_at)-julianday(r.created_at))*24.0)
                    END),2) AS avg_review_hours,
               ROUND(COALESCE(SUM(i.total),0),2) AS total_amount
           FROM invoice_cancel_requests r
           JOIN invoices i ON i.id = r.invoice_id AND i.business_id = r.business_id
           WHERE r.business_id=? AND date(r.created_at)=date(?)""",
        (biz_id, selected_date),
    ).fetchone()

    reviewer_rows = db.execute(
        """SELECT COALESCE(u.full_name, '—') AS reviewer_name,
                  SUM(CASE WHEN r.status='approved' THEN 1 ELSE 0 END) AS approved_count,
                  SUM(CASE WHEN r.status='rejected' THEN 1 ELSE 0 END) AS rejected_count,
                  COUNT(*) AS reviewed_total
           FROM invoice_cancel_requests r
           LEFT JOIN users u ON u.id = r.reviewed_by
           WHERE r.business_id=?
             AND date(COALESCE(r.reviewed_at, r.created_at))=date(?)
             AND r.status IN ('approved','rejected')
           GROUP BY COALESCE(u.full_name, '—')
           ORDER BY reviewed_total DESC, reviewer_name ASC""",
        (biz_id, selected_date),
    ).fetchall()

    top_requests = db.execute(
        f"""SELECT r.id, r.invoice_id, r.status, r.created_at, r.reviewed_at,
                  i.invoice_number, i.total,
                  {priority_expr} AS priority,
                  COALESCE(ru.full_name, '—') AS requested_by_name,
                  COALESCE(vu.full_name, '—') AS reviewed_by_name
           FROM invoice_cancel_requests r
           JOIN invoices i ON i.id = r.invoice_id AND i.business_id = r.business_id
           LEFT JOIN users ru ON ru.id = r.requested_by
           LEFT JOIN users vu ON vu.id = r.reviewed_by
           WHERE r.business_id=? AND date(r.created_at)=date(?)
           ORDER BY i.total DESC, r.id DESC
           LIMIT 20""",
        (biz_id, selected_date),
    ).fetchall()

    return render_template(
        "invoices/cancel_requests_report.html",
        selected_date=selected_date,
        summary=dict(summary_row) if summary_row else {},
        reviewer_rows=[dict(r) for r in reviewer_rows],
        top_requests=[dict(r) for r in top_requests],
        sla_thresholds={
            "critical": sla_critical_hours,
            "high": sla_high_hours,
            "normal": sla_normal_hours,
        },
    )


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
