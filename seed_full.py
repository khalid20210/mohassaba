"""
seed_full.py — إضافة منتجات كاملة لجميع الأنشطة التجارية
الهدف:
  - المتجر الرئيسي (retail/wholesale): 10,000 منتج
  - كل نشاط آخر: 2,000 منتج
"""
import sqlite3, datetime, random, itertools

DB  = "database/accounting.db"
NOW = datetime.datetime.now().isoformat(sep=" ", timespec="seconds")

# ══════════════════════════════════════════════════════════
# أدوات مساعدة
# ══════════════════════════════════════════════════════════
def ensure_cats(cur, biz_id, cats):
    cat_map = {}
    for c in cats:
        row = cur.execute(
            "SELECT id FROM product_categories WHERE business_id=? AND name=?",
            (biz_id, c)
        ).fetchone()
        if row:
            cat_map[c] = row[0]
        else:
            cur.execute(
                "INSERT INTO product_categories (business_id, name, is_active) VALUES (?,?,1)",
                (biz_id, c)
            )
            cat_map[c] = cur.lastrowid
    return cat_map


def existing_names(cur, biz_id):
    rows = cur.execute(
        "SELECT name FROM products WHERE business_id=?", (biz_id,)
    ).fetchall()
    return {r[0] for r in rows}


def batch_insert(cur, biz_id, cat_map, rows):
    """rows = list of (name, name_en, barcode, cat_name, sale_price, purchase_price)"""
    added = 0
    for name, name_en, barcode, cat_name, sale, purchase in rows:
        cur.execute("""
            INSERT INTO products
              (business_id, barcode, name, name_en, product_type,
               category_id, category_name,
               can_purchase, purchase_price,
               can_sell, sale_price,
               track_stock, is_pos, is_active,
               created_at, updated_at)
            VALUES (?,?,?,?,'product',
                    ?,?,
                    1,?,
                    1,?,
                    1,1,1,
                    ?,?)
        """, (biz_id, barcode, name, name_en,
              cat_map.get(cat_name), cat_name,
              purchase, sale,
              NOW, NOW))
        added += 1
    return added


def gen_barcode(prefix, n):
    return f"{prefix}{n:07d}"


