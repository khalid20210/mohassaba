"""
blueprints/supply/routes.py — المشتريات واستيراد الفواتير
"""
import secrets
from datetime import datetime
from pathlib import Path

from flask import (
    Blueprint, flash, jsonify, redirect, render_template,
    request, session, url_for
)

from modules.config import BASE_DIR, UPLOAD_FOLDER
from modules.extensions import (
    _allowed_file, _extract_text_from_image, _extract_text_from_pdf,
    _parse_invoice_lines, csrf_protect, get_db,
    get_account_id, next_entry_number
)
from modules.middleware import require_perm
from modules.ocr_limits import ocr_protected
from modules.validators import validate, V

bp = Blueprint("supply", __name__)

UPLOAD_FOLDER.mkdir(exist_ok=True)


@bp.route("/purchase-import")
@require_perm("purchases")
def purchase_import():
    return render_template("purchase_import.html")


@bp.route("/api/purchase-import/upload", methods=["POST"])
@require_perm("purchases")
@ocr_protected
def api_purchase_import_upload():
    biz_id = session["business_id"]
    db     = get_db()

    if "file" not in request.files:
        return jsonify({"success": False, "error": "لم يتم اختيار ملف"}), 400

    f = request.files["file"]
    if not f.filename or not _allowed_file(f.filename):
        return jsonify({"success": False, "error": "نوع الملف غير مدعوم (PDF, PNG, JPG)"}), 400

    ext       = f.filename.rsplit(".", 1)[1].lower()
    safe      = f"{biz_id}_{secrets.token_hex(8)}.{ext}"
    save_path = UPLOAD_FOLDER / safe
    f.save(save_path)

    text = _extract_text_from_pdf(save_path) if ext == "pdf" else _extract_text_from_image(save_path)

    products = [
        dict(r) for r in db.execute(
            "SELECT id, name, purchase_price FROM products WHERE business_id=? AND is_active=1 ORDER BY name LIMIT 2000",
            (biz_id,)
        ).fetchall()
    ]
    lines = _parse_invoice_lines(text, products)

    return jsonify({
        "success":  True,
        "file_ref": safe,
        "text_len": len(text),
        "lines":    lines,
        "raw_text": text[:800],
    })


