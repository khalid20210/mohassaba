"""
استيراد المنتجات من ملفات CSV إلى قاعدة البيانات SQLite
يدمج جميع الملفات ويزيل التكرار حسب الباركود
"""
import sqlite3
import csv
import os
import re
from pathlib import Path

BASE_DIR    = Path(__file__).parent
DB_PATH     = BASE_DIR / "accounting.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"
SEED_PATH   = BASE_DIR / "seed_data.sql"
CSV_DIR     = BASE_DIR.parent / "منتجات" / "منتجات"
BUSINESS_ID = 1
WAREHOUSE_ID = 1

def init_db(conn):
    """تهيئة قاعدة البيانات بالمخطط والبيانات الأساسية"""
    cur = conn.cursor()
    cur.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    cur.executescript(SEED_PATH.read_text(encoding="utf-8"))
    conn.commit()
    print("✓ تم تهيئة قاعدة البيانات")

def clean_barcode(raw: str) -> str:
    """تنظيف الباركود من الأحرف غير المرغوب فيها"""
    if not raw:
        return ""
    cleaned = raw.strip().strip('"').strip()
    # إزالة أي مسافات داخلية
    cleaned = re.sub(r'\s+', '', cleaned)
    return cleaned if cleaned else ""

def detect_delimiter(filepath: str) -> str:
    """اكتشاف الفاصل في ملف CSV"""
    with open(filepath, encoding="utf-8-sig", errors="replace") as f:
        first_line = f.readline()
    if first_line.count(";") > first_line.count(","):
        return ";"
    return ","

def parse_float(val: str) -> float:
    try:
        return float(str(val).strip().replace(",", ""))
    except (ValueError, TypeError):
        return 0.0

def parse_bool(val: str) -> int:
    return 1 if str(val).strip() in ("نعم", "yes", "1", "true") else 0

def unwrap_line(line: str) -> str:
    """
    بعض الصفوف محاطة بعلامات اقتباس خارجية مثل:
      "396984841485,فاتيكا,..."  →  396984841485,فاتيكا,...
    نزيل علامة الاقتباس الأولى والأخيرة من السطر بأكمله.
    كما نزيل الـ ; الزائدة في النهاية.
    """
    line = line.rstrip("\n\r")
    # إزالة ; النهائية قبل الفحص
    line = line.rstrip(";").rstrip()
    # إذا كان السطر كله محاطاً بـ " نزيلها
    if line.startswith('"') and line.endswith('"'):
        inner = line[1:-1]
        # استبدال """" بـ "" (الهروب المزدوج للفاصلة المقتبسة الفارغة)
        inner = inner.replace('""', '\x00EMPTY\x00')
        line = inner
    return line

def load_csv(filepath: str) -> list[dict]:
    """تحميل ملف CSV وإرجاع قائمة من القواميس"""
    with open(filepath, encoding="utf-8-sig", errors="replace") as f:
        raw_lines = f.readlines()

    # اكتشاف الفاصل من السطر الأول (قبل التنظيف)
    first_raw = raw_lines[0].rstrip() if raw_lines else ""
    delim = ";" if first_raw.count(";") > first_raw.count(",") else ","

    cleaned_lines = [unwrap_line(l) for l in raw_lines]

    rows = []
    reader = csv.reader(cleaned_lines, delimiter=delim)
    headers = None
    for row in reader:
        if headers is None:
            headers = [h.strip().replace(";", "").replace('"', '').strip() for h in row]
            continue
        if not any(c.strip() for c in row):
            continue
        # تنظيف كل خلية
        cleaned_row = []
        for c in row:
            c = c.strip().rstrip(";").strip()
            c = c.replace('\x00EMPTY\x00', '')  # استعادة الفارغة
            cleaned_row.append(c)
        while len(cleaned_row) < len(headers):
            cleaned_row.append("")
        rows.append(dict(zip(headers, cleaned_row)))
    return rows

def normalize_row(row: dict) -> dict | None:
    """توحيد أسماء الحقول من صيغ مختلفة"""
    # خريطة الأعمدة المحتملة
    field_map = {
        "الاسم":          ["الاسم", "name"],
        "name_en":        ["الاسم الانجليزي", "الاسمالانجليزي", "name_en", "الاسم;الانجليزي"],
        "description":    ["الوصف"],
        "product_type":   ["النوع"],
        "barcode":        ["الباركود"],
        "category_name":  ["صنف المنتج", "صنف;المنتج", "صنفالمنتج"],
        "can_purchase":   ["يُشتَرى"],
        "purchase_price": ["سعر الشراء", "سعر;الشراء", "سعرالشراء"],
        "can_sell":       ["يُبَاع"],
        "sale_price":     ["سعر البيع", "سعر;البيع", "سعرالبيع"],
        "quantity":       ["الكمية"],
        "track_stock":    ["مخزون؟"],
        "is_pos":         ["منتج نقاط بيع", "منتجنقاطبيع"],
        "serial_number":  ["الرقم التسلسلي", "الرقم;التسلسلي", "الرقمالتسلسلي"],
    }

    result = {}
    for target, sources in field_map.items():
        for src in sources:
            if src in row and row[src].strip():
                result[target] = row[src].strip().strip('"')
                break
        if target not in result:
            result[target] = ""

    name = result.get("الاسم", "").strip()
    if not name:
        return None  # تخطي الصفوف الفارغة

    barcode = clean_barcode(result.get("barcode", ""))
    return {
        "serial_number":   result.get("serial_number", ""),
        "barcode":         barcode,
        "name":            name,
        "name_en":         result.get("name_en", ""),
        "description":     result.get("description", ""),
        "product_type":    "product" if result.get("product_type", "منتج") in ("منتج", "product") else "service",
        "category_name":   result.get("category_name", ""),
        "can_purchase":    parse_bool(result.get("can_purchase", "نعم")),
        "purchase_price":  parse_float(result.get("purchase_price", "0")),
        "can_sell":        parse_bool(result.get("can_sell", "نعم")),
        "sale_price":      parse_float(result.get("sale_price", "0")),
        "quantity":        parse_float(result.get("quantity", "0")),
        "track_stock":     parse_bool(result.get("track_stock", "نعم")),
        "is_pos":          parse_bool(result.get("is_pos", "نعم")),
    }