# ══════════════════════════════════════════════════════════
# BUSINESS 1 — المتجر الرئيسي (wholesale retail) → 10,000
# ══════════════════════════════════════════════════════════
def seed_retail_main(cur, biz_id, target=10000):
    cats = [
        "مواد غذائية أساسية", "مشروبات", "معلبات وأغذية محفوظة",
        "حبوب وبقوليات", "زيوت وسمن", "منظفات ومواد العناية",
        "مجمدات", "ألبان ومشتقات", "حلويات ومكسرات",
        "توابل وبهارات", "منتجات خبز وطحين", "أدوات منزلية",
        "مستلزمات المطبخ", "منتجات التنظيف الشخصي"
    ]
    cat_map = ensure_cats(cur, biz_id, cats)
    existing = existing_names(cur, biz_id)

    brands_food = [
        "الطيب", "النخيل", "السفير", "الفجر", "الغلة", "الريف", "البستان",
        "الخير", "الأمانة", "الوفاء", "الأصيل", "المزرعة", "الراشد",
        "الفيصل", "التميز", "الجوهرة", "المياه", "النهضة", "الجزيرة", "العقيلة"
    ]
    brands_clean = [
        "برايت", "كلين بلاس", "فريش", "ميكا", "أكتيف", "سافون", "دايلون",
        "بريميوم كلين", "إيكو", "هوم كير"
    ]
    sizes_food = ["250 غ", "500 غ", "1 كغ", "2 كغ", "5 كغ", "10 كغ", "20 كغ",
                  "250 مل", "500 مل", "1 لتر", "1.5 لتر", "2 لتر", "5 لتر"]
    sizes_bev  = ["200 مل", "250 مل", "330 مل", "500 مل", "1 لتر", "1.5 لتر",
                  "2 لتر", "3 لتر", "5 لتر", "6 × 500 مل", "12 × 330 مل", "24 × 250 مل"]

    # قوائم المنتجات الأساسية
    grains = [
        ("أرز بسمتي","Basmati Rice","حبوب وبقوليات"),
        ("أرز مصري","Egyptian Rice","حبوب وبقوليات"),
        ("أرز أبو كاس","Short Grain Rice","حبوب وبقوليات"),
        ("أرز ياسمين","Jasmine Rice","حبوب وبقوليات"),
        ("عدس أخضر","Green Lentils","حبوب وبقوليات"),
        ("عدس أحمر","Red Lentils","حبوب وبقوليات"),
        ("حمص مجروش","Ground Chickpeas","حبوب وبقوليات"),
        ("حمص حبة","Whole Chickpeas","حبوب وبقوليات"),
        ("فول مدمس","Fava Beans","حبوب وبقوليات"),
        ("فاصوليا بيضاء","White Beans","حبوب وبقوليات"),
        ("لوبيا حمراء","Red Kidney Beans","حبوب وبقوليات"),
        ("برغل خشن","Coarse Bulgur","حبوب وبقوليات"),
        ("برغل ناعم","Fine Bulgur","حبوب وبقوليات"),
        ("شعير","Barley","حبوب وبقوليات"),
        ("ذرة صفراء","Yellow Corn","حبوب وبقوليات"),
        ("دقيق قمح","Wheat Flour","منتجات خبز وطحين"),
        ("دقيق ذرة","Corn Flour","منتجات خبز وطحين"),
        ("دقيق حمص","Chickpea Flour","منتجات خبز وطحين"),
        ("سميد خشن","Coarse Semolina","منتجات خبز وطحين"),
        ("سميد ناعم","Fine Semolina","منتجات خبز وطحين"),
        ("نشا ذرة","Corn Starch","منتجات خبز وطحين"),
        ("خميرة فورية","Instant Yeast","منتجات خبز وطحين"),
        ("بيكنج باودر","Baking Powder","منتجات خبز وطحين"),
    ]
    oils = [
        ("زيت زيتون","Olive Oil","زيوت وسمن"),
        ("زيت ذرة","Corn Oil","زيوت وسمن"),
        ("زيت دوار الشمس","Sunflower Oil","زيوت وسمن"),
        ("زيت فول السوداني","Peanut Oil","زيوت وسمن"),
        ("زيت جوز الهند","Coconut Oil","زيوت وسمن"),
        ("سمن بلدي","Ghee Local","زيوت وسمن"),
        ("سمن نباتي","Vegetable Ghee","زيوت وسمن"),
        ("زبدة مملحة","Salted Butter","زيوت وسمن"),
        ("زبدة غير مملحة","Unsalted Butter","زيوت وسمن"),
        ("مارغرين","Margarine","زيوت وسمن"),
    ]
    dairy = [
        ("حليب كامل الدسم","Full Fat Milk","ألبان ومشتقات"),
        ("حليب قليل الدسم","Low Fat Milk","ألبان ومشتقات"),
        ("حليب خالي الدسم","Skimmed Milk","ألبان ومشتقات"),
        ("حليب بالشوكولاتة","Chocolate Milk","ألبان ومشتقات"),
        ("حليب بالفراولة","Strawberry Milk","ألبان ومشتقات"),
        ("لبن زبادي سادة","Plain Yogurt","ألبان ومشتقات"),
        ("لبن زبادي فواكه","Fruit Yogurt","ألبان ومشتقات"),
        ("جبنة بيضاء","White Cheese","ألبان ومشتقات"),
        ("جبنة شيدر","Cheddar Cheese","ألبان ومشتقات"),
        ("جبنة ركبي","Rumi Cheese","ألبان ومشتقات"),
        ("جبنة كريمية","Cream Cheese","ألبان ومشتقات"),
        ("قشطة","Fresh Cream","ألبان ومشتقات"),
        ("لبن رائب","Buttermilk","ألبان ومشتقات"),
    ]
    canned = [
        ("تونة بالزيت","Tuna in Oil","معلبات وأغذية محفوظة"),
        ("تونة بالماء","Tuna in Water","معلبات وأغذية محفوظة"),
        ("سردين","Sardines","معلبات وأغذية محفوظة"),
        ("فول معلب","Canned Fava","معلبات وأغذية محفوظة"),
        ("حمص معلب","Canned Chickpeas","معلبات وأغذية محفوظة"),
        ("فاصوليا خضراء معلبة","Canned Green Beans","معلبات وأغذية محفوظة"),
        ("ذرة معلبة","Canned Corn","معلبات وأغذية محفوظة"),
        ("طماطم معلبة مقطعة","Diced Canned Tomato","معلبات وأغذية محفوظة"),
        ("معجون طماطم","Tomato Paste","معلبات وأغذية محفوظة"),
        ("مربى فراولة","Strawberry Jam","معلبات وأغذية محفوظة"),
        ("مربى مشمش","Apricot Jam","معلبات وأغذية محفوظة"),
        ("مربى تين","Fig Jam","معلبات وأغذية محفوظة"),
        ("مربى برتقال","Orange Marmalade","معلبات وأغذية محفوظة"),
        ("عسل نحل","Honey","معلبات وأغذية محفوظة"),
        ("طحينة","Tahini","معلبات وأغذية محفوظة"),
        ("زيتون أخضر","Green Olives","معلبات وأغذية محفوظة"),
        ("زيتون أسود","Black Olives","معلبات وأغذية محفوظة"),
        ("خيار مخلل","Pickled Cucumber","معلبات وأغذية محفوظة"),
        ("مخلل مشكل","Mixed Pickles","معلبات وأغذية محفوظة"),
        ("فليفلة محشوة","Stuffed Pepper","معلبات وأغذية محفوظة"),
    ]
    beverages = [
        ("مياه معدنية","Mineral Water","مشروبات"),
        ("مياه غازية","Sparkling Water","مشروبات"),
        ("عصير برتقال","Orange Juice","مشروبات"),
        ("عصير مانغو","Mango Juice","مشروبات"),
        ("عصير تفاح","Apple Juice","مشروبات"),
        ("عصير أناناس","Pineapple Juice","مشروبات"),
        ("عصير جوافة","Guava Juice","مشروبات"),
        ("عصير رمان","Pomegranate Juice","مشروبات"),
        ("عصير قصب","Cane Juice","مشروبات"),
        ("مشروب غازي كولا","Cola Soda","مشروبات"),
        ("مشروب غازي ليمون","Lemon Soda","مشروبات"),
        ("مشروب غازي برتقال","Orange Soda","مشروبات"),
        ("مشروب طاقة","Energy Drink","مشروبات"),
        ("شاي أسود","Black Tea","مشروبات"),
        ("شاي أخضر","Green Tea","مشروبات"),
        ("قهوة سريعة التحضير","Instant Coffee","مشروبات"),
        ("قهوة عربية","Arabic Coffee","مشروبات"),
        ("نسكافيه","Nescafe","مشروبات"),
        ("كاكاو","Cocoa","مشروبات"),
        ("حليب بالكاكاو","Chocolate Drink","مشروبات"),
    ]
    spices = [
        ("ملح طعام","Table Salt","توابل وبهارات"),
        ("فلفل أسود","Black Pepper","توابل وبهارات"),
        ("فلفل أحمر","Red Pepper","توابل وبهارات"),
        ("كمون","Cumin","توابل وبهارات"),
        ("كركم","Turmeric","توابل وبهارات"),
        ("زعتر","Thyme","توابل وبهارات"),
        ("هيل","Cardamom","توابل وبهارات"),
        ("قرفة","Cinnamon","توابل وبهارات"),
        ("زنجبيل","Ginger","توابل وبهارات"),
        ("بهارات مشكلة","Mixed Spices","توابل وبهارات"),
        ("أعشاب بروفانس","Herbs de Provence","توابل وبهارات"),
        ("خل أبيض","White Vinegar","توابل وبهارات"),
        ("خل تفاح","Apple Vinegar","توابل وبهارات"),
        ("صلصة الصويا","Soy Sauce","توابل وبهارات"),
        ("صلصة الحارة","Hot Sauce","توابل وبهارات"),
        ("مستردة","Mustard","توابل وبهارات"),
        ("مايونيز","Mayonnaise","توابل وبهارات"),
        ("كاتشب","Ketchup","توابل وبهارات"),
        ("سكر أبيض","White Sugar","مواد غذائية أساسية"),
        ("سكر بني","Brown Sugar","مواد غذائية أساسية"),
    ]
    sweets = [
        ("شوكولاتة داكنة","Dark Chocolate","حلويات ومكسرات"),
        ("شوكولاتة حليب","Milk Chocolate","حلويات ومكسرات"),
        ("شوكولاتة بيضاء","White Chocolate","حلويات ومكسرات"),
        ("حلوى قطعة","Candy","حلويات ومكسرات"),
        ("علكة فواكه","Fruit Gum","حلويات ومكسرات"),
        ("مكسرات مشكلة","Mixed Nuts","حلويات ومكسرات"),
        ("لوز محمص","Roasted Almonds","حلويات ومكسرات"),
        ("فستق محمص","Roasted Pistachios","حلويات ومكسرات"),
        ("كاجو","Cashews","حلويات ومكسرات"),
        ("تمر مجدول","Medjool Dates","حلويات ومكسرات"),
        ("تمر سكري","Sukkari Dates","حلويات ومكسرات"),
        ("زبيب","Raisins","حلويات ومكسرات"),
        ("مشمش مجفف","Dried Apricots","حلويات ومكسرات"),
        ("تين مجفف","Dried Figs","حلويات ومكسرات"),
        ("بسكويت شاي","Tea Biscuit","حلويات ومكسرات"),
        ("بسكويت شوكولاتة","Chocolate Biscuit","حلويات ومكسرات"),
        ("كيك سادة","Plain Cake","حلويات ومكسرات"),
        ("كيك شوكولاتة","Chocolate Cake","حلويات ومكسرات"),
        ("شيبس","Chips","حلويات ومكسرات"),
        ("فشار مملح","Salted Popcorn","حلويات ومكسرات"),
    ]
    frozen = [
        ("دجاج مجمد كامل","Whole Frozen Chicken","مجمدات"),
        ("فيليه دجاج مجمد","Frozen Chicken Fillet","مجمدات"),
        ("أرجل دجاج مجمدة","Frozen Chicken Legs","مجمدات"),
        ("أجنحة دجاج مجمدة","Frozen Chicken Wings","مجمدات"),
        ("لحم مفروم مجمد","Frozen Ground Meat","مجمدات"),
        ("سمك كامل مجمد","Whole Frozen Fish","مجمدات"),
        ("جمبري مجمد","Frozen Shrimp","مجمدات"),
        ("بازلاء مجمدة","Frozen Peas","مجمدات"),
        ("ذرة مجمدة","Frozen Corn","مجمدات"),
        ("خضار مشكلة مجمدة","Frozen Mixed Vegetables","مجمدات"),
        ("بطاطس مقلية مجمدة","Frozen French Fries","مجمدات"),
        ("سمبوسة مجمدة","Frozen Sambusa","مجمدات"),
        ("بيتزا مجمدة","Frozen Pizza","مجمدات"),
    ]
    cleaning = [
        ("سائل جلي صحون","Dish Washing Liquid","منظفات ومواد العناية"),
        ("مسحوق غسيل","Laundry Powder","منظفات ومواد العناية"),
        ("سائل غسيل ملابس","Liquid Laundry Detergent","منظفات ومواد العناية"),
        ("منظف متعدد الأغراض","Multi-Purpose Cleaner","منظفات ومواد العناية"),
        ("منظف الحمام","Bathroom Cleaner","منظفات ومواد العناية"),
        ("معطر جو","Air Freshener","منظفات ومواد العناية"),
        ("مبيض ملابس","Bleach","منظفات ومواد العناية"),
        ("منظف الأرضيات","Floor Cleaner","منظفات ومواد العناية"),
        ("سائل تلميع","Polish","منظفات ومواد العناية"),
        ("شامبو شعر","Shampoo","منتجات التنظيف الشخصي"),
        ("بلسم شعر","Conditioner","منتجات التنظيف الشخصي"),
        ("صابون استحمام","Bath Soap","منتجات التنظيف الشخصي"),
        ("سائل استحمام","Body Wash","منتجات التنظيف الشخصي"),
        ("معجون أسنان","Toothpaste","منتجات التنظيف الشخصي"),
        ("فرشاة أسنان","Toothbrush","منتجات التنظيف الشخصي"),
        ("مزيل عرق","Deodorant","منتجات التنظيف الشخصي"),
        ("مناديل ورقية","Tissues","منتجات التنظيف الشخصي"),
        ("فوط مبللة","Wet Wipes","منتجات التنظيف الشخصي"),
        ("كريم مرطب","Moisturizing Cream","منتجات التنظيف الشخصي"),
    ]
    kitchen = [
        ("أكياس قمامة","Garbage Bags","مستلزمات المطبخ"),
        ("أكياس تجميد","Freezer Bags","مستلزمات المطبخ"),
        ("طبق ورقي","Paper Plate","مستلزمات المطبخ"),
        ("كوب ورقي","Paper Cup","مستلزمات المطبخ"),
        ("شوكة بلاستيك","Plastic Fork","مستلزمات المطبخ"),
        ("سكين بلاستيك","Plastic Knife","مستلزمات المطبخ"),
        ("فويل ألومنيوم","Aluminum Foil","مستلزمات المطبخ"),
        ("ورق زبدة","Baking Paper","مستلزمات المطبخ"),
        ("لفافة بلاستيك","Cling Wrap","مستلزمات المطبخ"),
        ("إسفنجة جلي","Dish Sponge","مستلزمات المطبخ"),
        ("قفازات مطبخ","Kitchen Gloves","مستلزمات المطبخ"),
        ("فرشاة تنظيف","Cleaning Brush","مستلزمات المطبخ"),
    ]
    household = [
        ("بطارية AA","AA Battery","أدوات منزلية"),
        ("بطارية AAA","AAA Battery","أدوات منزلية"),
        ("لمبة LED","LED Bulb","أدوات منزلية"),
        ("شريط لاصق","Adhesive Tape","أدوات منزلية"),
        ("خيط خياطة","Sewing Thread","أدوات منزلية"),
        ("مسامير","Nails","أدوات منزلية"),
        ("أقلام","Pens","أدوات منزلية"),
        ("دفتر ملاحظات","Notebook","أدوات منزلية"),
        ("مقص","Scissors","أدوات منزلية"),
        ("شريط قياس","Measuring Tape","أدوات منزلية"),
    ]

    # قوائم البيانات الأساسية مجمعة
    base_templates = (
        grains + oils + dairy + canned + beverages +
        spices + sweets + frozen + cleaning + kitchen + household
    )

    # إنشاء المنتجات مع الماركات والأحجام
    rows_to_insert = []
    n = 1
    added_names = set(existing)

    # طبقة 1: منتج × ماركة × حجم
    for name_ar, name_en, cat in base_templates:
        brand_list = brands_food if cat not in ("منظفات ومواد العناية", "منتجات التنظيف الشخصي") else brands_clean
        size_list  = sizes_bev if cat == "مشروبات" else sizes_food
        for brand in brand_list:
            for size in size_list:
                full_name = f"{name_ar} {brand} {size}"
                if full_name in added_names:
                    continue
                added_names.add(full_name)
                price_base = random.randint(5, 50) * 10
                rows_to_insert.append((
                    full_name,
                    f"{name_en} {brand} {size}",
                    gen_barcode("RT1", n),
                    cat,
                    round(price_base * 1.25),
                    price_base
                ))
                n += 1
                if len(rows_to_insert) + len(existing) >= target:
                    break
            if len(rows_to_insert) + len(existing) >= target:
                break
        if len(rows_to_insert) + len(existing) >= target:
            break

    # طبقة 2: إذا لم نصل للهدف، نولّد منتجات بأرقام تسلسلية
    if len(rows_to_insert) + len(existing) < target:
        extra_cats_items = [
            ("مادة غذائية", "Food Item", "مواد غذائية أساسية", 30, 20),
            ("منتج تنظيف", "Cleaning Product", "منظفات ومواد العناية", 25, 15),
            ("مشروب", "Beverage", "مشروبات", 20, 12),
            ("توابل", "Spice", "توابل وبهارات", 15, 8),
            ("حلوى", "Sweet", "حلويات ومكسرات", 20, 12),
            ("منتج منزلي", "Household Item", "أدوات منزلية", 30, 18),
        ]
        for base_ar, base_en, cat, sale, purchase in itertools.cycle(extra_cats_items):
            i = n
            full_name = f"{base_ar} متنوع #{i}"
            if full_name not in added_names:
                added_names.add(full_name)
                rows_to_insert.append((
                    full_name,
                    f"{base_en} Variety #{i}",
                    gen_barcode("RT1", i),
                    cat,
                    sale * 10,
                    purchase * 10,
                ))
                n += 1
            if len(rows_to_insert) + len(existing) >= target:
                break

    added = batch_insert(cur, biz_id, cat_map, rows_to_insert)
    print(f"  المتجر الرئيسي → أضيف {added} منتج (الهدف: {target})")
    return added


