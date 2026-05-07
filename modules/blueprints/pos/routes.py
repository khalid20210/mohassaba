"""
blueprints/pos/routes.py — نقطة البيع (POS)
"""
from datetime import datetime

from flask import (
    Blueprint, g, jsonify, redirect, render_template,
    request, session, url_for
)

from modules.extensions import (
    InsufficientStockError, assert_stock_available, get_account_id, get_db,
    next_entry_number, next_invoice_number
)
from modules.middleware import require_perm
from modules.terminology import get_terms
from modules.validators import validate, V, SCHEMA_POS_CHECKOUT
from modules.zatca_queue import enqueue_invoice

bp = Blueprint("pos", __name__)

# ── POS UI config per pos_mode ────────────────────────────────────────────────
_POS_MODE_CONFIG = {
    "standard": {
        "show_images":        False,
        "show_tables":        False,
        "show_expiry":        False,
        "show_serial":        False,
        "show_variant":       False,
        "search_by_barcode":  True,
        "quick_add_barcode":  True,
        "kitchen_screen":     False,
        "primary_search":     "barcode",
    },
    "restaurant": {
        "show_images":        True,
        "show_tables":        True,
        "show_expiry":        False,
        "show_serial":        False,
        "show_variant":       False,
        "search_by_barcode":  False,
        "quick_add_barcode":  False,
        "kitchen_screen":     True,
        "primary_search":     "name",
    },
    "pharmacy": {
        "show_images":        False,
        "show_tables":        False,
        "show_expiry":        True,   # تاريخ الصلاحية ← أولوية الصيدلية
        "show_serial":        True,   # رقم التشغيلة
        "show_variant":       False,
        "search_by_barcode":  True,
        "quick_add_barcode":  True,
        "kitchen_screen":     False,
        "primary_search":     "barcode",
    },
    "fashion": {
        "show_images":        True,
        "show_tables":        False,
        "show_expiry":        False,
        "show_serial":        False,
        "show_variant":       True,   # مقاس / لون
        "search_by_barcode":  True,
        "quick_add_barcode":  False,
        "kitchen_screen":     False,
        "primary_search":     "name",
    },
    "wholesale": {
        "show_images":        False,
        "show_tables":        False,
        "show_expiry":        False,
        "show_serial":        False,
        "show_variant":       False,
        "search_by_barcode":  True,
        "quick_add_barcode":  True,
        "kitchen_screen":     False,
        "primary_search":     "barcode",
        "show_qty_tiers":     True,   # تسعير الكميات
    },
    "workshop": {
        "show_images":        False,
        "show_tables":        False,
        "show_expiry":        False,
        "show_serial":        True,   # رقم اللوحة
        "show_variant":       False,
        "search_by_barcode":  False,
        "quick_add_barcode":  False,
        "kitchen_screen":     False,
        "primary_search":     "name",
        "show_work_order":    True,
    },
    "construction": {
        "show_images":        False,
        "show_tables":        False,
        "show_expiry":        False,
        "show_serial":        False,
        "show_variant":       False,
        "search_by_barcode":  False,
        "quick_add_barcode":  False,
        "kitchen_screen":     False,
        "primary_search":     "name",
        "show_project":       True,
    },
    "rental": {
        "show_images":        True,
        "show_tables":        False,
        "show_expiry":        False,
        "show_serial":        True,   # رقم اللوحة
        "show_variant":       False,
        "search_by_barcode":  False,
        "quick_add_barcode":  False,
        "kitchen_screen":     False,
        "primary_search":     "name",
        "show_date_range":    True,
    },
    "medical": {
        "show_images":        False,
        "show_tables":        False,
        "show_expiry":        False,
        "show_serial":        False,
        "show_variant":       False,
        "search_by_barcode":  False,
        "quick_add_barcode":  False,
        "kitchen_screen":     False,
        "primary_search":     "name",
        "show_patient_id":    True,
    },
}


