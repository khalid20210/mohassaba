"""
_reseed_wholesale.py — إعادة تلقيم المنتجات لبيزنيسات الجملة الموجودة
يُضيف المنتجات الجديدة دون تكرار أو حذف للموجود
"""
import sqlite3, datetime, sys, random

DB  = "database/accounting_dev.db"
NOW = datetime.datetime.now().isoformat(sep=" ", timespec="seconds")

def barcode():
    digits = [random.randint(0, 9) for _ in range(12)]
    total = sum(d * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits))
    check = (10 - (total % 10)) % 10
    return "".join(str(d) for d in digits) + str(check)

WHOLESALE_PRODUCTS = {
    "wholesale_fnb_general": {
        "cats": ["مواد غذائية جملة", "مشروبات جملة", "تموينات جملة", "بقوليات", "بهارات جملة"],
        "prods": [
            ("أرز 50 كيلو",              "مواد غذائية جملة", 320.0, 224.0),
            ("سكر 50 كيلو",              "تموينات جملة",    210.0, 147.0),
            ("طحين 50 كيلو",             "تموينات جملة",    195.0, 136.5),
            ("مياه كرتون 12 زجاجة",     "مشروبات جملة",     18.0,  12.6),
            ("مياه باليت كامل",          "مشروبات جملة",    750.0, 525.0),
            ("عدس أحمر 25 كيلو",        "بقوليات",         145.0, 101.5),
            ("فول حبوب 25 كيلو",        "بقوليات",         130.0,  91.0),
            ("بهارات مشكلة — كرتون",    "بهارات جملة",     280.0, 196.0),
            ("هيل مطحون — كرتون",       "بهارات جملة",     350.0, 245.0),
            ("ملح طعام — كرتون 24",     "تموينات جملة",     48.0,  33.6),
            ("زيت نخيل 1.5 لتر — صندوق 12", "مواد غذائية جملة", 450.0, 315.0),
            ("سمن نباتي — صندوق 12",    "مواد غذائية جملة", 380.0, 266.0),
        ],
    },
    "wholesale_fnb_distribution": {
        "cats": ["حبوب وتموينات", "مشروبات", "زيوت وسمن", "معلبات", "منظفات جملة"],
        "prods": [
            ("أرز خام 50 كيلو — كرتون",     "حبوب وتموينات", 280.0, 196.0),
            ("سكر أبيض 50 كيلو — كيس",      "حبوب وتموينات", 210.0, 147.0),
            ("طحين 50 كيلو — كيس",           "حبوب وتموينات", 190.0, 133.0),
            ("زيت نخيل 1.5 لتر — صندوق 12", "زيوت وسمن",    450.0, 315.0),
            ("سمن نباتي — صندوق 12",         "زيوت وسمن",    380.0, 266.0),
            ("مياه 0.5 لتر — باليت",         "مشروبات",      850.0, 595.0),
            ("مياه 1.5 لتر — كرتون",         "مشروبات",       95.0,  66.5),
            ("عصير معلب — صندوق 24",         "مشروبات",      180.0, 126.0),
            ("تونة معلبة — كرتون 24",        "معلبات",       240.0, 168.0),
            ("صلصة طماطم — صندوق 12",        "معلبات",       120.0,  84.0),
            ("صابون بار — ربطة 72",          "منظفات جملة",  280.0, 196.0),
            ("مسحوق غسيل 5 كيلو — كرتون",   "منظفات جملة",  350.0, 245.0),
        ],
    },
    "wholesale_fashion_clothing": {
        "cats": ["ملابس رجالي جملة", "ملابس نسائي جملة", "ملابس أطفال جملة", "إكسسوارات جملة"],
        "prods": [
            ("قميص رجالي — كرتون 24",    "ملابس رجالي جملة",  960.0,  672.0),
            ("تيشيرت قطن — ربطة 12",     "ملابس رجالي جملة",  540.0,  378.0),
            ("جينز رجالي — صندوق 12",    "ملابس رجالي جملة",  840.0,  588.0),
            ("عباية سوداء — صندوق 12",   "ملابس نسائي جملة", 1800.0, 1260.0),
            ("حجاب شيفون — ربطة 24",     "ملابس نسائي جملة",  480.0,  336.0),
            ("فستان سهرة — صندوق 6",     "ملابس نسائي جملة", 1200.0,  840.0),
            ("لبس أطفال 3 قطع — كرتون",  "ملابس أطفال جملة",  720.0,  504.0),
            ("بيبي رومبر — ربطة 12",     "ملابس أطفال جملة",  360.0,  252.0),
            ("جوارب رجالي — ربطة 12",    "إكسسوارات جملة",    180.0,  126.0),
            ("حزام جلد — ربطة 12",       "إكسسوارات جملة",    360.0,  252.0),
        ],
    },
    "wholesale_auto_parts": {
        "cats": ["فلاتر", "زيوت وسوائل", "بطاريات", "إطارات", "كهربائيات سيارات"],
        "prods": [
            ("فلتر زيت — كرتون 24",      "فلاتر",             450.0,  315.0),
            ("فلتر هواء — كرتون 12",     "فلاتر",             360.0,  252.0),
            ("فلتر مكيف — كرتون 12",     "فلاتر",             280.0,  196.0),
            ("زيت محرك 4L — كرتون 6",   "زيوت وسوائل",       480.0,  336.0),
            ("سائل فرامل — كرتون 12",    "زيوت وسوائل",       240.0,  168.0),
            ("بطارية 70 أمبير — صندوق",  "بطاريات",          1400.0,  980.0),
            ("إطار 205/55R16 — 4 قطع",   "إطارات",           1120.0,  784.0),
            ("مصباح أمامي LED — ربطة",   "كهربائيات سيارات",  320.0,  224.0),
        ],
    },
    "wholesale_electronics_general": {
        "cats": ["أجهزة إلكترونية", "إكسسوارات", "شاشات وتلفزيون", "بطاريات وشحن", "أسلاك وتوصيل"],
        "prods": [
            ("شاشة 43 بوصة — كرتون",     "شاشات وتلفزيون", 1200.0,  840.0),
            ("شاشة 55 بوصة — كرتون",     "شاشات وتلفزيون", 1800.0, 1260.0),
            ("سماعة بلوتوث — صندوق 6",   "إكسسوارات",      480.0,  336.0),
            ("شاحن سريع — ربطة 12",      "بطاريات وشحن",   360.0,  252.0),
            ("كابل USB-C — ربطة 24",     "أسلاك وتوصيل",   180.0,  126.0),
            ("بطارية AA — كرتون 24 علبة","بطاريات وشحن",   480.0,  336.0),
            ("كفر جوال — صندوق 20",      "إكسسوارات",      280.0,  196.0),
        ],
    },
}