# ══════════════════════════════════════════════════════════
# BUSINESS 5 — مطعم (food_restaurant) → 2000
# ══════════════════════════════════════════════════════════
def seed_restaurant(cur, biz_id, target=2000):
    cats = [
        "مقبلات", "سلطات", "شوربات", "مشاوي", "أطباق رئيسية",
        "فطور", "سندويشات", "بيتزا وباستا", "مأكولات بحرية",
        "حلويات شرقية", "حلويات غربية", "مشروبات باردة",
        "مشروبات ساخنة", "عصائر طازجة", "وجبات أطفال"
    ]
    cat_map = ensure_cats(cur, biz_id, cats)
    existing = existing_names(cur, biz_id)
    rows = []
    n = 5001

    items = [
        # مقبلات
        ("حمص","Hummus","مقبلات",450,180), ("متبل","Mutabal","مقبلات",500,200),
        ("تبولة","Tabbouleh","مقبلات",400,150), ("فتوش","Fattoush","مقبلات",450,160),
        ("ورق عنب","Stuffed Vine Leaves","مقبلات",600,250),
        ("كبة مقلية","Fried Kibbeh","مقبلات",700,300),
        ("فلافل","Falafel","مقبلات",400,150), ("سمبوسة","Sambusa","مقبلات",500,200),
        ("بريك تونة","Tuna Brick","مقبلات",550,220), ("جبنة مقلية","Fried Cheese","مقبلات",600,250),
        # سلطات
        ("سلطة خضراء","Green Salad","سلطات",350,120), ("سلطة سيزر","Caesar Salad","سلطات",650,280),
        ("سلطة يونانية","Greek Salad","سلطات",700,300), ("سلطة نيسواز","Nicoise Salad","سلطات",750,320),
        ("سلطة كولسلو","Coleslaw","سلطات",400,150), ("سلطة شمندر","Beetroot Salad","سلطات",450,170),
        ("سلطة بطاطس","Potato Salad","سلطات",500,200), ("سلطة رائب","Yogurt Salad","سلطات",400,150),
        # شوربات
        ("شوربة عدس","Lentil Soup","شوربات",400,150), ("شوربة دجاج","Chicken Soup","شوربات",500,200),
        ("شوربة خضار","Vegetable Soup","شوربات",450,170), ("شوربة الحريرة","Harira Soup","شوربات",500,200),
        ("شوربة كريمة الفطر","Mushroom Cream Soup","شوربات",600,250),
        ("شوربة الطماطم","Tomato Soup","شوربات",450,180),
        # مشاوي
        ("كباب","Kebab","مشاوي",1200,600), ("كفتة مشوية","Grilled Kufta","مشاوي",1100,550),
        ("دجاج مشوي","Grilled Chicken","مشاوي",1500,750), ("أضلع لحم مشوية","Grilled Ribs","مشاوي",2000,1100),
        ("لقيمات لحم","Meat Lokma","مشاوي",900,450), ("شيش طاووق","Shish Tawook","مشاوي",1300,650),
        ("أسياخ لحم","Meat Skewers","مشاوي",1400,700),
        # أطباق رئيسية
        ("أرز بخاري بالدجاج","Chicken Bukhari","أطباق رئيسية",1800,900),
        ("أرز كابلي","Kabuli Rice","أطباق رئيسية",2000,1000),
        ("ملوخية بالدجاج","Chicken Molokhia","أطباق رئيسية",1600,800),
        ("كبسة لحم","Meat Kabsa","أطباق رئيسية",2200,1100),
        ("مندي دجاج","Chicken Mandi","أطباق رئيسية",2000,1000),
        ("برياني دجاج","Chicken Biryani","أطباق رئيسية",1800,900),
        ("فريكة بالدجاج","Chicken Freekeh","أطباق رئيسية",1700,850),
        ("معكرونة بولونيز","Bolognese Pasta","أطباق رئيسية",1400,700),
        ("لازانيا","Lasagna","أطباق رئيسية",1600,800),
        # فطور
        ("فول بالزيت","Foul with Oil","فطور",300,120), ("بيض مقلي","Fried Eggs","فطور",400,160),
        ("بيض مسلوق","Boiled Eggs","فطور",300,120), ("عجة","Omelet","فطور",500,200),
        ("شكشوكة","Shakshouka","فطور",600,250), ("حلوم مقلي","Fried Halloumi","فطور",700,300),
        ("فطير بالعسل","Fateer with Honey","فطور",500,200),
        # سندويشات
        ("برغر دجاج","Chicken Burger","سندويشات",1000,500),
        ("برغر لحم","Beef Burger","سندويشات",1200,600),
        ("سندويش شاورما دجاج","Chicken Shawarma","سندويشات",900,450),
        ("سندويش شاورما لحم","Meat Shawarma","سندويشات",1100,550),
        ("سندويش فلافل","Falafel Sandwich","سندويشات",350,140),
        ("كلوب سندويش","Club Sandwich","سندويشات",1100,550),
        ("سندويش حصة مشكلة","Mixed Sandwich","سندويشات",800,380),
        # بيتزا وباستا
        ("بيتزا مارغريتا S","Margherita Pizza S","بيتزا وباستا",1000,500),
        ("بيتزا مارغريتا M","Margherita Pizza M","بيتزا وباستا",1500,750),
        ("بيتزا مارغريتا L","Margherita Pizza L","بيتزا وباستا",1800,900),
        ("بيتزا دجاج S","Chicken Pizza S","بيتزا وباستا",1200,600),
        ("بيتزا دجاج M","Chicken Pizza M","بيتزا وباستا",1700,850),
        ("بيتزا دجاج L","Chicken Pizza L","بيتزا وباستا",2000,1000),
        ("فيتوتشيني كريمي","Creamy Fettuccine","بيتزا وباستا",1300,650),
        ("سباغيتي مارينارا","Spaghetti Marinara","بيتزا وباستا",1200,600),
        ("نودلز دجاج","Chicken Noodles","بيتزا وباستا",1100,550),
        # مأكولات بحرية
        ("سمك مقلي كيلو","Fried Fish 1kg","مأكولات بحرية",2500,1800),
        ("سمك مشوي كيلو","Grilled Fish 1kg","مأكولات بحرية",3000,2200),
        ("جمبري مقلي","Fried Shrimp","مأكولات بحرية",4000,2800),
        ("جمبري مشوي","Grilled Shrimp","مأكولات بحرية",4500,3200),
        ("حبار مقلي","Fried Calamari","مأكولات بحرية",3500,2500),
        ("سلطة بحرية","Seafood Salad","مأكولات بحرية",2800,2000),
        # حلويات شرقية
        ("قطائف بالجبن","Qatayef with Cheese","حلويات شرقية",800,350),
        ("كنافة","Kunafa","حلويات شرقية",900,400),
        ("بقلاوة","Baklava","حلويات شرقية",700,300),
        ("أم علي","Umm Ali","حلويات شرقية",600,250),
        ("مهلبية","Muhallebi","حلويات شرقية",400,160),
        ("رز بحليب","Rice Pudding","حلويات شرقية",350,140),
        ("لقيمات بالعسل","Honey Lokma","حلويات شرقية",450,180),
        # حلويات غربية
        ("تشيزكيك","Cheesecake","حلويات غربية",700,300),
        ("تيراميسو","Tiramisu","حلويات غربية",800,350),
        ("بروني","Brownie","حلويات غربية",500,200),
        ("كريم برولي","Creme Brulee","حلويات غربية",700,300),
        ("باناكوتا","Panna Cotta","حلويات غربية",600,250),
        ("مافن شوكولاتة","Chocolate Muffin","حلويات غربية",400,160),
        ("كواتر تشوكليت","Molten Chocolate","حلويات غربية",750,320),
        # مشروبات باردة
        ("كولا","Cola","مشروبات باردة",300,100), ("بيبسي","Pepsi","مشروبات باردة",300,100),
        ("مياه","Water","مشروبات باردة",150,50), ("ليمون بالنعناع","Lemon Mint","مشروبات باردة",400,150),
        ("موهيتو","Mojito","مشروبات باردة",600,250), ("لاتيه مثلج","Iced Latte","مشروبات باردة",700,300),
        ("سموثي مانغو","Mango Smoothie","مشروبات باردة",800,350),
        # مشروبات ساخنة
        ("قهوة سوداء","Black Coffee","مشروبات ساخنة",300,100),
        ("لاتيه","Latte","مشروبات ساخنة",600,250),
        ("كابتشينو","Cappuccino","مشروبات ساخنة",600,250),
        ("شاي أحمر","Red Tea","مشروبات ساخنة",250,80),
        ("شاي أخضر","Green Tea","مشروبات ساخنة",300,100),
        ("شوكولاتة ساخنة","Hot Chocolate","مشروبات ساخنة",500,200),
        ("شاي كرك","Karak Tea","مشروبات ساخنة",300,100),
        # عصائر
        ("عصير برتقال طازج","Fresh Orange Juice","عصائر طازجة",600,250),
        ("عصير تفاح طازج","Fresh Apple Juice","عصائر طازجة",600,250),
        ("عصير جزر طازج","Fresh Carrot Juice","عصائر طازجة",550,220),
        ("عصير مانغو طازج","Fresh Mango Juice","عصائر طازجة",700,300),
        ("عصير فراولة","Strawberry Juice","عصائر طازجة",700,300),
        ("عصير بطيخ","Watermelon Juice","عصائر طازجة",500,200),
        ("كوكتيل فواكه","Fruit Cocktail","عصائر طازجة",800,350),
        # وجبات أطفال
        ("نقيتس دجاج للأطفال","Kids Chicken Nuggets","وجبات أطفال",900,400),
        ("برغر صغير للأطفال","Kids Mini Burger","وجبات أطفال",800,380),
        ("بيتزا صغيرة","Kids Pizza","وجبات أطفال",700,300),
        ("عصائر أطفال","Kids Juice","وجبات أطفال",300,120),
    ]

    # نولّد variations حجم/درجة + رقم تسلسلي للوصول للهدف
    sizes = ["صغير", "وسط", "كبير", "فردي", "عائلي"]
    variants = ["الخاص", "المميز", "اليومي", "الوجبة الكاملة", "الحصة الخاصة"]
    added_names_set = set(existing)

    for name_ar, name_en, cat, sale, purchase in items:
        for var in variants:
            full = f"{name_ar} {var}"
            if full not in added_names_set:
                added_names_set.add(full)
                rows.append((full, f"{name_en} {var}", gen_barcode("RS5", n), cat, sale, purchase))
                n += 1
        if len(rows) + len(existing) >= target:
            break

    # تعبئة تسلسلية إن لزم
    if len(rows) + len(existing) < target:
        for base_ar, base_en, cat, sale, purchase in itertools.cycle(items):
            full = f"{base_ar} #{n}"
            if full not in added_names_set:
                added_names_set.add(full)
                rows.append((full, f"{base_en} #{n}", gen_barcode("RS5", n), cat, sale, purchase))
                n += 1
            if len(rows) + len(existing) >= target:
                break

    added = batch_insert(cur, biz_id, cat_map, rows)
    print(f"  مطعم الوجبات الذهبية → أضيف {added} منتج")
    return added


