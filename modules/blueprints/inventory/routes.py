"""
modules/blueprints/inventory/routes.py — إدارة المخزون الشاملة
Inventory Management System: Products, Stock Tracking, Alerts, Barcode Integration
"""

import json
import sqlite3
import csv
import io
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, jsonify, g, redirect, flash, Response
from functools import wraps

bp = Blueprint("inventory", __name__, url_prefix="/inventory")


def _norm_col(col: str) -> str:
    return (col or "").strip().lower().replace("_", "").replace("-", "").replace(" ", "")


def _first_val(row: dict, aliases: list[str]) -> str:
    normalized = {_norm_col(k): (v or "") for k, v in row.items()}
    for alias in aliases:
        val = normalized.get(_norm_col(alias), "")
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _to_float(value) -> float:
    raw = str(value or "").strip().replace(",", "")
    if not raw:
        return 0.0
    try:
        return float(raw)
    except Exception:
        return 0.0


def _read_products_file(file_storage):
    filename = (file_storage.filename or "").lower()
    payload = file_storage.read()

    if filename.endswith(".csv") or filename.endswith(".txt"):
        text = payload.decode("utf-8-sig", errors="replace")
        first = text.splitlines()[0] if text.splitlines() else ""
        delimiter = ";" if first.count(";") > first.count(",") else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        return [dict(r or {}) for r in reader]

    if filename.endswith(".xlsx"):
        try:
            import openpyxl
        except Exception as exc:
            raise ValueError("صيغة XLSX تحتاج مكتبة openpyxl") from exc

        wb = openpyxl.load_workbook(io.BytesIO(payload), data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []

        headers = [str(h or "").strip() for h in rows[0]]
        out = []
        for values in rows[1:]:
            item = {}
            for i, h in enumerate(headers):
                item[h] = "" if i >= len(values) or values[i] is None else str(values[i]).strip()
            out.append(item)
        return out

    raise ValueError("صيغة غير مدعومة. استخدم CSV أو XLSX")


def _normalize_uploaded_product(row: dict):
    name = _first_val(row, ["الاسم", "اسم المنتج", "name", "product name"])
    if not name:
        return None

    barcode = _first_val(row, ["الباركود", "barcode", "ean", "sku"]).replace(" ", "")
    sell_price = _to_float(_first_val(row, ["السعر", "سعر البيع", "price", "sale_price"]))
    cost_price = _to_float(_first_val(row, ["سعر الشراء", "cost", "purchase_price"]))
    qty = _to_float(_first_val(row, ["الكمية", "quantity", "qty"]))
    description = _first_val(row, ["الوصف", "description", "desc"])

    return {
        "name": name,
        "barcode": barcode,
        "sell_price": sell_price,
        "cost_price": cost_price,
        "qty": qty,
        "description": description,
    }


def _normalize_movement_type(raw_type: str):
    """Map UI movement types to DB-supported values."""
    mt = (raw_type or "").strip().lower()
    mapping = {
        "purchase": "purchase",
        "adjustment": "adjustment",
        "return": "return",
        "return_in": "return",
        "damage": "damage",
        "broken": "damage",
        "waste": "damage",
        "transfer": "transfer",
        "transfer_out": "transfer",
        "sale": "sale",
    }
    return mapping.get(mt)


def _upsert_low_stock_alert(db, business_id: int, product_id: int, sku: str, current_qty: float, min_qty: float):
    """Create or resolve low stock alert based on current quantity."""
    alert = db.execute(
        """SELECT id FROM stock_alerts
           WHERE business_id=? AND product_id=? AND alert_type='low_stock' AND is_resolved=0
           ORDER BY id DESC LIMIT 1""",
        (business_id, product_id)
    ).fetchone()

    if current_qty <= min_qty:
        msg = f"المخزون منخفض للصنف {sku or ('#' + str(product_id))}: المتاح {current_qty:.2f} / الحد {min_qty:.2f}"
        if alert:
            db.execute("UPDATE stock_alerts SET alert_message=? WHERE id=?", (msg, alert["id"]))
        else:
            db.execute(
                """INSERT INTO stock_alerts (business_id, product_id, alert_type, alert_message)
                   VALUES (?, ?, 'low_stock', ?)""",
                (business_id, product_id, msg)
            )
    elif alert:
        db.execute(
            "UPDATE stock_alerts SET is_resolved=1, resolved_at=datetime('now') WHERE id=?",
            (alert["id"],)
        )


def require_perm(*perms):
    """Decorator: التحقق من الصلاحيات"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not g.user or not g.business:
                return redirect("/login")
            
            user_perms = g.user.get("permissions", {})
            if isinstance(user_perms, str):
                try:
                    user_perms = json.loads(user_perms or "{}")
                except Exception:
                    user_perms = {}
            # إذا كان المستخدم مالك (all=true) يُسمح له بكل شيء
            if user_perms.get("all"):
                return f(*args, **kwargs)
            
            # وإلا، تحقق من الصلاحيات المطلوبة
            for perm in perms:
                if perm not in user_perms:
                    flash("غير مصرح لك بهذا الإجراء", "error")
                    return redirect("/dashboard")
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def log_activity(module, action, entity_id=None, changes=None):
    """تسجيل النشاط في audit_logs"""
    from modules.extensions import get_db
    
    if not g.user or not g.business:
        return
    
    db = get_db()
    db.execute("""
        INSERT INTO audit_logs (business_id, user_id, action, entity_type, entity_id, new_value, ip_address, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
    """, (
        g.business["id"],
        g.user.get("id"),
        action,
        module,
        entity_id,
        json.dumps(changes) if changes else None,
        request.remote_addr
    ))
    db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: INVENTORY DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/")
@require_perm("warehouse")
def dashboard():
    """لوحة تحكم المخزون — ملخص شامل"""
    from modules.extensions import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    # إحصائيات عامة
    stats = db.execute("""
        SELECT 
            COUNT(*) as total_products,
            COALESCE(SUM(pi.current_qty), 0) as total_units,
            COALESCE(SUM(pi.current_qty * COALESCE(pi.unit_cost, p.purchase_price, 0)), 0) as total_value
        FROM product_inventory pi
        LEFT JOIN products p ON pi.product_id = p.id
        WHERE pi.business_id = ?
    """, (business_id,)).fetchone()
    
    # الأصناف منخفضة المخزون
    low_stock = db.execute("""
        SELECT pi.id, COALESCE(p.name, pi.sku) AS name,
               pi.current_qty, pi.min_qty,
               COALESCE(pi.unit_price, p.sale_price, 0) AS unit_price
        FROM product_inventory pi
        LEFT JOIN products p ON pi.product_id = p.id
        WHERE pi.business_id = ? AND pi.current_qty <= pi.min_qty
        LIMIT 10
    """, (business_id,)).fetchall()
    
    # الأصناف التي تقارب انتهاء الصلاحية
    expiry_soon = db.execute("""
        SELECT id, sku, expiry_date, current_qty
        FROM product_inventory
        WHERE business_id = ? AND expiry_date IS NOT NULL
        AND expiry_date BETWEEN datetime('now') AND datetime('now', '+30 days')
        ORDER BY expiry_date ASC
        LIMIT 5
    """, (business_id,)).fetchall()
    
    # أعلى الأصناف مبيعاً (في آخر 30 يوم)
    top_sellers = db.execute("""
        SELECT pi.id, pi.sku, SUM(im.quantity) as sold_qty
        FROM product_inventory pi
        LEFT JOIN inventory_movements im ON pi.id = im.product_id
        WHERE pi.business_id = ? AND im.movement_type = 'sale'
        AND im.created_at >= datetime('now', '-30 days')
        GROUP BY pi.id
        ORDER BY sold_qty DESC
        LIMIT 5
    """, (business_id,)).fetchall()
    
    # التنبيهات النشطة
    alerts = db.execute("""
        SELECT id, alert_type, alert_message, created_at
        FROM stock_alerts
        WHERE business_id = ? AND is_resolved = 0
        ORDER BY created_at DESC
        LIMIT 5
    """, (business_id,)).fetchall()
    
    return render_template("inventory/dashboard.html", **{
        "stats": stats,
        "low_stock": low_stock,
        "expiry_soon": expiry_soon,
        "top_sellers": top_sellers,
        "alerts": alerts,
    })


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: PRODUCT INVENTORY MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/products")
@require_perm("warehouse")
def list_products():
    """قائمة جميع الأصناف مع فلاتر"""
    from modules.extensions import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    # فلاتر
    search = request.args.get("search", "") or request.args.get("q", "")
    category = request.args.get("category", "")
    status = request.args.get("status", "")  # 'all', 'low_stock', 'overstock', 'expiring'
    page = int(request.args.get("page", 1))
    per_page = 20
    
    # بناء الـ Query — ربط product_inventory بجدول products للحصول على الاسم والسعر
    base = """
        SELECT pi.*,
               COALESCE(p.name, pi.sku) AS name,
               COALESCE(p.category_name, '') AS category_name,
               COALESCE(pi.unit_price, p.sale_price, 0) AS sell_price,
               COALESCE(pi.unit_cost, p.purchase_price, 0) AS cost_price,
               COALESCE(pi.barcode, p.barcode) AS barcode
        FROM product_inventory pi
        LEFT JOIN products p ON pi.product_id = p.id
        WHERE pi.business_id = ?
    """
    params = [business_id]
    
    if search:
        base += " AND (p.name LIKE ? OR pi.sku LIKE ? OR pi.barcode LIKE ? OR p.barcode LIKE ?)"
        search_term = f"%{search}%"
        params.extend([search_term, search_term, search_term, search_term])
    
    if status == "low_stock":
        base += " AND pi.current_qty <= pi.min_qty"
    elif status == "overstock":
        base += " AND pi.current_qty >= pi.max_qty"
    elif status == "expiring":
        base += " AND pi.expiry_date IS NOT NULL AND pi.expiry_date <= datetime('now', '+30 days')"
    
    query = base + " ORDER BY COALESCE(p.name, pi.sku) ASC LIMIT ? OFFSET ?"
    params.extend([per_page, (page - 1) * per_page])
    
    products = db.execute(query, params).fetchall()
    total = db.execute(
        "SELECT COUNT(*) FROM product_inventory WHERE business_id = ?",
        (business_id,)
    ).fetchone()[0]
    
    return render_template("inventory/products_list.html", **{
        "products": products,
        "total": total,
        "page": page,
        "per_page": per_page,
        "search": search,
        "status": status,
    })


@bp.route("/products/export.csv")
@require_perm("warehouse")
def export_products_csv():
    """تصدير قائمة المنتجات الحالية بصيغة CSV"""
    from modules.extensions import get_db

    db = get_db()
    business_id = g.business["id"]
    rows = db.execute(
        """SELECT
               COALESCE(p.name, pi.sku) AS name,
               COALESCE(pi.barcode, p.barcode, '') AS barcode,
               COALESCE(pi.unit_price, p.sale_price, 0) AS price,
               COALESCE(pi.current_qty, 0) AS quantity,
               COALESCE(pi.notes, p.description, '') AS description
           FROM product_inventory pi
           LEFT JOIN products p ON p.id = pi.product_id
           WHERE pi.business_id = ?
           ORDER BY COALESCE(p.name, pi.sku) ASC""",
        (business_id,),
    ).fetchall()

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["الاسم", "الباركود", "السعر", "الكمية", "الوصف"])
    for r in rows:
        writer.writerow([
            r["name"] or "",
            r["barcode"] or "",
            r["price"] or 0,
            r["quantity"] or 0,
            r["description"] or "",
        ])

    filename = f"products_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    response = Response(out.getvalue(), mimetype="text/csv; charset=utf-8")
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response


@bp.route("/products/import", methods=["POST"])
@require_perm("warehouse")
def import_products_file():
    """استيراد ودمج المنتجات من CSV/XLSX"""
    from modules.extensions import get_db, csrf_protect

    guard = csrf_protect()
    if guard:
        return guard

    db = get_db()
    business_id = g.business["id"]
    uploaded = request.files.get("products_file")

    if not uploaded or not (uploaded.filename or "").strip():
        flash("اختر ملف المنتجات أولاً", "error")
        return redirect("/inventory/products")

    try:
        raw_rows = _read_products_file(uploaded)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect("/inventory/products")
    except Exception:
        flash("تعذر قراءة الملف. تأكد من التنسيق", "error")
        return redirect("/inventory/products")

    inserted = 0
    updated = 0
    skipped = 0
    seen = set()

    for raw in raw_rows:
        item = _normalize_uploaded_product(raw or {})
        if not item:
            skipped += 1
            continue

        key = f"bc:{item['barcode']}" if item["barcode"] else f"nm:{item['name'].strip().lower()}"
        if key in seen:
            skipped += 1
            continue
        seen.add(key)

        existing_product = None
        if item["barcode"]:
            existing_product = db.execute(
                "SELECT id FROM products WHERE business_id=? AND barcode=? LIMIT 1",
                (business_id, item["barcode"]),
            ).fetchone()

        if not existing_product:
            existing_product = db.execute(
                "SELECT id FROM products WHERE business_id=? AND LOWER(name)=LOWER(?) LIMIT 1",
                (business_id, item["name"]),
            ).fetchone()

        if existing_product:
            product_id = existing_product["id"]
            db.execute(
                """UPDATE products
                   SET name=?,
                       barcode=COALESCE(NULLIF(?,''), barcode),
                       description=?,
                       sale_price=?,
                       purchase_price=?,
                       updated_at=datetime('now')
                   WHERE id=? AND business_id=?""",
                (
                    item["name"],
                    item["barcode"],
                    item["description"],
                    item["sell_price"],
                    item["cost_price"],
                    product_id,
                    business_id,
                ),
            )
            updated += 1
        else:
            db.execute(
                """INSERT INTO products (
                       business_id, name, barcode, description,
                       sale_price, purchase_price, can_sell, can_purchase,
                       track_stock, is_pos, product_type, is_active
                   ) VALUES (?, ?, ?, ?, ?, ?, 1, 1, 1, 1, 'product', 1)""",
                (
                    business_id,
                    item["name"],
                    item["barcode"] or None,
                    item["description"],
                    item["sell_price"],
                    item["cost_price"],
                ),
            )
            product_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
            inserted += 1

        inv = db.execute(
            "SELECT id, current_qty FROM product_inventory WHERE business_id=? AND product_id=? LIMIT 1",
            (business_id, product_id),
        ).fetchone()

        if inv:
            new_qty = float(inv["current_qty"] or 0) + float(item["qty"] or 0)
            db.execute(
                """UPDATE product_inventory
                   SET sku=COALESCE(sku, ?),
                       barcode=COALESCE(NULLIF(?,''), barcode),
                       unit_price=?,
                       unit_cost=?,
                       notes=COALESCE(NULLIF(?,''), notes),
                       current_qty=?,
                       updated_at=datetime('now')
                   WHERE id=? AND business_id=?""",
                (
                    f"PRD-{product_id:05d}",
                    item["barcode"],
                    item["sell_price"],
                    item["cost_price"],
                    item["description"],
                    new_qty,
                    inv["id"],
                    business_id,
                ),
            )
        else:
            db.execute(
                """INSERT INTO product_inventory (
                       business_id, product_id, sku, barcode, current_qty,
                       min_qty, max_qty, unit_cost, unit_price, notes,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, 10, 1000, ?, ?, ?, datetime('now'), datetime('now'))""",
                (
                    business_id,
                    product_id,
                    f"PRD-{product_id:05d}",
                    item["barcode"] or None,
                    item["qty"],
                    item["cost_price"],
                    item["sell_price"],
                    item["description"],
                ),
            )

    db.commit()
    log_activity(
        "inventory",
        "products_import",
        changes={
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "filename": uploaded.filename,
        },
    )

    flash(f"تم الاستيراد والدمج: إضافة {inserted} | تحديث {updated} | تخطي {skipped}", "success")
    return redirect("/inventory/products")



@bp.route("/products/<int:product_id>")
@require_perm("warehouse")
def view_product(product_id):
    """عرض تفاصيل الصنف"""
    from modules.extensions import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    product = db.execute("""
        SELECT * FROM product_inventory
        WHERE id = ? AND business_id = ?
    """, (product_id, business_id)).fetchone()
    
    if not product:
        flash("الصنف غير موجود", "error")
        return redirect("/inventory/products")
    
    # حركات هذا الصنف (آخر 20)
    movements = db.execute("""
        SELECT * FROM inventory_movements
        WHERE product_id = ?
        ORDER BY created_at DESC
        LIMIT 20
    """, (product_id,)).fetchall()
    
    # سجل المسح (للأصناف بها باركود)
    scans = db.execute("""
        SELECT * FROM barcode_scans
        WHERE product_id = ?
        ORDER BY scanned_at DESC
        LIMIT 10
    """, (product_id,)).fetchall()
    
    return render_template("inventory/product_detail.html", **{
        "product": product,
        "movements": movements,
        "scans": scans,
    })


@bp.route("/products/new", methods=["GET", "POST"])
@require_perm("warehouse")
def add_product():
    """إضافة صنف جديد — نموذج شامل مع فئات وضريبة وتسلسل تلقائي"""
    from modules.extensions import get_db

    db = get_db()
    business_id = g.business["id"]

    if request.method == "POST":
        data = request.form

        # ── توليد الرقم التسلسلي (SKU) تلقائياً إن لم يُدخَل
        sku = (data.get("sku") or "").strip()
        if not sku:
            count_row = db.execute(
                "SELECT COUNT(*)+1 AS n FROM products WHERE business_id=?",
                (business_id,)
            ).fetchone()
            seq = count_row["n"] if count_row else 1
            sku = f"PRD-{seq:05d}"

        name = (data.get("name") or "").strip()
        if not name:
            flash("اسم المنتج مطلوب", "error")
            categories = db.execute(
                "SELECT id, name FROM product_categories ORDER BY name"
            ).fetchall()
            return render_template("inventory/product_form.html", categories=categories, sku_preview=sku)

        # أسعار الشراء مع/بدون ضريبة
        cost_raw   = float(data.get("cost_price", 0) or 0)
        cost_tax   = data.get("cost_has_tax") == "1"
        VAT = 0.15
        cost_price = cost_raw / (1 + VAT) if cost_tax else cost_raw

        # أسعار البيع مع/بدون ضريبة
        sell_raw   = float(data.get("sell_price", 0) or 0)
        sell_tax   = data.get("sell_has_tax") == "1"
        sell_price = sell_raw / (1 + VAT) if sell_tax else sell_raw

        category_id   = data.get("category_id") or None
        category_name = ""
        if category_id:
            cat = db.execute(
                "SELECT name FROM product_categories WHERE id=?", (category_id,)
            ).fetchone()
            category_name = cat["name"] if cat else ""

        # بيانات ZATCA/الجمارك من النموذج
        tax_category = (data.get("tax_category") or "S").strip() or "S"
        hs_code = (data.get("hs_code") or "").strip()
        origin_country = (data.get("origin_country") or "").strip()
        tax_exemption_reason = (data.get("tax_exemption_reason") or "").strip()

        notes_raw = (data.get("notes", "") or "").strip()
        extra_meta = {
            "tax_category": tax_category,
            "hs_code": hs_code,
            "origin_country": origin_country,
            "tax_exemption_reason": tax_exemption_reason,
        }

        # إدراج في جدول products أولاً
        cur = db.execute("""
            INSERT INTO products (
                business_id, name, name_en, serial_number, barcode,
                description, category_id, category_name,
                purchase_price, sale_price,
                can_purchase, can_sell, track_stock, is_pos, is_active,
                notes, supplier_id, expiry_date, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,1,1,1,1,1,?,?,?,datetime('now'),datetime('now'))
        """, (
            business_id,
            name,
            data.get("name_en", "").strip(),
            sku,
            data.get("barcode", "").strip() or None,
            data.get("description", "").strip(),
            category_id,
            category_name,
            cost_price,
            sell_price,
            notes_raw,
            data.get("supplier_id") or None,
            data.get("expiry_date") or None,
        ))
        product_id = cur.lastrowid

        # حفظ حقول ZATCA بشكل مرن: في أعمدة products إن كانت موجودة، وإلا داخل notes كـ JSON.
        product_columns = {
            c["name"]
            for c in db.execute("PRAGMA table_info(products)").fetchall()
        }
        update_sets = []
        update_vals = []

        for col_name, col_val in (
            ("tax_category", tax_category),
            ("hs_code", hs_code),
            ("origin_country", origin_country),
            ("tax_exemption_reason", tax_exemption_reason),
        ):
            if col_name in product_columns:
                update_sets.append(f"{col_name} = ?")
                update_vals.append(col_val)

        if update_sets:
            update_vals.extend([product_id, business_id])
            db.execute(
                f"UPDATE products SET {', '.join(update_sets)}, updated_at=datetime('now') "
                "WHERE id=? AND business_id=?",
                tuple(update_vals),
            )
        else:
            # fallback متوافق للخلف إذا لم تكن الأعمدة موجودة بعد
            meta_json = json.dumps(extra_meta, ensure_ascii=False)
            merged_notes = notes_raw + ("\n\n" if notes_raw else "") + f"[PRODUCT_TAX_META]{meta_json}"
            db.execute(
                "UPDATE products SET notes=?, updated_at=datetime('now') WHERE id=? AND business_id=?",
                (merged_notes, product_id, business_id),
            )

        # إدراج في product_inventory
        init_qty = float(data.get("initial_qty", 0) or 0)
        min_qty  = float(data.get("min_qty", 5) or 5)
        max_qty  = float(data.get("max_qty", 1000) or 1000)
        location = data.get("location", "").strip()

        db.execute("""
            INSERT INTO product_inventory (
                business_id, product_id, sku, barcode,
                current_qty, min_qty, max_qty,
                unit_cost, unit_price,
                location, notes,
                created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))
        """, (
            business_id, product_id, sku,
            data.get("barcode", "").strip() or None,
            init_qty, min_qty, max_qty,
            cost_price, sell_price,
            location or None,
            notes_raw,
        ))
        db.commit()

        if init_qty <= min_qty:
            _upsert_low_stock_alert(db, business_id, product_id, sku, init_qty, min_qty)

        log_activity("inventory", "add_product", product_id, {"name": name, "sku": sku})
        flash(f"✅ تم إضافة المنتج «{name}» بنجاح — الرقم: {sku}", "success")
        return redirect("/inventory/products")

    # GET: تحميل الفئات وتوليد SKU مبدئي للمعاينة
    categories = db.execute(
        "SELECT id, name FROM product_categories ORDER BY name"
    ).fetchall()
    count_row = db.execute(
        "SELECT COUNT(*)+1 AS n FROM products WHERE business_id=?",
        (business_id,)
    ).fetchone()
    seq = count_row["n"] if count_row else 1
    sku_preview = f"PRD-{seq:05d}"

    return render_template("inventory/product_form.html",
                           categories=categories,
                           sku_preview=sku_preview)


@bp.route("/products/<int:product_id>/edit", methods=["POST"])
@require_perm("warehouse")
def edit_product(product_id):
    """تعديل بيانات الصنف"""
    from modules.extensions import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    data = request.form
    
    db.execute("""
        UPDATE product_inventory SET
            min_qty = ?, max_qty = ?, unit_price = ?, location = ?,
            supplier_id = ?, notes = ?, updated_at = datetime('now')
        WHERE id = ? AND business_id = ?
    """, (
        float(data.get("min_qty", 10)),
        float(data.get("max_qty", 1000)),
        float(data.get("unit_price", 0)),
        data.get("location"),
        data.get("supplier_id") or None,
        data.get("notes"),
        product_id,
        business_id,
    ))
    db.commit()
    
    log_activity("inventory", "edit_product", product_id)
    flash("تم تحديث بيانات الصنف", "success")
    return redirect(f"/inventory/products/{product_id}")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: STOCK MOVEMENTS
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/movements")
@require_perm("warehouse")
def list_movements():
    """سجل حركات المخزون"""
    from modules.extensions import get_db

    db = get_db()
    business_id = g.business["id"]

    page = int(request.args.get("page", 1))
    per_page = 30

    movement_type = request.args.get("type", "").strip().lower()
    date_from = request.args.get("from", "").strip()
    date_to = request.args.get("to", "").strip()
    product_id = request.args.get("product_id", "").strip()

    where = ["im.business_id = ?"]
    params = [business_id]

    normalized_type = _normalize_movement_type(movement_type) if movement_type else None
    if movement_type and normalized_type:
        where.append("im.movement_type = ?")
        params.append(normalized_type)

    if date_from:
        where.append("date(im.created_at) >= date(?)")
        params.append(date_from)
    if date_to:
        where.append("date(im.created_at) <= date(?)")
        params.append(date_to)
    if product_id.isdigit():
        where.append("im.product_id = ?")
        params.append(int(product_id))

    where_sql = " AND ".join(where)

    movements = db.execute(
        f"""SELECT im.*, pi.sku, pi.sku AS product_name, im.reason AS notes
            FROM inventory_movements im
            LEFT JOIN product_inventory pi ON im.product_id = pi.id
            WHERE {where_sql}
            ORDER BY im.created_at DESC
            LIMIT ? OFFSET ?""",
        (*params, per_page, (page - 1) * per_page)
    ).fetchall()

    total = db.execute(
        f"SELECT COUNT(*) FROM inventory_movements im WHERE {where_sql}",
        params,
    ).fetchone()[0]

    return render_template("inventory/movements_list.html", **{
        "movements": movements,
        "total": total,
        "page": page,
        "per_page": per_page,
    })


@bp.route("/movements/add", methods=["POST"])
@require_perm("warehouse")
def add_movement():
    """تسجيل حركة مخزون يدوية"""
    from modules.extensions import get_db

    db = get_db()
    business_id = g.business["id"]

    data = request.form
    product_id = int(data.get("product_id"))
    quantity = float(data.get("quantity"))
    raw_type = data.get("movement_type")
    movement_type = _normalize_movement_type(raw_type)

    if not movement_type:
        return jsonify({"error": "نوع الحركة غير مدعوم"}), 400
    if quantity <= 0:
        return jsonify({"error": "الكمية يجب أن تكون أكبر من صفر"}), 400

    # تحديث الكمية
    product = db.execute(
        "SELECT current_qty, sku, min_qty FROM product_inventory WHERE id = ? AND business_id = ?",
        (product_id, business_id)
    ).fetchone()

    if not product:
        return jsonify({"error": "الصنف غير موجود"}), 404

    incoming_types = {"adjustment", "purchase", "return"}
    if movement_type in incoming_types:
        new_qty = float(product["current_qty"] or 0) + quantity
    else:
        new_qty = float(product["current_qty"] or 0) - quantity

    if new_qty < 0:
        return jsonify({"error": "الكمية المطلوبة تتجاوز المخزون المتاح"}), 400

    reason = (data.get("reason") or data.get("notes") or "").strip()
    if raw_type in ("broken", "waste"):
        reason = f"{raw_type}: {reason}" if reason else raw_type

    # تسجيل الحركة
    db.execute("""
        INSERT INTO inventory_movements (
            business_id, product_id, movement_type, quantity, reason,
            performed_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
    """, (
        business_id,
        product_id,
        movement_type,
        quantity,
        reason,
        g.user.get("id"),
    ))

    # تحديث الكمية
    db.execute(
        "UPDATE product_inventory SET current_qty = ?, updated_at = datetime('now') WHERE id = ?",
        (new_qty, product_id)
    )

    _upsert_low_stock_alert(
        db,
        business_id,
        product_id,
        product["sku"],
        float(new_qty),
        float(product["min_qty"] or 0),
    )

    db.commit()

    log_activity("inventory", f"movement_{movement_type}", product_id, {"quantity": quantity, "raw_type": raw_type})
    return jsonify({"success": True, "new_qty": new_qty, "movement_type": movement_type})


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4: STOCK ALERTS
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/alerts")
@require_perm("warehouse")
def view_alerts():
    """عرض جميع التنبيهات"""
    from modules.extensions import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    show_resolved = request.args.get("show_resolved", "0") == "1"
    
    query = "SELECT * FROM stock_alerts WHERE business_id = ?"
    params = [business_id]
    
    if not show_resolved:
        query += " AND is_resolved = 0"
    
    query += " ORDER BY created_at DESC"
    
    alerts = db.execute(query, params).fetchall()
    
    return render_template("inventory/alerts.html", **{
        "alerts": alerts,
        "show_resolved": show_resolved,
    })


@bp.route("/alerts/<int:alert_id>/resolve", methods=["POST"])
@require_perm("warehouse")
def resolve_alert(alert_id):
    """تصنيف التنبيه كمحلول"""
    from modules.extensions import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    db.execute("""
        UPDATE stock_alerts
        SET is_resolved = 1, resolved_at = datetime('now')
        WHERE id = ? AND business_id = ?
    """, (alert_id, business_id))
    db.commit()
    
    log_activity("inventory", "resolve_alert", alert_id)
    return jsonify({"success": True})


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5: STOCK COUNTING & PHYSICAL INVENTORY
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/stock-count")
@require_perm("warehouse")
def stock_count():
    """صفحة الجرد الدوري (عد المخزون الفعلي)"""
    from modules.extensions import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    products = db.execute("""
        SELECT id, sku, current_qty, unit_price
        FROM product_inventory
        WHERE business_id = ?
        ORDER BY sku ASC
    """, (business_id,)).fetchall()
    
    return render_template("inventory/stock_count.html", **{
        "products": products,
    })


@bp.route("/stock-count/submit", methods=["POST"])
@require_perm("warehouse")
def submit_stock_count():
    """حفظ نتائج الجرد"""
    from modules.extensions import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    data = request.get_json()
    counted_items = data.get("items", [])
    
    total_difference = 0
    
    for item in counted_items:
        product_id = item["product_id"]
        physical_qty = float(item["physical_qty"])
        
        product = db.execute(
            "SELECT current_qty FROM product_inventory WHERE id = ? AND business_id = ?",
            (product_id, business_id)
        ).fetchone()
        
        if product:
            system_qty = product["current_qty"]
            difference = physical_qty - system_qty
            total_difference += abs(difference)
            
            if difference != 0:
                # تسجيل التفاوت
                db.execute("""
                    INSERT INTO inventory_movements (
                        business_id, product_id, movement_type, quantity,
                        reason, performed_by, created_at
                    ) VALUES (?, ?, 'adjustment', ?, 'stock_count_difference', ?, datetime('now'))
                """, (business_id, product_id, difference, g.user.get("id")))
                
                # تحديث الكمية
                db.execute(
                    "UPDATE product_inventory SET current_qty = ?, last_stock_check = datetime('now') WHERE id = ?",
                    (physical_qty, product_id)
                )
    
    db.commit()
    
    log_activity("inventory", "stock_count_completed", None, {
        "total_items": len(counted_items),
        "total_difference": total_difference
    })
    
    return jsonify({"success": True, "total_difference": total_difference})


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6: REPORTS
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/reports")
@require_perm("warehouse")
def reports():
    """تقارير المخزون"""
    from modules.extensions import get_db
    
    db = get_db()
    business_id = g.business["id"]
    
    report_type = request.args.get("type", "inventory_value")
    
    if report_type == "inventory_value":
        # قيمة المخزون الإجمالية
        data = db.execute("""
            SELECT 
                SUM(current_qty * unit_cost) as total_cost,
                SUM(current_qty * unit_price) as total_retail_value,
                COUNT(*) as total_items
            FROM product_inventory
            WHERE business_id = ?
        """, (business_id,)).fetchone()
        
        return render_template("inventory/report_value.html", data=data)
    
    elif report_type == "aging":
        # الأصناف البطيئة (لم تُبع منذ 90 يوم)
        aging_products = db.execute("""
            SELECT pi.sku, pi.current_qty, MAX(im.created_at) as last_movement
            FROM product_inventory pi
            LEFT JOIN inventory_movements im ON pi.id = im.product_id AND im.movement_type = 'sale'
            WHERE pi.business_id = ?
            GROUP BY pi.id
            HAVING last_movement IS NULL OR last_movement < datetime('now', '-90 days')
            ORDER BY last_movement DESC
        """, (business_id,)).fetchall()
        
        return render_template("inventory/report_aging.html", products=aging_products)
    
    return render_template("inventory/reports.html")


# API endpoints
@bp.route("/api/stock/<int:product_id>")
def api_stock(product_id):
    """API: الحصول على الكمية المتاحة"""
    from modules.extensions import get_db

    db = get_db()
    business_id = g.business["id"]

    product = db.execute(
        "SELECT current_qty, sku FROM product_inventory WHERE id = ? AND business_id = ?",
        (product_id, business_id)
    ).fetchone()

    if product:
        return jsonify({
            "available_qty": product["current_qty"],
            "sku": product["sku"]
        })

    return jsonify({"error": "Product not found"}), 404


@bp.route("/api/reorder-suggestions")
@require_perm("warehouse")
def api_reorder_suggestions():
    """API: اقتراحات إعادة الطلب حسب الحد الأدنى."""
    from modules.extensions import get_db

    db = get_db()
    business_id = g.business["id"]

    rows = db.execute(
        """SELECT id, sku, barcode, current_qty, min_qty, max_qty
           FROM product_inventory
           WHERE business_id=? AND min_qty > 0 AND current_qty <= min_qty
           ORDER BY (min_qty - current_qty) DESC, sku ASC
           LIMIT 150""",
        (business_id,)
    ).fetchall()

    suggestions = []
    for r in rows:
        r = dict(r)
        max_qty = float(r.get("max_qty") or 0)
        min_qty = float(r.get("min_qty") or 0)
        current = float(r.get("current_qty") or 0)
        target = max(max_qty, min_qty)
        r["reorder_qty"] = max(round(target - current, 3), 0)
        suggestions.append(r)

    return jsonify({"success": True, "count": len(suggestions), "items": suggestions})


@bp.route("/api/quick-adjust", methods=["POST"])
@require_perm("warehouse")
def api_quick_adjust():
    """API: تسوية سريعة للتجزئة (هالك/مكسور/تعديل)."""
    from modules.extensions import get_db

    db = get_db()
    business_id = g.business["id"]
    payload = request.get_json(silent=True) or {}

    try:
        product_id = int(payload.get("product_id"))
        quantity = float(payload.get("quantity"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "بيانات غير صالحة"}), 400

    raw_type = payload.get("movement_type")
    movement_type = _normalize_movement_type(raw_type)
    if movement_type not in {"adjustment", "damage", "purchase", "return", "sale", "transfer"}:
        return jsonify({"success": False, "error": "نوع الحركة غير مدعوم"}), 400
    if quantity <= 0:
        return jsonify({"success": False, "error": "الكمية يجب أن تكون أكبر من صفر"}), 400

    product = db.execute(
        "SELECT id, sku, current_qty, min_qty FROM product_inventory WHERE id=? AND business_id=?",
        (product_id, business_id)
    ).fetchone()
    if not product:
        return jsonify({"success": False, "error": "الصنف غير موجود"}), 404

    incoming_types = {"adjustment", "purchase", "return"}
    current = float(product["current_qty"] or 0)
    new_qty = current + quantity if movement_type in incoming_types else current - quantity
    if new_qty < 0:
        return jsonify({"success": False, "error": "لا يمكن أن يصبح المخزون سالباً"}), 400

    reason = str(payload.get("reason") or "").strip()
    if raw_type in ("broken", "waste"):
        reason = f"{raw_type}: {reason}" if reason else raw_type

    db.execute(
        """INSERT INTO inventory_movements
           (business_id, product_id, movement_type, quantity, reason, performed_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
        (business_id, product_id, movement_type, quantity, reason, g.user.get("id"))
    )
    db.execute(
        "UPDATE product_inventory SET current_qty=?, updated_at=datetime('now') WHERE id=? AND business_id=?",
        (new_qty, product_id, business_id)
    )

    _upsert_low_stock_alert(
        db,
        business_id,
        product_id,
        product["sku"],
        float(new_qty),
        float(product["min_qty"] or 0),
    )
    db.commit()

    log_activity("inventory", f"quick_adjust_{movement_type}", product_id, {
        "quantity": quantity,
        "raw_type": raw_type,
        "reason": reason,
    })
    return jsonify({"success": True, "new_qty": new_qty, "movement_type": movement_type})


@bp.route("/reports/damage-waste")
@require_perm("warehouse")
def report_damage_waste():
    """تقرير الهالك والمكسور حسب الفترة الزمنية."""
    from modules.extensions import get_db

    db = get_db()
    business_id = g.business["id"]

    date_from = request.args.get("from", "").strip()
    date_to = request.args.get("to", "").strip()

    where = ["im.business_id = ? AND im.movement_type = 'damage'"]
    params = [business_id]

    if date_from:
        where.append("DATE(im.created_at) >= DATE(?)")
        params.append(date_from)
    if date_to:
        where.append("DATE(im.created_at) <= DATE(?)")
        params.append(date_to)

    where_sql = " AND ".join(where)

    # ملخص التقرير
    summary = db.execute(
        f"""SELECT 
            COUNT(*) AS count,
            SUM(quantity) AS total_qty
        FROM inventory_movements im
        WHERE {where_sql}""",
        params,
    ).fetchone()

    # تفاصيل الهالك حسب السبب
    by_reason = db.execute(
        f"""SELECT 
            im.reason, 
            COUNT(*) AS cnt,
            SUM(quantity) AS total_qty,
            pi.sku
        FROM inventory_movements im
        LEFT JOIN product_inventory pi ON im.product_id = pi.id
        WHERE {where_sql}
        GROUP BY im.reason
        ORDER BY total_qty DESC""",
        params,
    ).fetchall()

    # أكثر الأصناف هالكاً
    top_damaged = db.execute(
        f"""SELECT 
            pi.sku,
            COUNT(*) AS cnt,
            SUM(im.quantity) AS total_qty,
            ROUND(SUM(im.quantity * COALESCE(pi.unit_cost, 0)), 2) AS estimated_cost
        FROM inventory_movements im
        LEFT JOIN product_inventory pi ON im.product_id = pi.id
        WHERE {where_sql}
        GROUP BY im.product_id
        ORDER BY total_qty DESC
        LIMIT 10""",
        params,
    ).fetchall()

    return render_template(
        "inventory/report_damage_waste.html",
        date_from=date_from,
        date_to=date_to,
        summary=dict(summary) if summary else {"count": 0, "total_qty": 0},
        by_reason=[dict(r) for r in by_reason],
        top_damaged=[dict(r) for r in top_damaged],
    )


@bp.route("/reports/inventory-turnover")
@require_perm("warehouse")
def report_inventory_turnover():
    """تقرير معدل دوران المخزون والأصناف البطيئة."""
    from modules.extensions import get_db

    db = get_db()
    business_id = g.business["id"]

    days = request.args.get("days", "30")
    try:
        days = int(days)
    except ValueError:
        days = 30

    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    # معدل دوران كل صنف: (إجمالي المبيعات / متوسط المخزون)
    turnover = db.execute(f"""
        SELECT 
            pi.sku,
            p.name AS product_name,
            pi.current_qty AS current_stock,
            ROUND(pi.unit_cost * pi.current_qty, 2) AS stock_value,
            COALESCE(SUM(CASE WHEN i.invoice_type='sale' AND i.status='paid' THEN il.quantity ELSE 0 END), 0) AS units_sold,
            COALESCE(SUM(CASE WHEN i.invoice_type='sale' AND i.status='paid' THEN il.total ELSE 0 END), 0) AS sales_value,
            CASE 
                WHEN COALESCE(pi.current_qty, 0) > 0 
                THEN ROUND(COALESCE(SUM(CASE WHEN i.invoice_type='sale' AND i.status='paid' THEN il.quantity ELSE 0 END), 0) / pi.current_qty, 2)
                ELSE 0 
            END AS turnover_rate,
            ROUND(COALESCE(SUM(CASE WHEN i.invoice_type='sale' AND i.status='paid' THEN il.quantity ELSE 0 END), 0) * 1.0 / {days}, 2) AS avg_daily_sales
        FROM product_inventory pi
        LEFT JOIN products p ON p.id = pi.product_id
        LEFT JOIN invoice_lines il ON il.description = p.name
        LEFT JOIN invoices i ON i.id = il.invoice_id AND i.business_id = pi.business_id
          AND DATE(i.created_at) >= ?
        WHERE pi.business_id = ?
        GROUP BY pi.id
        ORDER BY turnover_rate DESC
    """, (since, business_id)).fetchall()

    # الأصناف البطيئة جداً (لم تُباع في آخر 30/60/90 يوم)
    slow_moving = db.execute(f"""
        SELECT 
            pi.sku,
            p.name AS product_name,
            pi.current_qty,
            ROUND(pi.unit_cost * pi.current_qty, 2) AS stock_value,
            CASE 
                WHEN NOT EXISTS (
                    SELECT 1 FROM invoice_lines il
                    JOIN invoices i ON i.id = il.invoice_id
                    WHERE il.description = p.name AND i.business_id = pi.business_id
                      AND i.invoice_type = 'sale' AND i.status = 'paid'
                      AND DATE(i.created_at) >= ?
                )
                THEN 'لم تُباع'
                ELSE 'مبيعات بطيئة'
            END AS status,
            COALESCE((
                SELECT MAX(DATE(i.created_at)) FROM invoice_lines il
                JOIN invoices i ON i.id = il.invoice_id
                WHERE il.description = p.name AND i.business_id = pi.business_id
                  AND i.invoice_type = 'sale' AND i.status = 'paid'
            ), 'غير معروف') AS last_sale_date
        FROM product_inventory pi
        JOIN products p ON p.id = pi.product_id
        WHERE pi.business_id = ? AND pi.current_qty > 0
          AND p.name NOT IN (
              SELECT DISTINCT il.description FROM invoice_lines il
              JOIN invoices i ON i.id = il.invoice_id
              WHERE i.business_id = pi.business_id AND i.invoice_type = 'sale'
                AND i.status = 'paid' AND DATE(i.created_at) >= ?
          )
        ORDER BY pi.current_qty DESC
        LIMIT 20
    """, (since, business_id, since)).fetchall()

    return render_template(
        "inventory/report_inventory_turnover.html",
        days=days,
        turnover=[dict(r) for r in turnover],
        slow_moving=[dict(r) for r in slow_moving],
    )


@bp.route("/reports/distributor-performance")
@require_perm("sales")
def report_distributor_performance():
    """تقرير أداء الموزعين (للجملة): إجمالي الطلبات، الحجم، الديون."""
    from modules.extensions import get_db

    db = get_db()
    business_id = g.business["id"]

    months = request.args.get("months", "3")
    try:
        months = int(months)
    except ValueError:
        months = 3

    since = (datetime.now() - timedelta(days=months * 30)).strftime("%Y-%m-%d")

    # أداء كل موزع
    distributors = db.execute(f"""
        SELECT 
            c.id,
            c.name AS distributor_name,
            COUNT(i.id) AS total_orders,
            COALESCE(SUM(CASE WHEN i.status='paid' THEN i.total ELSE 0 END), 0) AS paid_amount,
            COALESCE(SUM(CASE WHEN i.status='pending' THEN i.total - COALESCE(i.paid_amount, 0) ELSE 0 END), 0) AS outstanding_debt,
            ROUND(COALESCE(SUM(i.total), 0), 2) AS total_volume,
            COUNT(CASE WHEN i.status='paid' THEN 1 END) AS paid_orders,
            COUNT(CASE WHEN i.status='pending' THEN 1 END) AS pending_orders,
            CASE 
                WHEN COUNT(i.id) > 0 
                THEN ROUND(COUNT(CASE WHEN i.status='paid' THEN 1 END) * 100.0 / COUNT(i.id), 1)
                ELSE 0 
            END AS payment_rate
        FROM contacts c
        LEFT JOIN invoices i ON i.party_id = c.id AND i.business_id = c.business_id
          AND i.invoice_type = 'sale' AND DATE(i.created_at) >= ?
        WHERE c.business_id = ? AND c.contact_type = 'customer'
        GROUP BY c.id
        ORDER BY total_volume DESC
    """, (since, business_id)).fetchall()

    return render_template(
        "inventory/report_distributor_performance.html",
        months=months,
        distributors=[dict(r) for r in distributors],
    )


# ═══════════════════════════════════════════════════════════════
#  تقرير المبيعات التفصيلي بفلاتر (كاشير + تاريخ + صنف)
# ═══════════════════════════════════════════════════════════════

@bp.route("/reports/sales-detail")
@require_perm("reports")
def report_sales_detail():
    """تقرير مبيعات تفصيلي مع فلترة بالتاريخ والصنف والكاشير."""
    from modules.extensions import get_db

    db = get_db()
    business_id = g.business["id"]

    date_from = request.args.get("from", (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"))
    date_to   = request.args.get("to",   datetime.now().strftime("%Y-%m-%d"))
    cashier_filter = request.args.get("cashier", "").strip()
    product_filter = request.args.get("product", "").strip()

    where_clauses = [
        "i.business_id = ?",
        "i.invoice_type IN ('sale', 'table')",
        "i.status = 'paid'",
        "DATE(i.created_at) >= ?",
        "DATE(i.created_at) <= ?",
    ]
    params = [business_id, date_from, date_to]

    if cashier_filter:
        where_clauses.append("i.created_by = ?")
        params.append(cashier_filter)
    if product_filter:
        where_clauses.append("il.description LIKE ?")
        params.append(f"%{product_filter}%")

    where_sql = " AND ".join(where_clauses)

    # سطور المبيعات التفصيلية
    sales_lines = db.execute(f"""
        SELECT
            DATE(i.created_at) AS sale_date,
            i.invoice_number,
            il.description AS product_name,
            ROUND(il.quantity, 3) AS qty,
            ROUND(il.unit_price, 2) AS unit_price,
            ROUND(il.total, 2) AS line_total,
            i.created_by AS cashier_id,
            COALESCE(u.full_name, CAST(i.created_by AS TEXT)) AS cashier_name
        FROM invoice_lines il
        JOIN invoices i ON i.id = il.invoice_id
        LEFT JOIN users u ON u.id = i.created_by
        WHERE {where_sql}
        ORDER BY i.created_at DESC, il.id
        LIMIT 500
    """, params).fetchall()

    # ملخص حسب التاريخ
    daily_summary = db.execute(f"""
        SELECT
            DATE(i.created_at) AS sale_date,
            COUNT(DISTINCT i.id) AS invoice_count,
            ROUND(SUM(il.quantity), 2) AS total_qty,
            ROUND(SUM(il.total), 2) AS total_revenue
        FROM invoice_lines il
        JOIN invoices i ON i.id = il.invoice_id
        WHERE {where_sql}
        GROUP BY DATE(i.created_at)
        ORDER BY sale_date DESC
    """, params).fetchall()

    # ملخص حسب الصنف
    product_summary = db.execute(f"""
        SELECT
            il.description AS product_name,
            ROUND(SUM(il.quantity), 2) AS total_qty,
            ROUND(SUM(il.total), 2) AS total_revenue,
            ROUND(AVG(il.unit_price), 2) AS avg_price,
            COUNT(DISTINCT i.id) AS sale_count
        FROM invoice_lines il
        JOIN invoices i ON i.id = il.invoice_id
        WHERE {where_sql}
        GROUP BY il.description
        ORDER BY total_revenue DESC
        LIMIT 30
    """, params).fetchall()

    # الكاشيرون المتاحون للفلتر
    cashiers = db.execute("""
        SELECT DISTINCT i.created_by AS id, COALESCE(u.full_name, CAST(i.created_by AS TEXT)) AS name
        FROM invoices i
        LEFT JOIN users u ON u.id = i.created_by
        WHERE i.business_id=? AND i.invoice_type IN ('sale','table') AND i.status='paid'
        ORDER BY name
    """, (business_id,)).fetchall()

    grand_total = sum(r["total_revenue"] for r in daily_summary)

    return render_template(
        "inventory/report_sales_detail.html",
        date_from=date_from,
        date_to=date_to,
        cashier_filter=cashier_filter,
        product_filter=product_filter,
        sales_lines=[dict(r) for r in sales_lines],
        daily_summary=[dict(r) for r in daily_summary],
        product_summary=[dict(r) for r in product_summary],
        cashiers=[dict(r) for r in cashiers],
        grand_total=round(grand_total, 2),
    )


# ═══════════════════════════════════════════════════════════════
#  تحليل هامش الربح للمنتجات
# ═══════════════════════════════════════════════════════════════

@bp.route("/reports/profit-margin")
@require_perm("reports")
def report_profit_margin():
    """تحليل هامش الربح: مقارنة سعر التكلفة بسعر البيع لكل صنف."""
    from modules.extensions import get_db

    db = get_db()
    business_id = g.business["id"]

    days = request.args.get("days", "30")
    try:
        days = int(days)
    except ValueError:
        days = 30

    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    # هامش الربح لكل صنف
    margins = db.execute(f"""
        SELECT
            pi.sku,
            p.name AS product_name,
            ROUND(COALESCE(pi.unit_cost, 0), 2) AS unit_cost,
            ROUND(COALESCE(p.sale_price, 0), 2) AS sale_price,
            ROUND(COALESCE(p.sale_price, 0) - COALESCE(pi.unit_cost, 0), 2) AS gross_profit_per_unit,
            CASE
                WHEN COALESCE(p.sale_price, 0) > 0
                THEN ROUND((COALESCE(p.sale_price, 0) - COALESCE(pi.unit_cost, 0)) * 100.0 / p.sale_price, 1)
                ELSE 0
            END AS margin_pct,
            COALESCE(SUM(il.quantity), 0) AS units_sold,
            ROUND(COALESCE(SUM(il.total), 0), 2) AS revenue,
            ROUND(COALESCE(SUM(il.quantity * COALESCE(pi.unit_cost, 0)), 0), 2) AS cogs,
            ROUND(COALESCE(SUM(il.total), 0) - COALESCE(SUM(il.quantity * COALESCE(pi.unit_cost, 0)), 0), 2) AS gross_profit
        FROM product_inventory pi
        LEFT JOIN products p ON p.id = pi.product_id
        LEFT JOIN invoice_lines il ON il.description = p.name
        LEFT JOIN invoices i ON i.id = il.invoice_id AND i.business_id = pi.business_id
          AND i.invoice_type = 'sale' AND i.status = 'paid'
          AND DATE(i.created_at) >= ?
        WHERE pi.business_id = ?
        GROUP BY pi.id
        ORDER BY gross_profit DESC
    """, (since, business_id)).fetchall()

    # الأكثر ربحية
    top_margin   = sorted([dict(r) for r in margins], key=lambda x: x["margin_pct"], reverse=True)[:10]
    # الأقل ربحية (هامش سلبي أو منخفض)
    low_margin   = [r for r in [dict(r) for r in margins] if r["margin_pct"] < 20][:10]
    # إجمالي
    total_revenue = sum(r["revenue"] for r in [dict(r) for r in margins])
    total_cogs    = sum(r["cogs"] for r in [dict(r) for r in margins])
    total_profit  = total_revenue - total_cogs
    avg_margin    = round(total_profit * 100 / total_revenue, 1) if total_revenue > 0 else 0

    return render_template(
        "inventory/report_profit_margin.html",
        days=days,
        margins=[dict(r) for r in margins],
        top_margin=top_margin,
        low_margin=low_margin,
        total_revenue=round(total_revenue, 2),
        total_cogs=round(total_cogs, 2),
        total_profit=round(total_profit, 2),
        avg_margin=avg_margin,
    )


# ═══════════════════════════════════════════════════════════════
#  الموردون المتأخرون في الدفع
# ═══════════════════════════════════════════════════════════════

@bp.route("/reports/suppliers-overdue")
@require_perm("purchases")
def report_suppliers_overdue():
    """قائمة المشتريات غير المدفوعة للموردين."""
    from modules.extensions import get_db

    db = get_db()
    business_id = g.business["id"]

    # مشتريات معلقة (غير مدفوعة)
    overdue_by_supplier = db.execute("""
        SELECT
            c.id AS supplier_id,
            c.name AS supplier_name,
            c.phone,
            COUNT(i.id) AS invoice_count,
            ROUND(SUM(i.total - COALESCE(i.paid_amount, 0)), 2) AS total_owed,
            MIN(i.due_date) AS oldest_due,
            CAST((julianday('now') - julianday(MIN(COALESCE(i.due_date, i.invoice_date)))) AS INTEGER) AS max_days_overdue
        FROM invoices i
        JOIN contacts c ON c.id = i.party_id
        WHERE i.business_id=? AND i.invoice_type='purchase'
          AND i.status IN ('unpaid', 'partial', 'pending')
          AND (i.total - COALESCE(i.paid_amount, 0)) > 0
        GROUP BY c.id
        ORDER BY total_owed DESC
    """, (business_id,)).fetchall()

    # تفاصيل الفواتير المستحقة
    overdue_invoices = db.execute("""
        SELECT
            i.id, i.invoice_number, i.invoice_date, i.due_date,
            ROUND(i.total - COALESCE(i.paid_amount, 0), 2) AS owed,
            CAST((julianday('now') - julianday(COALESCE(i.due_date, i.invoice_date))) AS INTEGER) AS days_since,
            c.name AS supplier_name, c.id AS supplier_id
        FROM invoices i
        JOIN contacts c ON c.id = i.party_id
        WHERE i.business_id=? AND i.invoice_type='purchase'
          AND i.status IN ('unpaid', 'partial', 'pending')
          AND (i.total - COALESCE(i.paid_amount, 0)) > 0
        ORDER BY i.due_date ASC NULLS LAST
    """, (business_id,)).fetchall()

    total_owed = sum(r["total_owed"] for r in overdue_by_supplier)

    return render_template(
        "inventory/report_suppliers_overdue.html",
        overdue_by_supplier=[dict(r) for r in overdue_by_supplier],
        overdue_invoices=[dict(r) for r in overdue_invoices],
        total_owed=round(total_owed, 2),
    )
