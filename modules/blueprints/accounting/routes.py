"""
blueprints/accounting/routes.py — المحاسبة، التقارير، طباعة الفاتورة، ZATCA
"""
from datetime import datetime

from flask import (
    Blueprint, Response, g, redirect, render_template,
    request, session, jsonify, url_for
)

from modules.extensions import get_db, zatca_qr_b64, zatca_xml
from modules.country_engine import get_business_country
from modules.engines.accounting_engine import compute_pagination, parse_iso_date_range
from modules.middleware import onboarding_required, require_perm
from modules.sovereign_controls import create_owner_action_request, ensure_sovereign_tables, get_owner_policy_bool, log_owner_impact

bp = Blueprint("accounting", __name__)


@bp.route("/accounting/<int:je_id>/request-edit", methods=["POST"])
@require_perm("accounting")
def request_posted_journal_edit(je_id: int):
    db = get_db()
    biz_id = session["business_id"]
    ensure_sovereign_tables(db)

    entry = db.execute(
        "SELECT id, entry_number, is_posted, total_debit, total_credit, description FROM journal_entries WHERE id=? AND business_id=? LIMIT 1",
        (je_id, biz_id),
    ).fetchone()
    if not entry:
        return jsonify({"success": False, "error": "القيد غير موجود"}), 404

    if int(entry["is_posted"] or 0) != 1:
        return jsonify({"success": False, "error": "القيد غير مرحّل، ولا يحتاج إذن استثنائي"}), 400

    if not get_owner_policy_bool(db, int(biz_id), "journal_posted_requires_owner", True):
        return jsonify({"success": False, "error": "سياسة تجميد القيود المرحّلة غير مفعلة"}), 400

    reason = (request.form.get("reason") or request.get_json(silent=True) or {}).get("reason") if request.is_json else request.form.get("reason")
    reason = str(reason or "").strip()[:500]
    if len(reason) < 8:
        return jsonify({"success": False, "error": "سبب طلب التعديل مطلوب وبحد أدنى 8 أحرف"}), 400

    request_id = create_owner_action_request(
        db,
        business_id=int(biz_id),
        request_type="accounting.posted_journal_edit",
        entity_type="journal_entry",
        entity_id=int(je_id),
        requested_by=int(session.get("user_id") or 0) or None,
        reason=reason,
        payload={
            "entry_number": entry["entry_number"],
            "total_debit": float(entry["total_debit"] or 0),
            "total_credit": float(entry["total_credit"] or 0),
            "description": entry["description"],
        },
    )
    log_owner_impact(
        db,
        business_id=int(biz_id),
        category="accounting_guard",
        action_key="journal.posted_edit_requested",
        summary=f"طلب إذن تعديل مؤقت للقيد المرحّل {entry['entry_number']}",
        reason=reason,
        entity_type="journal_entry",
        entity_id=int(je_id),
        actor_user_id=int(session.get("user_id") or 0) or None,
        protected_amount=float(entry["total_debit"] or 0),
        payload={"request_id": request_id},
    )
    db.commit()
    return jsonify({"success": True, "request_id": request_id, "message": "تم إرسال طلب إذن تعديل مؤقت للمالك"})