# ══════════════════════════════════════════════════════════
# BUSINESS 6 — صيدلية → 2000
# ══════════════════════════════════════════════════════════
def seed_pharmacy(cur, biz_id, target=2000):
    cats = [
        "أدوية موصوفة", "أدوية بدون وصفة", "مضادات حيوية",
        "مسكنات وخافضات حرارة", "فيتامينات ومكملات",
        "مستلزمات طبية", "مستحضرات تجميل", "منتجات الأم والطفل",
        "أدوية مزمنة", "طب عيون وأذن"
    ]
    cat_map = ensure_cats(cur, biz_id, cats)
    existing = existing_names(cur, biz_id)
    rows = []
    n = 6001

    items = [
        # مسكنات
        ("باراسيتامول 500مغ","Paracetamol 500mg","مسكنات وخافضات حرارة",150,80),
        ("باراسيتامول 1000مغ","Paracetamol 1000mg","مسكنات وخافضات حرارة",200,110),
        ("إيبوبروفين 400مغ","Ibuprofen 400mg","مسكنات وخافضات حرارة",200,100),
        ("إيبوبروفين 600مغ","Ibuprofen 600mg","مسكنات وخافضات حرارة",250,130),
        ("أسبرين 100مغ","Aspirin 100mg","مسكنات وخافضات حرارة",180,90),
        ("أسبرين 500مغ","Aspirin 500mg","مسكنات وخافضات حرارة",200,100),
        ("ديكلوفيناك","Diclofenac","مسكنات وخافضات حرارة",300,150),
        ("ناميتا","Namita","مسكنات وخافضات حرارة",350,180),
        ("ترامادول","Tramadol","أدوية موصوفة",400,200),
        ("كيتوبروفين","Ketoprofen","مسكنات وخافضات حرارة",350,180),
        # مضادات حيوية
        ("أموكسيسيلين 250مغ","Amoxicillin 250mg","مضادات حيوية",500,250),
        ("أموكسيسيلين 500مغ","Amoxicillin 500mg","مضادات حيوية",650,330),
        ("أزيثروميسين 250مغ","Azithromycin 250mg","مضادات حيوية",800,400),
        ("أزيثروميسين 500مغ","Azithromycin 500mg","مضادات حيوية",1000,500),
        ("سيبروفلوكساسين","Ciprofloxacin","مضادات حيوية",700,350),
        ("كلاريثروميسين","Clarithromycin","مضادات حيوية",900,450),
        ("ميترونيدازول","Metronidazole","مضادات حيوية",400,200),
        ("سيفالكسين","Cephalexin","مضادات حيوية",600,300),
        ("دوكسيسيكلين","Doxycycline","مضادات حيوية",550,275),
        ("ليفوفلوكساسين","Levofloxacin","مضادات حيوية",800,400),
        # فيتامينات
        ("فيتامين C 1000مغ","Vitamin C 1000mg","فيتامينات ومكملات",500,250),
        ("فيتامين D3 1000وحدة","Vitamin D3 1000IU","فيتامينات ومكملات",600,300),
        ("فيتامين D3 5000وحدة","Vitamin D3 5000IU","فيتامينات ومكملات",800,400),
        ("فيتامين B12","Vitamin B12","فيتامينات ومكملات",700,350),
        ("فيتامين E 400وحدة","Vitamin E 400IU","فيتامينات ومكملات",600,300),
        ("أوميغا 3","Omega 3","فيتامينات ومكملات",900,450),
        ("زنك 50مغ","Zinc 50mg","فيتامينات ومكملات",400,200),
        ("كالسيوم مع فيتامين D","Calcium + Vit D","فيتامينات ومكملات",700,350),
        ("فوليك أسيد","Folic Acid","فيتامينات ومكملات",350,175),
        ("مغنيسيوم","Magnesium","فيتامينات ومكملات",500,250),
        ("حديد","Iron","فيتامينات ومكملات",400,200),
        ("بروبيوتيك","Probiotic","فيتامينات ومكملات",1200,600),
        ("مولتي فيتامين","Multivitamin","فيتامينات ومكملات",800,400),
        ("كيو تن","CoQ10","فيتامينات ومكملات",1500,750),
        # مستلزمات
        ("شاشة قياس سكر","Glucometer","مستلزمات طبية",3500,2500),
        ("شرائط قياس سكر","Glucose Test Strips","مستلزمات طبية",1500,1000),
        ("جهاز قياس ضغط","Blood Pressure Monitor","مستلزمات طبية",5000,3500),
        ("سماعة طبية","Stethoscope","مستلزمات طبية",3000,2000),
        ("ميزان حرارة رقمي","Digital Thermometer","مستلزمات طبية",800,500),
        ("ضمادات طبية","Medical Bandages","مستلزمات طبية",300,150),
        ("قفازات طبية S","Medical Gloves S","مستلزمات طبية",400,200),
        ("قفازات طبية M","Medical Gloves M","مستلزمات طبية",400,200),
        ("قفازات طبية L","Medical Gloves L","مستلزمات طبية",400,200),
        ("كمامات طبية","Medical Masks","مستلزمات طبية",300,150),
        ("محقنة 5مل","Syringe 5ml","مستلزمات طبية",100,50),
        ("محقنة 10مل","Syringe 10ml","مستلزمات طبية",120,60),
        ("شاشة اكسجين","Pulse Oximeter","مستلزمات طبية",1000,600),
        # تجميل
        ("كريم مرطب SPF50","Moisturizer SPF50","مستحضرات تجميل",1500,800),
        ("غسول وجه","Face Wash","مستحضرات تجميل",800,400),
        ("تونر","Toner","مستحضرات تجميل",700,350),
        ("سيروم فيتامين C","Vit C Serum","مستحضرات تجميل",2000,1000),
        ("مزيل مكياج","Makeup Remover","مستحضرات تجميل",600,300),
        ("كريم عيون","Eye Cream","مستحضرات تجميل",1200,600),
        # أم وطفل
        ("حليب أطفال 0-6 أشهر","Baby Formula 0-6m","منتجات الأم والطفل",3000,2000),
        ("حليب أطفال 6-12 أشهر","Baby Formula 6-12m","منتجات الأم والطفل",3200,2100),
        ("حفاضات S","Diapers S","منتجات الأم والطفل",2000,1300),
        ("حفاضات M","Diapers M","منتجات الأم والطفل",2200,1400),
        ("حفاضات L","Diapers L","منتجات الأم والطفل",2400,1600),
        ("شامبو أطفال","Baby Shampoo","منتجات الأم والطفل",700,350),
        ("كريم حفاضات","Diaper Cream","منتجات الأم والطفل",600,300),
        ("مناديل أطفال","Baby Wipes","منتجات الأم والطفل",500,250),
        # أدوية مزمنة
        ("ميتفورمين 500مغ","Metformin 500mg","أدوية مزمنة",300,150),
        ("ميتفورمين 1000مغ","Metformin 1000mg","أدوية مزمنة",400,200),
        ("أتورفاستاتين 10مغ","Atorvastatin 10mg","أدوية مزمنة",600,300),
        ("أتورفاستاتين 20مغ","Atorvastatin 20mg","أدوية مزمنة",800,400),
        ("أملوديبين 5مغ","Amlodipine 5mg","أدوية مزمنة",400,200),
        ("أملوديبين 10مغ","Amlodipine 10mg","أدوية مزمنة",500,250),
        ("إيزومبرازول","Esomeprazole","أدوية مزمنة",600,300),
        ("أومبرازول","Omeprazole","أدوية مزمنة",500,250),
        ("رانيتيدين","Ranitidine","أدوية مزمنة",350,175),
        ("لوسارتان","Losartan","أدوية مزمنة",500,250),
        # عيون وأذن
        ("قطرة عيون ملطفة","Eye Drops Lubricant","طب عيون وأذن",700,350),
        ("قطرة عيون حساسية","Allergy Eye Drops","طب عيون وأذن",800,400),
        ("غسول أذن","Ear Wash","طب عيون وأذن",600,300),
        ("قطرة أذن","Ear Drops","طب عيون وأذن",500,250),
        ("نظارة قراءة +1","Reading Glasses +1","طب عيون وأذن",1500,800),
        ("نظارة قراءة +1.5","Reading Glasses +1.5","طب عيون وأذن",1500,800),
        ("نظارة قراءة +2","Reading Glasses +2","طب عيون وأذن",1500,800),
        ("نظارة قراءة +2.5","Reading Glasses +2.5","طب عيون وأذن",1500,800),
        ("نظارة قراءة +3","Reading Glasses +3","طب عيون وأذن",1500,800),
    ]

    brands = ["نوفارتيس","فايزر","باير","جلاكسو","سانوفي","روش","أسترا","ميرك","تيفا","ريزولف","فارمكس","ميدفارما"]
    forms  = ["أقراص","كبسولات","شراب","بودر","حقن","تحاميل","جل","كريم","قطرة","رذاذ"]

    added_set = set(existing)
    for name_ar, name_en, cat, sale, purchase in items:
        for brand in brands:
            for form in forms:
                full = f"{name_ar} {brand} {form}"
                if full not in added_set:
                    added_set.add(full)
                    rows.append((full, f"{name_en} {brand} {form}",
                                 gen_barcode("PH6", n), cat, sale, purchase))
                    n += 1
                if len(rows) + len(existing) >= target:
                    break
            if len(rows) + len(existing) >= target:
                break
        if len(rows) + len(existing) >= target:
            break

    if len(rows) + len(existing) < target:
        for base_ar, base_en, cat, sale, purchase in itertools.cycle(items):
            full = f"{base_ar} #{n}"
            if full not in added_set:
                added_set.add(full)
                rows.append((full, f"{base_en} #{n}", gen_barcode("PH6", n), cat, sale, purchase))
                n += 1
            if len(rows) + len(existing) >= target:
                break

    added = batch_insert(cur, biz_id, cat_map, rows)
    print(f"  صيدلية الشفاء → أضيف {added} منتج")
    return added