@bp.route("/pos")
@require_perm("pos")
def pos():
    db             = get_db()
    biz_id         = session["business_id"]
    user_branch_id = g.user["branch_id"] if g.user else None

    warehouses = db.execute(
        "SELECT id, name FROM warehouses WHERE business_id=? AND is_active=1 ORDER BY is_default DESC",
        (biz_id,)
    ).fetchall()

    if user_branch_id:
        warehouses = [w for w in warehouses if w["id"] == user_branch_id]

    categories = db.execute(
        "SELECT DISTINCT category_name FROM products WHERE business_id=? AND is_active=1 AND category_name IS NOT NULL ORDER BY category_name",
        (biz_id,)
    ).fetchall()

    # ── تحديد واجهة POS حسب قطاع المنشأة ─────────────────────────────────────
    biz           = g.business
    industry_type = biz["industry_type"] if biz else "retail_other"
    terms         = get_terms(industry_type)
    pos_mode      = terms.get("pos_mode", "standard")
    ui_config     = {**_POS_MODE_CONFIG.get(pos_mode, _POS_MODE_CONFIG["standard"]), **{
        "pos_mode":        pos_mode,
        "industry_icon":   terms.get("industry_icon", "🏪"),
        "industry_label":  terms.get("industry_label", "نشاط تجاري"),
        "pos_search_hint": terms.get("pos_search_hint", "ابحث بالاسم أو الباركود..."),
        "pos_quick_label": terms.get("pos_quick_label", "بيع سريع"),
        "T_product":       terms.get("product", "منتج"),
        "T_customer":      terms.get("customer", "عميل"),
        "T_seller":        terms.get("seller", "بائع"),
        "T_invoice":       terms.get("invoice", "فاتورة"),
        "T_order":         terms.get("order", "طلب"),
        "T_new_sale":      terms.get("new_sale", "بيع جديد"),
        "T_expiry":        terms.get("expiry", "تاريخ الانتهاء"),
        "T_serial":        terms.get("serial", "الرقم التسلسلي"),
        "T_variant":       terms.get("variant", "نوع / مقاس"),
        "T_work_order":    terms.get("work_order", "أمر عمل"),
        "T_unit":          terms.get("unit", "وحدة"),
    }}

    return render_template(
        "pos.html",
        warehouses=[dict(w) for w in warehouses],
        categories=[r["category_name"] for r in categories],
        user_branch_id=user_branch_id,
        ui_config=ui_config,
    )


@bp.route("/api/pos/config")
@require_perm("pos")
def api_pos_config():
    """
    يُعيد كامل إعدادات واجهة POS بصيغة JSON.
    يستخدمه الـ JavaScript لتكييف الواجهة ديناميكياً.
    """
    biz           = g.business
    industry_type = biz["industry_type"] if biz else "retail_other"
    terms         = get_terms(industry_type)
    pos_mode      = terms.get("pos_mode", "standard")
    config        = {**_POS_MODE_CONFIG.get(pos_mode, _POS_MODE_CONFIG["standard"])}
    config.update({
        "pos_mode":        pos_mode,
        "industry_type":   industry_type,
        "industry_icon":   terms.get("industry_icon", "🏪"),
        "industry_label":  terms.get("industry_label", "نشاط تجاري"),
        "pos_search_hint": terms.get("pos_search_hint", "ابحث بالاسم أو الباركود..."),
        "pos_quick_label": terms.get("pos_quick_label", "بيع سريع"),
        "labels": {
            "product":    terms.get("product", "منتج"),
            "customer":   terms.get("customer", "عميل"),
            "seller":     terms.get("seller", "بائع"),
            "invoice":    terms.get("invoice", "فاتورة"),
            "order":      terms.get("order", "طلب"),
            "new_sale":   terms.get("new_sale", "بيع جديد"),
            "expiry":     terms.get("expiry", "تاريخ الانتهاء"),
            "serial":     terms.get("serial", "الرقم التسلسلي"),
            "variant":    terms.get("variant", "نوع / مقاس"),
            "work_order": terms.get("work_order", "أمر عمل"),
            "unit":       terms.get("unit", "وحدة"),
            "quantity":   terms.get("quantity", "الكمية"),
            "price":      terms.get("price", "السعر"),
            "total":      terms.get("total", "الإجمالي"),
        },
    })
    return jsonify({"success": True, "config": config})


@bp.route("/api/pos/search")
@require_perm("pos")
def api_pos_search():
    biz_id         = session["business_id"]
    db             = get_db()
    user_branch_id = g.user["branch_id"] if g.user else None

    q            = request.args.get("q", "").strip()
    category     = request.args.get("category", "").strip()
    warehouse_id = request.args.get("warehouse_id", "")

    # الكاشير لا يمكنه اختيار مستودع آخر
    if user_branch_id:
        warehouse_id = str(user_branch_id)

    where  = "WHERE p.business_id=? AND p.is_active=1 AND p.is_pos=1"
    params = [biz_id]

    if q:
        where  += " AND (p.name LIKE ? OR p.barcode LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if category:
        where  += " AND p.category_name=?"
        params.append(category)

    stock_join = ""
    if warehouse_id:
        try:
            wh_id = int(warehouse_id)
            stock_join = f"LEFT JOIN stock s ON s.product_id=p.id AND s.warehouse_id={wh_id}"
        except ValueError:
            stock_join = ""
    else:
        stock_join = "LEFT JOIN stock s ON s.product_id=p.id"

    products = db.execute(
        f"""SELECT p.id, p.name, p.barcode, p.sale_price, p.category_name,
                   0 AS tax_rate, COALESCE(s.quantity, 0) AS stock_qty
            FROM products p {stock_join}
            {where}
            ORDER BY p.name LIMIT 100""",
        params
    ).fetchall()

    return jsonify({"products": [dict(p) for p in products]})


