"""
blueprints/restaurant/routes.py — المطعم: طاولات، مطبخ، طلبات جملة، أسعار
"""
from datetime import datetime

from flask import (
    Blueprint, flash, g, jsonify, redirect, render_template,
    request, session, url_for
)

from modules.extensions import (
    get_db, get_account_id, csrf_protect, next_entry_number, next_invoice_number
)
from modules.middleware import login_required, onboarding_required
from modules.validators import validate, V, SCHEMA_PRICING_UPDATE
from modules.zatca_queue import enqueue_invoice

bp = Blueprint("restaurant", __name__)


# ════════════════════════════════════════════════════════════════════════════════
# ORDERS — أوامر بيع الجملة
# ════════════════════════════════════════════════════════════════════════════════

@bp.route("/orders", methods=["GET", "POST"])
@onboarding_required
def orders():
    db     = get_db()
    biz_id = session["business_id"]

    if request.method == "GET":
        page     = max(1, int(request.args.get("page", 1)))
        per_page = 20
        offset   = (page - 1) * per_page
        q        = request.args.get("q", "").strip()

        where  = "WHERE i.business_id=? AND i.invoice_type='sale'"
        params = [biz_id]
        if q:
            where  += " AND (i.invoice_number LIKE ? OR i.party_name LIKE ?)"
            params += [f"%{q}%", f"%{q}%"]

        invoices_list = db.execute(
            f"""SELECT i.id, i.invoice_number, i.invoice_date, i.due_date,
                       i.party_name, i.subtotal, i.discount_amount,
                       i.tax_amount, i.total, i.paid_amount, i.status,
                       u.full_name AS created_by_name
                FROM invoices i
                LEFT JOIN users u ON u.id = i.created_by
                {where}
                ORDER BY i.id DESC LIMIT ? OFFSET ?""",
            params + [per_page, offset]
        ).fetchall()

        total = db.execute(
            f"SELECT COUNT(*) FROM invoices i {where}", params
        ).fetchone()[0]

        customers = db.execute(
            """SELECT id, name, phone FROM contacts
               WHERE business_id=? AND contact_type IN ('customer','both') AND is_active=1
               ORDER BY name""",
            (biz_id,)
        ).fetchall()

        products = db.execute(
            """SELECT p.id, p.name, p.barcode, p.sale_price, p.purchase_price, p.category_name,
                      COALESCE(s.quantity, 0) AS stock_qty
               FROM products p
               LEFT JOIN stock s ON s.product_id=p.id
               WHERE p.business_id=? AND p.is_active=1
               ORDER BY p.name LIMIT 500""",
            (biz_id,)
        ).fetchall()

        total_pages = max(1, (total + per_page - 1) // per_page)
        return render_template(
            "orders.html",
            invoices=invoices_list,
            customers=customers,
            products=products,
            page=page,
            total_pages=total_pages,
            total=total,
            q=q,
        )

    # POST: حفظ أمر بيع جملة
    guard = csrf_protect()
    if guard:
        return guard

    customer_id    = request.form.get("customer_id",    "").strip()
    customer_name  = request.form.get("customer_name",  "").strip()
    order_date     = request.form.get("order_date",     "").strip()
    due_date       = request.form.get("due_date",       "").strip()
    payment_method = request.form.get("payment_method", "cash")
    discount_pct   = float(request.form.get("discount_pct", 0) or 0)
    tax_pct        = float(request.form.get("tax_pct",      0) or 0)
    notes          = request.form.get("notes", "").strip()

    product_ids    = request.form.getlist("product_id[]")
    quantities     = request.form.getlist("quantity[]")
    unit_prices    = request.form.getlist("unit_price[]")
    line_discounts = request.form.getlist("line_discount[]")

    if not order_date:
        flash("تاريخ الأمر مطلوب", "error")
        return redirect(url_for("restaurant.orders"))
    if not product_ids:
        flash("يجب إضافة منتج واحد على الأقل", "error")
        return redirect(url_for("restaurant.orders"))

    user_id    = session["user_id"]
    subtotal   = cogs_total = 0.0
    validated  = []

    for i, (pid, qty_s, price_s) in enumerate(zip(product_ids, quantities, unit_prices)):
        try:
            qty       = float(qty_s)
            price     = float(price_s)
            line_disc = float(line_discounts[i]) if i < len(line_discounts) else 0.0
        except (ValueError, TypeError):
            continue
        if qty <= 0 or price < 0:
            continue
        product = db.execute(
            "SELECT * FROM products WHERE id=? AND business_id=?", (int(pid), biz_id)
        ).fetchone()
        if not product:
            continue
        line_sub      = round(qty * price, 4)
        line_disc_amt = round(line_sub * line_disc / 100, 4)
        line_net      = round(line_sub - line_disc_amt, 4)
        line_cost     = round(qty * float(product["purchase_price"] or 0), 4)
        subtotal   += line_net
        cogs_total += line_cost
        validated.append({
            "product_id": int(pid), "name": product["name"],
            "quantity": qty, "unit_price": price,
            "discount_pct": line_disc, "discount_amount": line_disc_amt,
            "line_net": line_net, "purchase_price": float(product["purchase_price"] or 0),
        })

    if not validated:
        flash("البنود غير صالحة — تحقق من الكميات والأسعار", "error")
        return redirect(url_for("restaurant.orders"))

    subtotal            = round(subtotal, 2)
    overall_disc_amt    = round(subtotal * discount_pct / 100, 2)
    subtotal_after_disc = round(subtotal - overall_disc_amt, 2)
    tax_total           = round(subtotal_after_disc * tax_pct / 100, 2)
    grand_total         = round(subtotal_after_disc + tax_total, 2)
    cogs_total          = round(cogs_total, 2)

    debit_code   = {"cash": "1101", "bank": "1102", "credit": "1103"}.get(payment_method, "1101")
    debit_acc_id = get_account_id(db, biz_id, debit_code)
    sales_acc_id = get_account_id(db, biz_id, "4101")
    tax_acc_id   = get_account_id(db, biz_id, "2102")
    cogs_acc_id  = get_account_id(db, biz_id, "5101")
    inv_acc_id   = get_account_id(db, biz_id, "1104")

    if not all([debit_acc_id, sales_acc_id, cogs_acc_id, inv_acc_id]):
        flash("شجرة الحسابات غير مكتملة — راجع الإعدادات", "error")
        return redirect(url_for("restaurant.orders"))

    wh = db.execute(
        "SELECT id FROM warehouses WHERE business_id=? AND is_default=1 LIMIT 1", (biz_id,)
    ).fetchone()
    warehouse_id = wh["id"] if wh else None

    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # BEGIN IMMEDIATE: يمنع Race Condition عند توليد أرقام الأوامر المتزامنة
        db.execute("BEGIN IMMEDIATE")

        cnt = db.execute(
            "SELECT COUNT(*) FROM invoices WHERE business_id=? AND invoice_type='sale'", (biz_id,)
        ).fetchone()[0]
        order_number = f"ORD-{cnt + 1:05d}"

        cust_id = int(customer_id) if customer_id else None
        if cust_id:
            row = db.execute(
                "SELECT name FROM contacts WHERE id=? AND business_id=?", (cust_id, biz_id)
            ).fetchone()
            if row:
                customer_name = row["name"]

        db.execute(
            """INSERT INTO invoices
               (business_id, invoice_number, invoice_type, invoice_date, due_date,
                party_id, party_name, subtotal, discount_pct, discount_amount,
                tax_amount, total, paid_amount, status, warehouse_id, notes, created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (biz_id, order_number, "sale", order_date, due_date or None,
             cust_id, customer_name or None,
             round(subtotal + overall_disc_amt, 2), discount_pct, overall_disc_amt,
             tax_total, grand_total,
             grand_total if payment_method != "credit" else 0,
             "paid" if payment_method != "credit" else "partial",
             warehouse_id, notes or None, user_id)
        )
        inv_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        for idx, item in enumerate(validated):
            line_tax = round(item["line_net"] * tax_pct / 100, 4)
            db.execute(
                """INSERT INTO invoice_lines
                   (invoice_id, product_id, description, quantity, unit_price,
                    discount_pct, discount_amount, tax_rate, tax_amount, total, line_order)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (inv_id, item["product_id"], item["name"],
                 item["quantity"], item["unit_price"],
                 item["discount_pct"], item["discount_amount"],
                 tax_pct, line_tax, round(item["line_net"] + line_tax, 4), idx + 1)
            )
            if warehouse_id:
                db.execute(
                    "INSERT OR IGNORE INTO stock (business_id,product_id,warehouse_id,quantity,avg_cost) VALUES (?,?,?,0,0)",
                    (biz_id, item["product_id"], warehouse_id)
                )
                db.execute(
                    "UPDATE stock SET quantity=quantity-?,last_updated=? WHERE product_id=? AND warehouse_id=?",
                    (item["quantity"], now, item["product_id"], warehouse_id)
                )
                db.execute(
                    """INSERT INTO stock_movements
                       (business_id,product_id,warehouse_id,movement_type,
                        quantity,unit_cost,reference_type,reference_id,created_by)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (biz_id, item["product_id"], warehouse_id, "sale",
                     -item["quantity"], item["purchase_price"], "invoice", inv_id, user_id)
                )

        je_num      = next_entry_number(db, biz_id)
        debit_label = {"cash": "نقداً من العميل", "bank": "تحويل بنكي",
                       "credit": f"بالآجل — {customer_name or 'عميل'}"}.get(payment_method, "نقداً")

        db.execute(
            """INSERT INTO journal_entries
               (business_id,entry_number,entry_date,description,
                reference_type,reference_id,total_debit,total_credit,is_posted,created_by)
               VALUES (?,?,?,?,?,?,?,?,1,?)""",
            (biz_id, je_num, order_date,
             f"قيد مبيعات جملة — {order_number}" + (f" | {customer_name}" if customer_name else ""),
             "invoice", inv_id, grand_total, grand_total, user_id)
        )
        je_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        db.execute("INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
                   (je_id, debit_acc_id, debit_label, grand_total, 0, 1))
        db.execute("INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
                   (je_id, sales_acc_id, f"إيرادات مبيعات جملة — {order_number}", 0, subtotal_after_disc, 2))
        if tax_total > 0 and tax_acc_id:
            db.execute("INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
                       (je_id, tax_acc_id, "ضريبة القيمة المضافة", 0, tax_total, 3))

        db.execute("UPDATE invoices SET journal_entry_id=? WHERE id=?", (je_id, inv_id))

        if cogs_total > 0:
            je_cogs_num = next_entry_number(db, biz_id)
            db.execute(
                """INSERT INTO journal_entries
                   (business_id,entry_number,entry_date,description,
                    reference_type,reference_id,total_debit,total_credit,is_posted,created_by)
                   VALUES (?,?,?,?,?,?,?,?,1,?)""",
                (biz_id, je_cogs_num, order_date,
                 f"قيد تكلفة مبيعات جملة — {order_number}",
                 "invoice", inv_id, cogs_total, cogs_total, user_id)
            )
            je_cogs_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.execute("INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
                       (je_cogs_id, cogs_acc_id, "تكلفة مبيعات جملة", cogs_total, 0, 1))
            db.execute("INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
                       (je_cogs_id, inv_acc_id, "إقفال مخزون مباع جملة", 0, cogs_total, 2))

        db.commit()
        flash(f"✓ تم إنشاء أمر البيع {order_number} وتوليد القيد المحاسبي", "success")
        return redirect(url_for("restaurant.orders"))

    except Exception as e:
        db.rollback()
        import logging
        logging.getLogger(__name__).error(f"Orders save error: {e}")
        flash("حدث خطأ أثناء الحفظ — يرجى المحاولة مرة أخرى", "error")
        return redirect(url_for("restaurant.orders"))


# ════════════════════════════════════════════════════════════════════════════════
# PRICING — إدارة قوائم الأسعار
# ════════════════════════════════════════════════════════════════════════════════

@bp.route("/pricing")
@onboarding_required
def pricing():
    db     = get_db()
    biz_id = session["business_id"]

    page        = max(1, int(request.args.get("page", 1)))
    per_page    = 50
    offset      = (page - 1) * per_page
    q           = request.args.get("q", "").strip()
    category_id = request.args.get("cat", "").strip()

    where  = "WHERE p.business_id=? AND p.is_active=1"
    params = [biz_id]
    if category_id:
        where  += " AND p.category_id=?"
        params.append(int(category_id))
    if q:
        where  += " AND (p.name LIKE ? OR p.barcode LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]

    products = db.execute(
        f"""SELECT p.id, p.name, p.barcode, p.category_name,
                   p.purchase_price, p.sale_price,
                   COALESCE(s.quantity, 0) AS stock_qty
            FROM products p
            LEFT JOIN stock s ON s.product_id=p.id
            {where}
            ORDER BY p.category_name, p.name LIMIT ? OFFSET ?""",
        params + [per_page, offset]
    ).fetchall()

    total = db.execute(f"SELECT COUNT(*) FROM products p {where}", params).fetchone()[0]

    categories = db.execute(
        "SELECT id, name FROM product_categories WHERE business_id=? AND is_active=1 ORDER BY name",
        (biz_id,)
    ).fetchall()

    total_pages = max(1, (total + per_page - 1) // per_page)
    return render_template(
        "pricing.html",
        products=products,
        categories=categories,
        page=page,
        total_pages=total_pages,
        total=total,
        q=q,
        selected_cat=category_id,
    )


@bp.route("/api/pricing/update", methods=["POST"])
@onboarding_required
def api_pricing_update():
    data       = request.get_json(force=True) or {}
    biz_id     = session["business_id"]

    cleaned, errs = validate(data, SCHEMA_PRICING_UPDATE)
    if errs:
        return jsonify({"success": False, "errors": errs}), 400

    product_id = cleaned["product_id"]
    sale_price = round(cleaned["sale_price"], 4)

    db  = get_db()
    row = db.execute(
        "SELECT id, name, purchase_price FROM products WHERE id=? AND business_id=?",
        (int(product_id), biz_id)
    ).fetchone()
    if not row:
        return jsonify({"success": False, "error": "المنتج غير موجود"}), 404

    db.execute(
        "UPDATE products SET sale_price=?, updated_at=datetime('now') WHERE id=? AND business_id=?",
        (sale_price, int(product_id), biz_id)
    )
    db.commit()
    purchase = float(row["purchase_price"] or 0)
    margin   = round(((sale_price - purchase) / sale_price * 100), 1) if sale_price > 0 else 0
    return jsonify({"success": True, "name": row["name"], "sale_price": sale_price, "margin": margin})


# ════════════════════════════════════════════════════════════════════════════════
# TABLES — إدارة الطاولات
# ════════════════════════════════════════════════════════════════════════════════

@bp.route("/tables")
@onboarding_required
def tables():
    db     = get_db()
    biz_id = session["business_id"]

    row = db.execute(
        "SELECT value FROM settings WHERE business_id=? AND key='table_count'", (biz_id,)
    ).fetchone()
    table_count = int(row["value"]) if row else 10

    open_orders = db.execute(
        """SELECT i.id, i.party_name, i.status, i.subtotal, i.total, i.created_at,
                  COUNT(il.id) AS items_count
           FROM invoices i
           LEFT JOIN invoice_lines il ON il.invoice_id=i.id
           WHERE i.business_id=? AND i.invoice_type='table'
             AND i.status IN ('draft','partial','issued')
           GROUP BY i.id""",
        (biz_id,)
    ).fetchall()

    open_map = {o["party_name"]: dict(o) for o in open_orders}

    products = db.execute(
        """SELECT p.id, p.name, p.sale_price, p.category_name, p.barcode,
                  COALESCE(s.quantity, 0) AS stock_qty
           FROM products p
           LEFT JOIN stock s ON s.product_id=p.id
           WHERE p.business_id=? AND p.is_active=1 AND p.is_pos=1
           ORDER BY p.category_name, p.name LIMIT 300""",
        (biz_id,)
    ).fetchall()

    tables_list = []
    for i in range(1, table_count + 1):
        name  = f"طاولة {i}"
        order = open_map.get(name)
        tables_list.append({
            "number": i, "name": name,
            "status": ("ready" if order and order["status"] == "issued"
                       else "occupied" if order else "free"),
            "order": order,
        })

    stats = {
        "free":     sum(1 for t in tables_list if t["status"] == "free"),
        "occupied": sum(1 for t in tables_list if t["status"] == "occupied"),
        "ready":    sum(1 for t in tables_list if t["status"] == "ready"),
    }

    return render_template(
        "tables.html",
        tables=tables_list,
        products=[dict(p) for p in products],
        stats=stats,
        table_count=table_count,
    )


@bp.route("/api/tables/open", methods=["POST"])
@onboarding_required
def api_tables_open():
    data       = request.get_json(force=True) or {}
    biz_id     = session["business_id"]
    user_id    = session["user_id"]
    table_name = data.get("table_name", "").strip()

    if not table_name:
        return jsonify({"success": False, "error": "اسم الطاولة مطلوب"}), 400

    db = get_db()

    try:
        # BEGIN IMMEDIATE: يمنع فتح نفس الطاولة مرتين في وقت واحد
        db.execute("BEGIN IMMEDIATE")

        existing = db.execute(
            """SELECT id FROM invoices
               WHERE business_id=? AND party_name=? AND invoice_type='table'
                 AND status IN ('draft','partial','issued')""",
            (biz_id, table_name)
        ).fetchone()
        if existing:
            return jsonify({"success": False, "error": "الطاولة مشغولة",
                            "invoice_id": existing["id"]}), 409

        today = datetime.now().strftime("%Y-%m-%d")
        cnt   = db.execute(
            "SELECT COUNT(*) FROM invoices WHERE business_id=? AND invoice_type='table'", (biz_id,)
        ).fetchone()[0]
        inv_number = f"TBL-{cnt + 1:05d}"

        wh = db.execute(
            "SELECT id FROM warehouses WHERE business_id=? AND is_default=1 LIMIT 1", (biz_id,)
        ).fetchone()
        warehouse_id = wh["id"] if wh else None

        db.execute(
            """INSERT INTO invoices
               (business_id,invoice_number,invoice_type,invoice_date,
                party_name,subtotal,tax_amount,total,paid_amount,
                status,warehouse_id,created_by)
               VALUES (?,?,'table',?,?,0,0,0,0,'draft',?,?)""",
            (biz_id, inv_number, today, table_name, warehouse_id, user_id)
        )
        inv_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
    except Exception as e:
        db.rollback()
        import logging
        logging.getLogger(__name__).error(f"Tables open error: {e}")
        return jsonify({"success": False, "error": "حدث خطأ أثناء فتح الطاولة"}), 500
    return jsonify({"success": True, "invoice_id": inv_id, "invoice_number": inv_number})


@bp.route("/api/tables/add-item", methods=["POST"])
@onboarding_required
def api_tables_add_item():
    data       = request.get_json(force=True) or {}
    biz_id     = session["business_id"]
    invoice_id = data.get("invoice_id")
    product_id = data.get("product_id")
    quantity   = float(data.get("quantity", 1))

    if not invoice_id or not product_id:
        return jsonify({"success": False, "error": "بيانات ناقصة"}), 400

    db  = get_db()
    inv = db.execute(
        "SELECT * FROM invoices WHERE id=? AND business_id=? AND invoice_type='table' AND status IN ('draft','partial')",
        (int(invoice_id), biz_id)
    ).fetchone()
    if not inv:
        return jsonify({"success": False, "error": "الطلب غير موجود أو لا يمكن تعديله"}), 404

    product = db.execute(
        "SELECT * FROM products WHERE id=? AND business_id=? AND is_active=1",
        (int(product_id), biz_id)
    ).fetchone()
    if not product:
        return jsonify({"success": False, "error": "المنتج غير موجود"}), 404

    unit_price = float(product["sale_price"])
    existing   = db.execute(
        "SELECT id, quantity FROM invoice_lines WHERE invoice_id=? AND product_id=?",
        (int(invoice_id), int(product_id))
    ).fetchone()

    if existing:
        new_qty = float(existing["quantity"]) + quantity
        db.execute(
            "UPDATE invoice_lines SET quantity=?, total=? WHERE id=?",
            (new_qty, round(new_qty * unit_price, 4), existing["id"])
        )
    else:
        order_cnt = db.execute(
            "SELECT COUNT(*) FROM invoice_lines WHERE invoice_id=?", (int(invoice_id),)
        ).fetchone()[0]
        db.execute(
            """INSERT INTO invoice_lines
               (invoice_id,product_id,description,quantity,unit_price,total,line_order)
               VALUES (?,?,?,?,?,?,?)""",
            (int(invoice_id), int(product_id), product["name"],
             quantity, unit_price, round(quantity * unit_price, 4), order_cnt + 1)
        )

    totals   = db.execute("SELECT SUM(total) AS s FROM invoice_lines WHERE invoice_id=?",
                          (int(invoice_id),)).fetchone()
    subtotal = round(float(totals["s"] or 0), 2)
    db.execute("UPDATE invoices SET subtotal=?, total=? WHERE id=?",
               (subtotal, subtotal, int(invoice_id)))
    db.commit()
    return jsonify({"success": True, "subtotal": subtotal, "item_name": product["name"]})


@bp.route("/api/tables/remove-item", methods=["POST"])
@onboarding_required
def api_tables_remove_item():
    data       = request.get_json(force=True) or {}
    biz_id     = session["business_id"]
    line_id    = data.get("line_id")
    invoice_id = data.get("invoice_id")

    if not line_id or not invoice_id:
        return jsonify({"success": False, "error": "بيانات ناقصة"}), 400

    db  = get_db()
    inv = db.execute(
        "SELECT id FROM invoices WHERE id=? AND business_id=? AND status='draft'",
        (int(invoice_id), biz_id)
    ).fetchone()
    if not inv:
        return jsonify({"success": False, "error": "لا يمكن تعديل طلب أُرسل للمطبخ"}), 403

    db.execute("DELETE FROM invoice_lines WHERE id=? AND invoice_id=?",
               (int(line_id), int(invoice_id)))
    totals   = db.execute("SELECT SUM(total) AS s FROM invoice_lines WHERE invoice_id=?",
                          (int(invoice_id),)).fetchone()
    subtotal = round(float(totals["s"] or 0), 2)
    db.execute("UPDATE invoices SET subtotal=?, total=? WHERE id=?",
               (subtotal, subtotal, int(invoice_id)))
    db.commit()
    return jsonify({"success": True, "subtotal": subtotal})


@bp.route("/api/tables/send-kitchen", methods=["POST"])
@onboarding_required
def api_tables_send_kitchen():
    data       = request.get_json(force=True) or {}
    biz_id     = session["business_id"]
    invoice_id = data.get("invoice_id")

    if not invoice_id:
        return jsonify({"success": False, "error": "معرّف الطلب مطلوب"}), 400

    db  = get_db()
    inv = db.execute(
        "SELECT * FROM invoices WHERE id=? AND business_id=? AND status='draft'",
        (int(invoice_id), biz_id)
    ).fetchone()
    if not inv:
        return jsonify({"success": False, "error": "الطلب غير موجود أو أُرسل مسبقاً"}), 404

    cnt = db.execute("SELECT COUNT(*) FROM invoice_lines WHERE invoice_id=?",
                     (int(invoice_id),)).fetchone()[0]
    if cnt == 0:
        return jsonify({"success": False, "error": "الطلب فارغ — أضف أصنافاً أولاً"}), 400

    db.execute("UPDATE invoices SET status='partial' WHERE id=? AND business_id=?",
               (int(invoice_id), biz_id))
    db.commit()
    return jsonify({"success": True, "message": "تم إرسال الطلب للمطبخ"})


@bp.route("/api/tables/checkout", methods=["POST"])
@onboarding_required
def api_tables_checkout():
    data           = request.get_json(force=True) or {}
    biz_id         = session["business_id"]
    user_id        = session["user_id"]
    invoice_id     = data.get("invoice_id")
    payment_method = data.get("payment_method", "cash")

    if not invoice_id:
        return jsonify({"success": False, "error": "معرّف الطلب مطلوب"}), 400

    db  = get_db()
    inv = db.execute(
        """SELECT * FROM invoices
           WHERE id=? AND business_id=? AND invoice_type='table'
             AND status IN ('draft','partial','issued')""",
        (int(invoice_id), biz_id)
    ).fetchone()
    if not inv:
        return jsonify({"success": False, "error": "الطلب غير موجود أو مغلق مسبقاً"}), 404

    lines = db.execute(
        "SELECT il.*, p.purchase_price FROM invoice_lines il LEFT JOIN products p ON p.id=il.product_id WHERE il.invoice_id=?",
        (int(invoice_id),)
    ).fetchall()

    if not lines:
        return jsonify({"success": False, "error": "الطلب فارغ"}), 400

    grand_total = float(inv["total"])
    if grand_total <= 0:
        return jsonify({"success": False, "error": "إجمالي الطلب صفر"}), 400
    tax_total = float(inv["tax_amount"] or 0)

    cash_code    = "1102" if payment_method == "bank" else "1101"
    cash_acc_id  = get_account_id(db, biz_id, cash_code)
    sales_acc_id = get_account_id(db, biz_id, "4101")
    cogs_acc_id  = get_account_id(db, biz_id, "5101")
    inv_acc_id   = get_account_id(db, biz_id, "1104")

    if not all([cash_acc_id, sales_acc_id]):
        return jsonify({"success": False, "error": "شجرة الحسابات غير مكتملة"}), 400

    wh_id      = inv["warehouse_id"]
    today      = datetime.now().strftime("%Y-%m-%d")
    now        = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subtotal   = float(inv["subtotal"])
    cogs_total = round(
        sum(float(l["quantity"]) * float(l["purchase_price"] or 0) for l in lines), 2
    )

    try:
        # BEGIN IMMEDIATE: يمنع Race Condition عند خصم المخزون المتزامن
        db.execute("BEGIN IMMEDIATE")

        if wh_id:
            for line in lines:
                if not line["product_id"]:
                    continue
                db.execute(
                    "INSERT OR IGNORE INTO stock (business_id,product_id,warehouse_id,quantity,avg_cost) VALUES (?,?,?,0,0)",
                    (biz_id, line["product_id"], wh_id)
                )
                db.execute(
                    "UPDATE stock SET quantity=quantity-?,last_updated=? WHERE product_id=? AND warehouse_id=?",
                    (float(line["quantity"]), now, line["product_id"], wh_id)
                )
                db.execute(
                    """INSERT INTO stock_movements
                       (business_id,product_id,warehouse_id,movement_type,
                        quantity,unit_cost,reference_type,reference_id,created_by)
                       VALUES (?,?,?,'sale',?,?,'invoice',?,?)""",
                    (biz_id, line["product_id"], wh_id,
                     -float(line["quantity"]), float(line["purchase_price"] or 0),
                     int(invoice_id), user_id)
                )

        je_num = next_entry_number(db, biz_id)
        db.execute(
            """INSERT INTO journal_entries
               (business_id,entry_number,entry_date,description,
                reference_type,reference_id,total_debit,total_credit,is_posted,created_by)
               VALUES (?,?,?,?,?,?,?,?,1,?)""",
            (biz_id, je_num, today,
             f"مبيعات مطعم — {inv['party_name']} — {inv['invoice_number']}",
             "invoice", int(invoice_id), grand_total, grand_total, user_id)
        )
        je_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        cash_label = "نقداً" if payment_method == "cash" else "بطاقة/تحويل"
        db.execute("INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
                   (je_id, cash_acc_id, cash_label, grand_total, 0, 1))
        db.execute("INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
                   (je_id, sales_acc_id, f"إيرادات مطعم — {inv['party_name']}", 0, subtotal, 2))

        if cogs_total > 0 and cogs_acc_id and inv_acc_id:
            je_cogs_num = next_entry_number(db, biz_id)
            db.execute(
                """INSERT INTO journal_entries
                   (business_id,entry_number,entry_date,description,
                    reference_type,reference_id,total_debit,total_credit,is_posted,created_by)
                   VALUES (?,?,?,?,?,?,?,?,1,?)""",
                (biz_id, je_cogs_num, today, f"تكلفة مبيعات مطعم — {inv['party_name']}",
                 "invoice", int(invoice_id), cogs_total, cogs_total, user_id)
            )
            je_cogs_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.execute("INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
                       (je_cogs_id, cogs_acc_id, "تكلفة مبيعات مطعم", cogs_total, 0, 1))
            db.execute("INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
                       (je_cogs_id, inv_acc_id, "إقفال مخزون مطعم", 0, cogs_total, 2))

        db.execute("UPDATE invoices SET status='paid',paid_amount=?,journal_entry_id=? WHERE id=?",
                   (grand_total, je_id, int(invoice_id)))
        db.commit()

        # ── ZATCA: أضف الفاتورة لقائمة الإرسال ───────────────────────────────
        try:
            enqueue_invoice(
                db, biz_id, int(invoice_id), inv["invoice_number"],
                {"total": grand_total, "tax": tax_total, "type": "table"}
            )
        except Exception:
            pass  # ZATCA failure must never block the sale

        return jsonify({
            "success":        True,
            "total":          grand_total,
            "invoice_number": inv["invoice_number"],
            "table_name":     inv["party_name"],
            "message":        f"تم إغلاق {inv['party_name']} وتوليد القيد المحاسبي ✓",
        })

    except Exception as e:
        db.rollback()
        import logging
        logging.getLogger(__name__).error(f"Table checkout error: {e}")
        return jsonify({"success": False, "error": "حدث خطأ — يرجى المحاولة مرة أخرى"}), 500


@bp.route("/api/tables/order-lines/<int:invoice_id>")
@onboarding_required
def api_tables_order_lines(invoice_id):
    biz_id = session["business_id"]
    db     = get_db()

    inv = db.execute(
        "SELECT * FROM invoices WHERE id=? AND business_id=? AND invoice_type='table'",
        (invoice_id, biz_id)
    ).fetchone()
    if not inv:
        return jsonify({"success": False, "error": "الطلب غير موجود"}), 404

    lines = db.execute(
        """SELECT il.id, il.product_id, il.description, il.quantity, il.unit_price, il.total
           FROM invoice_lines il WHERE il.invoice_id=? ORDER BY il.line_order""",
        (invoice_id,)
    ).fetchall()

    return jsonify({"success": True, "invoice": dict(inv), "lines": [dict(l) for l in lines]})


# ════════════════════════════════════════════════════════════════════════════════
# KITCHEN — شاشة المطبخ KDS
# ════════════════════════════════════════════════════════════════════════════════

@bp.route("/kitchen")
@onboarding_required
def kitchen():
    db     = get_db()
    biz_id = session["business_id"]

    orders_list = db.execute(
        """SELECT i.id, i.invoice_number, i.party_name, i.status, i.created_at, i.total
           FROM invoices i
           WHERE i.business_id=? AND i.invoice_type='table'
             AND i.status IN ('partial','issued')
           ORDER BY i.created_at ASC""",
        (biz_id,)
    ).fetchall()

    orders_with_lines = []
    for o in orders_list:
        lines = db.execute(
            "SELECT il.id, il.description, il.quantity, il.unit_price FROM invoice_lines il WHERE il.invoice_id=? ORDER BY il.line_order",
            (o["id"],)
        ).fetchall()
        orders_with_lines.append({"order": dict(o), "lines": [dict(l) for l in lines]})

    return render_template("kitchen.html", orders=orders_with_lines)


@bp.route("/api/kitchen/done", methods=["POST"])
@onboarding_required
def api_kitchen_done():
    data       = request.get_json(force=True) or {}
    biz_id     = session["business_id"]
    invoice_id = data.get("invoice_id")

    if not invoice_id:
        return jsonify({"success": False, "error": "معرّف الطلب مطلوب"}), 400

    db  = get_db()
    inv = db.execute(
        "SELECT id, party_name FROM invoices WHERE id=? AND business_id=? AND status='partial'",
        (int(invoice_id), biz_id)
    ).fetchone()
    if not inv:
        return jsonify({"success": False, "error": "الطلب غير موجود أو تم تجهيزه مسبقاً"}), 404

    db.execute("UPDATE invoices SET status='issued' WHERE id=? AND business_id=?",
               (int(invoice_id), biz_id))
    db.commit()
    return jsonify({"success": True, "message": f"✓ تم تجهيز {inv['party_name']}"})


# ─── API: معلومات المستخدم الحالي ─────────────────────────────────────────────
@bp.route("/api/me")
@login_required
def api_me():
    if not g.user or not g.business:
        return jsonify({"error": "غير مصرح"}), 401
    return jsonify({
        "user": {
            "id":        g.user["id"],
            "username":  g.user["username"],
            "full_name": g.user["full_name"],
            "role":      g.user["role_name"],
        },
        "business": {
            "id":            g.business["id"],
            "name":          g.business["name"],
            "industry_type": g.business["industry_type"],
            "currency":      g.business["currency"],
        },
        "sidebar": g.sidebar_items,
    })
