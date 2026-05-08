"""
نسخ منتجات البيزنس المرجعي إلى حساب الديمو
"""
import sqlite3, random, time

DB = "database/accounting_dev.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# ─── بيانات النقل ─────────────────────────────────────────────────
# [retail] مرجع: id=30 (10000 منتج) → demo: id=223
# [wholesale] مرجع: id=23 (1018 منتج) → يُنشأ حساب جديد
COPY_JOBS = [
    {
        "label": "سوبرماركت تجزئة",
        "src_biz": 30,
        "dst_biz": 223,
        "sku_prefix": "SPM",
    },
]

def copy_biz_products(src_biz, dst_biz, sku_prefix):
    # احذف المنتجات القديمة للحساب الجديد لتجنب التكرار
    cur.execute("DELETE FROM product_inventory WHERE business_id=?", (dst_biz,))
    cur.execute("DELETE FROM stock WHERE business_id=?", (dst_biz,))
    cur.execute("DELETE FROM products WHERE business_id=?", (dst_biz,))
    conn.commit()

    # جلب تصنيفات المصدر
    src_cats = cur.execute(
        "SELECT name FROM product_categories WHERE business_id=?", (src_biz,)
    ).fetchall()
    cat_map = {}
    for c in src_cats:
        existing = cur.execute(
            "SELECT id FROM product_categories WHERE business_id=? AND name=?",
            (dst_biz, c["name"])
        ).fetchone()
        if existing:
            cat_map[c["name"]] = existing["id"]
        else:
            r = cur.execute(
                "INSERT INTO product_categories (business_id, name) VALUES (?,?)",
                (dst_biz, c["name"])
            )
            cat_map[c["name"]] = r.lastrowid

    # جلب المستودع الافتراضي للحساب الجديد
    wh = cur.execute(
        "SELECT id FROM warehouses WHERE business_id=? AND is_default=1 LIMIT 1",
        (dst_biz,)
    ).fetchone()
    if not wh:
        r = cur.execute(
            "INSERT INTO warehouses (business_id, name, is_default) VALUES (?,?,1)",
            (dst_biz, "المستودع الرئيسي")
        )
        wh_id = r.lastrowid
    else:
        wh_id = wh["id"]

    # جلب منتجات المصدر
    src_products = cur.execute(
        """SELECT name, product_type, category_name, sale_price, purchase_price,
                  track_stock, is_pos, barcode
           FROM products WHERE business_id=? AND is_active=1""",
        (src_biz,)
    ).fetchall()

    inserted = 0
    batch_size = 500

    print(f"  نسخ {len(src_products)} منتج...")

    for i, p in enumerate(src_products, 1):
        # توليد باركود فريد
        barcode = f"6{random.randint(10**11, 10**12-1)}"
        sku = f"{sku_prefix}-{i:06d}"
        cat_id = cat_map.get(p["category_name"] or "")

        # إدراج في products
        r = cur.execute(
            """INSERT INTO products
               (business_id, name, product_type, category_id, category_name,
                sale_price, purchase_price, track_stock, is_pos, is_active, barcode)
               VALUES (?,?,?,?,?,?,?,?,?,1,?)""",
            (
                dst_biz, p["name"], p["product_type"] or "product",
                cat_id, p["category_name"] or "",
                p["sale_price"] or 0, p["purchase_price"] or 0,
                p["track_stock"] or 1,
                p["is_pos"] or 1,
                barcode,
            )
        )
        prod_id = r.lastrowid

        # عشوائي مخزون واقعي بين 50-500
        qty = random.randint(50, 500)

        # إدراج في product_inventory
        cur.execute(
            """INSERT OR IGNORE INTO product_inventory
               (business_id, product_id, sku, barcode, current_qty, min_qty, max_qty,
                unit_cost, unit_price, created_at, updated_at)
               VALUES (?,?,?,?,?,5,?,?,?,datetime('now'),datetime('now'))""",
            (dst_biz, prod_id, sku, barcode, qty, qty * 2,
             p["purchase_price"] or 0, p["sale_price"] or 0)
        )

        # إدراج في stock
        cur.execute(
            """INSERT OR IGNORE INTO stock
               (business_id, product_id, warehouse_id, quantity, avg_cost)
               VALUES (?,?,?,?,?)""",
            (dst_biz, prod_id, wh_id, qty, p["purchase_price"] or 0)
        )

        inserted += 1
        if inserted % batch_size == 0:
            conn.commit()
            print(f"  ✓ {inserted}/{len(src_products)} منتج...")

    conn.commit()
    print(f"  ✅ اكتمل: {inserted} منتج")
    return inserted


# ─── تنفيذ ────────────────────────────────────────────────────────
for job in COPY_JOBS:
    print(f"\n{'='*55}")
    print(f"  {job['label']}: business {job['src_biz']} → {job['dst_biz']}")
    print(f"{'='*55}")
    n = copy_biz_products(job["src_biz"], job["dst_biz"], job["sku_prefix"])

# ─── إنشاء حساب جملة غذاء وإدراج منتجاته ────────────────────────
print(f"\n{'='*55}")
print("  إنشاء حساب جملة غذاء ونسخ المنتجات...")
print(f"{'='*55}")

# إيجاد مستخدم jinan_demo
user = cur.execute(
    "SELECT id, business_id FROM users WHERE username=?", ("jinan_demo2026",)
).fetchone()

if user:
    # إنشاء بيزنس جملة جديد
    r = cur.execute(
        """INSERT INTO businesses (name, industry_type, is_active, created_at)
           VALUES (?, 'wholesale_fnb_distribution', 1, datetime('now'))""",
        ("جنان للجملة والتوزيع",)
    )
    wh_biz_id = r.lastrowid
    conn.commit()

    # تعيين هذا البيزنس لمستخدم جديد مرتبط به
    # (نحتفظ ببيزنس السوبرماركت للمستخدم الحالي)
    wh_count = copy_biz_products(23, wh_biz_id, "WHL")
    print(f"  ✅ تم إنشاء بيزنس الجملة id={wh_biz_id} بـ {wh_count} منتج")
else:
    print("  ⚠️ لم يُعثر على مستخدم jinan_demo2026")

# ─── ملخص نهائي ───────────────────────────────────────────────────
print(f"\n{'='*55}")
print("  📊 ملخص الأرقام النهائية:")
print(f"{'='*55}")

results = cur.execute("""
    SELECT b.name, b.industry_type, COUNT(p.id) as cnt
    FROM businesses b
    LEFT JOIN products p ON p.business_id = b.id
    WHERE b.id IN (223, 23)
       OR b.name LIKE '%جنان%'
    GROUP BY b.id
    ORDER BY cnt DESC
""").fetchall()

for r in results:
    print(f"  {r['name'][:30]:<32} {r['industry_type']:<30} {r['cnt']:>8,} منتج")

conn.close()
print(f"\n  ✅ انتهى — أعِد تحديث صفحة المتصفح!")