@bp.route("/api/pos/checkout", methods=["POST"])
@require_perm("pos")
def api_pos_checkout():
    """
    إتمام عملية البيع:
    1. حفظ الفاتورة وبنودها
    2. خصم الكميات من المخزون + تسجيل حركة
    3. قيد مبيعات: د/الصندوق — ك/إيرادات + ك/ضريبة
    4. قيد تكلفة: د/COGS — ك/مخزون
    """
    data    = request.get_json(force=True) or {}
    biz_id  = session["business_id"]
    user_id = session["user_id"]
    db      = get_db()

    # ── Validate top-level request ─────────────────────────────────────────
    top, errs = validate(data, SCHEMA_POS_CHECKOUT)
    if errs:
        return jsonify({"success": False, "errors": errs}), 400

    items          = top["items"]
    payment_method = top["payment_method"]

    cash_acc_id  = get_account_id(db, biz_id, "1102" if payment_method == "bank" else "1101")
    sales_acc_id = get_account_id(db, biz_id, "4101")
    tax_acc_id   = get_account_id(db, biz_id, "2102")
    cogs_acc_id  = get_account_id(db, biz_id, "5101")
    inv_acc_id   = get_account_id(db, biz_id, "1104")

    if not all([cash_acc_id, sales_acc_id, cogs_acc_id, inv_acc_id]):
        return jsonify({"success": False, "error": "شجرة الحسابات غير مكتملة"}), 400

    user_branch_id = g.user["branch_id"] if g.user else None
    requested_wh   = data.get("warehouse_id")

    if user_branch_id:
        wh = db.execute(
            "SELECT id FROM warehouses WHERE id=? AND business_id=? AND is_active=1",
            (user_branch_id, biz_id)
        ).fetchone()
    elif requested_wh:
        try:
            requested_wh = int(requested_wh)
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "المستودع المحدد غير صالح"}), 400
        wh = db.execute(
            "SELECT id FROM warehouses WHERE id=? AND business_id=? AND is_active=1",
            (requested_wh, biz_id)
        ).fetchone()
    else:
        wh = db.execute(
            "SELECT id FROM warehouses WHERE business_id=? AND is_default=1 LIMIT 1", (biz_id,)
        ).fetchone()
    if not wh:
        wh = db.execute("SELECT id FROM warehouses WHERE business_id=? LIMIT 1", (biz_id,)).fetchone()
    warehouse_id = wh["id"] if wh else None

    today = datetime.now().strftime("%Y-%m-%d")
    now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subtotal = tax_total = cogs_total = 0.0
    validated = []

    for item in items:
        try:
            product_id = int(item["product_id"])
            qty        = float(item["quantity"])
            unit_price = float(item["unit_price"])
            tax_rate   = float(item.get("tax_rate", 0))
        except (KeyError, ValueError, TypeError):
            return jsonify({"success": False, "error": "بيانات البنود غير صالحة"}), 400

        if qty <= 0 or unit_price < 0:
            return jsonify({"success": False, "error": "الكمية والسعر يجب أن يكونا موجبين"}), 400

        product = db.execute(
            "SELECT * FROM products WHERE id=? AND business_id=? AND is_active=1",
            (product_id, biz_id)
        ).fetchone()
        if not product:
            return jsonify({"success": False, "error": f"المنتج ID={product_id} غير موجود"}), 400

        line_sub  = round(qty * unit_price, 4)
        line_tax  = round(line_sub * tax_rate / 100, 4)
        line_tot  = round(line_sub + line_tax, 4)
        line_cost = round(qty * float(product["purchase_price"] or 0), 4)

        subtotal   += line_sub
        tax_total  += line_tax
        cogs_total += line_cost

        validated.append({
            "product_id":     product_id,
            "description":    product["name"],
            "quantity":       qty,
            "unit_price":     unit_price,
            "tax_rate":       tax_rate,
            "tax_amount":     line_tax,
            "total":          line_tot,
            "purchase_price": float(product["purchase_price"] or 0),
        })

    subtotal    = round(subtotal,    2)
    tax_total   = round(tax_total,   2)
    grand_total = round(subtotal + tax_total, 2)
    cogs_total  = round(cogs_total,  2)

    try:
        # BEGIN IMMEDIATE: يمنع Race Condition عند خصم المخزون المتزامن
        db.execute("BEGIN IMMEDIATE")

        inv_number  = next_invoice_number(db, biz_id)
        je_sale_num = next_entry_number(db, biz_id)

        db.execute(
            """INSERT INTO invoices
               (business_id, invoice_number, invoice_type, invoice_date,
                subtotal, tax_amount, total, paid_amount, status, warehouse_id, created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (biz_id, inv_number, "sale", today,
             subtotal, tax_total, grand_total, grand_total, "paid", warehouse_id, user_id)
        )
        invoice_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        for idx, item in enumerate(validated):
            assert_stock_available(
                db, biz_id, item["product_id"], warehouse_id,
                item["quantity"], item["description"]
            )
            db.execute(
                """INSERT INTO invoice_lines
                   (invoice_id, product_id, description, quantity, unit_price,
                    tax_rate, tax_amount, total, line_order)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (invoice_id, item["product_id"], item["description"],
                 item["quantity"], item["unit_price"],
                 item["tax_rate"], item["tax_amount"], item["total"], idx + 1)
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
                     -item["quantity"], item["purchase_price"], "invoice", invoice_id, user_id)
                )

        db.execute(
            """INSERT INTO journal_entries
               (business_id,entry_number,entry_date,description,
                reference_type,reference_id,total_debit,total_credit,is_posted,created_by)
               VALUES (?,?,?,?,?,?,?,?,1,?)""",
            (biz_id, je_sale_num, today,
             f"قيد مبيعات نقدية — فاتورة {inv_number}",
             "invoice", invoice_id, grand_total, grand_total, user_id)
        )
        je_sale_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        cash_label = "نقدية مقبوضة" if payment_method == "cash" else "تحويل بنكي"
        db.execute(
            "INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
            (je_sale_id, cash_acc_id, cash_label, grand_total, 0, 1)
        )
        db.execute(
            "INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
            (je_sale_id, sales_acc_id, f"إيرادات مبيعات — {inv_number}", 0, subtotal, 2)
        )
        if tax_total > 0 and tax_acc_id:
            db.execute(
                "INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
                (je_sale_id, tax_acc_id, "ضريبة القيمة المضافة", 0, tax_total, 3)
            )

        db.execute("UPDATE invoices SET journal_entry_id=? WHERE id=?", (je_sale_id, invoice_id))

        if cogs_total > 0:
            je_cogs_num = next_entry_number(db, biz_id)
            db.execute(
                """INSERT INTO journal_entries
                   (business_id,entry_number,entry_date,description,
                    reference_type,reference_id,total_debit,total_credit,is_posted,created_by)
                   VALUES (?,?,?,?,?,?,?,?,1,?)""",
                (biz_id, je_cogs_num, today,
                 f"قيد تكلفة البضاعة المباعة — فاتورة {inv_number}",
                 "invoice", invoice_id, cogs_total, cogs_total, user_id)
            )
            je_cogs_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.execute(
                "INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
                (je_cogs_id, cogs_acc_id, "تكلفة البضاعة المباعة", cogs_total, 0, 1)
            )
            db.execute(
                "INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
                (je_cogs_id, inv_acc_id, "إقفال مخزون مباع", 0, cogs_total, 2)
            )

        db.commit()

        # ── ZATCA: أضف الفاتورة لقائمة الإرسال ─────────────────────────────
        try:
            enqueue_invoice(
                db, biz_id, invoice_id, inv_number,
                {"total": grand_total, "tax": tax_total, "items_count": len(validated)}
            )
        except Exception:
            pass  # ZATCA failure must never block the sale

        return jsonify({
            "success":        True,
            "invoice_number": inv_number,
            "invoice_id":     invoice_id,
            "total":          grand_total,
            "message":        f"تمت عملية البيع بنجاح — فاتورة {inv_number}",
        })

    except InsufficientStockError as e:
        db.rollback()
        return jsonify({
            "success": False,
            "error": f"المخزون غير كافٍ للصنف: {e.product_name}",
            "available_qty": e.available_qty,
            "requested_qty": e.requested_qty,
        }), 409
    except Exception as e:
        db.rollback()
        import logging
        logging.getLogger(__name__).error(f"POS checkout error: {e}")
        return jsonify({"success": False, "error": "حدث خطأ أثناء حفظ الفاتورة"}), 500