def ensure_cats(cur, biz_id, cats):
    cat_map = {}
    for c in cats:
        row = cur.execute("SELECT id FROM product_categories WHERE business_id=? AND name=?", (biz_id, c)).fetchone()
        if row:
            cat_map[c] = row[0]
        else:
            cur.execute("INSERT INTO product_categories (business_id, name, is_active) VALUES (?,?,1)", (biz_id, c))
            cat_map[c] = cur.lastrowid
    return cat_map

def add_products(cur, biz_id, cat_map, prods):
    added = 0
    for name, cat, price, cost in prods:
        if cur.execute("SELECT 1 FROM products WHERE business_id=? AND name=?", (biz_id, name)).fetchone():
            continue
        cur.execute("""
            INSERT INTO products (business_id, barcode, name, product_type,
               category_id, category_name, can_purchase, purchase_price, can_sell, sale_price,
               track_stock, is_pos, is_active, created_at, updated_at)
            VALUES (?,?,?,'product', ?,?, 1,?,1,?, 1,1,1, ?,?)
        """, (biz_id, barcode(), name,
              cat_map.get(cat), cat, cost, price, NOW, NOW))
        added += 1
    return added

conn = sqlite3.connect(DB)
cur  = conn.cursor()

# تحديد البيزنيسات التي تحتاج تلقيم
cur.execute("""
    SELECT b.id, b.name, b.industry_type
    FROM businesses b
    WHERE b.industry_type LIKE 'wholesale_%' OR b.industry_type = 'wholesale'
    ORDER BY b.id
""")
bizs = cur.fetchall()

total_added = 0
for biz_id, biz_name, industry_type in bizs:
    cur.execute("SELECT COUNT(*) FROM products WHERE business_id=?", (biz_id,))
    cnt_before = cur.fetchone()[0]

    # تحديد بيانات البذور المناسبة
    seed_key = None
    for k in WHOLESALE_PRODUCTS:
        if industry_type.startswith(k) or industry_type == k:
            seed_key = k
            break
    if seed_key is None:
        seed_key = "wholesale_fnb_general"  # افتراضي للجملة

    seed = WHOLESALE_PRODUCTS[seed_key]
    cat_map = ensure_cats(cur, biz_id, seed["cats"])
    added   = add_products(cur, biz_id, cat_map, seed["prods"])
    total_added += added
    print(f"[{biz_id}] {biz_name} ({industry_type}): كان {cnt_before} → أضفنا {added} منتج")

conn.commit()
conn.close()
print(f"\n✅ الإجمالي المضاف: {total_added} منتج")
