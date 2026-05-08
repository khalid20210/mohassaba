"""
_import_excel_to_dev.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
استيراد المنتجات الحقيقية من ملفات Excel/CSV إلى accounting_dev.db

المصادر:
  1) 1k.xlsx        → 1000 منتج ألبان/بيض حقيقي بباركود وأسعار
  2) جاهزه.xlsx     → نفس المنتجات (تُستخدم للتحقق والدمج)
  3) Products-2026-03-02.csv → 743 منتج عناية شخصية + غذاء

التوزيع:
  • ألبان/بيض → بقالة الأمل (11) + سوق الخير (12) + مؤسسة الأمانة (30) + ففف (23)
  • عناية شخصية → صيدلية الشفاء (6) + بوتيك (9)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import sqlite3
import csv
import random
import warnings
warnings.filterwarnings("ignore")

DB_PATH  = r"c:\Users\JEN21\OneDrive\سطح المكتب\محاسبه\database\accounting_dev.db"
FILES    = {
    "1k":     r"c:\Users\JEN21\OneDrive\سطح المكتب\محاسبه\منتجات\منتجات\1k.xlsx",
    "jahza":  r"c:\Users\JEN21\OneDrive\سطح المكتب\محاسبه\منتجات\منتجات\جاهزه.xlsx",
    "csv03":  r"c:\Users\JEN21\OneDrive\سطح المكتب\محاسبه\منتجات\منتجات\Products-2026-03-02.csv",
}

# منشآت الاستيراد: {biz_id: [مجموعات الفئات التي تناسبها]}
FOOD_BIZ_IDS   = [11, 12, 23, 30]   # بقالة، سوق، ففف، مؤسسة الأمانة
HEALTH_BIZ_IDS = [6]                 # صيدلية الشفاء

# خريطة فئة CSV → فئة عربية نظيفة
CAT_CLEAN = {
    "اغذيه":                 "مواد غذائية",
    "كريمات شعر وللجسم":     "مستحضرات تجميل",
    "غسول للجسم":            "منتجات العناية بالجسم",
    "شامبوهات":              "شامبو وبلسم",
    "مشروبات غازيه":         "مشروبات",
}


# ───────────────────────────────────────────────────────
def load_1k_xlsx():
    """يقرأ 1k.xlsx: barcode,name_ar,name_en,cat_main,_,cat_sub,_,brand,_,_,unit,price,img"""
    import openpyxl
    wb = openpyxl.load_workbook(FILES["1k"], read_only=True, data_only=True)
    rows = list(wb.active.iter_rows(values_only=True))[1:]  # skip header
    products = []
    for r in rows:
        barcode   = str(r[0]).strip() if r[0] else ""
        name_ar   = str(r[1]).strip() if r[1] else ""
        name_en   = str(r[2]).strip() if r[2] else ""
        cat_main  = str(r[3]).strip() if r[3] else "مواد غذائية"
        cat_sub   = str(r[5]).strip() if r[5] else cat_main
        brand     = str(r[7]).strip() if r[7] else ""
        price     = float(r[11]) if r[11] and str(r[11]).replace('.','').isdigit() else 0.0
        if not name_ar:
            continue
        products.append({
            "barcode":       barcode,
            "name":          name_ar,
            "name_en":       name_en,
            "category_name": cat_sub,
            "brand":         brand,
            "sale_price":    price,
            "purchase_price": round(price * 0.7, 2) if price else 0.0,
            "product_type":  "product",
            "track_stock":   1,
            "is_pos":        1,
            "source":        "food",
        })
    return products


def load_csv_products():
    """يقرأ Products-2026-03-02.csv"""
    rows = list(csv.reader(open(FILES["csv03"], encoding="utf-8-sig")))
    headers = rows[0] if rows else []
    products = []
    for r in rows[1:]:
        if not any(c.strip() for c in r):
            continue
        row_dict = dict(zip(headers, r + [""] * 20))
        name_ar  = row_dict.get("الاسم", "").strip()
        if not name_ar:
            continue
        barcode  = row_dict.get("الباركود", "").strip()
        cat_raw  = row_dict.get("صنف المنتج", "").strip()
        cat_name = CAT_CLEAN.get(cat_raw, cat_raw or "متنوع")
        try:
            sale_p = float(row_dict.get("سعر البيع", "0").strip() or "0")
        except ValueError:
            sale_p = 0.0
        try:
            buy_p = float(row_dict.get("سعر الشراء", "0").strip() or "0")
        except ValueError:
            buy_p = 0.0

        # تحديد المصدر
        food_cats = {"اغذيه", "مشروبات غازيه"}
        source = "food" if cat_raw in food_cats else "health"

        products.append({
            "barcode":       barcode,
            "name":          name_ar,
            "name_en":       row_dict.get("الاسم الانجليزي", "").strip(),
            "category_name": cat_name,
            "brand":         "",
            "sale_price":    sale_p,
            "purchase_price": buy_p,
            "product_type":  "product",
            "track_stock":   1,
            "is_pos":        1,
            "source":        source,
        })
    return products


def ensure_category(db, biz_id: int, cat_name: str, cat_cache: dict) -> int | None:
    """يضمن وجود الفئة ويعيد id-ها."""
    key = (biz_id, cat_name)
    if key in cat_cache:
        return cat_cache[key]
    row = db.execute(
        "SELECT id FROM product_categories WHERE business_id=? AND name=?",
        (biz_id, cat_name)
    ).fetchone()
    if row:
        cat_cache[key] = row[0]
        return row[0]
    db.execute(
        "INSERT INTO product_categories (business_id, name, is_active) VALUES (?,?,1)",
        (biz_id, cat_name)
    )
    cat_cache[key] = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    return cat_cache[key]


def import_to_business(db, biz_id: int, products: list[dict], cat_cache: dict,
                        sku_prefix: str) -> dict:
    """يستورد قائمة المنتجات لمنشأة واحدة."""
    inserted = 0
    skipped  = 0
    seq = db.execute(
        "SELECT COUNT(*) FROM products WHERE business_id=?", (biz_id,)
    ).fetchone()[0] + 1

    for p in products:
        # تحقق من التكرار بالاسم
        exists = db.execute(
            "SELECT id FROM products WHERE business_id=? AND name=?",
            (biz_id, p["name"])
        ).fetchone()
        if exists:
            skipped += 1
            continue

        cat_id = ensure_category(db, biz_id, p["category_name"], cat_cache)

        # إدراج المنتج
        db.execute("""
            INSERT INTO products
              (business_id, barcode, name, name_en, product_type,
               category_id, category_name, can_purchase, purchase_price,
               can_sell, sale_price, track_stock, is_pos, is_active,
               created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,1,?,1,?,?,1,1,datetime('now'),datetime('now'))
        """, (
            biz_id, p["barcode"], p["name"], p["name_en"], p["product_type"],
            cat_id, p["category_name"],
            p["purchase_price"], p["sale_price"],
            p["track_stock"]
        ))
        prod_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # SKU
        sku_val = f"{sku_prefix}-IMP-{seq:04d}"
        seq += 1

        # product_inventory
        db.execute("""
            INSERT OR IGNORE INTO product_inventory
              (business_id, product_id, sku, barcode, current_qty, min_qty, max_qty,
               unit_cost, unit_price, created_at, updated_at)
            VALUES (?,?,?,?,0,5,500,?,?,datetime('now'),datetime('now'))
        """, (
            biz_id, prod_id, sku_val, p["barcode"],
            p["purchase_price"], p["sale_price"]
        ))
        inserted += 1

    db.commit()
    return {"inserted": inserted, "skipped": skipped}


def get_biz_prefix(db, biz_id: int) -> str:
    row = db.execute(
        "SELECT value FROM settings WHERE business_id=? AND key='invoice_prefix' LIMIT 1",
        (biz_id,)
    ).fetchone()
    if row and row[0] and row[0] not in ("PRD", "GEN"):
        return row[0].upper()
    row2 = db.execute(
        "SELECT industry_type FROM businesses WHERE id=?", (biz_id,)
    ).fetchone()
    itype = row2[0] if row2 else ""
    MAP = {
        "retail_fnb_grocery": "GRO", "retail_fnb_supermarket": "SPM",
        "wholesale_fnb_general": "WHL", "food_restaurant": "RES",
        "food_cafe": "CAF", "retail_health_pharmacy": "PHR",
        "retail_fashion_clothing_m": "MFA",
    }
    return MAP.get(itype, "PRD")


def main():
    print("=" * 60)
    print("  استيراد المنتجات الحقيقية من Excel/CSV")
    print("=" * 60)

    # قراءة الملفات
    print("\n[1] قراءة 1k.xlsx...")
    food_products_1k = load_1k_xlsx()
    print(f"    ✓ {len(food_products_1k)} منتج")

    print("[2] قراءة Products-2026-03-02.csv...")
    csv_products = load_csv_products()
    food_csv    = [p for p in csv_products if p["source"] == "food"]
    health_csv  = [p for p in csv_products if p["source"] == "health"]
    print(f"    ✓ غذائي: {len(food_csv)} | صحة/عناية: {len(health_csv)}")

    # دمج المنتجات الغذائية
    food_all = food_products_1k + food_csv
    # إزالة تكرار بالاسم
    seen_names = set()
    food_unique = []
    for p in food_all:
        if p["name"] not in seen_names:
            seen_names.add(p["name"])
            food_unique.append(p)
    print(f"\n    إجمالي غذائي فريد: {len(food_unique)}")
    print(f"    صحة/عناية فريد:    {len(health_csv)}")

    # الاتصال بقاعدة البيانات
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=OFF")

    cat_cache = {}

    print("\n[3] استيراد للمنشآت الغذائية...")
    total_food = 0
    for biz_id in FOOD_BIZ_IDS:
        row = db.execute("SELECT name FROM businesses WHERE id=?", (biz_id,)).fetchone()
        if not row:
            print(f"    ⚠ منشأة {biz_id} غير موجودة")
            continue
        prefix = get_biz_prefix(db, biz_id)
        result = import_to_business(db, biz_id, food_unique, cat_cache, prefix)
        print(f"    ✅ {row['name'][:30]:30s} | +{result['inserted']:4d} جديد | {result['skipped']:4d} موجود")
        total_food += result["inserted"]

    print("\n[4] استيراد للمنشآت الصحية/العناية...")
    total_health = 0
    for biz_id in HEALTH_BIZ_IDS:
        row = db.execute("SELECT name FROM businesses WHERE id=?", (biz_id,)).fetchone()
        if not row:
            continue
        prefix = get_biz_prefix(db, biz_id)
        result = import_to_business(db, biz_id, health_csv, cat_cache, prefix)
        print(f"    ✅ {row['name'][:30]:30s} | +{result['inserted']:4d} جديد | {result['skipped']:4d} موجود")
        total_health += result["inserted"]

    db.close()

    print(f"\n{'='*60}")
    print(f"  تم استيراد: {total_food + total_health} منتج جديد")
    print(f"  غذائي: {total_food} | صحة: {total_health}")
    print("✅ اكتمل الاستيراد!")


if __name__ == "__main__":
    main()