# ══════════════════════════════════════════════════════════
# BUSINESS 7 — ملحمة (butcher) → 2000
# ══════════════════════════════════════════════════════════
def seed_butcher(cur, biz_id, target=2000):
    cats = ["لحوم حمراء", "دواجن", "أسماك ومأكولات بحرية",
            "لحوم مصنعة", "مجمدات", "توابل ومتممات"]
    cat_map = ensure_cats(cur, biz_id, cats)
    existing = existing_names(cur, biz_id)
    rows = []
    n = 7001

    items = [
        ("لحم بقري طازج","Fresh Beef","لحوم حمراء",3500,2800),
        ("لحم عجل","Veal","لحوم حمراء",4000,3200),
        ("لحم غنم","Lamb","لحوم حمراء",4500,3600),
        ("لحم ماعز","Goat Meat","لحوم حمراء",4000,3200),
        ("كبدة بقري","Beef Liver","لحوم حمراء",2500,2000),
        ("كلاوي","Kidney","لحوم حمراء",2000,1600),
        ("مخ","Brain","لحوم حمراء",2500,2000),
        ("كرشة","Tripe","لحوم حمراء",2000,1600),
        ("أرجل بقري","Beef Feet","لحوم حمراء",1800,1400),
        ("ذيل بقري","Oxtail","لحوم حمراء",3000,2400),
        ("ريش بقري","Beef Ribs","لحوم حمراء",3500,2800),
        ("فيليه بقري","Beef Tenderloin","لحوم حمراء",6000,4800),
        ("ستيك","Steak","لحوم حمراء",5000,4000),
        ("لحم مفروم","Ground Meat","لحوم حمراء",3000,2400),
        ("لحم مكعبات","Meat Cubes","لحوم حمراء",3200,2600),
        ("دجاج كامل","Whole Chicken","دواجن",1500,1200),
        ("صدر دجاج","Chicken Breast","دواجن",2000,1600),
        ("فخذ دجاج","Chicken Thigh","دواجن",1800,1440),
        ("أجنحة دجاج","Chicken Wings","دواجن",1600,1280),
        ("كبدة دجاج","Chicken Liver","دواجن",1200,960),
        ("قوانص دجاج","Chicken Gizzard","دواجن",1000,800),
        ("دجاج بلدي","Free Range Chicken","دواجن",3000,2400),
        ("حمام","Pigeon","دواجن",2500,2000),
        ("سمان","Quail","دواجن",3000,2400),
        ("ديك رومي","Turkey","دواجن",4000,3200),
        ("سمك لوث","Luth Fish","أسماك ومأكولات بحرية",3000,2400),
        ("سمك حلول","Haloul Fish","أسماك ومأكولات بحرية",3500,2800),
        ("سمك سبيطي","Sabaiti Fish","أسماك ومأكولات بحرية",4000,3200),
        ("جمبري كبير","Large Shrimp","أسماك ومأكولات بحرية",5000,4000),
        ("جمبري صغير","Small Shrimp","أسماك ومأكولات بحرية",3500,2800),
        ("حبار","Squid","أسماك ومأكولات بحرية",4000,3200),
        ("كابوريا","Crab","أسماك ومأكولات بحرية",5000,4000),
        ("تونة طازجة","Fresh Tuna","أسماك ومأكولات بحرية",4000,3200),
        ("سالمون","Salmon","أسماك ومأكولات بحرية",8000,6400),
        ("سمك مطبوخ جاهز","Ready Cooked Fish","أسماك ومأكولات بحرية",3500,2500),
        ("نقانق لحم","Beef Sausage","لحوم مصنعة",2000,1500),
        ("نقانق دجاج","Chicken Sausage","لحوم مصنعة",1800,1350),
        ("برغر لحم مصنوع","Beef Burger Patty","لحوم مصنعة",2500,1900),
        ("برغر دجاج مصنوع","Chicken Burger Patty","لحوم مصنعة",2200,1700),
        ("باسترمي","Pastrami","لحوم مصنعة",2500,1900),
        ("سجق","Salami","لحوم مصنعة",2000,1500),
        ("لحم علبة","Canned Meat","لحوم مصنعة",2000,1500),
    ]

    weights = ["250 غ", "500 غ", "1 كغ", "2 كغ", "3 كغ", "5 كغ", "كامل"]
    cuts   = ["مقطع", "مطحون", "شرائح", "مكعبات", "كامل", "منزوع العظم"]

    added_set = set(existing)
    for name_ar, name_en, cat, sale, purchase in items:
        for w in weights:
            for c in cuts:
                full = f"{name_ar} {w} {c}"
                if full not in added_set:
                    added_set.add(full)
                    rows.append((full, f"{name_en} {w} {c}",
                                 gen_barcode("BT7", n), cat,
                                 round(sale * random.uniform(0.8, 1.2)),
                                 round(purchase * random.uniform(0.8, 1.2))))
                    n += 1
                if len(rows) + len(existing) >= target:
                    break
            if len(rows) + len(existing) >= target:
                break
        if len(rows) + len(existing) >= target:
            break

    if len(rows) + len(existing) < target:
        for base_ar, base_en, cat, sale, purchase in itertools.cycle(items):
            full = f"{base_ar} #{n}"
            if full not in added_set:
                added_set.add(full)
                rows.append((full, f"{base_en} #{n}", gen_barcode("BT7", n), cat, sale, purchase))
                n += 1
            if len(rows) + len(existing) >= target:
                break

    added = batch_insert(cur, biz_id, cat_map, rows)
    print(f"  ملحمة الخير → أضيف {added} منتج")
    return added


# ══════════════════════════════════════════════════════════
# BUSINESS 8 — كافيه → 2000
# ══════════════════════════════════════════════════════════
def seed_cafe(cur, biz_id, target=2000):
    cats = ["قهوة", "شاي وأعشاب", "مشروبات باردة", "مشروبات ساخنة",
            "عصائر", "كيك وحلويات", "سندويشات خفيفة", "وجبات إفطار",
            "مثلجات", "خامات ومشتريات"]
    cat_map = ensure_cats(cur, biz_id, cats)
    existing = existing_names(cur, biz_id)
    rows = []
    n = 8001

    items = [
        ("إسبريسو واحد","Single Espresso","قهوة",300,80),
        ("إسبريسو مزدوج","Double Espresso","قهوة",400,100),
        ("أمريكانو","Americano","قهوة",400,90),
        ("لاتيه","Latte","قهوة",600,180),
        ("كابتشينو","Cappuccino","قهوة",600,180),
        ("فلات وايت","Flat White","قهوة",650,190),
        ("ماكياتو","Macchiato","قهوة",550,160),
        ("موكا","Mocha","قهوة",700,220),
        ("كراميل ماكياتو","Caramel Macchiato","قهوة",750,230),
        ("قهوة عربية","Arabic Coffee","قهوة",250,60),
        ("قهوة تركية","Turkish Coffee","قهوة",350,90),
        ("قهوة فلتر","Filter Coffee","قهوة",400,100),
        ("كولد برو","Cold Brew","قهوة",700,200),
        ("نيترو كوفي","Nitro Coffee","قهوة",800,220),
        ("شاي أحمر","Black Tea","شاي وأعشاب",250,60),
        ("شاي أخضر","Green Tea","شاي وأعشاب",300,70),
        ("شاي أحمر بالحليب","Milk Tea","شاي وأعشاب",400,100),
        ("شاي مغربي","Moroccan Tea","شاي وأعشاب",350,90),
        ("شاي كرك","Karak Tea","شاي وأعشاب",350,90),
        ("شاي هيل","Cardamom Tea","شاي وأعشاب",350,90),
        ("شاي نعناع","Mint Tea","شاي وأعشاب",300,70),
        ("شاي زنجبيل","Ginger Tea","شاي وأعشاب",350,90),
        ("شاي بابونج","Chamomile Tea","شاي وأعشاب",350,90),
        ("ليبتون","Lipton","شاي وأعشاب",200,50),
        ("ليمون بالنعناع","Lemon Mint","مشروبات باردة",500,150),
        ("موهيتو","Mojito","مشروبات باردة",600,180),
        ("كولا","Cola","مشروبات باردة",300,80),
        ("بيبسي","Pepsi","مشروبات باردة",300,80),
        ("مياه","Water","مشروبات باردة",150,40),
        ("مياه غازية","Sparkling Water","مشروبات باردة",250,70),
        ("آيس تي","Iced Tea","مشروبات باردة",500,150),
        ("لاتيه مثلج","Iced Latte","مشروبات باردة",700,200),
        ("كابتشينو مثلج","Iced Cappuccino","مشروبات باردة",700,200),
        ("فرابيه","Frappe","مشروبات باردة",800,250),
        ("سموثي مانغو","Mango Smoothie","عصائر",800,250),
        ("سموثي فراولة","Strawberry Smoothie","عصائر",800,250),
        ("عصير برتقال طازج","Fresh Orange Juice","عصائر",600,200),
        ("عصير تفاح","Apple Juice","عصائر",500,160),
        ("عصير موز","Banana Juice","عصائر",600,200),
        ("عصير مشكل","Mixed Juice","عصائر",700,220),
        ("كيك تشيز","Cheesecake Slice","كيك وحلويات",600,250),
        ("براوني","Brownie","كيك وحلويات",450,180),
        ("مافن شوكولاتة","Chocolate Muffin","كيك وحلويات",400,160),
        ("كرواسون","Croissant","كيك وحلويات",350,140),
        ("كيك ريد فيلفيت","Red Velvet Slice","كيك وحلويات",600,250),
        ("كوكي","Cookie","كيك وحلويات",200,80),
        ("تيراميسو","Tiramisu","كيك وحلويات",700,280),
        ("مافن توت","Blueberry Muffin","كيك وحلويات",400,160),
        ("دونات","Donut","كيك وحلويات",300,120),
        ("واير","Wafer","كيك وحلويات",250,100),
        ("سندويش دجاج","Chicken Sandwich","سندويشات خفيفة",700,300),
        ("سندويش تونة","Tuna Sandwich","سندويشات خفيفة",650,280),
        ("سندويش جبنة","Cheese Sandwich","سندويشات خفيفة",500,200),
        ("سندويش خضار","Veggie Sandwich","سندويشات خفيفة",500,200),
        ("ساندويش كلوب","Club Sandwich","سندويشات خفيفة",900,380),
        ("بانيني دجاج","Chicken Panini","سندويشات خفيفة",800,350),
        ("بيتزا صغيرة","Mini Pizza","سندويشات خفيفة",700,300),
        ("بيض مقلي","Fried Eggs","وجبات إفطار",400,160),
        ("بيض مع جبنة","Eggs with Cheese","وجبات إفطار",500,200),
        ("طبق إفطار","Breakfast Plate","وجبات إفطار",1200,500),
        ("آيسكريم فانيليا","Vanilla Ice Cream","مثلجات",400,150),
        ("آيسكريم شوكولاتة","Chocolate Ice Cream","مثلجات",400,150),
        ("آيسكريم فراولة","Strawberry Ice Cream","مثلجات",400,150),
        ("ميلك شيك فانيليا","Vanilla Milkshake","مثلجات",700,270),
        ("ميلك شيك شوكولاتة","Chocolate Milkshake","مثلجات",700,270),
        ("ميلك شيك فراولة","Strawberry Milkshake","مثلجات",700,270),
        ("صنداي شوكولاتة","Chocolate Sundae","مثلجات",500,200),
    ]

    sizes  = ["S", "M", "L", "XL"]
    extras = ["بالحليب كامل", "بالحليب قليل الدسم", "بالحليب النباتي", "إضافي سكر", "بدون سكر", "ساخن", "مثلج"]

    added_set = set(existing)
    for name_ar, name_en, cat, sale, purchase in items:
        for sz in sizes:
            for ex in extras:
                full = f"{name_ar} {sz} {ex}"
                if full not in added_set:
                    added_set.add(full)
                    rows.append((full, f"{name_en} {sz} {ex}",
                                 gen_barcode("CF8", n), cat, sale, purchase))
                    n += 1
                if len(rows) + len(existing) >= target:
                    break
            if len(rows) + len(existing) >= target:
                break
        if len(rows) + len(existing) >= target:
            break

    if len(rows) + len(existing) < target:
        for base_ar, base_en, cat, sale, purchase in itertools.cycle(items):
            full = f"{base_ar} #{n}"
            if full not in added_set:
                added_set.add(full)
                rows.append((full, f"{base_en} #{n}", gen_barcode("CF8", n), cat, sale, purchase))
                n += 1
            if len(rows) + len(existing) >= target:
                break

    added = batch_insert(cur, biz_id, cat_map, rows)
    print(f"  كافيه السحاب → أضيف {added} منتج")
    return added


