"""
blueprints/accounting/routes.py — المحاسبة، التقارير، طباعة الفاتورة، ZATCA
"""
from datetime import datetime

from flask import (
    Blueprint, Response, g, redirect, render_template,
    request, session, jsonify, url_for
)

from modules.extensions import get_db, zatca_qr_b64, zatca_xml
from modules.middleware import onboarding_required, require_perm

bp = Blueprint("accounting", __name__)


@bp.route("/accounting")
@require_perm("accounting")
def accounting():
    db     = get_db()
    biz_id = session["business_id"]

    page     = max(1, int(request.args.get("page", 1)))
    per_page = 20
    offset   = (page - 1) * per_page
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

    date_from = request.args.get("from", datetime.now().strftime("%Y-%m-01"))
    date_to   = request.args.get("to",   datetime.now().strftime("%Y-%m-%d"))

    try:
        datetime.strptime(date_from, "%Y-%m-%d")
        datetime.strptime(date_to,   "%Y-%m-%d")
    except ValueError:
        date_from = datetime.now().strftime("%Y-%m-01")
        date_to   = datetime.now().strftime("%Y-%m-%d")

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
        SELECT invoice_number, invoice_date, party_name, subtotal, tax_amount, total
        FROM invoices
        WHERE business_id=? AND invoice_type IN ('sale','table') AND status='paid'
          AND DATE(invoice_date) BETWEEN ? AND ?
        ORDER BY invoice_date DESC LIMIT 100
    """, (biz_id, date_from, date_to)).fetchall()

    purch_invoices = db.execute("""
        SELECT invoice_number, invoice_date, party_name, subtotal, tax_amount, total
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
    seller     = biz["name"]       if biz else "غير محدد"
    vat_number = biz["tax_number"] if biz else ""
    ts = str(inv["created_at"] or inv["invoice_date"] or datetime.now().isoformat())
    if len(ts) == 10:
        ts += "T00:00:00Z"

    qr_b64 = zatca_qr_b64(seller, vat_number, ts,
                           float(inv["total"] or 0),
                           float(inv["tax_amount"] or 0))
    mode = request.args.get("mode", "a4")

    return render_template(
        "invoice_print.html",
        inv=dict(inv),
        lines=[dict(r) for r in lines],
        biz=dict(biz) if biz else {},
        qr_b64=qr_b64,
        mode=mode,
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
