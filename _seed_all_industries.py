#!/usr/bin/env python3
"""
إنشاء منشأة حقيقية لكل industry_type في config.py
ويُذرّ منتجات من industry_seeds.py لكل منشأة.
"""

import sqlite3, sys, os, copy, random, re
sys.stdout = __import__('io').TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

DB_PATH = os.path.join(os.path.dirname(__file__), 'database', 'accounting_dev.db')

# ─── أسماء المنشآت لكل نشاط ────────────────────────────────────────────────
BUSINESS_NAMES: dict[str, str] = {
    "retail":                          "المتجر العام للتجزئة",
    "wholesale":                       "شركة التجارة العامة للجملة",
    "restaurant":                      "مطعم النخبة للمأكولات",
    "retail_fnb_supermarket":          "سوبرماركت الوفاء",
    "retail_fnb_grocery":              "بقالة البركة",
    "retail_fnb_roaster":              "محمصة القهوة العربية",
    "retail_fnb_bakery":               "مخبز الخير للمخبوزات",
    "retail_fnb_butcher":              "ملحمة الطازج",
    "retail_fnb_produce":              "سوق الخضار والفواكه",
    "retail_fnb_dates":                "متجر التمور الذهبية",
    "retail_fnb_beverages":            "متجر المشروبات المتنوعة",
    "retail_fashion_clothing_m":       "بوتيك الرجل الأنيق",
    "retail_fashion_clothing_f":       "بوتيك الأزياء النسائية",
    "retail_fashion_clothing_k":       "متجر ملابس الأطفال",
    "retail_fashion_shoes":            "متجر الأحذية الفاخرة",
    "retail_fashion_bags":             "متجر الحقائب والشنط",
    "retail_fashion_watches":          "متجر الساعات والمجوهرات",
    "retail_fashion_optics":           "بصريات النور",
    "retail_fashion_fabric":           "دار الأقمشة والنسيج",
    "retail_fashion_tailoring":        "بيت الخياطة والتفصيل",
    "retail_construction_materials":   "معرض مواد البناء والتشييد",
    "retail_construction_plumbing":    "متجر لوازم السباكة",
    "retail_construction_electrical":  "متجر الأدوات الكهربائية",
    "retail_construction_paints":      "محل الدهانات والألوان",
    "retail_construction_flooring":    "معرض الأرضيات والسيراميك",
    "retail_construction_hardware":    "متجر العدد والأدوات اليدوية",
    "retail_electronics_mobile":       "متجر الجوالات والإلكترونيات",
    "retail_electronics_computers":    "متجر الحاسبات ومستلزماتها",
    "retail_electronics_appliances":   "معرض الأجهزة الكهربائية المنزلية",
    "retail_electronics_entertainment":"متجر الترفيه والألعاب الإلكترونية",
    "retail_electronics_security":     "متجر كاميرات المراقبة والأمن",
    "retail_health_pharmacy":          "صيدلية الشفاء",
    "صيدلية":                          "صيدلية الأمل",
    "retail_health_perfume":           "متجر العطور والبخور",
    "retail_health_cosmetics":         "متجر مستحضرات التجميل",
    "retail_health_medical":           "متجر الأجهزة الطبية",
    "retail_health_supplements":       "متجر المكملات الغذائية",
    "retail_auto_parts":               "متجر قطع غيار السيارات",
    "retail_auto_tires":               "متجر الإطارات والبطاريات",
    "retail_auto_accessories":         "متجر إكسسوارات السيارات",
    "retail_auto_workshop":            "ورشة الصيانة الشاملة",
    "retail_home_furniture":           "معرض الأثاث والديكور",
    "retail_home_carpet":              "معرض السجاد والموكيت",
    "retail_home_kitchenware":         "متجر أدوات المطبخ والمنزل",
    "retail_home_stationery":          "متجر القرطاسية والمكتبة",
    "retail_home_office":              "متجر الأثاث والمعدات المكتبية",
    "retail_specialized_tobacco":      "متجر الدخان والنارجيلة",
    "retail_specialized_flowers":      "محل الورود والزهور",
    "retail_specialized_toys":         "متجر الألعاب والترفيه للأطفال",
    "retail_specialized_pets":         "متجر الحيوانات الأليفة ومستلزماتها",
    "retail_specialized_sports":       "متجر الأدوات والملابس الرياضية",
    "retail_specialized_camping":      "متجر التخييم والرحلات",
    "wholesale_fnb_distribution":      "شركة التوزيع الغذائي الشاملة",
    "wholesale_fnb_beverages":         "شركة جملة المشروبات",
    "wholesale_fnb_roaster":           "شركة جملة القهوة والبهارات",
    "wholesale_fnb_general":           "شركة التجارة الغذائية بالجملة",
    "wholesale_fnb_bakery":            "شركة جملة مواد المخابز",
    "wholesale_fnb_butcher":           "شركة جملة اللحوم والدواجن",
    "wholesale_fnb_produce":           "شركة جملة الخضار والفواكه",
    "wholesale_fnb_dates":             "شركة جملة التمور والمنتجات الزراعية",
    "wholesale_fashion_clothing":      "شركة جملة الملابس الجاهزة",
    "wholesale_fashion_fabric":        "شركة جملة الأقمشة والنسيج",
    "wholesale_fashion_shoes":         "شركة جملة الأحذية",
    "wholesale_fashion_bags":          "شركة جملة الحقائب",
    "wholesale_fashion_clothing_m":    "شركة جملة الملابس الرجالية",
    "wholesale_fashion_clothing_f":    "شركة جملة الملابس النسائية",
    "wholesale_fashion_clothing_k":    "شركة جملة ملابس الأطفال",
    "wholesale_fashion_watches":       "شركة جملة الساعات والمجوهرات",
    "wholesale_fashion_optics":        "شركة جملة البصريات والنظارات",
    "wholesale_construction_materials":"شركة جملة مواد البناء",
    "wholesale_construction_timber":   "شركة جملة الأخشاب ومواد التشطيب",
    "wholesale_construction_plumbing": "شركة جملة لوازم السباكة",
    "wholesale_construction_electrical":"شركة جملة الأدوات والمواد الكهربائية",
    "wholesale_construction_paints":   "شركة جملة الدهانات ومواد الطلاء",
    "wholesale_construction_flooring": "شركة جملة الأرضيات والسيراميك",
    "wholesale_electronics_general":   "شركة جملة الإلكترونيات العامة",
    "wholesale_electronics_mobile":    "شركة جملة الجوالات والأجهزة الذكية",
    "wholesale_electronics_computers": "شركة جملة الحاسبات والأجهزة",
    "wholesale_electronics_appliances":"شركة جملة الأجهزة الكهربائية المنزلية",
    "wholesale_electronics_entertainment":"شركة جملة أجهزة الترفيه والألعاب",
    "wholesale_health_medical":        "شركة جملة الأجهزة والمستلزمات الطبية",
    "wholesale_health_pharmacy":       "شركة جملة الأدوية ومستلزمات الصيدليات",
    "wholesale_health_perfume":        "شركة جملة العطور والبخور",
    "wholesale_health_cosmetics":      "شركة جملة مستحضرات التجميل",
    "wholesale_health_supplements":    "شركة جملة المكملات الغذائية والفيتامينات",
    "wholesale_auto_parts":            "شركة جملة قطع غيار السيارات",
    "wholesale_auto_tires":            "شركة جملة الإطارات والبطاريات",
    "wholesale_auto_accessories":      "شركة جملة إكسسوارات السيارات",
    "wholesale_auto_workshop":         "شركة جملة معدات الورش والصيانة",
    "wholesale_home_furniture":        "شركة جملة الأثاث والمفروشات",
    "wholesale_home_carpet":           "شركة جملة السجاد والموكيت",
    "wholesale_home_kitchenware":      "شركة جملة أدوات المطبخ",
    "wholesale_home_stationery":       "شركة جملة القرطاسية والمكتبية",
    "wholesale_home_office":           "شركة جملة الأثاث المكتبي",
    "wholesale_specialized_tobacco":   "شركة جملة الدخان والنارجيلة",
    "wholesale_specialized_flowers":   "شركة جملة الورود والزهور",
    "wholesale_specialized_toys":      "شركة جملة الألعاب والهدايا",
    "wholesale_specialized_pets":      "شركة جملة مستلزمات الحيوانات الأليفة",
    "wholesale_specialized_sports":    "شركة جملة الأدوات الرياضية",
    "wholesale_specialized_camping":   "شركة جملة معدات التخييم والرياضة الخارجية",
    "food_restaurant":                 "مطعم الوجبات الذهبية",
    "مطعم":                            "مطعم الأصالة العربية",
    "food_cafe":                       "كافيه السحاب",
    "كافيه":                           "كافيه الربيع",
    "food_coffeeshop":                 "قهوة المختصة",
    "مقهى":                            "مقهى الديوانية",
    "food_hookah":                     "استراحة الشيشة",
    "medical_complex":                 "المجمع الطبي الشامل",
    "construction":                    "شركة البناء والتشييد الحديثة",
    "car_rental":                      "شركة تأجير السيارات",
    "medical":                         "العيادة الطبية المتخصصة",
    "services":                        "شركة الخدمات المتكاملة",
}