# ══════════════════════════════════════════════════════════
# BUSINESS 9 — بوتيك رجال → 2000
# ══════════════════════════════════════════════════════════
def seed_fashion(cur, biz_id, target=2000):
    cats = ["ثياب رسمية", "ثياب كاجوال", "ملابس رياضية",
            "ملابس داخلية وجوارب", "أحذية", "حقائب وإكسسوار",
            "عطور وعناية", "ثياب تقليدية"]
    cat_map = ensure_cats(cur, biz_id, cats)
    existing = existing_names(cur, biz_id)
    rows = []
    n = 9001

    items = [
        ("قميص رسمي","Formal Shirt","ثياب رسمية",1500,900),
        ("بدلة رجالية","Men's Suit","ثياب رسمية",8000,5000),
        ("بنطال رسمي","Formal Pants","ثياب رسمية",2000,1200),
        ("تي شيرت","T-Shirt","ثياب كاجوال",800,450),
        ("قميص كاجوال","Casual Shirt","ثياب كاجوال",1200,700),
        ("جينز","Jeans","ثياب كاجوال",2500,1500),
        ("شورت","Shorts","ثياب كاجوال",800,450),
        ("هودي","Hoodie","ثياب كاجوال",2000,1200),
        ("جاكيت","Jacket","ثياب كاجوال",3000,1800),
        ("بلوفر","Pullover","ثياب كاجوال",2000,1200),
        ("تراك رياضي","Sports Tracksuit","ملابس رياضية",3000,1800),
        ("قميص رياضي","Sports Shirt","ملابس رياضية",1200,700),
        ("شورت رياضي","Sports Shorts","ملابس رياضية",800,450),
        ("حذاء رياضي","Sports Shoes","ملابس رياضية",3000,1800),
        ("جوارب رياضية","Sports Socks","ملابس رياضية",300,150),
        ("فانيلة داخلية","Undershirt","ملابس داخلية وجوارب",500,250),
        ("بوكسر","Boxer","ملابس داخلية وجوارب",600,300),
        ("جوارب قطنية","Cotton Socks","ملابس داخلية وجوارب",250,120),
        ("جوارب رسمية","Dress Socks","ملابس داخلية وجوارب",300,150),
        ("حذاء رسمي","Formal Shoes","أحذية",3500,2000),
        ("حذاء كاجوال","Casual Shoes","أحذية",2500,1500),
        ("صندل","Sandal","أحذية",1500,800),
        ("شبشب","Slippers","أحذية",800,400),
        ("حذاء جلد","Leather Shoes","أحذية",4500,2800),
        ("حزام جلد","Leather Belt","حقائب وإكسسوار",1200,600),
        ("محفظة جلد","Leather Wallet","حقائب وإكسسوار",1500,750),
        ("حقيبة ظهر","Backpack","حقائب وإكسسوار",2500,1400),
        ("حقيبة يد","Handbag","حقائب وإكسسوار",2000,1100),
        ("ساعة يد","Wristwatch","حقائب وإكسسوار",5000,3000),
        ("نظارة شمسية","Sunglasses","حقائب وإكسسوار",1500,800),
        ("ربطة عنق","Tie","حقائب وإكسسوار",800,400),
        ("عطر رجالي","Men's Perfume","عطور وعناية",3000,1500),
        ("رول أون","Roll-on Deodorant","عطور وعناية",500,250),
        ("كريم حلاقة","Shaving Cream","عطور وعناية",600,300),
        ("جل شعر","Hair Gel","عطور وعناية",500,250),
        ("شامبو رجالي","Men's Shampoo","عطور وعناية",700,350),
        ("ثوب رجالي","Men's Thobe","ثياب تقليدية",3000,1800),
        ("بشت","Bisht","ثياب تقليدية",5000,3000),
        ("شماغ أحمر","Red Shemagh","ثياب تقليدية",1500,800),
        ("عقال","Iqal","ثياب تقليدية",800,400),
    ]

    sizes   = ["XS", "S", "M", "L", "XL", "XXL", "3XL"]
    colors  = ["أبيض", "أسود", "رمادي", "بيج", "كحلي", "بني", "زيتي", "أزرق", "أحمر", "خاكي"]
    brands  = ["زارا", "H&M", "LC وايكيكي", "ماسيمو دوتي", "جاب", "بول أند بير", "بولو رالف"]

    added_set = set(existing)
    for name_ar, name_en, cat, sale, purchase in items:
        for color in colors:
            for size in sizes:
                full = f"{name_ar} {color} {size}"
                if full not in added_set:
                    added_set.add(full)
                    rows.append((full, f"{name_en} {color} {size}",
                                 gen_barcode("FN9", n), cat, sale, purchase))
                    n += 1
                if len(rows) + len(existing) >= target:
                    break
            if len(rows) + len(existing) >= target:
                break
        if len(rows) + len(existing) >= target:
            break

    if len(rows) + len(existing) < target:
        for base_ar, base_en, cat, sale, purchase in itertools.cycle(items):
            full = f"{base_ar} #{n}"
            if full not in added_set:
                added_set.add(full)
                rows.append((full, f"{base_en} #{n}", gen_barcode("FN9", n), cat, sale, purchase))
                n += 1
            if len(rows) + len(existing) >= target:
                break

    added = batch_insert(cur, biz_id, cat_map, rows)
    print(f"  بوتيك الرجل الأنيق → أضيف {added} منتج")
    return added