@bp.route("/accounting")
@require_perm("accounting")
def accounting():
    db     = get_db()
    biz_id = session["business_id"]

    page, per_page, offset = compute_pagination(request.args.get("page", 1), 20)
    q        = request.args.get("q", "").strip()

    base_where = "WHERE je.business_id = ?"
    params     = [biz_id]
    if q:
        base_where += " AND (je.entry_number LIKE ? OR je.description LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]

    total = db.execute(
        f"SELECT COUNT(*) FROM journal_entries je {base_where}", params
    ).fetchone()[0]

    entries = db.execute(
        f"""SELECT je.id, je.entry_number, je.entry_date, je.description,
                   je.total_debit, je.total_credit, je.is_posted,
                   je.reference_type, je.reference_id,
                   u.full_name AS created_by_name
            FROM journal_entries je
            LEFT JOIN users u ON u.id = je.created_by
            {base_where}
            ORDER BY je.id DESC
            LIMIT ? OFFSET ?""",
        params + [per_page, offset]
    ).fetchall()

    entries_with_lines = []
    for e in entries:
        lines = db.execute(
            """SELECT jel.debit, jel.credit, jel.description AS line_desc,
                      a.code, a.name AS account_name
               FROM journal_entry_lines jel
               JOIN accounts a ON a.id = jel.account_id
               WHERE jel.entry_id = ?
               ORDER BY jel.line_order""",
            (e["id"],)
        ).fetchall()
        entries_with_lines.append({"entry": dict(e), "lines": [dict(l) for l in lines]})

    total_pages = max(1, (total + per_page - 1) // per_page)
    return render_template(
        "accounting.html",
        entries=entries_with_lines,
        page=page,
        total_pages=total_pages,
        total=total,
        q=q,
    )


@bp.route("/reports")
@bp.route("/reports/vat")
@require_perm("reports")
def reports():
    db     = get_db()
    biz_id = session["business_id"]

    country_profile = g.country_profile or get_business_country(db, int(biz_id))
    tax_label_ar = country_profile.get("tax_label_ar", "الضريبة")
    tax_label_en = country_profile.get("tax_label_en", "Tax")
    tax_system = str(country_profile.get("tax_system", "none") or "none").lower()
    currency_symbol = country_profile.get("currency_symbol", "ر.س")
    default_tax_rate = float(country_profile.get("default_tax_rate", 0) or 0)

    date_from, date_to = parse_iso_date_range(
        request.args.get("from", datetime.now().strftime("%Y-%m-01")),
        request.args.get("to", datetime.now().strftime("%Y-%m-%d")),
    )

    sales_vat = db.execute("""
        SELECT COUNT(*) AS count,
               COALESCE(SUM(subtotal),0) AS subtotal,
               COALESCE(SUM(tax_amount),0) AS vat,
               COALESCE(SUM(total),0) AS total
        FROM invoices
        WHERE business_id=? AND invoice_type IN ('sale','table') AND status='paid'
          AND DATE(invoice_date) BETWEEN ? AND ?
    """, (biz_id, date_from, date_to)).fetchone()

    purch_vat = db.execute("""
        SELECT COUNT(*) AS count,
               COALESCE(SUM(subtotal),0) AS subtotal,
               COALESCE(SUM(tax_amount),0) AS vat,
               COALESCE(SUM(total),0) AS total
        FROM invoices
        WHERE business_id=? AND invoice_type='purchase' AND status='paid'
          AND DATE(invoice_date) BETWEEN ? AND ?
    """, (biz_id, date_from, date_to)).fetchone()

    sale_invoices = db.execute("""
                SELECT id, invoice_number, invoice_date, party_name, party_vat, subtotal, tax_amount, total
        FROM invoices
        WHERE business_id=? AND invoice_type IN ('sale','table') AND status='paid'
          AND DATE(invoice_date) BETWEEN ? AND ?
        ORDER BY invoice_date DESC LIMIT 100
    """, (biz_id, date_from, date_to)).fetchall()

    purch_invoices = db.execute("""
                SELECT id, invoice_number, invoice_date, party_name, party_vat, subtotal, tax_amount, total
        FROM invoices
        WHERE business_id=? AND invoice_type='purchase' AND status='paid'
          AND DATE(invoice_date) BETWEEN ? AND ?
        ORDER BY invoice_date DESC LIMIT 100
    """, (biz_id, date_from, date_to)).fetchall()

    net_vat = float(sales_vat["vat"] or 0) - float(purch_vat["vat"] or 0)

    return render_template(
        "reports_vat.html",
        date_from=date_from,
        date_to=date_to,
        sales_vat=dict(sales_vat),
        purch_vat=dict(purch_vat),
        net_vat=net_vat,
        tax_label_ar=tax_label_ar,
        tax_label_en=tax_label_en,
        tax_system=tax_system,
        currency_symbol=currency_symbol,
        default_tax_rate=default_tax_rate,
        requires_zatca=bool(country_profile.get("requires_zatca", 0)),
        sale_invoices=[dict(r) for r in sale_invoices],
        purch_invoices=[dict(r) for r in purch_invoices],
    )


@bp.route("/invoice/<int:inv_id>/print")
@onboarding_required
def invoice_print(inv_id: int):
    db     = get_db()
    biz_id = session["business_id"]

    inv = db.execute(
        "SELECT * FROM invoices WHERE id=? AND business_id=?", (inv_id, biz_id)
    ).fetchone()
    if not inv:
        return render_template("404.html"), 404

    lines = db.execute(
        """SELECT il.*, p.name AS product_name
           FROM invoice_lines il
           LEFT JOIN products p ON p.id = il.product_id
           WHERE il.invoice_id=? ORDER BY il.line_order""",
        (inv_id,)
    ).fetchall()

    biz        = db.execute("SELECT * FROM businesses WHERE id=?", (biz_id,)).fetchone()
    country_profile = g.country_profile or get_business_country(db, int(biz_id))
    tax_label_ar = country_profile.get("tax_label_ar", "الضريبة")
    tax_number_label = country_profile.get("tax_number_label", "الرقم الضريبي")
    default_tax_rate = float(country_profile.get("default_tax_rate", 0) or 0)
    currency_symbol = country_profile.get("currency_symbol", "ر.س")
    requires_zatca = bool(country_profile.get("requires_zatca", 0))

    seller     = biz["name"]       if biz else "غير محدد"
    vat_number = biz["tax_number"] if biz else ""
    ts = str(inv["created_at"] or inv["invoice_date"] or datetime.now().isoformat())
    if len(ts) == 10:
        ts += "T00:00:00Z"

    qr_b64 = zatca_qr_b64(seller, vat_number, ts,
                           float(inv["total"] or 0),
                           float(inv["tax_amount"] or 0))
    mode = request.args.get("mode", "a4")

    # الرقم الضريبي للعميل — من العمود المستقل أو fallback لـ parse الملاحظات (للفواتير القديمة)
    import re as _re
    notes_raw = inv["notes"] or ""
    client_vat = inv.get("party_vat") or ""
    if not client_vat:
        # fallback للفواتير القديمة المخزّنة في الملاحظات
        m = _re.search(r"الرقم الضريبي للعميل:\s*([^\n]+)", notes_raw)
        client_vat = m.group(1).strip() if m else ""
    # إزالة سطر الرقم الضريبي من الملاحظات القديمة للعرض النظيف
    clean_notes = _re.sub(r"الرقم الضريبي للعميل:\s*[^\n]+\n?", "", notes_raw).strip()

    # قاموس طرق الدفع
    payment_labels = {
        "cash":   "نقدي",
        "bank":   "تحويل بنكي",
        "credit": "آجل",
        "card":   "بطاقة",
        "cheque": "شيك",
        "pos":    "نقطة بيع",
    }
    payment_label = payment_labels.get(inv["payment_method"] or "cash", inv["payment_method"] or "نقدي")

    return render_template(
        "invoice_print.html",
        inv=dict(inv),
        lines=[dict(r) for r in lines],
        biz=dict(biz) if biz else {},
        qr_b64=qr_b64,
        mode=mode,
        client_vat=client_vat,
        clean_notes=clean_notes,
        payment_label=payment_label,
        country_profile=country_profile,
        tax_label_ar=tax_label_ar,
        tax_number_label=tax_number_label,
        default_tax_rate=default_tax_rate,
        currency_symbol=currency_symbol,
        requires_zatca=requires_zatca,
    )


@bp.route("/api/invoice/<int:inv_id>/zatca-qr")
@onboarding_required
def api_zatca_qr(inv_id: int):
    biz_id = session["business_id"]
    db     = get_db()

    inv = db.execute(
        "SELECT * FROM invoices WHERE id=? AND business_id=?", (inv_id, biz_id)
    ).fetchone()
    if not inv:
        return jsonify({"success": False, "error": "الفاتورة غير موجودة"}), 404

    biz        = g.business
    seller     = biz["name"]       if biz else "غير محدد"
    vat_number = biz["tax_number"] if biz else ""
    ts         = str(inv["created_at"] or inv["invoice_date"] or datetime.now().isoformat())
    if len(ts) == 10:
        ts += "T00:00:00Z"

    total = float(inv["total"]      or 0)
    vat   = float(inv["tax_amount"] or 0)

    return jsonify({
        "success":    True,
        "qr_data":    zatca_qr_b64(seller, vat_number, ts, total, vat),
        "seller":     seller,
        "vat_number": vat_number,
        "timestamp":  ts[:19].replace("T", " "),
        "total":      total,
        "vat":        vat,
    })


@bp.route("/api/invoice/<int:inv_id>/zatca-xml")
@onboarding_required
def api_zatca_xml(inv_id: int):
    biz_id = session["business_id"]
    db     = get_db()

    inv = db.execute(
        "SELECT * FROM invoices WHERE id=? AND business_id=?", (inv_id, biz_id)
    ).fetchone()
    if not inv:
        return jsonify({"success": False, "error": "الفاتورة غير موجودة"}), 404

    biz        = g.business
    seller     = biz["name"]       if biz else "غير محدد"
    vat_number = biz["tax_number"] if biz else ""
    inv_num    = inv["invoice_number"] or f"INV-{inv_id}"

    return Response(
        zatca_xml(dict(inv), seller, vat_number),
        mimetype="application/xml",
        headers={"Content-Disposition": f"attachment; filename=ZATCA_{inv_num}.xml"}
    )