# ─── خريطة الأنشطة العربية إلى نظيراتها الإنجليزية للبذور ──────────────────
ARABIC_TYPE_MAP: dict[str, str] = {
    "صيدلية": "retail_health_pharmacy",
    "مطعم":   "food_restaurant",
    "كافيه":  "food_cafe",
    "مقهى":   "food_coffeeshop",
    "restaurant": "food_restaurant",
    "medical_complex": "medical",
}

# ─── بذور مدمجة مباشرة (لتفادي الاستيراد المعقد) ───────────────────────────
# نستورد مباشرة من industry_seeds.py
sys.path.insert(0, os.path.dirname(__file__))
from modules.industry_seeds import seed_industry_defaults, _get_seed, _prepare_seed_for_activity

TARGET_PRODUCTS = 300  # عدد المنتجات لكل منشأة

SUFFIXES = [
    "", " - نوع أ", " - نوع ب", " - نوع ج",
    " - ممتاز", " - اقتصادي", " - درجة أولى",
    " - استيراد", " - محلي", " - صناعي", " - طبيعي",
]


def expand_and_insert_products(
    conn: sqlite3.Connection, biz_id: int, seed_products: list, target: int
):
    """يوسّع المنتجات الأساسية ويُدخلها مباشرة في DB."""
    c = conn.cursor()
    # جمع الفئات الموجودة
    cat_rows = c.execute(
        "SELECT name, id FROM product_categories WHERE business_id=?", (biz_id,)
    ).fetchall()
    cat_id_map = {r[0]: r[1] for r in cat_rows}
    cats = list(cat_id_map.keys())

    # عدد المنتجات الحالية
    current_count = c.execute(
        "SELECT COUNT(*) FROM products WHERE business_id=?", (biz_id,)
    ).fetchone()[0]

    needed = max(0, target - current_count)
    if needed == 0:
        return 0

    inserted = 0
    i = 0
    prefix = industry_type_prefix(biz_id)
    sku_start = current_count + 1

    while inserted < needed:
        base = seed_products[i % len(seed_products)]
        suf_idx = (i // len(seed_products)) + 1
        sfx = SUFFIXES[suf_idx % len(SUFFIXES)]

        p_name  = base.get("name", f"منتج {i}") + (sfx if suf_idx > 0 else "")
        p_cat   = base.get("category", cats[0] if cats else "منتجات")
        p_price = float(base.get("price", 50.0))
        p_type  = base.get("product_type", "product")
        cat_id  = cat_id_map.get(p_cat)

        # فئة جديدة إن لم تكن موجودة
        if cat_id is None:
            c.execute(
                "INSERT INTO product_categories (business_id, name, is_active) VALUES (?,?,1)",
                (biz_id, p_cat)
            )
            cat_id = c.lastrowid
            cat_id_map[p_cat] = cat_id

        purchase_price = round(p_price * 0.7, 2)
        sku = f"{prefix}-{sku_start + inserted:04d}"

        c.execute("""
            INSERT INTO products
              (business_id, name, product_type, category_id, category_name,
               sale_price, purchase_price, is_active, is_pos, track_stock)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, 1)
        """, (biz_id, p_name, p_type, cat_id, p_cat, p_price, purchase_price))
        prod_id = c.lastrowid

        qty = random.randint(50, 500)
        c.execute("""
            INSERT INTO product_inventory
              (business_id, product_id, sku, current_qty, min_qty, max_qty,
               unit_cost, unit_price)
            VALUES (?, ?, ?, ?, 10, 1000, ?, ?)
        """, (biz_id, prod_id, sku, qty, purchase_price, p_price))

        inserted += 1
        i += 1

    return inserted


def industry_type_prefix(biz_id: int) -> str:
    return f"B{biz_id}"


def seed_business(conn: sqlite3.Connection, industry_type: str) -> int:
    """ينشئ منشأة واحدة مع منتجاتها — يُرجع business_id."""
    c = conn.cursor()

    biz_name = BUSINESS_NAMES.get(industry_type, f"منشأة {industry_type}")

    # التحقق من عدم التكرار بالاسم
    existing = c.execute(
        "SELECT id FROM businesses WHERE name = ?", (biz_name,)
    ).fetchone()
    if existing:
        biz_id = existing[0]
        cnt = c.execute("SELECT COUNT(*) FROM products WHERE business_id=?", (biz_id,)).fetchone()[0]
        print(f"  ⟳ موجود مسبقاً: {biz_name} [{biz_id}] ({cnt} منتج)")
        return biz_id

    # إنشاء المنشأة
    c.execute("""
        INSERT INTO businesses (name, industry_type, country, currency, country_code, is_active)
        VALUES (?, ?, 'SA', 'SAR', 'SA', 1)
    """, (biz_name, industry_type))
    biz_id = c.lastrowid
    conn.commit()

    # البذر الأساسي عبر seed_industry_defaults
    seed_key = ARABIC_TYPE_MAP.get(industry_type, industry_type)
    try:
        summary = seed_industry_defaults(conn, biz_id, seed_key)
        base_count = summary.get("products_inserted", 0)
    except Exception as e:
        print(f"    ⚠ seed_industry_defaults فشلت ({e})")
        base_count = 0

    # توسيع إلى TARGET_PRODUCTS
    seed = _prepare_seed_for_activity(_get_seed(seed_key), seed_key)
    seed_products = seed.get("products", [
        {"name": "منتج نموذجي", "category": "منتجات", "price": 50.0, "unit": "قطعة"}
    ])

    added = expand_and_insert_products(conn, biz_id, seed_products, TARGET_PRODUCTS)
    conn.commit()

    total = base_count + added
    print(f"  ✓ [{biz_id}] {biz_name} — {total} منتج ({base_count} أساسي + {added} موسّع)")
    return biz_id


def main():
    # قراءة INDUSTRY_TYPES من config.py
    cfg_path = os.path.join(os.path.dirname(__file__), 'modules', 'config.py')
    with open(cfg_path, encoding='utf-8') as f:
        cfg_text = f.read()

    it_match = re.search(r'INDUSTRY_TYPES\s*=\s*\[(.+?)\]', cfg_text, re.DOTALL)
    if not it_match:
        print("❌ لم يُعثر على INDUSTRY_TYPES في config.py")
        return

    raw = it_match.group(1)
    # استخراج المفاتيح (الجزء الأول من كل tuple)
    industry_types = re.findall(r'"([\w\u0600-\u06FF_]+)"', raw)
    # إزالة التكرار مع الحفاظ على الترتيب
    seen = set()
    unique_types = []
    for t in industry_types:
        if t not in seen:
            seen.add(t)
            unique_types.append(t)

    print(f"📋 إجمالي INDUSTRY_TYPES: {len(unique_types)}")

    conn = sqlite3.connect(DB_PATH)

    # فحص الموجود مسبقاً
    existing_rows = conn.execute(
        "SELECT industry_type FROM businesses"
    ).fetchall()
    existing_types = {r[0] for r in existing_rows}

    missing = [t for t in unique_types if t not in existing_types]
    print(f"➕ أنشطة مطلوب إنشاؤها: {len(missing)}\n")

    for itype in missing:
        try:
            seed_business(conn, itype)
        except Exception as e:
            print(f"  ❌ خطأ في {itype}: {e}")
            conn.rollback()

    # إحصائيات نهائية
    total_biz = conn.execute("SELECT COUNT(*) FROM businesses").fetchone()[0]
    total_prod = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    print(f"\n{'='*55}")
    print(f"✅ الإجمالي: {total_biz} منشأة — {total_prod:,} منتج")
    conn.close()


if __name__ == "__main__":
    main()