# ══════════════════════════════════════════════════════════
# BUSINESS 10 — ورشة سيارات → 2000
# ══════════════════════════════════════════════════════════
def seed_auto(cur, biz_id, target=2000):
    cats = ["زيوت وسوائل", "فلاتر", "بطاريات", "إطارات", "فرامل",
            "تعليق وتوجيه", "إضاءة", "كهرباء وإلكترونيات", "هيكل وبودي",
            "أدوات ومعدات", "خدمات"]
    cat_map = ensure_cats(cur, biz_id, cats)
    existing = existing_names(cur, biz_id)
    rows = []
    n = 10001

    items = [
        ("زيت محرك 5W30","Engine Oil 5W30","زيوت وسوائل",1200,800),
        ("زيت محرك 5W40","Engine Oil 5W40","زيوت وسوائل",1300,870),
        ("زيت محرك 10W40","Engine Oil 10W40","زيوت وسوائل",1100,730),
        ("زيت محرك 15W40","Engine Oil 15W40","زيوت وسوائل",1000,670),
        ("زيت ناقل حركة","Transmission Oil","زيوت وسوائل",1500,1000),
        ("زيت تفاضلي","Differential Oil","زيوت وسوائل",1400,930),
        ("زيت هيدروليك","Hydraulic Oil","زيوت وسوائل",1000,670),
        ("سائل فرامل","Brake Fluid","زيوت وسوائل",500,300),
        ("سائل تبريد","Coolant","زيوت وسوائل",700,450),
        ("شحمة","Grease","زيوت وسوائل",400,250),
        ("فلتر زيت تويوتا","Oil Filter Toyota","فلاتر",300,180),
        ("فلتر زيت كيا","Oil Filter Kia","فلاتر",300,180),
        ("فلتر زيت هيونداي","Oil Filter Hyundai","فلاتر",300,180),
        ("فلتر زيت نيسان","Oil Filter Nissan","فلاتر",350,210),
        ("فلتر هواء","Air Filter","فلاتر",400,240),
        ("فلتر كابين","Cabin Filter","فلاتر",350,210),
        ("فلتر وقود","Fuel Filter","فلاتر",500,300),
        ("بطارية 45Ah","Battery 45Ah","بطاريات",3000,2000),
        ("بطارية 55Ah","Battery 55Ah","بطاريات",3500,2350),
        ("بطارية 65Ah","Battery 65Ah","بطاريات",4000,2700),
        ("بطارية 75Ah","Battery 75Ah","بطاريات",4500,3000),
        ("بطارية 90Ah","Battery 90Ah","بطاريات",5000,3350),
        ("إطار 195/65R15","Tyre 195/65R15","إطارات",2000,1400),
        ("إطار 205/55R16","Tyre 205/55R16","إطارات",2200,1540),
        ("إطار 215/60R17","Tyre 215/60R17","إطارات",2500,1750),
        ("إطار 225/45R18","Tyre 225/45R18","إطارات",3000,2100),
        ("إطار 235/65R18","Tyre 235/65R18","إطارات",3500,2450),
        ("تبديل وتوازن إطار","Tyre Change & Balance","خدمات",500,0),
        ("فحدفة أمامية","Front Brake Pads","فرامل",800,500),
        ("فحدفة خلفية","Rear Brake Pads","فرامل",700,440),
        ("قرص فرامل أمامي","Front Brake Disc","فرامل",1500,1000),
        ("قرص فرامل خلفي","Rear Brake Disc","فرامل",1300,870),
        ("أسطوانة فرامل","Brake Drum","فرامل",1000,670),
        ("مضخة فرامل رئيسية","Master Cylinder","فرامل",2000,1350),
        ("مطانب فرامل","Brake Hoses","فرامل",400,250),
        ("مساعد أمامي","Front Shock Absorber","تعليق وتوجيه",2000,1350),
        ("مساعد خلفي","Rear Shock Absorber","تعليق وتوجيه",1800,1200),
        ("رأس مقود","Tie Rod End","تعليق وتوجيه",800,500),
        ("دراع مقود","Steering Arm","تعليق وتوجيه",1000,670),
        ("كاوتش علوي","Upper Arm Bushing","تعليق وتوجيه",500,300),
        ("قضيب توازن","Stabilizer Bar","تعليق وتوجيه",1200,800),
        ("لمبة أمامية LED","LED Headlight Bulb","إضاءة",500,300),
        ("لمبة خلفية","Tail Light Bulb","إضاءة",200,120),
        ("لمبة ضباب","Fog Light Bulb","إضاءة",300,180),
        ("مصباح أمامي كامل","Full Headlight Assembly","إضاءة",3000,2000),
        ("بوجيه","Spark Plug","كهرباء وإلكترونيات",400,250),
        ("شمعة إشعال","Glow Plug","كهرباء وإلكترونيات",500,300),
        ("ديناموه","Alternator","كهرباء وإلكترونيات",3000,2000),
        ("بادئ تشغيل","Starter Motor","كهرباء وإلكترونيات",2500,1670),
        ("سلك بطارية","Battery Cable","كهرباء وإلكترونيات",300,180),
        ("ريلاي","Relay","كهرباء وإلكترونيات",200,120),
        ("فيوز","Fuse","كهرباء وإلكترونيات",50,25),
        ("زجاج أمامي","Front Windshield","هيكل وبودي",2000,1350),
        ("مرآة جانبية يمين","Right Side Mirror","هيكل وبودي",800,500),
        ("مرآة جانبية يسار","Left Side Mirror","هيكل وبودي",800,500),
        ("مقبض باب","Door Handle","هيكل وبودي",400,250),
        ("بريد فرن","Car Paint","هيكل وبودي",500,300),
        ("فتحة سقف","Sunroof","هيكل وبودي",5000,3350),
        ("مفتاح ربط","Wrench Set","أدوات ومعدات",1000,600),
        ("رافعة هيدروليكية","Hydraulic Jack","أدوات ومعدات",2000,1300),
        ("جهاز تشخيص","Diagnostic Scanner","أدوات ومعدات",5000,3300),
        ("تغيير زيت وفلتر","Oil & Filter Change","خدمات",800,0),
        ("فحص شامل","Full Inspection","خدمات",500,0),
        ("تصحيح زوايا","Wheel Alignment","خدمات",600,0),
    ]

    car_brands = ["تويوتا", "كيا", "هيونداي", "نيسان", "هوندا", "مازدا", "سوبارو", "فورد", "شيفروليه", "ميتسوبيشي"]
    models     = ["كامري", "كورولا", "سيارة عامة", "سيبتيما", "لانسر", "باترول", "برادو", "ايلانترا"]

    added_set = set(existing)
    for name_ar, name_en, cat, sale, purchase in items:
        for brand in car_brands:
            full = f"{name_ar} - {brand}"
            if full not in added_set:
                added_set.add(full)
                rows.append((full, f"{name_en} - {brand}",
                             gen_barcode("AW10", n), cat, sale, purchase))
                n += 1
            for model in models:
                full2 = f"{name_ar} {brand} {model}"
                if full2 not in added_set:
                    added_set.add(full2)
                    rows.append((full2, f"{name_en} {brand} {model}",
                                 gen_barcode("AW10", n), cat, sale, purchase))
                    n += 1
                if len(rows) + len(existing) >= target:
                    break
            if len(rows) + len(existing) >= target:
                break
        if len(rows) + len(existing) >= target:
            break

    if len(rows) + len(existing) < target:
        for base_ar, base_en, cat, sale, purchase in itertools.cycle(items):
            full = f"{base_ar} #{n}"
            if full not in added_set:
                added_set.add(full)
                rows.append((full, f"{base_en} #{n}", gen_barcode("AW10", n), cat, sale, purchase))
                n += 1
            if len(rows) + len(existing) >= target:
                break

    added = batch_insert(cur, biz_id, cat_map, rows)
    print(f"  ورشة الأمين للسيارات → أضيف {added} منتج")
    return added


# ══════════════════════════════════════════════════════════
# BUSINESS 11 — بقالة الأمل → 2000
# ══════════════════════════════════════════════════════════
def seed_grocery(cur, biz_id, biz_name, prefix, target=2000):
    cats = ["خضار طازجة", "فواكه طازجة", "ألبان وبيض",
            "مواد غذائية أساسية", "مشروبات", "معلبات",
            "خبز ومعجنات", "حلويات وسناكات", "منظفات", "متفرقات"]
    cat_map = ensure_cats(cur, biz_id, cats)
    existing = existing_names(cur, biz_id)
    rows = []
    n = int(prefix) * 1000 + 1

    vegetables = [
        ("طماطم","Tomatoes","خضار طازجة",200,120),
        ("خيار","Cucumber","خضار طازجة",150,90),
        ("بطاطس","Potatoes","خضار طازجة",180,110),
        ("بصل","Onion","خضار طازجة",150,90),
        ("ثوم","Garlic","خضار طازجة",300,180),
        ("جزر","Carrots","خضار طازجة",160,95),
        ("كوسا","Zucchini","خضار طازجة",200,120),
        ("باذنجان","Eggplant","خضار طازجة",180,108),
        ("فلفل","Pepper","خضار طازجة",250,150),
        ("ملفوف","Cabbage","خضار طازجة",200,120),
        ("خس","Lettuce","خضار طازجة",200,120),
        ("بقدونس","Parsley","خضار طازجة",100,60),
        ("نعناع","Mint","خضار طازجة",100,60),
        ("سبانخ","Spinach","خضار طازجة",200,120),
        ("قرنبيط","Cauliflower","خضار طازجة",250,150),
        ("بروكلي","Broccoli","خضار طازجة",300,180),
        ("بطاطا حلوة","Sweet Potato","خضار طازجة",250,150),
        ("فجل","Radish","خضار طازجة",150,90),
        ("كراث","Leek","خضار طازجة",200,120),
        ("بازلاء","Peas","خضار طازجة",300,180),
    ]
    fruits = [
        ("تفاح","Apples","فواكه طازجة",300,180),
        ("موز","Bananas","فواكه طازجة",250,150),
        ("برتقال","Oranges","فواكه طازجة",250,150),
        ("مانغو","Mango","فواكه طازجة",500,300),
        ("فراولة","Strawberries","فواكه طازجة",600,360),
        ("عنب","Grapes","فواكه طازجة",500,300),
        ("بطيخ","Watermelon","فواكه طازجة",150,90),
        ("شمام","Cantaloupe","فواكه طازجة",300,180),
        ("خوخ","Peach","فواكه طازجة",500,300),
        ("إجاص","Pear","فواكه طازجة",400,240),
        ("دراقن","Plum","فواكه طازجة",600,360),
        ("ليمون","Lemon","فواكه طازجة",300,180),
        ("جريب فروت","Grapefruit","فواكه طازجة",400,240),
        ("رمان","Pomegranate","فواكه طازجة",500,300),
        ("تمر","Dates","فواكه طازجة",700,420),
        ("أفوكادو","Avocado","فواكه طازجة",600,360),
        ("كيوي","Kiwi","فواكه طازجة",600,360),
        ("أناناس","Pineapple","فواكه طازجة",800,480),
        ("باباي","Papaya","فواكه طازجة",500,300),
        ("تين","Figs","فواكه طازجة",800,480),
    ]
    other_items = [
        ("بيض كرتونة 30","Eggs 30pcs","ألبان وبيض",2000,1500),
        ("بيض كرتونة 12","Eggs 12pcs","ألبان وبيض",900,650),
        ("حليب ليتر","Milk 1L","ألبان وبيض",700,500),
        ("جبنة بيضاء كيلو","White Cheese 1kg","ألبان وبيض",2500,1800),
        ("زبادي 200غ","Yogurt 200g","ألبان وبيض",300,200),
        ("خبز أبيض","White Bread","خبز ومعجنات",500,300),
        ("خبز قمح","Wheat Bread","خبز ومعجنات",600,370),
        ("خبز تميس","Tamis Bread","خبز ومعجنات",400,240),
        ("سكر كيلو","Sugar 1kg","مواد غذائية أساسية",500,350),
        ("ملح كيلو","Salt 1kg","مواد غذائية أساسية",300,180),
        ("دقيق 5كغ","Flour 5kg","مواد غذائية أساسية",1500,1000),
        ("أرز 2كغ","Rice 2kg","مواد غذائية أساسية",1500,1050),
        ("معكرونة 500غ","Pasta 500g","مواد غذائية أساسية",500,330),
        ("زيت 1لتر","Oil 1L","مواد غذائية أساسية",1200,800),
        ("كولا 500مل","Cola 500ml","مشروبات",300,180),
        ("مياه 1.5لتر","Water 1.5L","مشروبات",150,80),
        ("عصير كرتون 200مل","Juice Carton 200ml","مشروبات",200,120),
        ("فول معلب","Canned Fava","معلبات",400,270),
        ("تونة 185غ","Tuna 185g","معلبات",600,400),
        ("مربى 400غ","Jam 400g","معلبات",500,330),
        ("شيبس","Chips","حلويات وسناكات",250,160),
        ("شوكولاتة","Chocolate","حلويات وسناكات",300,190),
        ("بسكويت","Biscuit","حلويات وسناكات",300,190),
        ("سائل جلي","Dish Soap","منظفات",600,380),
        ("مسحوق غسيل 500غ","Laundry Powder 500g","منظفات",800,530),
    ]

    weights = ["250 غ", "500 غ", "1 كغ", "2 كغ", "5 كغ", "صندوق", "شوال"]
    all_items = vegetables + fruits + other_items

    added_set = set(existing)
    for name_ar, name_en, cat, sale, purchase in all_items:
        for w in weights:
            full = f"{name_ar} {w}"
            if full not in added_set:
                added_set.add(full)
                rows.append((full, f"{name_en} {w}",
                             gen_barcode(f"GR{prefix}", n), cat, sale, purchase))
                n += 1
            if len(rows) + len(existing) >= target:
                break
        if len(rows) + len(existing) >= target:
            break

    if len(rows) + len(existing) < target:
        for base_ar, base_en, cat, sale, purchase in itertools.cycle(all_items):
            full = f"{base_ar} #{n}"
            if full not in added_set:
                added_set.add(full)
                rows.append((full, f"{base_en} #{n}", gen_barcode(f"GR{prefix}", n), cat, sale, purchase))
                n += 1
            if len(rows) + len(existing) >= target:
                break

    added = batch_insert(cur, biz_id, cat_map, rows)
    print(f"  {biz_name} → أضيف {added} منتج")
    return added