def import_products(conn, all_rows: list[dict]):
    """إدراج المنتجات في قاعدة البيانات مع تجنب التكرار"""
    cur = conn.cursor()
    inserted = 0
    updated  = 0
    skipped  = 0
    seen_barcodes = set()

    for row in all_rows:
        name    = row["name"]
        barcode = row["barcode"]

        # تجنب التكرار: إذا كان هناك باركود نستخدمه، وإلا نستخدم الاسم
        key = f"bc_{barcode}" if barcode else f"nm_{name.strip()}"
        if key in seen_barcodes:
            skipped += 1
            continue
        seen_barcodes.add(key)

        # تحقق من وجود المنتج في قاعدة البيانات
        if barcode:
            cur.execute(
                "SELECT id FROM products WHERE business_id=? AND barcode=?",
                (BUSINESS_ID, barcode)
            )
        else:
            cur.execute(
                "SELECT id FROM products WHERE business_id=? AND name=? AND (barcode IS NULL OR barcode='')",
                (BUSINESS_ID, name)
            )

        existing = cur.fetchone()

        if existing:
            cur.execute("""
                UPDATE products SET
                    name=?, name_en=?, description=?, product_type=?,
                    category_name=?, can_purchase=?, purchase_price=?,
                    can_sell=?, sale_price=?, track_stock=?, is_pos=?,
                    updated_at=datetime('now')
                WHERE id=?
            """, (
                name, row["name_en"], row["description"], row["product_type"],
                row["category_name"], row["can_purchase"], row["purchase_price"],
                row["can_sell"], row["sale_price"], row["track_stock"], row["is_pos"],
                existing[0]
            ))
            prod_id = existing[0]
            updated += 1
        else:
            try:
                cur.execute("""
                    INSERT INTO products
                        (business_id, serial_number, barcode, name, name_en, description,
                         product_type, category_name, can_purchase, purchase_price,
                         can_sell, sale_price, track_stock, is_pos)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    BUSINESS_ID,
                    row["serial_number"], barcode, name, row["name_en"],
                    row["description"], row["product_type"], row["category_name"],
                    row["can_purchase"], row["purchase_price"],
                    row["can_sell"], row["sale_price"],
                    row["track_stock"], row["is_pos"]
                ))
                prod_id = cur.lastrowid
                inserted += 1
            except sqlite3.IntegrityError:
                # الباركود موجود بالفعل (تكرار بمفتاح مختلف) - تخطَّ
                skipped += 1
                continue

        # إنشاء رصيد مخزوني مبدئي
        qty = row["quantity"]
        cur.execute("""
            INSERT OR IGNORE INTO stock (business_id, product_id, warehouse_id, quantity, avg_cost)
            VALUES (?,?,?,?,?)
        """, (BUSINESS_ID, prod_id, WAREHOUSE_ID, qty, row["purchase_price"]))

    conn.commit()
    return inserted, updated, skipped

def main():
    print("=" * 55)
    print("  استيراد المنتجات إلى قاعدة البيانات")
    print("=" * 55)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")

    # تهيئة قاعدة البيانات
    init_db(conn)

    # قراءة جميع ملفات CSV
    csv_files = list(CSV_DIR.glob("*.csv"))
    if not csv_files:
        print("⚠ لم يتم العثور على ملفات CSV في المجلد:", CSV_DIR)
        return

    all_rows = []
    for f in csv_files:
        rows = load_csv(str(f))
        normalized = [normalize_row(r) for r in rows]
        normalized = [r for r in normalized if r is not None]
        all_rows.extend(normalized)
        print(f"  • {f.name}: {len(normalized)} منتج")

    print(f"\n  إجمالي الصفوف قبل إزالة التكرار: {len(all_rows)}")

    inserted, updated, skipped = import_products(conn, all_rows)
    conn.close()

    # الإحصائيات النهائية
    print(f"""
✓ اكتمل الاستيراد:
  - تم إضافة  : {inserted} منتج جديد
  - تم تحديث  : {updated} منتج موجود
  - تم تخطي   : {skipped} مكرر
""")

    # التحقق من العدد النهائي
    conn2 = sqlite3.connect(DB_PATH)
    cur = conn2.cursor()
    cur.execute("SELECT COUNT(*) FROM products WHERE business_id=?", (BUSINESS_ID,))
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM products WHERE business_id=? AND barcode!='' AND barcode IS NOT NULL", (BUSINESS_ID,))
    with_barcode = cur.fetchone()[0]
    conn2.close()

    print(f"  إجمالي المنتجات في قاعدة البيانات: {total}")
    print(f"  منتجات لها باركود: {with_barcode}")
    print(f"  منتجات بدون باركود: {total - with_barcode}")

if __name__ == "__main__":
    main()