@bp.route("/api/purchase-import/confirm", methods=["POST"])
@require_perm("purchases")
def api_purchase_import_confirm():
    data     = request.get_json(force=True) or {}
    biz_id   = session["business_id"]
    db       = get_db()

    supplier = (data.get("supplier_name") or "مورد غير محدد").strip()
    lines    = data.get("lines", [])

    if not lines:
        return jsonify({"success": False, "error": "لا توجد بنود"}), 400

    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db.execute("BEGIN IMMEDIATE")

        prefix_row = db.execute(
            "SELECT value FROM settings WHERE business_id=? AND key='invoice_prefix_purchase'",
            (biz_id,)
        ).fetchone()
        prefix = prefix_row["value"] if prefix_row else "PUR"
        cnt = db.execute(
            "SELECT COUNT(*) FROM invoices WHERE business_id=? AND invoice_type='purchase'",
            (biz_id,)
        ).fetchone()[0]
        inv_num = f"{prefix}-{cnt + 1:05d}"
        subtotal = sum(float(l.get("qty", 0)) * float(l.get("price", 0)) for l in lines)

        db.execute(
            """INSERT INTO invoices
               (business_id, invoice_type, invoice_number, party_name,
                subtotal, tax_amount, total, status, created_at)
               VALUES (?,?,?,?,?,0,?,?,?)""",
            (biz_id, "purchase", inv_num, supplier, subtotal, subtotal, "paid", now)
        )
        inv_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        wh = db.execute("SELECT id FROM warehouses WHERE business_id=? LIMIT 1", (biz_id,)).fetchone()
        wh_id = wh["id"] if wh else None

        for idx, line in enumerate(lines, 1):
            pid   = line.get("product_id")
            qty   = float(line.get("qty", 0))
            price = float(line.get("price", 0))
            if not pid or qty <= 0:
                continue
            prod = db.execute(
                "SELECT id, name FROM products WHERE id=? AND business_id=?",
                (int(pid), biz_id)
            ).fetchone()
            if not prod:
                continue
            db.execute(
                """INSERT INTO invoice_lines
                   (invoice_id, product_id, description, quantity, unit_price, total, line_order)
                   VALUES (?,?,?,?,?,?,?)""",
                (inv_id, pid, prod["name"], qty, price, qty * price, idx)
            )
            if wh_id:
                existing = db.execute(
                    "SELECT id, quantity FROM stock WHERE product_id=? AND warehouse_id=?",
                    (pid, wh_id)
                ).fetchone()
                if existing:
                    db.execute("UPDATE stock SET quantity=quantity+? WHERE id=?",
                               (qty, existing["id"]))
                else:
                    db.execute(
                        "INSERT INTO stock (business_id, product_id, warehouse_id, quantity) VALUES (?,?,?,?)",
                        (biz_id, pid, wh_id, qty)
                    )
                db.execute(
                    """INSERT INTO stock_movements
                       (business_id, product_id, warehouse_id, movement_type, quantity, reference_id, created_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (biz_id, pid, wh_id, "purchase", qty, inv_id, now)
                )
            db.execute(
                "UPDATE products SET purchase_price=? WHERE id=? AND business_id=?",
                (price, pid, biz_id)
            )

        db.commit()
        return jsonify({
            "success":       True,
            "invoice_id":    inv_id,
            "invoice_number": inv_num,
            "message":       f"✓ تم إنشاء فاتورة {inv_num} وتحديث المخزون",
        })
    except Exception as e:
        db.rollback()
        import logging
        logging.getLogger(__name__).error(f"Purchase import confirm error: {e}")
        return jsonify({"success": False, "error": "حدث خطأ أثناء تثبيت فاتورة الشراء"}), 500


@bp.route("/purchases", methods=["GET", "POST"])
@require_perm("purchases")
def purchases():
    db     = get_db()
    biz_id = session["business_id"]

    if request.method == "GET":
        page     = max(1, int(request.args.get("page", 1)))
        per_page = 20
        offset   = (page - 1) * per_page

        invoices_list = db.execute(
            """SELECT i.id, i.invoice_number, i.invoice_date, i.party_name,
                      i.subtotal, i.tax_amount, i.total, i.status,
                      i.notes, i.created_at
               FROM invoices i
               WHERE i.business_id=? AND i.invoice_type='purchase'
               ORDER BY i.id DESC LIMIT ? OFFSET ?""",
            (biz_id, per_page, offset)
        ).fetchall()

        total = db.execute(
            "SELECT COUNT(*) FROM invoices WHERE business_id=? AND invoice_type='purchase'",
            (biz_id,)
        ).fetchone()[0]

        products = db.execute(
            """SELECT id, name, barcode, purchase_price, category_name
               FROM products WHERE business_id=? AND is_active=1
               ORDER BY name LIMIT 500""",
            (biz_id,)
        ).fetchall()

        total_pages = max(1, (total + per_page - 1) // per_page)
        return render_template(
            "purchases.html",
            invoices=invoices_list,
            products=products,
            page=page,
            total_pages=total_pages,
            total=total,
        )

    # POST: حفظ فاتورة شراء
    guard = csrf_protect()
    if guard:
        return guard

    supplier_name  = request.form.get("supplier_name", "").strip()
    invoice_date   = request.form.get("invoice_date",  "").strip()
    tax_pct        = float(request.form.get("tax_pct", 0) or 0)
    notes          = request.form.get("notes",         "").strip()
    payment_method = request.form.get("payment_method", "cash")

    product_ids = request.form.getlist("product_id[]")
    quantities  = request.form.getlist("quantity[]")
    unit_costs  = request.form.getlist("unit_cost[]")

    if not invoice_date:
        flash("تاريخ الفاتورة مطلوب", "error")
        return redirect(url_for("supply.purchases"))

    if not product_ids:
        flash("يجب إضافة منتج واحد على الأقل", "error")
        return redirect(url_for("supply.purchases"))

    # رفع ملف الفاتورة
    uploaded_file  = request.files.get("invoice_file")
    saved_filename = None
    if uploaded_file and uploaded_file.filename:
        import re as _re
        safe      = _re.sub(r"[^\w.\-]", "_", uploaded_file.filename)
        upload_dir = BASE_DIR / "static" / "uploads"
        upload_dir.mkdir(exist_ok=True)
        saved_filename = f"{biz_id}_{secrets.token_hex(6)}_{safe}"
        allowed = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
        ext     = Path(safe).suffix.lower()
        if ext not in allowed:
            flash("نوع الملف غير مدعوم — يُسمح بـ PDF والصور فقط", "error")
            return redirect(url_for("supply.purchases"))
        uploaded_file.save(str(upload_dir / saved_filename))

    user_id  = session["user_id"]
    subtotal = tax_total = 0.0
    validated = []

    for pid, qty_s, cost_s in zip(product_ids, quantities, unit_costs):
        try:
            qty  = float(qty_s)
            cost = float(cost_s)
        except ValueError:
            continue
        if qty <= 0 or cost < 0:
            continue
        product = db.execute(
            "SELECT * FROM products WHERE id=? AND business_id=?", (int(pid), biz_id)
        ).fetchone()
        if not product:
            continue
        line_sub  = round(qty * cost, 4)
        line_tax  = round(line_sub * tax_pct / 100, 4)
        subtotal  += line_sub
        tax_total += line_tax
        validated.append({
            "product_id": int(pid), "name": product["name"],
            "quantity": qty, "unit_cost": cost,
            "tax_amount": line_tax, "total": round(line_sub + line_tax, 4),
        })

    if not validated:
        flash("البنود غير صالحة — تحقق من الكميات والأسعار", "error")
        return redirect(url_for("supply.purchases"))

    subtotal    = round(subtotal,    2)
    tax_total   = round(tax_total,   2)
    grand_total = round(subtotal + tax_total, 2)

    if payment_method == "cash":
        credit_acc_id = get_account_id(db, biz_id, "1101")
    elif payment_method == "bank":
        credit_acc_id = get_account_id(db, biz_id, "1102")
    else:
        credit_acc_id = get_account_id(db, biz_id, "2101")

    inv_acc_id   = get_account_id(db, biz_id, "1104")
    tax_input_id = get_account_id(db, biz_id, "2102")

    if not credit_acc_id or not inv_acc_id:
        flash("شجرة الحسابات غير مكتملة — راجع الإعدادات", "error")
        return redirect(url_for("supply.purchases"))

    try:
        today = datetime.now().strftime("%Y-%m-%d")
        now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # BEGIN IMMEDIATE: يمنع Race Condition عند توليد أرقام الفواتير المتزامنة
        db.execute("BEGIN IMMEDIATE")

        prefix_row = db.execute(
            "SELECT value FROM settings WHERE business_id=? AND key='invoice_prefix_purchase'",
            (biz_id,)
        ).fetchone()
        prefix = prefix_row["value"] if prefix_row else "PUR"
        cnt = db.execute(
            "SELECT COUNT(*) FROM invoices WHERE business_id=? AND invoice_type='purchase'",
            (biz_id,)
        ).fetchone()[0]
        pur_number = f"{prefix}-{cnt + 1:05d}"

        wh = db.execute(
            "SELECT id FROM warehouses WHERE business_id=? AND is_default=1 LIMIT 1", (biz_id,)
        ).fetchone()
        warehouse_id = wh["id"] if wh else None

        db.execute(
            """INSERT INTO invoices
               (business_id, invoice_number, invoice_type, invoice_date,
                party_name, subtotal, tax_amount, total, paid_amount,
                status, warehouse_id, notes, created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (biz_id, pur_number, "purchase", invoice_date,
             supplier_name or None, subtotal, tax_total, grand_total,
             grand_total if payment_method != "credit" else 0,
             "paid" if payment_method != "credit" else "partial",
             warehouse_id, notes or None, user_id)
        )
        inv_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        for idx, item in enumerate(validated):
            db.execute(
                """INSERT INTO invoice_lines
                   (invoice_id, product_id, description, quantity, unit_price,
                    tax_rate, tax_amount, total, line_order)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (inv_id, item["product_id"], item["name"], item["quantity"],
                 item["unit_cost"], tax_pct, item["tax_amount"], item["total"], idx + 1)
            )
            if warehouse_id:
                db.execute(
                    """INSERT OR IGNORE INTO stock
                       (business_id, product_id, warehouse_id, quantity, avg_cost)
                       VALUES (?,?,?,0,0)""",
                    (biz_id, item["product_id"], warehouse_id)
                )
                st = db.execute(
                    "SELECT quantity, avg_cost FROM stock WHERE product_id=? AND warehouse_id=?",
                    (item["product_id"], warehouse_id)
                ).fetchone()
                old_qty  = float(st["quantity"])
                old_cost = float(st["avg_cost"])
                new_qty  = old_qty + item["quantity"]
                new_cost = ((old_qty * old_cost) + (item["quantity"] * item["unit_cost"])) / new_qty if new_qty else item["unit_cost"]
                db.execute(
                    "UPDATE stock SET quantity=?, avg_cost=?, last_updated=? WHERE product_id=? AND warehouse_id=?",
                    (new_qty, round(new_cost, 4), now, item["product_id"], warehouse_id)
                )
                db.execute(
                    """INSERT INTO stock_movements
                       (business_id, product_id, warehouse_id, movement_type,
                        quantity, unit_cost, reference_type, reference_id, created_by)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (biz_id, item["product_id"], warehouse_id, "purchase",
                     item["quantity"], item["unit_cost"], "invoice", inv_id, user_id)
                )

        je_num = next_entry_number(db, biz_id)
        db.execute(
            """INSERT INTO journal_entries
               (business_id, entry_number, entry_date, description,
                reference_type, reference_id, total_debit, total_credit,
                is_posted, created_by)
               VALUES (?,?,?,?,?,?,?,?,1,?)""",
            (biz_id, je_num, invoice_date,
             f"قيد مشتريات — فاتورة {pur_number}" + (f" | {supplier_name}" if supplier_name else ""),
             "invoice", inv_id, grand_total, grand_total, user_id)
        )
        je_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        db.execute(
            "INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
            (je_id, inv_acc_id, "إضافة للمخزون", subtotal, 0, 1)
        )
        order = 2
        if tax_total > 0 and tax_input_id:
            db.execute(
                "INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
                (je_id, tax_input_id, "ضريبة المدخلات", tax_total, 0, order)
            )
            order += 1

        credit_label = {"cash": "نقداً من الصندوق", "bank": "تحويل بنكي",
                        "credit": f"بالآجل — {supplier_name or 'مورد'}"}.get(payment_method, "نقداً من الصندوق")
        db.execute(
            "INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
            (je_id, credit_acc_id, credit_label, 0, grand_total, order)
        )

        db.execute("UPDATE invoices SET journal_entry_id=? WHERE id=?", (je_id, inv_id))
        db.commit()
        flash(f"✓ تم حفظ فاتورة الشراء {pur_number} وتوليد القيد المحاسبي", "success")
        return redirect(url_for("supply.purchases"))

    except Exception as e:
        db.rollback()
        import logging
        logging.getLogger(__name__).error(f"Purchase save error: {e}")
        flash("حدث خطأ أثناء الحفظ — يرجى المحاولة مرة أخرى", "error")
        return redirect(url_for("supply.purchases"))


# ═══════════════════════════════════════════════════════════════════════════════
# Smart Excel Importer — استيراد منتجات من ملف Excel
# ═══════════════════════════════════════════════════════════════════════════════

# أعمدة Excel المقبولة مع alias عربي وإنجليزي
_EXCEL_COL_MAP = {
    # عربي
    "اسم المنتج":      "name",
    "الاسم":           "name",
    "المنتج":          "name",
    "الباركود":        "barcode",
    "باركود":          "barcode",
    "سعر البيع":       "sale_price",
    "سعر الشراء":      "purchase_price",
    "التصنيف":         "category_name",
    "الفئة":           "category_name",
    "الكمية":          "initial_qty",
    "الحد الأدنى":     "min_stock",
    "وصف":             "description",
    "الوصف":           "description",
    "وحدة القياس":     "unit",
    "الوحدة":          "unit",
    # English aliases
    "name":            "name",
    "barcode":         "barcode",
    "sku":             "barcode",
    "sale_price":      "sale_price",
    "selling_price":   "sale_price",
    "price":           "sale_price",
    "purchase_price":  "purchase_price",
    "cost":            "purchase_price",
    "category":        "category_name",
    "category_name":   "category_name",
    "qty":             "initial_qty",
    "quantity":        "initial_qty",
    "min_stock":       "min_stock",
    "reorder_point":   "min_stock",
    "description":     "description",
    "unit":            "unit",
}

_PRODUCT_SCHEMA = {
    "name":           [V.required, V.str_max(200), V.safe_text],
    "barcode":        [V.optional, V.str_max(100), V.safe_text],
    "sale_price":     [V.required, V.positive_number],
    "purchase_price": [V.optional, V.positive_number],
    "category_name":  [V.optional, V.str_max(100), V.safe_text],
    "initial_qty":    [V.optional, V.positive_number],
    "min_stock":      [V.optional, V.positive_number],
    "description":    [V.optional, V.str_max(500), V.safe_text],
    "unit":           [V.optional, V.str_max(50), V.safe_text],
}

_EXCEL_FOLDER = BASE_DIR / "uploads" / "excel"
_EXCEL_FOLDER.mkdir(parents=True, exist_ok=True)


@bp.route("/excel-import")
@require_perm("warehouse")
def excel_import():
    """صفحة استيراد منتجات من Excel"""
    return render_template("excel_import.html")


@bp.route("/api/excel-import/preview", methods=["POST"])
@require_perm("warehouse")
def api_excel_import_preview():
    """
    يستقبل ملف Excel، يُحلّله، يُشغّل validators على كل صف،
    ويُعيد preview مع قائمة الصفوف الصالحة والمرفوضة.
    """
    biz_id = session["business_id"]

    if "file" not in request.files:
        return jsonify({"success": False, "error": "لم يتم رفع أي ملف"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"success": False, "error": "اسم الملف فارغ"}), 400

    ext = f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
    if ext not in ("xlsx", "xls", "csv"):
        return jsonify({"success": False, "error": "يُقبل فقط: xlsx, xls, csv"}), 400

    safe_name = f"{biz_id}_{secrets.token_hex(8)}.{ext}"
    save_path = _EXCEL_FOLDER / safe_name
    f.save(save_path)

    try:
        import openpyxl
        rows_raw = []

        if ext == "csv":
            import csv, io
            content = save_path.read_bytes()
            # حاول UTF-8 أولاً ثم arabic encodings
            text = None
            for enc in ("utf-8-sig", "utf-8", "windows-1256", "cp1256"):
                try:
                    text = content.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            if text is None:
                # fallback: latin-1 يُعيد كل بايت بلا أخطاء
                text = content.decode("latin-1", errors="replace")
            reader = csv.DictReader(io.StringIO(text))
            headers = [h.strip() for h in (reader.fieldnames or [])]
            for row in reader:
                rows_raw.append({h.strip(): (v.strip() if v else "") for h, v in row.items()})
        else:
            wb = openpyxl.load_workbook(save_path, read_only=True, data_only=True)
            ws = wb.active
            all_rows = list(ws.iter_rows(values_only=True))
            if not all_rows:
                return jsonify({"success": False, "error": "الملف فارغ"}), 400
            headers = [str(h).strip() if h is not None else "" for h in all_rows[0]]
            for row in all_rows[1:]:
                if all(c is None or str(c).strip() == "" for c in row):
                    continue  # تجاهل الصفوف الفارغة
                rows_raw.append({
                    headers[i]: (str(row[i]).strip() if row[i] is not None else "")
                    for i in range(len(headers))
                })
            wb.close()

        # حذف الملف المؤقت بعد القراءة
        save_path.unlink(missing_ok=True)

    except Exception as exc:
        save_path.unlink(missing_ok=True)
        return jsonify({"success": False, "error": f"تعذّر قراءة الملف: {str(exc)[:100]}"}), 400

    if not rows_raw:
        return jsonify({"success": False, "error": "لم يُعثر على بيانات في الملف"}), 400

    if len(rows_raw) > 5000:
        return jsonify({"success": False, "error": "يتجاوز الحد الأقصى (5000 صف لكل عملية)"}), 400

    # ── تحويل أسماء الأعمدة إلى مفاتيح نظام ─────────────────────────────────
    def _normalize_row(raw: dict) -> dict:
        out = {}
        for col_name, value in raw.items():
            key = _EXCEL_COL_MAP.get(col_name) or _EXCEL_COL_MAP.get(col_name.lower())
            if key and value not in ("", None):
                out[key] = value
        return out

    # ── تشغيل validators على كل صف ───────────────────────────────────────────
    valid_rows   = []
    invalid_rows = []

    for i, raw in enumerate(rows_raw, 1):
        normalized = _normalize_row(raw)
        if not normalized.get("name") and not normalized.get("sale_price"):
            continue  # صف فارغ فعلياً

        # تحويل الأرقام من العربية إذا وُجدت
        for num_field in ("sale_price", "purchase_price", "initial_qty", "min_stock"):
            if num_field in normalized:
                val = str(normalized[num_field]).replace(",", ".").replace("٫", ".")
                # تحويل الأرقام العربية
                val = val.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
                normalized[num_field] = val

        cleaned, errors = validate(normalized, _PRODUCT_SCHEMA)

        if errors:
            invalid_rows.append({
                "row":    i,
                "data":   raw,
                "errors": errors,
            })
        else:
            valid_rows.append({
                "row":            i,
                "name":           cleaned.get("name", ""),
                "barcode":        cleaned.get("barcode", ""),
                "sale_price":     float(cleaned.get("sale_price", 0)),
                "purchase_price": float(cleaned.get("purchase_price", 0) or 0),
                "category_name":  cleaned.get("category_name", ""),
                "initial_qty":    float(cleaned.get("initial_qty", 0) or 0),
                "min_stock":      float(cleaned.get("min_stock", 0) or 0),
                "description":    cleaned.get("description", ""),
                "unit":           cleaned.get("unit", ""),
            })

    return jsonify({
        "success":       True,
        "total_rows":    len(rows_raw),
        "valid_count":   len(valid_rows),
        "invalid_count": len(invalid_rows),
        "valid_rows":    valid_rows[:200],   # أرسل أول 200 للمعاينة
        "invalid_rows":  invalid_rows[:50],  # أرسل أول 50 خطأ فقط
        "detected_cols": list(set(
            _EXCEL_COL_MAP.get(h) or _EXCEL_COL_MAP.get(h.lower(), "?")
            for h in (headers if ext != "csv" else list(rows_raw[0].keys()))
        )),
    })


@bp.route("/api/excel-import/confirm", methods=["POST"])
@require_perm("warehouse")
def api_excel_import_confirm():
    """
    يستقبل الصفوف الصالحة المُعتمدة من المستخدم ويُضيفها للـ DB.
    يتجنب التكرار (barcode يُحدَّث بدلاً من الإضافة).
    """
    data   = request.get_json(force=True) or {}
    biz_id = session["business_id"]
    rows   = data.get("rows", [])

    if not rows:
        return jsonify({"success": False, "error": "لا توجد صفوف للاستيراد"}), 400

    if len(rows) > 5000:
        return jsonify({"success": False, "error": "يتجاوز الحد الأقصى 5000 صف"}), 400

    db  = get_db()
    wh  = db.execute(
        "SELECT id FROM warehouses WHERE business_id=? AND is_default=1 LIMIT 1",
        (biz_id,)
    ).fetchone()
    wh_id = wh["id"] if wh else None

    now        = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inserted   = 0
    updated    = 0
    errors_out = []

    try:
        db.execute("BEGIN IMMEDIATE")

        for i, row in enumerate(rows):
            # إعادة التحقق من كل صف عند الحفظ الفعلي
            cleaned, errs = validate(row, _PRODUCT_SCHEMA)
            if errs:
                errors_out.append({"row": i + 1, "errors": errs})
                continue

            name          = cleaned["name"]
            barcode       = cleaned.get("barcode") or None
            sale_price    = float(cleaned["sale_price"])
            purchase_price= float(cleaned.get("purchase_price") or 0)
            category_name = cleaned.get("category_name") or None
            initial_qty   = float(cleaned.get("initial_qty") or 0)
            min_stock_val = float(cleaned.get("min_stock") or 0)
            description   = cleaned.get("description") or None
            unit          = cleaned.get("unit") or None

            # هل المنتج موجود؟ (بالباركود أولاً ثم الاسم)
            existing = None
            if barcode:
                existing = db.execute(
                    "SELECT id FROM products WHERE business_id=? AND barcode=?",
                    (biz_id, barcode)
                ).fetchone()
            if not existing:
                existing = db.execute(
                    "SELECT id FROM products WHERE business_id=? AND name=?",
                    (biz_id, name)
                ).fetchone()

            if existing:
                # تحديث المنتج الموجود
                db.execute(
                    """UPDATE products
                       SET sale_price=?, purchase_price=?, min_stock=?,
                           category_name=?, description=?, unit=?,
                           updated_at=?
                       WHERE id=? AND business_id=?""",
                    (sale_price, purchase_price, min_stock_val,
                     category_name, description, unit,
                     now, existing["id"], biz_id)
                )
                prod_id = existing["id"]
                updated += 1
            else:
                # إضافة منتج جديد
                db.execute(
                    """INSERT INTO products
                       (business_id, name, barcode, sale_price, purchase_price,
                        min_stock, category_name, description, unit, is_active, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,1,?)""",
                    (biz_id, name, barcode, sale_price, purchase_price,
                     min_stock_val, category_name, description, unit, now)
                )
                prod_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                inserted += 1

            # تحديث الكمية الافتتاحية إذا وُجدت ومستودع متاح
            if initial_qty > 0 and wh_id:
                db.execute(
                    "INSERT OR IGNORE INTO stock (business_id,product_id,warehouse_id,quantity,avg_cost) VALUES (?,?,?,0,0)",
                    (biz_id, prod_id, wh_id)
                )
                db.execute(
                    "UPDATE stock SET quantity=quantity+?,avg_cost=?,last_updated=? WHERE product_id=? AND warehouse_id=?",
                    (initial_qty, purchase_price, now, prod_id, wh_id)
                )
                db.execute(
                    """INSERT INTO stock_movements
                       (business_id,product_id,warehouse_id,movement_type,quantity,unit_cost,reference_type,created_by)
                       VALUES (?,?,?,'initial_import',?,?,'excel_import',?)""",
                    (biz_id, prod_id, wh_id, initial_qty, purchase_price,
                     session.get("user_id"))
                )

        db.commit()

    except Exception as exc:
        db.rollback()
        import logging
        logging.getLogger(__name__).error(f"Excel import error: {exc}")
        return jsonify({"success": False, "error": "حدث خطأ أثناء الاستيراد — يرجى المحاولة مرة أخرى"}), 500

    return jsonify({
        "success":     True,
        "inserted":    inserted,
        "updated":     updated,
        "error_count": len(errors_out),
        "errors":      errors_out[:20],
        "message":     (
            f"✓ تم استيراد {inserted} منتج جديد"
            + (f" وتحديث {updated}" if updated else "")
            + (f" — {len(errors_out)} صف تجاهلناه" if errors_out else "")
        ),
    })