# ══════════════════════════════════════════════════════════
# BUSINESS 13 — إلكترونيات → 2000
# ══════════════════════════════════════════════════════════
def seed_electronics(cur, biz_id, target=2000):
    cats = ["هواتف ذكية", "لابتوب وكمبيوتر", "تلفزيونات", "صوتيات",
            "أجهزة منزلية صغيرة", "أجهزة منزلية كبيرة",
            "إكسسوار هواتف", "إكسسوار كمبيوتر", "ألعاب وترفيه",
            "كاميرات", "شبكات وإنترنت"]
    cat_map = ensure_cats(cur, biz_id, cats)
    existing = existing_names(cur, biz_id)
    rows = []
    n = 13001

    items = [
        ("هاتف Samsung Galaxy S","Samsung Galaxy S","هواتف ذكية",8000,6000),
        ("هاتف Samsung Galaxy A","Samsung Galaxy A","هواتف ذكية",4000,3000),
        ("هاتف iPhone","iPhone","هواتف ذكية",12000,9000),
        ("هاتف Xiaomi Redmi","Xiaomi Redmi","هواتف ذكية",3500,2600),
        ("هاتف Xiaomi Mi","Xiaomi Mi","هواتف ذكية",5000,3750),
        ("هاتف OPPO A Series","OPPO A Series","هواتف ذكية",3500,2600),
        ("هاتف OPPO Reno","OPPO Reno","هواتف ذكية",5500,4100),
        ("هاتف Huawei P","Huawei P","هواتف ذكية",5000,3750),
        ("هاتف Vivo V","Vivo V","هواتف ذكية",4000,3000),
        ("هاتف Realme","Realme","هواتف ذكية",3000,2250),
        ("لابتوب Dell Inspiron","Dell Inspiron Laptop","لابتوب وكمبيوتر",8000,6000),
        ("لابتوب HP Pavilion","HP Pavilion Laptop","لابتوب وكمبيوتر",7500,5600),
        ("لابتوب Lenovo IdeaPad","Lenovo IdeaPad Laptop","لابتوب وكمبيوتر",7000,5250),
        ("لابتوب Asus VivoBook","Asus VivoBook Laptop","لابتوب وكمبيوتر",7500,5600),
        ("لابتوب Apple MacBook Air","MacBook Air","لابتوب وكمبيوتر",15000,11250),
        ("لابتوب Apple MacBook Pro","MacBook Pro","لابتوب وكمبيوتر",20000,15000),
        ("كمبيوتر مكتبي","Desktop PC","لابتوب وكمبيوتر",6000,4500),
        ("تلفزيون 32 بوصة","TV 32 inch","تلفزيونات",4000,3000),
        ("تلفزيون 43 بوصة","TV 43 inch","تلفزيونات",6000,4500),
        ("تلفزيون 55 بوصة","TV 55 inch","تلفزيونات",9000,6750),
        ("تلفزيون 65 بوصة","TV 65 inch","تلفزيونات",13000,9750),
        ("تلفزيون OLED","OLED TV","تلفزيونات",20000,15000),
        ("سماعات بلوتوث","Bluetooth Headphones","صوتيات",2000,1300),
        ("سماعات لاسلكية AirPods","AirPods","صوتيات",3000,2000),
        ("مكبر صوت بلوتوث","Bluetooth Speaker","صوتيات",1500,1000),
        ("مكبر صوت منزلي","Home Speaker","صوتيات",3000,2000),
        ("ساعة ذكية","Smartwatch","إكسسوار هواتف",3000,2000),
        ("ساعة Apple Watch","Apple Watch","إكسسوار هواتف",8000,6000),
        ("كفر هاتف","Phone Case","إكسسوار هواتف",300,150),
        ("شاشة حماية","Screen Protector","إكسسوار هواتف",200,100),
        ("شاحن سريع","Fast Charger","إكسسوار هواتف",500,300),
        ("باور بنك 10000","Powerbank 10000mAh","إكسسوار هواتف",1000,650),
        ("باور بنك 20000","Powerbank 20000mAh","إكسسوار هواتف",1500,975),
        ("كابل USB-C","USB-C Cable","إكسسوار هواتف",200,100),
        ("ماوس لاسلكي","Wireless Mouse","إكسسوار كمبيوتر",600,390),
        ("لوحة مفاتيح لاسلكية","Wireless Keyboard","إكسسوار كمبيوتر",800,520),
        ("فلاش ميموري 32GB","Flash 32GB","إكسسوار كمبيوتر",300,180),
        ("فلاش ميموري 64GB","Flash 64GB","إكسسوار كمبيوتر",500,300),
        ("فلاش ميموري 128GB","Flash 128GB","إكسسوار كمبيوتر",800,500),
        ("هارد خارجي 1TB","External HDD 1TB","إكسسوار كمبيوتر",2000,1350),
        ("كاميرا كانون","Canon Camera","كاميرات",8000,6000),
        ("كاميرا نيكون","Nikon Camera","كاميرات",9000,6750),
        ("كاميرا سوني","Sony Camera","كاميرات",10000,7500),
        ("كاميرا مراقبة","Security Camera","كاميرات",2000,1350),
        ("راوتر واي فاي","WiFi Router","شبكات وإنترنت",1500,1000),
        ("سويتش شبكة","Network Switch","شبكات وإنترنت",1000,650),
        ("بلايستيشن 5","PlayStation 5","ألعاب وترفيه",15000,11250),
        ("إكس بوكس","Xbox","ألعاب وترفيه",14000,10500),
        ("نينتندو سويتش","Nintendo Switch","ألعاب وترفيه",8000,6000),
        ("غيم باد","Gamepad","ألعاب وترفيه",2000,1350),
        ("مكنسة كهربائية","Vacuum Cleaner","أجهزة منزلية صغيرة",3000,2000),
        ("خلاط كهربائي","Blender","أجهزة منزلية صغيرة",1000,650),
        ("طباخ أرز","Rice Cooker","أجهزة منزلية صغيرة",1500,1000),
        ("مكواة ملابس","Iron","أجهزة منزلية صغيرة",800,520),
        ("ميكروويف","Microwave","أجهزة منزلية كبيرة",5000,3500),
        ("ثلاجة","Refrigerator","أجهزة منزلية كبيرة",15000,10500),
        ("غسالة ملابس","Washing Machine","أجهزة منزلية كبيرة",12000,8400),
        ("مكيف","Air Conditioner","أجهزة منزلية كبيرة",20000,14000),
    ]

    brands = ["Samsung", "Apple", "Sony", "LG", "Xiaomi", "Huawei", "OPPO", "Dell", "HP", "Lenovo"]
    storages = ["64GB", "128GB", "256GB", "512GB", "1TB"]
    colors = ["أسود", "أبيض", "رمادي", "ذهبي", "أزرق"]

    added_set = set(existing)
    for name_ar, name_en, cat, sale, purchase in items:
        for color in colors:
            for stor in storages:
                full = f"{name_ar} {color} {stor}"
                if full not in added_set:
                    added_set.add(full)
                    rows.append((full, f"{name_en} {color} {stor}",
                                 gen_barcode("EL13", n), cat, sale, purchase))
                    n += 1
                if len(rows) + len(existing) >= target:
                    break
            if len(rows) + len(existing) >= target:
                break
        if len(rows) + len(existing) >= target:
            break

    if len(rows) + len(existing) < target:
        for base_ar, base_en, cat, sale, purchase in itertools.cycle(items):
            full = f"{base_ar} #{n}"
            if full not in added_set:
                added_set.add(full)
                rows.append((full, f"{base_en} #{n}", gen_barcode("EL13", n), cat, sale, purchase))
                n += 1
            if len(rows) + len(existing) >= target:
                break

    added = batch_insert(cur, biz_id, cat_map, rows)
    print(f"  تيك هاوس للإلكترونيات → أضيف {added} منتج")
    return added


# ══════════════════════════════════════════════════════════
# التنفيذ الرئيسي
# ══════════════════════════════════════════════════════════
def main():
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-32000")
    cur = conn.cursor()

    print("=" * 60)
    print("  seed_full.py — إضافة منتجات كاملة لجميع الأنشطة")
    print("=" * 60)

    # جلب معرّفات المنشآت
    def get_id(name):
        row = cur.execute("SELECT id FROM businesses WHERE name=? AND is_active=1", (name,)).fetchone()
        return row[0] if row else None

    biz1  = get_id("المتجر الرئيسي")
    biz5  = get_id("مطعم الوجبات الذهبية")
    biz6  = get_id("صيدلية الشفاء")
    biz7  = get_id("ملحمة الخير الطازجة")
    biz8  = get_id("كافيه السحاب")
    biz9  = get_id("بوتيك الرجل الأنيق")
    biz10 = get_id("ورشة الأمين للسيارات")
    biz11 = get_id("بقالة الأمل")
    biz12 = get_id("سوق الخير للخضار والفواكه")
    biz13 = get_id("تيك هاوس للإلكترونيات")

    total = 0
    if biz1:  total += seed_retail_main(cur, biz1,  target=10000)
    if biz5:  total += seed_restaurant(cur, biz5,   target=2000)
    if biz6:  total += seed_pharmacy(cur, biz6,     target=2000)
    if biz7:  total += seed_butcher(cur, biz7,      target=2000)
    if biz8:  total += seed_cafe(cur, biz8,         target=2000)
    if biz9:  total += seed_fashion(cur, biz9,      target=2000)
    if biz10: total += seed_auto(cur, biz10,        target=2000)
    if biz11: total += seed_grocery(cur, biz11, "بقالة الأمل",            "11", target=2000)
    if biz12: total += seed_grocery(cur, biz12, "سوق الخير للخضار والفواكه", "12", target=2000)
    if biz13: total += seed_electronics(cur, biz13, target=2000)

    conn.commit()
    conn.close()

    print("=" * 60)
    print(f"  ✅ اكتمل — إجمالي المضاف: {total:,} منتج")
    print("=" * 60)

    # التحقق النهائي
    conn2 = sqlite3.connect(DB)
    rows = conn2.execute("""
        SELECT b.name, COUNT(p.id) as cnt
        FROM businesses b
        LEFT JOIN products p ON p.business_id = b.id AND p.is_active=1
        WHERE b.is_active=1
        GROUP BY b.id ORDER BY b.id
    """).fetchall()
    grand = conn2.execute("SELECT COUNT(*) FROM products WHERE is_active=1").fetchone()[0]
    conn2.close()

    print("\n  ملخص المنتجات النهائي:")
    for r in rows:
        print(f"    {r[0]:<40} {r[1]:>6} منتج")
    print(f"\n  ═══ الإجمالي الكلي: {grand:,} منتج نشط ═══")


if __name__ == "__main__":
    main()
