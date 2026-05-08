"""
_prod_cleanup.py — تنظيف قاعدة البيانات وتجهيزها للإنتاج
"""
import sqlite3

DB = r"c:\Users\JEN21\OneDrive\سطح المكتب\محاسبه\database\accounting_dev.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("=" * 60)
print("  تنظيف وتجهيز قاعدة البيانات للإنتاج")
print("=" * 60)

# ─── 1. حذف المنشآت التجريبية (0-8 منتجات وأسماء تجريبية) ───────────────────
junk_patterns = ["dbg_%", "seed_spm_%", "seed_wcl_%"]
junk_names    = ["kkk", "test", "تجريبي", "منشأة test"]

print("\n[1] حذف المنشآت التجريبية...")

# الأسماء الصريحة
for name in junk_names:
    rows = cur.execute("SELECT id, name FROM businesses WHERE name = ?", (name,)).fetchall()
    for r in rows:
        biz_id = r["id"]
        cur.execute("DELETE FROM product_inventory WHERE business_id=?", (biz_id,))
        cur.execute("DELETE FROM products WHERE business_id=?", (biz_id,))
        cur.execute("DELETE FROM product_categories WHERE business_id=?", (biz_id,))
        cur.execute("DELETE FROM businesses WHERE id=?", (biz_id,))
        print(f"  ✓ حُذفت: [{biz_id}] {r['name']}")

# الأنماط التجريبية (LIKE)
for pat in junk_patterns:
    rows = cur.execute("SELECT id, name FROM businesses WHERE name LIKE ?", (pat,)).fetchall()
    for r in rows:
        biz_id = r["id"]
        cur.execute("DELETE FROM product_inventory WHERE business_id=?", (biz_id,))
        cur.execute("DELETE FROM products WHERE business_id=?", (biz_id,))
        cur.execute("DELETE FROM product_categories WHERE business_id=?", (biz_id,))
        cur.execute("DELETE FROM businesses WHERE id=?", (biz_id,))
        print(f"  ✓ حُذفت: [{biz_id}] {r['name']}")

conn.commit()

# ─── 2. تصحيح industry_type العربية → الإنجليزية ───────────────────────────
print("\n[2] تصحيح industry_type العربية...")
type_fixes = {
    "صيدلية":  "retail_health_pharmacy",
    "مطعم":    "food_restaurant",
    "كافيه":   "food_cafe",
    "مقهى":    "food_cafe",
    "restaurant": "food_restaurant",
    "retail":   "retail_fnb_general",
    "wholesale": "wholesale_fnb_general",
    "medical":  "medical_complex",
    "construction": "retail_construction_materials",
}
for old, new in type_fixes.items():
    rows = cur.execute(
        "SELECT id, name FROM businesses WHERE industry_type=?", (old,)
    ).fetchall()
    for r in rows:
        cur.execute("UPDATE businesses SET industry_type=? WHERE id=?", (new, r["id"]))
        print(f"  ✓ [{r['id']}] {r['name']}: {old} → {new}")
conn.commit()

# ─── 3. التأكد من أن جميع المنشآت لها is_active = 1 ────────────────────────
print("\n[3] تفعيل المنشآت غير النشطة التي لها منتجات...")
updated = cur.execute("""
    UPDATE businesses SET is_active=1
    WHERE is_active=0
    AND id IN (SELECT DISTINCT business_id FROM products WHERE is_active=1)
""").rowcount
conn.commit()
print(f"  ✓ فُعِّلت {updated} منشأة")

# ─── 4. التحقق من SKUs الفارغة ───────────────────────────────────────────────
print("\n[4] تعيين SKU للمنتجات الفارغة...")
no_sku = cur.execute("""
    SELECT COUNT(*) FROM product_inventory
    WHERE sku IS NULL OR TRIM(sku) = ''
""").fetchone()[0]

if no_sku > 0:
    # نعيّن SKUs مؤقتة بناءً على ID
    cur.execute("""
        UPDATE product_inventory
        SET sku = 'PRD-' || printf('%06d', product_id)
        WHERE sku IS NULL OR TRIM(sku) = ''
    """)
    conn.commit()
    print(f"  ✓ عُيِّن SKU لـ {no_sku} منتج")
else:
    print("  ✓ جميع المنتجات لها SKU")

# ─── 5. التقرير النهائي ───────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("  التقرير النهائي بعد التنظيف")
print("=" * 60)

bizs   = cur.execute("SELECT COUNT(*) FROM businesses WHERE is_active=1").fetchone()[0]
prods  = cur.execute("SELECT COUNT(*) FROM products WHERE is_active=1").fetchone()[0]
invs   = cur.execute("SELECT COUNT(*) FROM invoices").fetchone()[0]
users  = cur.execute("SELECT COUNT(*) FROM users WHERE is_active=1").fetchone()[0]
types  = cur.execute("SELECT COUNT(DISTINCT industry_type) FROM businesses WHERE is_active=1").fetchone()[0]
no_sku_left = cur.execute("""
    SELECT COUNT(*) FROM product_inventory WHERE sku IS NULL OR TRIM(sku)=''
""").fetchone()[0]

print(f"\n  ✅ منشآت نشطة  : {bizs}")
print(f"  ✅ مستخدمون     : {users}")
print(f"  ✅ منتجات       : {prods:,}")
print(f"  ✅ فواتير        : {invs:,}")
print(f"  ✅ أنواع نشاط   : {types}")
print(f"  ✅ منتجات بدون SKU : {no_sku_left}")

# التحقق من وجود منشآت بدون منتجات
empty_biz = cur.execute("""
    SELECT b.id, b.name FROM businesses b
    WHERE b.is_active=1
    AND NOT EXISTS (SELECT 1 FROM products p WHERE p.business_id=b.id AND p.is_active=1)
""").fetchall()
if empty_biz:
    print(f"\n  ⚠ منشآت بدون منتجات ({len(empty_biz)}):")
    for r in empty_biz:
        print(f"    - [{r['id']}] {r['name']}")
else:
    print(f"\n  ✅ جميع المنشآت لها منتجات")

conn.close()
print("\n✅ اكتملت عملية التنظيف والتجهيز!\n")
