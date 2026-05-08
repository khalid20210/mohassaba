"""
استيراد المنتجات الحقيقية من ملفات CSV إلى قاعدة البيانات الحقيقية (accounting_dev.db)
يقرأ ملفات CSV من مجلد منتجات/ ويربطها بأول شركة في قاعدة البيانات (business_id=1)
"""
import csv, os, sqlite3, sys

os.chdir(r"c:\Users\JEN21\OneDrive\سطح المكتب\محاسبه")
DB = r"database\accounting_dev.db"

conn = sqlite3.connect(DB)
conn.execute("PRAGMA foreign_keys=OFF")
conn.execute("PRAGMA journal_mode=WAL")

# اقرأ أسماء الأعمدة الموجودة في جدول products
cols_info = conn.execute("PRAGMA table_info(products)").fetchall()
existing_cols = {r[1] for r in cols_info}
print("Columns in products table:", sorted(existing_cols))

# تحقق من الأعمال الموجودة
biz = conn.execute("SELECT id, name FROM businesses LIMIT 5").fetchall()
print("\nFirst businesses:", biz)

# اختر business_id=1 (أول شركة)
biz_id = biz[0][0] if biz else 1
biz_name = biz[0][1] if biz else "?"
print(f"\nTarget business_id={biz_id} ({biz_name})")

# مسار CSV الحقيقي
csv_paths = [
    r"منتجات\منتجات\Products-2026-03-02.csv",
    r"منتجات\منتجات\Products-2026-02-26 (4).csvمنتجات.csv",
    r"منتجات\products_export.csv",
]

inserted = 0
skipped_dup = 0
skipped_err = 0

for csv_path in csv_paths:
    if not os.path.exists(csv_path):
        continue
    sz = os.path.getsize(csv_path)
    if sz < 500:
        continue
    print(f"\n📄 CSV: {csv_path} ({sz//1024} KB)")

    with open(csv_path, encoding="utf-8-sig", errors="replace") as f:
        sample_line = f.readline()

    # تحديد المحدد (فاصلة أو فاصلة منقوطة)
    sep = ";" if sample_line.count(";") > sample_line.count(",") else ","

    with open(csv_path, encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f, delimiter=sep)
        rows = list(reader)

    print(f"  cols: {reader.fieldnames}")
    print(f"  rows: {len(rows)}")

    for row in rows:
        def _get(*keys):
            for k in keys:
                v = row.get(k) or ""
                if v.strip():
                    return v.strip()
            return ""

        name    = _get("الاسم", "Name (AR)")
        barcode = _get("الباركود", "Barcode")
        serial  = _get("الرقم التسلسلي", "الرقم;التسلسلي", "Code")
        name_en = _get("الاسم الانجليزي", "الاسم;الانجليزي", "Name (EN)")
        descr   = _get("الوصف", "Description")
        catname = _get("صنف المنتج", "صنف;المنتج", "Category Name")
        try:
            sale_price = float(_get("سعر البيع", "سعر;البيع", "Price") or 0)
        except:
            sale_price = 0.0
        try:
            buy_price = float(_get("سعر الشراء", "سعر;الشراء", "Cost") or 0)
        except:
            buy_price = 0.0

        if not name:
            skipped_err += 1
            continue

        # تحقق من التكرار بالـ barcode أو serial داخل نفس الشركة
        if barcode:
            dup = conn.execute(
                "SELECT id FROM products WHERE business_id=? AND barcode=?",
                (biz_id, barcode)
            ).fetchone()
            if dup:
                skipped_dup += 1
                continue
        elif serial:
            dup = conn.execute(
                "SELECT id FROM products WHERE business_id=? AND serial_number=?",
                (biz_id, serial)
            ).fetchone()
            if dup:
                skipped_dup += 1
                continue

        try:
            conn.execute("""
                INSERT INTO products
                    (business_id, serial_number, barcode, name, name_en,
                     description, category_name, sale_price, purchase_price,
                     can_sell, can_purchase, is_active, is_pos, track_stock)
                VALUES (?,?,?,?,?,?,?,?,?,1,1,1,1,1)
            """, (biz_id, serial or None, barcode or None, name, name_en or None,
                  descr or None, catname or None, sale_price, buy_price))
            inserted += 1
        except Exception as e:
            skipped_err += 1

conn.commit()
conn.close()

print(f"\n{'='*55}")
print(f"  النتيجة النهائية")
print(f"{'='*55}")
print(f"  ✅ تم إضافة   : {inserted:,} منتج")
print(f"  ⚠️  مكررة (تخطي): {skipped_dup:,}")
print(f"  ❌ أخطاء (تخطي): {skipped_err:,}")

# تأكيد
conn2 = sqlite3.connect(DB)
total = conn2.execute("SELECT COUNT(*) FROM products WHERE business_id=?", (biz_id,)).fetchone()[0]
conn2.close()
print(f"\n  📦 إجمالي منتجات business_id={biz_id}: {total:,}")
