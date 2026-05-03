"""
modules/industry_seeds.py — بذور البيانات الأولية حسب نوع النشاط

عند اكتمال onboarding، يُستدعى seed_industry_defaults() لتهيئة:
  1. تصنيفات المنتجات المناسبة للنشاط
  2. منتجات/خدمات نموذجية (5-8 أصناف)
  3. إعدادات النشاط (POS mode، بادئة الفاتورة، إلخ)

الهدف: العميل يبدأ شغله فوراً بدون تهيئة يدوية
"""
from __future__ import annotations
import sqlite3
import logging

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# 1. قاعدة بيانات البذور — كل نشاط لوحده
# ═══════════════════════════════════════════════════════════════════════════════

# كل إدخال:
#   categories: [اسم التصنيف, ...]
#   products:   [{name, category, price, unit, product_type="product"|"service", is_pos=1}]
#   settings:   {key: value}  ← يُدمج مع إعدادات النشاط

_SEEDS: dict[str, dict] = {

    # ──────────────────────────────────────────────────────────────────────────
    # ■ مطاعم وكافيهات
    # ──────────────────────────────────────────────────────────────────────────
    "food_restaurant": {
        "categories": ["مشروبات", "مشويات", "وجبات رئيسية", "سلطات", "حلويات", "إضافات"],
        "products": [
            {"name": "مياه معدنية",      "category": "مشروبات",       "price": 2.0,   "unit": "زجاجة"},
            {"name": "عصير طازج",        "category": "مشروبات",       "price": 15.0,  "unit": "كوب"},
            {"name": "دجاج مشوي",        "category": "مشويات",        "price": 45.0,  "unit": "حصة"},
            {"name": "لحم مشوي",         "category": "مشويات",        "price": 65.0,  "unit": "حصة"},
            {"name": "وجبة عائلية",      "category": "وجبات رئيسية", "price": 120.0, "unit": "طبق"},
            {"name": "سلطة خضراء",      "category": "سلطات",         "price": 18.0,  "unit": "طبق"},
            {"name": "كيكة شوكولا",     "category": "حلويات",        "price": 22.0,  "unit": "قطعة"},
            {"name": "صلصة زيادة",      "category": "إضافات",        "price": 3.0,   "unit": "طبق"},
        ],
        "settings": {
            "pos_mode":       "restaurant",
            "invoice_prefix": "RES",
            "show_tables":    "1",
            "show_kitchen":   "1",
        },
    },
    "food_cafe": {
        "categories": ["قهوة", "شاي", "مشروبات باردة", "حلويات", "وجبات خفيفة"],
        "products": [
            {"name": "قهوة عربية",       "category": "قهوة",            "price": 12.0,  "unit": "كوب"},
            {"name": "قهوة لاتيه",       "category": "قهوة",            "price": 18.0,  "unit": "كوب"},
            {"name": "كابتشينو",         "category": "قهوة",            "price": 18.0,  "unit": "كوب"},
            {"name": "شاي أخضر",        "category": "شاي",             "price": 10.0,  "unit": "كوب"},
            {"name": "عصير فراولة",     "category": "مشروبات باردة",   "price": 20.0,  "unit": "كوب"},
            {"name": "موكا فريد",        "category": "مشروبات باردة",   "price": 22.0,  "unit": "كوب"},
            {"name": "كاب كيك",          "category": "حلويات",          "price": 15.0,  "unit": "قطعة"},
            {"name": "كرواسان",          "category": "وجبات خفيفة",    "price": 12.0,  "unit": "قطعة"},
        ],
        "settings": {
            "pos_mode":       "restaurant",
            "invoice_prefix": "CAF",
            "show_tables":    "1",
        },
    },
    "food_coffeeshop": {
        "categories": ["قهوة مختصة", "مشروبات باردة", "مشروبات ساخنة", "حلويات"],
        "products": [
            {"name": "إسبريسو",          "category": "قهوة مختصة",     "price": 12.0,  "unit": "كوب"},
            {"name": "فلات وايت",       "category": "قهوة مختصة",     "price": 20.0,  "unit": "كوب"},
            {"name": "كولد برو",         "category": "مشروبات باردة",  "price": 22.0,  "unit": "كوب"},
            {"name": "ماتشا لاتيه",     "category": "مشروبات ساخنة",  "price": 22.0,  "unit": "كوب"},
            {"name": "بسكويت",           "category": "حلويات",         "price": 8.0,   "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "restaurant", "invoice_prefix": "COF"},
    },
    "food_hookah": {
        "categories": ["معسل", "فحم", "مشروبات", "وجبات خفيفة"],
        "products": [
            {"name": "معسل تفاح",        "category": "معسل",           "price": 50.0,  "unit": "رأس"},
            {"name": "معسل عنب نعناع",  "category": "معسل",           "price": 55.0,  "unit": "رأس"},
            {"name": "معسل توت",         "category": "معسل",           "price": 50.0,  "unit": "رأس"},
            {"name": "فحم سريع",         "category": "فحم",            "price": 5.0,   "unit": "قطعة"},
            {"name": "مياه معدنية",      "category": "مشروبات",        "price": 3.0,   "unit": "زجاجة"},
        ],
        "settings": {"pos_mode": "restaurant", "invoice_prefix": "HKH"},
    },

    # ──────────────────────────────────────────────────────────────────────────
    # ■ تجزئة غذائية
    # ──────────────────────────────────────────────────────────────────────────
    "retail_fnb_supermarket": {
        "categories": ["مواد غذائية", "مشروبات", "ألبان وأجبان", "خضار وفواكه", "منظفات", "مجمدات"],
        "products": [
            {"name": "أرز بسمتي 5 كيلو",  "category": "مواد غذائية", "price": 32.0, "unit": "كيس"},
            {"name": "سكر أبيض 2 كيلو",   "category": "مواد غذائية", "price": 10.0, "unit": "كيس"},
            {"name": "زيت نباتي 1.5 لتر", "category": "مواد غذائية", "price": 18.0, "unit": "زجاجة"},
            {"name": "حليب طازج",          "category": "ألبان وأجبان","price": 8.0,  "unit": "علبة"},
            {"name": "مياه معدنية 6 زجاجات","category": "مشروبات",   "price": 10.0, "unit": "كرتون"},
            {"name": "عصير برتقال 1 لتر",  "category": "مشروبات",   "price": 12.0, "unit": "عبوة"},
            {"name": "صابون يدين",         "category": "منظفات",     "price": 7.0,  "unit": "قطعة"},
            {"name": "دجاج مجمد 1 كيلو",  "category": "مجمدات",    "price": 28.0, "unit": "كيلو"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "SPM"},
    },
    "retail_fnb_grocery": {
        "categories": ["تموينات", "مواد غذائية", "مشروبات", "منظفات"],
        "products": [
            {"name": "طحين 2 كيلو",       "category": "تموينات",     "price": 8.0,  "unit": "كيس"},
            {"name": "أرز 2 كيلو",        "category": "تموينات",     "price": 14.0, "unit": "كيس"},
            {"name": "معكرونة",            "category": "مواد غذائية", "price": 5.0,  "unit": "علبة"},
            {"name": "مياه معدنية",        "category": "مشروبات",    "price": 2.0,  "unit": "زجاجة"},
            {"name": "شاي أكواب",         "category": "تموينات",     "price": 9.0,  "unit": "علبة"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "GRO"},
    },
    "retail_fnb_bakery": {
        "categories": ["خبز", "حلويات", "كيك وتورتة", "مخبوزات"],
        "products": [
            {"name": "خبز عربي",           "category": "خبز",         "price": 2.0,  "unit": "كيس"},
            {"name": "كرواسان",            "category": "مخبوزات",    "price": 5.0,  "unit": "قطعة"},
            {"name": "كيكة إسفنجية",      "category": "كيك وتورتة", "price": 35.0, "unit": "قطعة"},
            {"name": "بسكويت شوكولا",     "category": "حلويات",     "price": 12.0, "unit": "علبة"},
            {"name": "صمون",              "category": "خبز",         "price": 1.0,  "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "BKR"},
    },
    "retail_fnb_butcher": {
        "categories": ["لحوم حمراء", "دواجن", "أسماك", "مشتقات"],
        "products": [
            {"name": "لحم بقري مفروم",    "category": "لحوم حمراء", "price": 55.0, "unit": "كيلو"},
            {"name": "لحم غنم",           "category": "لحوم حمراء", "price": 75.0, "unit": "كيلو"},
            {"name": "دجاج كامل",         "category": "دواجن",     "price": 25.0, "unit": "كيلو"},
            {"name": "صدر دجاج",          "category": "دواجن",     "price": 38.0, "unit": "كيلو"},
            {"name": "سمك فيليه",         "category": "أسماك",     "price": 50.0, "unit": "كيلو"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "BUT"},
    },
    "retail_fnb_roaster": {
        "categories": ["قهوة", "بهارات", "مكسرات", "شاي"],
        "products": [
            {"name": "قهوة عربية محمصة 250 جم",  "category": "قهوة",    "price": 35.0, "unit": "كيس"},
            {"name": "هيل مطحون",                  "category": "بهارات", "price": 15.0, "unit": "كيس"},
            {"name": "مكسرات مشكلة",              "category": "مكسرات", "price": 45.0, "unit": "كيلو"},
            {"name": "شاي أسود",                  "category": "شاي",    "price": 20.0, "unit": "علبة"},
            {"name": "خلطة بهارات",               "category": "بهارات", "price": 12.0, "unit": "كيس"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "RST"},
    },

    # ──────────────────────────────────────────────────────────────────────────
    # ■ صيدلية — هوية كاملة
    # ──────────────────────────────────────────────────────────────────────────
    "retail_health_pharmacy": {
        "categories": ["أدوية وصفة طبية", "أدوية بدون وصفة", "فيتامينات ومكملات",
                       "مستلزمات طبية", "مستحضرات تجميل طبية", "أطفال ورضع"],
        "products": [
            {"name": "بانادول 500 مجم",      "category": "أدوية بدون وصفة",  "price": 12.0, "unit": "علبة"},
            {"name": "فيتامين C 1000 مجم",  "category": "فيتامينات ومكملات","price": 35.0, "unit": "علبة"},
            {"name": "جبيرة يد",             "category": "مستلزمات طبية",    "price": 25.0, "unit": "قطعة"},
            {"name": "جرثومة المعدة — شريط","category": "أدوية بدون وصفة",  "price": 28.0, "unit": "شريط"},
            {"name": "كريم موضعي",           "category": "مستحضرات تجميل طبية","price": 40.0,"unit": "أنبوب"},
            {"name": "حفاضات مولود",         "category": "أطفال ورضع",       "price": 55.0, "unit": "علبة"},
            {"name": "ضغط الدم رقمي",       "category": "مستلزمات طبية",    "price": 180.0,"unit": "جهاز"},
        ],
        "settings": {
            "pos_mode":       "pharmacy",
            "invoice_prefix": "PHR",
            "track_expiry":   "1",
        },
    },
    "retail_health_perfume": {
        "categories": ["عطور رجالي", "عطور نسائي", "بخور وعود", "أدوات عطور"],
        "products": [
            {"name": "عطر رجالي فاخر",     "category": "عطور رجالي", "price": 250.0, "unit": "زجاجة"},
            {"name": "عطر نسائي",          "category": "عطور نسائي", "price": 220.0, "unit": "زجاجة"},
            {"name": "دخون عود أصيل",     "category": "بخور وعود",  "price": 120.0, "unit": "قطعة"},
            {"name": "عود كمبودي",         "category": "بخور وعود",  "price": 350.0, "unit": "جرام"},
            {"name": "مبخرة فضية",         "category": "أدوات عطور", "price": 85.0,  "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "fashion", "invoice_prefix": "PRF"},
    },
    "retail_health_cosmetics": {
        "categories": ["عناية بالبشرة", "مكياج", "عناية بالشعر", "عطور وبودي"],
        "products": [
            {"name": "كريم ترطيب",       "category": "عناية بالبشرة", "price": 65.0, "unit": "عبوة"},
            {"name": "مسكرة",            "category": "مكياج",         "price": 45.0, "unit": "قطعة"},
            {"name": "أحمر شفاه",       "category": "مكياج",         "price": 38.0, "unit": "قطعة"},
            {"name": "شامبو مرطب",      "category": "عناية بالشعر",  "price": 35.0, "unit": "زجاجة"},
            {"name": "بودي لوشن",       "category": "عطور وبودي",    "price": 48.0, "unit": "زجاجة"},
        ],
        "settings": {"pos_mode": "fashion", "invoice_prefix": "COS"},
    },
    "retail_health_supplements": {
        "categories": ["بروتين", "فيتامينات", "طاقة وحرق", "صحة عامة"],
        "products": [
            {"name": "بروتين واي 1 كيلو",  "category": "بروتين",       "price": 180.0, "unit": "علبة"},
            {"name": "فيتامين D3",         "category": "فيتامينات",    "price": 45.0,  "unit": "علبة"},
            {"name": "أوميغا 3",           "category": "صحة عامة",    "price": 55.0,  "unit": "علبة"},
            {"name": "كرياتين 500 جم",    "category": "بروتين",       "price": 95.0,  "unit": "علبة"},
            {"name": "حارق دهون",          "category": "طاقة وحرق",   "price": 120.0, "unit": "علبة"},
        ],
        "settings": {"pos_mode": "pharmacy", "invoice_prefix": "SUP"},
    },

    # ──────────────────────────────────────────────────────────────────────────
    # ■ ملابس وأزياء
    # ──────────────────────────────────────────────────────────────────────────
    "retail_fashion_clothing_m": {
        "categories": ["قمصان وبولو", "بناطيل وجينز", "ثوب سعودي", "ملابس رياضية", "إكسسوارات"],
        "products": [
            {"name": "قميص رجالي قطن",     "category": "قمصان وبولو",    "price": 85.0,  "unit": "قطعة"},
            {"name": "جينز عادي",           "category": "بناطيل وجينز",  "price": 120.0, "unit": "قطعة"},
            {"name": "ثوب سعودي أبيض",     "category": "ثوب سعودي",     "price": 180.0, "unit": "قطعة"},
            {"name": "تيشيرت رياضي",       "category": "ملابس رياضية",  "price": 55.0,  "unit": "قطعة"},
            {"name": "حزام جلد",            "category": "إكسسوارات",     "price": 45.0,  "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "fashion", "invoice_prefix": "MFA"},
    },
    "retail_fashion_clothing_f": {
        "categories": ["فساتين", "عبايات", "بلايز وتيشيرت", "بناطيل", "إكسسوارات"],
        "products": [
            {"name": "عباية سوداء كلاسيك", "category": "عبايات",          "price": 220.0, "unit": "قطعة"},
            {"name": "فستان سهرة",          "category": "فساتين",          "price": 350.0, "unit": "قطعة"},
            {"name": "بلوزة شيفون",         "category": "بلايز وتيشيرت", "price": 95.0,  "unit": "قطعة"},
            {"name": "بنطلون قماش",         "category": "بناطيل",         "price": 110.0, "unit": "قطعة"},
            {"name": "حجاب شيفون",         "category": "إكسسوارات",      "price": 35.0,  "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "fashion", "invoice_prefix": "FFA"},
    },
    "retail_fashion_clothing_k": {
        "categories": ["مواليد (0-2 سنة)", "أطفال صغار (2-6)", "مدرسة (6-14)", "رياضة أطفال"],
        "products": [
            {"name": "بيبي رومبر",          "category": "مواليد (0-2 سنة)",   "price": 45.0, "unit": "قطعة"},
            {"name": "لبس طفل 2 قطعة",    "category": "أطفال صغار (2-6)",  "price": 75.0, "unit": "طقم"},
            {"name": "زي مدرسي",           "category": "مدرسة (6-14)",      "price": 95.0, "unit": "طقم"},
            {"name": "تيشيرت رياضي أطفال","category": "رياضة أطفال",       "price": 35.0, "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "fashion", "invoice_prefix": "KFA"},
    },
    "retail_fashion_shoes": {
        "categories": ["أحذية رجالي", "أحذية نسائي", "أحذية أطفال", "شنط وحقائب"],
        "products": [
            {"name": "حذاء رسمي رجالي",   "category": "أحذية رجالي", "price": 250.0, "unit": "قطعة"},
            {"name": "حذاء رياضي",         "category": "أحذية رجالي", "price": 180.0, "unit": "قطعة"},
            {"name": "حذاء نسائي كعب",    "category": "أحذية نسائي", "price": 195.0, "unit": "قطعة"},
            {"name": "حذاء أطفال",         "category": "أحذية أطفال", "price": 95.0,  "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "fashion", "invoice_prefix": "SHO"},
    },
    "retail_fashion_watches": {
        "categories": ["ساعات رجالي", "ساعات نسائي", "مجوهرات ذهب", "مجوهرات فضة"],
        "products": [
            {"name": "ساعة كلاسيك رجالي",  "category": "ساعات رجالي",    "price": 450.0,  "unit": "قطعة"},
            {"name": "ساعة ذكية",           "category": "ساعات رجالي",    "price": 800.0,  "unit": "قطعة"},
            {"name": "ساعة نسائي ذهبي",    "category": "ساعات نسائي",    "price": 380.0,  "unit": "قطعة"},
            {"name": "خاتم ذهب 21",        "category": "مجوهرات ذهب",    "price": 1200.0, "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "WTC"},
    },

    # ──────────────────────────────────────────────────────────────────────────
    # ■ إلكترونيات
    # ──────────────────────────────────────────────────────────────────────────
    "retail_electronics_mobile": {
        "categories": ["جوالات", "تابلت", "إكسسوارات جوال", "سماعات", "ساعات ذكية"],
        "products": [
            {"name": "جوال سامسونج A55",  "category": "جوالات",          "price": 1800.0, "unit": "جهاز"},
            {"name": "آيفون 15",           "category": "جوالات",          "price": 4200.0, "unit": "جهاز"},
            {"name": "كفر حماية",          "category": "إكسسوارات جوال", "price": 35.0,   "unit": "قطعة"},
            {"name": "سماعة لاسلكية",     "category": "سماعات",          "price": 250.0,  "unit": "قطعة"},
            {"name": "شاحن سريع",         "category": "إكسسوارات جوال", "price": 55.0,   "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "MOB"},
    },
    "retail_electronics_computers": {
        "categories": ["لابتوب", "كمبيوتر مكتبي", "قطع وأجزاء", "شبكات", "طابعات"],
        "products": [
            {"name": "لابتوب HP Core i5",  "category": "لابتوب",          "price": 3200.0, "unit": "جهاز"},
            {"name": "ماوس لاسلكي",        "category": "قطع وأجزاء",     "price": 65.0,   "unit": "قطعة"},
            {"name": "كيبورد ميكانيكي",    "category": "قطع وأجزاء",     "price": 180.0,  "unit": "قطعة"},
            {"name": "راوتر واي فاي",      "category": "شبكات",           "price": 250.0,  "unit": "جهاز"},
            {"name": "هارد ديسك 1 ترا",   "category": "قطع وأجزاء",     "price": 220.0,  "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "CMP"},
    },
    "retail_electronics_appliances": {
        "categories": ["أجهزة مطبخ", "تكييف وتبريد", "غسيل وتنظيف", "شاشات وتلفزيون"],
        "products": [
            {"name": "غسالة أوتوماتيك",   "category": "غسيل وتنظيف",   "price": 1800.0, "unit": "جهاز"},
            {"name": "مكيف سبليت 18000",  "category": "تكييف وتبريد",  "price": 3500.0, "unit": "جهاز"},
            {"name": "تلفزيون 55 بوصة",   "category": "شاشات وتلفزيون","price": 2800.0, "unit": "جهاز"},
            {"name": "ثلاجة دبل دور",     "category": "أجهزة مطبخ",    "price": 2200.0, "unit": "جهاز"},
            {"name": "مايكروويف",          "category": "أجهزة مطبخ",    "price": 380.0,  "unit": "جهاز"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "APP"},
    },
    "retail_electronics_security": {
        "categories": ["كاميرات مراقبة", "أنظمة إنذار", "أقفال ذكية", "خدمات تركيب"],
        "products": [
            {"name": "كاميرا 4MP خارجية", "category": "كاميرات مراقبة", "price": 350.0,  "unit": "جهاز"},
            {"name": "NVR 8 قناة",        "category": "أنظمة إنذار",    "price": 850.0,  "unit": "جهاز"},
            {"name": "قفل بصمة",           "category": "أقفال ذكية",    "price": 650.0,  "unit": "قطعة"},
            {"name": "خدمة تركيب كاميرا", "category": "خدمات تركيب",   "price": 200.0,  "unit": "خدمة",
             "product_type": "service"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "SEC"},
    },

    # ──────────────────────────────────────────────────────────────────────────
    # ■ قطع غيار وسيارات
    # ──────────────────────────────────────────────────────────────────────────
    "retail_auto_parts": {
        "categories": ["فلاتر", "زيوت وسوائل", "فرامل", "إضاءة", "إلكترونيات سيارة"],
        "products": [
            {"name": "فلتر زيت",            "category": "فلاتر",            "price": 25.0,  "unit": "قطعة"},
            {"name": "فلتر هواء",            "category": "فلاتر",            "price": 35.0,  "unit": "قطعة"},
            {"name": "زيت موتور 5W-30 4L",  "category": "زيوت وسوائل",    "price": 95.0,  "unit": "عبوة"},
            {"name": "تيل فرامل أمامي",     "category": "فرامل",           "price": 65.0,  "unit": "طقم"},
            {"name": "بطارية 70 أمبير",     "category": "إلكترونيات سيارة","price": 350.0, "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "AUT"},
    },
    "retail_auto_tires": {
        "categories": ["إطارات", "بطاريات", "جنوط", "خدمات"],
        "products": [
            {"name": "إطار 205/55R16",    "category": "إطارات",   "price": 280.0, "unit": "قطعة"},
            {"name": "إطار 225/65R17",    "category": "إطارات",   "price": 340.0, "unit": "قطعة"},
            {"name": "بطارية 70 أمبير",   "category": "بطاريات",  "price": 350.0, "unit": "قطعة"},
            {"name": "تبديل إطار",        "category": "خدمات",    "price": 20.0,  "unit": "قطعة",
             "product_type": "service"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "TIR"},
    },

    # ──────────────────────────────────────────────────────────────────────────
    # ■ مواد بناء
    # ──────────────────────────────────────────────────────────────────────────
    "retail_construction_materials": {
        "categories": ["إسمنت وجبس", "حديد وصلب", "رمل وبحص", "بلاط وسيراميك", "عزل"],
        "products": [
            {"name": "إسمنت كيس 50 كيلو", "category": "إسمنت وجبس", "price": 25.0,  "unit": "كيس"},
            {"name": "حديد تسليح 12 مم",  "category": "حديد وصلب",  "price": 280.0, "unit": "طن"},
            {"name": "بلاط سيراميك 60×60","category": "بلاط وسيراميك","price": 75.0, "unit": "م²"},
            {"name": "رمل بناء",           "category": "رمل وبحص",   "price": 180.0, "unit": "متر مكعب"},
            {"name": "لفة عازل مائي",     "category": "عزل",         "price": 120.0, "unit": "لفة"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "CON"},
    },
    "retail_construction_plumbing": {
        "categories": ["مواسير", "خلاطات", "مراحيض وأحواض", "أدوات السباكة"],
        "products": [
            {"name": "ماسورة PVC 4 بوصة", "category": "مواسير",            "price": 18.0,  "unit": "متر"},
            {"name": "خلاط بارد وسخن",    "category": "خلاطات",            "price": 95.0,  "unit": "قطعة"},
            {"name": "مرحاض فرنجي",       "category": "مراحيض وأحواض",    "price": 350.0, "unit": "قطعة"},
            {"name": "مضخة مياه",         "category": "أدوات السباكة",    "price": 280.0, "unit": "جهاز"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "PLM"},
    },
    "retail_construction_electrical": {
        "categories": ["كابلات وأسلاك", "قواطع وبواكس", "إضاءة", "أجهزة كهربائية"],
        "products": [
            {"name": "سلك كهربائي 2.5 مم", "category": "كابلات وأسلاك",   "price": 2.5,  "unit": "متر"},
            {"name": "قاطع 16 أمبير",      "category": "قواطع وبواكس",   "price": 25.0, "unit": "قطعة"},
            {"name": "لمبة LED 12 واط",    "category": "إضاءة",           "price": 12.0, "unit": "قطعة"},
            {"name": "بريزة مع مفتاح",     "category": "قواطع وبواكس",   "price": 8.0,  "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "ELC"},
    },
    "retail_construction_paints": {
        "categories": ["دهان داخلي", "دهان خارجي", "طلاء معادن", "ملحقات"],
        "products": [
            {"name": "دهان داخلي أبيض 3.5 لتر", "category": "دهان داخلي",  "price": 55.0,  "unit": "سطل"},
            {"name": "دهان خارجي مقاوم للطقس",  "category": "دهان خارجي",  "price": 85.0,  "unit": "سطل"},
            {"name": "فرشاة دهان",               "category": "ملحقات",      "price": 8.0,   "unit": "قطعة"},
            {"name": "رول دهان",                 "category": "ملحقات",      "price": 12.0,  "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "PNT"},
    },
    "retail_construction_hardware": {
        "categories": ["عدد يدوية", "معدات كهربائية", "مسامير وبراغي", "لوازم"],
        "products": [
            {"name": "مثقاب كهربائي",          "category": "معدات كهربائية", "price": 280.0, "unit": "جهاز"},
            {"name": "مفك براغي طقم",           "category": "عدد يدوية",     "price": 45.0,  "unit": "طقم"},
            {"name": "مسامير خشب 3 بوصة",      "category": "مسامير وبراغي", "price": 12.0,  "unit": "علبة"},
            {"name": "شريط قياس 5 متر",        "category": "عدد يدوية",     "price": 15.0,  "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "HRW"},
    },

    # ──────────────────────────────────────────────────────────────────────────
    # ■ أثاث ومنزليات
    # ──────────────────────────────────────────────────────────────────────────
    "retail_home_furniture": {
        "categories": ["غرف نوم", "غرف معيشة", "مطابخ", "مكاتب", "ديكور"],
        "products": [
            {"name": "طقم غرفة نوم",     "category": "غرف نوم",    "price": 4500.0, "unit": "طقم"},
            {"name": "كنبة 3 مقاعد",     "category": "غرف معيشة", "price": 2200.0, "unit": "قطعة"},
            {"name": "مكتب دراسة",       "category": "مكاتب",     "price": 850.0,  "unit": "قطعة"},
            {"name": "ستارة",            "category": "ديكور",     "price": 180.0,  "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "FRN"},
    },
    "retail_home_kitchenware": {
        "categories": ["أواني طبخ", "أجهزة مطبخ صغيرة", "أدوات مائدة", "تخزين"],
        "products": [
            {"name": "طقم أواني طبخ",     "category": "أواني طبخ",             "price": 250.0, "unit": "طقم"},
            {"name": "خلاط كهربائي",      "category": "أجهزة مطبخ صغيرة",    "price": 180.0, "unit": "جهاز"},
            {"name": "طقم أكواب",         "category": "أدوات مائدة",           "price": 85.0,  "unit": "طقم"},
            {"name": "علب تخزين زجاجية", "category": "تخزين",                  "price": 45.0,  "unit": "طقم"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "KTC"},
    },
    "retail_home_stationery": {
        "categories": ["قرطاسية مكتب", "قرطاسية مدرسة", "كتب ومراجع", "طباعة وتصوير"],
        "products": [
            {"name": "دفتر A4 100 ورقة",  "category": "قرطاسية مكتب",   "price": 8.0,  "unit": "قطعة"},
            {"name": "أقلام جاف 10 قلم", "category": "قرطاسية مكتب",   "price": 12.0, "unit": "علبة"},
            {"name": "ورق A4 رزمة",       "category": "طباعة وتصوير",  "price": 22.0, "unit": "رزمة"},
            {"name": "مقص",               "category": "قرطاسية مكتب",   "price": 5.0,  "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "STN"},
    },

    # ──────────────────────────────────────────────────────────────────────────
    # ■ جملة
    # ──────────────────────────────────────────────────────────────────────────
    "wholesale_fnb_distribution": {
        "categories": ["حبوب وتموينات", "مشروبات", "زيوت وسمن", "معلبات"],
        "products": [
            {"name": "أرز خام — كرتون", "category": "حبوب وتموينات","price": 280.0, "unit": "كرتون"},
            {"name": "زيت نخيل — صندوق","category": "زيوت وسمن",   "price": 450.0, "unit": "صندوق"},
            {"name": "مياه معدنية — باليت","category": "مشروبات",   "price": 850.0, "unit": "باليت"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WHL"},
    },
    "wholesale_fnb_general": {
        "categories": ["مواد غذائية جملة", "مشروبات جملة", "تموينات جملة"],
        "products": [
            {"name": "أرز 50 كيلو",      "category": "مواد غذائية جملة","price": 320.0, "unit": "كيس"},
            {"name": "سكر 50 كيلو",      "category": "تموينات جملة",    "price": 210.0, "unit": "كيس"},
            {"name": "مياه كرتون 12",    "category": "مشروبات جملة",    "price": 18.0,  "unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WHL"},
    },
    "wholesale_electronics_general": {
        "categories": ["أجهزة إلكترونية", "إكسسوارات", "شاشات وتلفزيون"],
        "products": [
            {"name": "شاشة 43 بوصة كرتون", "category": "شاشات وتلفزيون","price": 1200.0, "unit": "جهاز"},
            {"name": "سماعات جملة",         "category": "إكسسوارات",     "price": 85.0,   "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WEL"},
    },
    "wholesale_auto_parts": {
        "categories": ["فلاتر", "زيوت", "بطاريات", "إطارات"],
        "products": [
            {"name": "فلاتر زيت — كرتون", "category": "فلاتر",   "price": 450.0, "unit": "كرتون"},
            {"name": "زيت محرك 4L × 6",   "category": "زيوت",   "price": 480.0, "unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WAP"},
    },

    # ──────────────────────────────────────────────────────────────────────────
    # ■ قطاعات متخصصة
    # ──────────────────────────────────────────────────────────────────────────
    "retail_specialized_tobacco": {
        "categories": ["معسل", "سجائر", "فحم وأدوات"],
        "products": [
            {"name": "معسل تفاح 50 جم",    "category": "معسل",          "price": 18.0, "unit": "علبة"},
            {"name": "فحم طبيعي 250 جم",  "category": "فحم وأدوات",   "price": 12.0, "unit": "علبة"},
            {"name": "رأس نارجيلة",        "category": "فحم وأدوات",   "price": 35.0, "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "TOB"},
    },
    "retail_specialized_flowers": {
        "categories": ["زهور طازجة", "زهور صناعية", "هدايا مغلفة", "ديكور زهور"],
        "products": [
            {"name": "باقة ورد طبيعي",    "category": "زهور طازجة",   "price": 85.0,  "unit": "باقة"},
            {"name": "زهور صناعية للديكور","category": "زهور صناعية",  "price": 120.0, "unit": "طقم"},
            {"name": "علبة هدايا مغلفة",  "category": "هدايا مغلفة",  "price": 180.0, "unit": "علبة"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "FLW"},
    },
    "retail_specialized_toys": {
        "categories": ["ألعاب أطفال", "ألعاب تعليمية", "مجسمات وعرائس", "هدايا"],
        "products": [
            {"name": "لعبة ليجو 100 قطعة", "category": "ألعاب تعليمية", "price": 95.0,  "unit": "علبة"},
            {"name": "سيارة لعبة",          "category": "ألعاب أطفال",   "price": 35.0,  "unit": "قطعة"},
            {"name": "دمية كبيرة",          "category": "مجسمات وعرائس", "price": 65.0,  "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "TOY"},
    },
    "retail_specialized_pets": {
        "categories": ["طعام حيوانات", "لوازم عناية", "إكسسوارات", "طبية بيطرية"],
        "products": [
            {"name": "طعام قطط 1 كيلو",    "category": "طعام حيوانات", "price": 35.0,  "unit": "كيس"},
            {"name": "طعام كلاب 3 كيلو",   "category": "طعام حيوانات", "price": 65.0,  "unit": "كيس"},
            {"name": "طوق حيوان",           "category": "إكسسوارات",   "price": 25.0,  "unit": "قطعة"},
            {"name": "شامبو حيوانات",       "category": "لوازم عناية", "price": 28.0,  "unit": "زجاجة"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "PET"},
    },
    "retail_specialized_sports": {
        "categories": ["ملابس رياضية", "معدات جيم", "رياضة مائية", "تخييم"],
        "products": [
            {"name": "تيشيرت رياضي",       "category": "ملابس رياضية", "price": 65.0,  "unit": "قطعة"},
            {"name": "حبل قفز",             "category": "معدات جيم",   "price": 25.0,  "unit": "قطعة"},
            {"name": "حذاء رياضي",         "category": "ملابس رياضية", "price": 220.0, "unit": "قطعة"},
            {"name": "كرة قدم",            "category": "معدات جيم",   "price": 85.0,  "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "SPT"},
    },

    # ──────────────────────────────────────────────────────────────────────────
    # ■ قطاعات خدمية
    # ──────────────────────────────────────────────────────────────────────────
    "construction": {
        "categories": ["خدمات هندسية", "مواد مشروع", "معدات"],
        "products": [
            {"name": "خدمة إشراف هندسي", "category": "خدمات هندسية", "price": 5000.0, "unit": "شهر",
             "product_type": "service"},
            {"name": "خدمة تصميم معماري", "category": "خدمات هندسية", "price": 3500.0, "unit": "مشروع",
             "product_type": "service"},
            {"name": "إسمنت كيس 50 كيلو", "category": "مواد مشروع",  "price": 25.0,   "unit": "كيس"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "CON"},
    },
    "car_rental": {
        "categories": ["سيارات اقتصادية", "سيارات فاخرة", "سيارات SUV", "خدمات"],
        "products": [
            {"name": "إيجار سيارة اقتصادية", "category": "سيارات اقتصادية", "price": 150.0, "unit": "يوم",
             "product_type": "service"},
            {"name": "إيجار سيارة SUV",       "category": "سيارات SUV",     "price": 250.0, "unit": "يوم",
             "product_type": "service"},
            {"name": "إيجار سيارة فاخرة",     "category": "سيارات فاخرة",   "price": 450.0, "unit": "يوم",
             "product_type": "service"},
            {"name": "خدمة السائق",           "category": "خدمات",          "price": 200.0, "unit": "يوم",
             "product_type": "service"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "RNT"},
    },
    "medical": {
        "categories": ["كشوفات طبية", "إجراءات وعمليات", "مستلزمات طبية", "أدوية صرف"],
        "products": [
            {"name": "كشف طبي عام",          "category": "كشوفات طبية",      "price": 150.0, "unit": "زيارة",
             "product_type": "service"},
            {"name": "تحليل دم شامل",        "category": "إجراءات وعمليات", "price": 120.0, "unit": "خدمة",
             "product_type": "service"},
            {"name": "أشعة سينية",           "category": "إجراءات وعمليات", "price": 200.0, "unit": "خدمة",
             "product_type": "service"},
            {"name": "ضغط الدم رقمي",       "category": "مستلزمات طبية",   "price": 180.0, "unit": "جهاز"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "MED"},
    },
    "services": {
        "categories": ["خدمات صيانة", "خدمات تقنية", "استشارات", "خدمات عامة"],
        "products": [
            {"name": "صيانة منزلية عامة",   "category": "خدمات صيانة", "price": 200.0, "unit": "زيارة",
             "product_type": "service"},
            {"name": "إصلاح أجهزة",         "category": "خدمات تقنية", "price": 150.0, "unit": "خدمة",
             "product_type": "service"},
            {"name": "استشارة تقنية",       "category": "استشارات",    "price": 300.0, "unit": "ساعة",
             "product_type": "service"},
            {"name": "خدمة تنظيف",          "category": "خدمات عامة",  "price": 250.0, "unit": "زيارة",
             "product_type": "service"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "SRV"},
    },

    # ══════════════════════════════════════════════════════════════════════════
    # ■ تجزئة — بذور مخصصة إضافية
    # ══════════════════════════════════════════════════════════════════════════

    "retail_fnb_produce": {
        "categories": ["خضروات", "فواكه", "أعشاب وتوابل", "مجمدات خضار"],
        "products": [
            {"name": "طماطم",              "category": "خضروات",        "price": 4.0,  "unit": "كيلو"},
            {"name": "خيار",               "category": "خضروات",        "price": 3.5,  "unit": "كيلو"},
            {"name": "بطاطس",              "category": "خضروات",        "price": 3.0,  "unit": "كيلو"},
            {"name": "موز",                "category": "فواكه",          "price": 6.0,  "unit": "كيلو"},
            {"name": "تفاح أحمر",          "category": "فواكه",          "price": 9.0,  "unit": "كيلو"},
            {"name": "برتقال",             "category": "فواكه",          "price": 5.0,  "unit": "كيلو"},
            {"name": "نعناع طازج",         "category": "أعشاب وتوابل",  "price": 2.0,  "unit": "ربطة"},
            {"name": "ذرة حلوة مجمدة",    "category": "مجمدات خضار",   "price": 8.0,  "unit": "كيس"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "PRD"},
    },
    "retail_fnb_dates": {
        "categories": ["تمور محلية", "تمور مستوردة", "منتجات تمر", "تغليف هدايا"],
        "products": [
            {"name": "تمر سكري ممتاز",    "category": "تمور محلية",    "price": 45.0, "unit": "كيلو"},
            {"name": "تمر خلاص",           "category": "تمور محلية",    "price": 35.0, "unit": "كيلو"},
            {"name": "تمر مجدول أردني",    "category": "تمور مستوردة",  "price": 85.0, "unit": "كيلو"},
            {"name": "دبس تمر",            "category": "منتجات تمر",    "price": 25.0, "unit": "عبوة"},
            {"name": "علبة تمر هدية 1 كيلو","category": "تغليف هدايا", "price": 75.0, "unit": "علبة"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "DAT"},
    },
    "retail_fnb_beverages": {
        "categories": ["مياه معدنية", "عصائر", "مشروبات غازية", "مشروبات طاقة", "مشروبات حارة"],
        "products": [
            {"name": "مياه معدنية 0.5 لتر","category": "مياه معدنية",   "price": 1.5,  "unit": "زجاجة"},
            {"name": "مياه 1.5 لتر",       "category": "مياه معدنية",   "price": 3.0,  "unit": "زجاجة"},
            {"name": "عصير برتقال 1 لتر",  "category": "عصائر",         "price": 12.0, "unit": "عبوة"},
            {"name": "مشروب غازي علبة",    "category": "مشروبات غازية", "price": 3.5,  "unit": "علبة"},
            {"name": "مشروب طاقة 250 مل",  "category": "مشروبات طاقة",  "price": 8.0,  "unit": "علبة"},
            {"name": "شاي أكياس",          "category": "مشروبات حارة",  "price": 9.0,  "unit": "علبة"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "BEV"},
    },
    "retail_fashion_bags": {
        "categories": ["حقائب نسائي", "حقائب رجالي", "حقائب سفر", "محافظ ومحافظ"],
        "products": [
            {"name": "حقيبة يد نسائية",    "category": "حقائب نسائي",  "price": 180.0, "unit": "قطعة"},
            {"name": "حقيبة كروس بودي",    "category": "حقائب نسائي",  "price": 145.0, "unit": "قطعة"},
            {"name": "شنطة ظهر رجالي",    "category": "حقائب رجالي",  "price": 165.0, "unit": "قطعة"},
            {"name": "حقيبة سفر 24 بوصة", "category": "حقائب سفر",    "price": 350.0, "unit": "قطعة"},
            {"name": "محفظة رجالي جلد",   "category": "محافظ ومحافظ", "price": 95.0,  "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "fashion", "invoice_prefix": "BAG"},
    },
    "retail_fashion_fabric": {
        "categories": ["أقمشة قطنية", "أقمشة شيفون", "كتان وكاجوال", "أقمشة فاخرة"],
        "products": [
            {"name": "قماش قطن عرض 150 سم","category": "أقمشة قطنية",  "price": 18.0,  "unit": "متر"},
            {"name": "شيفون كوري",         "category": "أقمشة شيفون",  "price": 25.0,  "unit": "متر"},
            {"name": "قماش كتان طبيعي",   "category": "كتان وكاجوال", "price": 32.0,  "unit": "متر"},
            {"name": "قماش حرير",          "category": "أقمشة فاخرة",  "price": 85.0,  "unit": "متر"},
            {"name": "قماش عباية",         "category": "أقمشة فاخرة",  "price": 45.0,  "unit": "متر"},
        ],
        "settings": {"pos_mode": "fashion", "invoice_prefix": "FAB"},
    },
    "retail_fashion_tailoring": {
        "categories": ["خيوط وأزرار", "أقمشة تبطين", "أدوات خياطة", "إكسسوارات خياطة"],
        "products": [
            {"name": "خيط خياطة 500 م",    "category": "خيوط وأزرار",      "price": 5.0,  "unit": "بكرة"},
            {"name": "أزرار بلاستيك 12 حبة","category": "خيوط وأزرار",     "price": 4.0,  "unit": "علبة"},
            {"name": "قماش تبطين",         "category": "أقمشة تبطين",      "price": 12.0, "unit": "متر"},
            {"name": "مقص خياطة",          "category": "أدوات خياطة",      "price": 55.0, "unit": "قطعة"},
            {"name": "شريط قياس خياطة",   "category": "أدوات خياطة",      "price": 3.0,  "unit": "قطعة"},
            {"name": "سحاب ملابس",         "category": "إكسسوارات خياطة", "price": 2.0,  "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "fashion", "invoice_prefix": "TAI"},
    },
    "retail_fashion_optics": {
        "categories": ["نظارات طبية", "نظارات شمسية", "عدسات لاصقة", "إكسسوارات نظارة"],
        "products": [
            {"name": "نظارة طبية رجالي",   "category": "نظارات طبية",     "price": 350.0, "unit": "قطعة"},
            {"name": "نظارة طبية نسائي",   "category": "نظارات طبية",     "price": 320.0, "unit": "قطعة"},
            {"name": "نظارة شمسية",        "category": "نظارات شمسية",    "price": 180.0, "unit": "قطعة"},
            {"name": "عدسات لاصقة شهرية", "category": "عدسات لاصقة",    "price": 65.0,  "unit": "علبة"},
            {"name": "سائل عدسات",         "category": "إكسسوارات نظارة", "price": 22.0,  "unit": "زجاجة"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "OPT"},
    },
    "retail_construction_flooring": {
        "categories": ["سيراميك", "بورسلان", "رخام", "باركيه", "موزاييك"],
        "products": [
            {"name": "سيراميك أرضي 60×60",  "category": "سيراميك",   "price": 75.0,  "unit": "م²"},
            {"name": "بورسلان مصقول 80×80", "category": "بورسلان",   "price": 120.0, "unit": "م²"},
            {"name": "رخام أبيض",           "category": "رخام",      "price": 280.0, "unit": "م²"},
            {"name": "باركيه خشبي 12 مم",  "category": "باركيه",    "price": 95.0,  "unit": "م²"},
            {"name": "موزاييك حمام",        "category": "موزاييك",   "price": 55.0,  "unit": "م²"},
            {"name": "غراء سيراميك 20 كيلو","category": "سيراميك",  "price": 22.0,  "unit": "كيس"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "FLR"},
    },
    "retail_health_medical": {
        "categories": ["أجهزة طبية", "مستلزمات جرح وضماد", "أدوات قياس", "كراسي ومعدات"],
        "products": [
            {"name": "جهاز قياس ضغط الدم", "category": "أجهزة طبية",       "price": 180.0, "unit": "جهاز"},
            {"name": "جهاز قياس سكر",      "category": "أجهزة طبية",       "price": 120.0, "unit": "جهاز"},
            {"name": "شرائط قياس سكر 50",  "category": "أدوات قياس",       "price": 55.0,  "unit": "علبة"},
            {"name": "ضمادة طبية 10×10",   "category": "مستلزمات جرح وضماد","price": 12.0,  "unit": "علبة"},
            {"name": "قفازات طبية M",       "category": "مستلزمات جرح وضماد","price": 18.0,  "unit": "علبة"},
            {"name": "سماعة طبية",         "category": "أجهزة طبية",       "price": 250.0, "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "pharmacy", "invoice_prefix": "MDL"},
    },
    "retail_auto_accessories": {
        "categories": ["كاميرات وشاشات", "صوتيات", "تزيين خارجي", "تزيين داخلي"],
        "products": [
            {"name": "كاميرا رؤية خلفية",  "category": "كاميرات وشاشات", "price": 180.0, "unit": "قطعة"},
            {"name": "شاشة أندرويد 9 بوصة","category": "كاميرات وشاشات", "price": 650.0, "unit": "قطعة"},
            {"name": "سماعات سيارة 6 بوصة","category": "صوتيات",         "price": 250.0, "unit": "زوج"},
            {"name": "جنط ألمنيوم R18",    "category": "تزيين خارجي",    "price": 1200.0,"unit": "طقم"},
            {"name": "عطر سيارة",          "category": "تزيين داخلي",    "price": 25.0,  "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "ACC"},
    },
    "retail_auto_workshop": {
        "categories": ["معدات رافعة", "أدوات تشخيص", "كمبروسر وهواء", "معدات دهان"],
        "products": [
            {"name": "رافعة هيدروليك 2 طن","category": "معدات رافعة",    "price": 1800.0,"unit": "جهاز"},
            {"name": "جهاز قراءة أعطال",  "category": "أدوات تشخيص",   "price": 950.0, "unit": "جهاز"},
            {"name": "كمبروسر هواء 50 لتر","category": "كمبروسر وهواء", "price": 1200.0,"unit": "جهاز"},
            {"name": "مسدس رش دهان",       "category": "معدات دهان",    "price": 280.0, "unit": "قطعة"},
            {"name": "مرجاحة سيارة",       "category": "معدات رافعة",   "price": 450.0, "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "WRK"},
    },
    "retail_home_carpet": {
        "categories": ["سجاد إيراني", "سجاد تركي", "موكيت", "سجاد ممرات"],
        "products": [
            {"name": "سجادة إيرانية 2×3",  "category": "سجاد إيراني", "price": 850.0,  "unit": "قطعة"},
            {"name": "سجادة تركية 1.5×2.5","category": "سجاد تركي",  "price": 650.0,  "unit": "قطعة"},
            {"name": "موكيت أزرق عرض 4 م",  "category": "موكيت",      "price": 45.0,   "unit": "متر"},
            {"name": "سجادة ممر 1×3",      "category": "سجاد ممرات",  "price": 180.0,  "unit": "قطعة"},
            {"name": "سجادة صلاة",         "category": "سجاد ممرات",  "price": 65.0,   "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "CRP"},
    },
    "retail_home_office": {
        "categories": ["مكاتب وكراسي", "أجهزة مكتبية", "خزائن وأرفف", "ملحقات مكتب"],
        "products": [
            {"name": "مكتب L شكل",         "category": "مكاتب وكراسي",   "price": 1200.0,"unit": "قطعة"},
            {"name": "كرسي مديري",         "category": "مكاتب وكراسي",   "price": 850.0, "unit": "قطعة"},
            {"name": "خزانة ملفات معدن",   "category": "خزائن وأرفف",    "price": 650.0, "unit": "قطعة"},
            {"name": "طابعة ليزر",         "category": "أجهزة مكتبية",   "price": 950.0, "unit": "جهاز"},
            {"name": "لوحة عرض وايت بورد", "category": "ملحقات مكتب",   "price": 280.0, "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "OFF"},
    },
    "retail_electronics_entertainment": {
        "categories": ["ألعاب فيديو", "تلفزيون وشاشات", "سبيكرات", "أجهزة بث"],
        "products": [
            {"name": "PS5 جهاز ألعاب",      "category": "ألعاب فيديو",    "price": 2200.0,"unit": "جهاز"},
            {"name": "لعبة بلايستيشن",      "category": "ألعاب فيديو",    "price": 280.0, "unit": "قطعة"},
            {"name": "تلفزيون OLED 55 بوصة","category": "تلفزيون وشاشات", "price": 4500.0,"unit": "جهاز"},
            {"name": "سبيكر بلوتوث محمول",  "category": "سبيكرات",        "price": 220.0, "unit": "قطعة"},
            {"name": "Apple TV",            "category": "أجهزة بث",       "price": 650.0, "unit": "جهاز"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "ENT"},
    },
    "retail_specialized_camping": {
        "categories": ["خيام ومعدات تخييم", "لوازم صيد", "معدات رحلات", "ملابس خارجية"],
        "products": [
            {"name": "خيمة عائلية 4 أشخاص",  "category": "خيام ومعدات تخييم", "price": 450.0, "unit": "قطعة"},
            {"name": "كيس نوم",               "category": "خيام ومعدات تخييم", "price": 120.0, "unit": "قطعة"},
            {"name": "مصباح LED للتخييم",     "category": "معدات رحلات",       "price": 65.0,  "unit": "قطعة"},
            {"name": "سنارة صيد",             "category": "لوازم صيد",         "price": 85.0,  "unit": "قطعة"},
            {"name": "شنطة ظهر 40 لتر",      "category": "معدات رحلات",       "price": 180.0, "unit": "قطعة"},
            {"name": "جاكيت مقاوم للمطر",    "category": "ملابس خارجية",      "price": 250.0, "unit": "قطعة"},
        ],
        "settings": {"pos_mode": "standard", "invoice_prefix": "CAM"},
    },

    # ══════════════════════════════════════════════════════════════════════════
    # ■ جملة — بذور مخصصة لكل نشاط (وحدات جملة: كرتون، باليت، صندوق، كيس 50 كيلو)
    # ══════════════════════════════════════════════════════════════════════════

    "wholesale_fnb_beverages": {
        "categories": ["مياه معدنية", "عصائر جملة", "مشروبات غازية", "مشروبات طاقة"],
        "products": [
            {"name": "مياه 0.5 لتر — باليت 1200 زجاجة","category": "مياه معدنية",    "price": 1200.0,"unit": "باليت"},
            {"name": "مياه 1.5 لتر — كرتون 12",         "category": "مياه معدنية",    "price": 28.0,  "unit": "كرتون"},
            {"name": "عصير برتقال — كرتون 12",           "category": "عصائر جملة",     "price": 95.0,  "unit": "كرتون"},
            {"name": "مشروب غازي — كرتون 24",           "category": "مشروبات غازية",  "price": 72.0,  "unit": "كرتون"},
            {"name": "مشروب طاقة — كرتون 24",           "category": "مشروبات طاقة",   "price": 150.0, "unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WBV"},
    },
    "wholesale_fnb_roaster": {
        "categories": ["قهوة جملة", "بهارات جملة", "مكسرات جملة", "شاي جملة"],
        "products": [
            {"name": "قهوة عربية — كيس 10 كيلو",   "category": "قهوة جملة",   "price": 1100.0,"unit": "كيس"},
            {"name": "هيل — كيس 5 كيلو",           "category": "بهارات جملة", "price": 450.0, "unit": "كيس"},
            {"name": "لوز خام — كيس 25 كيلو",      "category": "مكسرات جملة", "price": 850.0, "unit": "كيس"},
            {"name": "شاي أسود — كرتون 48 علبة",   "category": "شاي جملة",    "price": 380.0, "unit": "كرتون"},
            {"name": "بهارات مشكلة — كيس 10 كيلو", "category": "بهارات جملة", "price": 320.0, "unit": "كيس"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WRS"},
    },
    "wholesale_fnb_bakery": {
        "categories": ["طحين ومواد خبز", "سكر وملح جملة", "زيوت خبز", "مواد حلويات"],
        "products": [
            {"name": "طحين أبيض — كيس 50 كيلو",      "category": "طحين ومواد خبز", "price": 95.0,  "unit": "كيس"},
            {"name": "سكر أبيض — كيس 50 كيلو",       "category": "سكر وملح جملة",  "price": 110.0, "unit": "كيس"},
            {"name": "زيت نباتي — صندوق 12 لتر",     "category": "زيوت خبز",       "price": 180.0, "unit": "صندوق"},
            {"name": "خميرة جافة — كيلو",             "category": "طحين ومواد خبز", "price": 25.0,  "unit": "كيلو"},
            {"name": "بودرة كاكاو — كيس 25 كيلو",    "category": "مواد حلويات",    "price": 420.0, "unit": "كيس"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WBK"},
    },
    "wholesale_fnb_butcher": {
        "categories": ["لحوم حمراء جملة", "دواجن جملة", "مجمدات لحوم", "أسماك جملة"],
        "products": [
            {"name": "لحم بقري — كرتون 25 كيلو",   "category": "لحوم حمراء جملة", "price": 1250.0,"unit": "كرتون"},
            {"name": "لحم غنم — كيس 20 كيلو",      "category": "لحوم حمراء جملة", "price": 1400.0,"unit": "كيس"},
            {"name": "دجاج كامل مجمد — كرتون 10 كيلو","category": "دواجن جملة",   "price": 230.0, "unit": "كرتون"},
            {"name": "صدر دجاج مجمد — كرتون 10 كيلو","category": "دواجن جملة",   "price": 360.0, "unit": "كرتون"},
            {"name": "سمك فيليه مجمد — كرتون 5 كيلو","category": "أسماك جملة",   "price": 230.0, "unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WBT"},
    },
    "wholesale_fnb_produce": {
        "categories": ["خضار جملة", "فواكه جملة", "محاصيل موسمية"],
        "products": [
            {"name": "طماطم — صندوق 15 كيلو",  "category": "خضار جملة",      "price": 55.0,  "unit": "صندوق"},
            {"name": "بطاطس — كيس 50 كيلو",    "category": "خضار جملة",      "price": 130.0, "unit": "كيس"},
            {"name": "بصل — كيس 25 كيلو",      "category": "خضار جملة",      "price": 60.0,  "unit": "كيس"},
            {"name": "موز — صندوق 18 كيلو",    "category": "فواكه جملة",     "price": 100.0, "unit": "صندوق"},
            {"name": "تفاح — صندوق 18 كيلو",   "category": "فواكه جملة",     "price": 150.0, "unit": "صندوق"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WPR"},
    },
    "wholesale_fnb_dates": {
        "categories": ["تمور جملة", "منتجات تمر جملة", "تعبئة وتغليف"],
        "products": [
            {"name": "تمر سكري ممتاز — كرتون 10 كيلو","category": "تمور جملة",       "price": 400.0, "unit": "كرتون"},
            {"name": "تمر خلاص — كيس 30 كيلو",        "category": "تمور جملة",       "price": 950.0, "unit": "كيس"},
            {"name": "تمر مجدول — كرتون 5 كيلو",      "category": "تمور جملة",       "price": 400.0, "unit": "كرتون"},
            {"name": "دبس تمر — كرتون 12 عبوة",       "category": "منتجات تمر جملة", "price": 280.0, "unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WDT"},
    },

    "wholesale_fashion_clothing": {
        "categories": ["ملابس رجالي جملة", "ملابس نسائي جملة", "ملابس أطفال جملة"],
        "products": [
            {"name": "قمصان رجالي — دستة",    "category": "ملابس رجالي جملة", "price": 480.0, "unit": "دستة"},
            {"name": "بناطيل رجالي — دستة",   "category": "ملابس رجالي جملة", "price": 960.0, "unit": "دستة"},
            {"name": "عبايات نسائي — دستة",   "category": "ملابس نسائي جملة", "price": 1800.0,"unit": "دستة"},
            {"name": "ملابس أطفال مشكلة — ربطة","category": "ملابس أطفال جملة","price": 650.0, "unit": "ربطة"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WCL"},
    },
    "wholesale_fashion_clothing_m": {
        "categories": ["قمصان رجالي", "بناطيل جملة", "أثواب جملة", "رياضي رجالي"],
        "products": [
            {"name": "قمصان قطن رجالي — دستة",  "category": "قمصان رجالي",  "price": 480.0,  "unit": "دستة"},
            {"name": "جينز رجالي — دستة",        "category": "بناطيل جملة",  "price": 960.0,  "unit": "دستة"},
            {"name": "أثواب سعودية — دستة",      "category": "أثواب جملة",   "price": 1680.0, "unit": "دستة"},
            {"name": "تيشيرت رياضي — ربطة 12",  "category": "رياضي رجالي",  "price": 420.0,  "unit": "ربطة"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WCM"},
    },
    "wholesale_fashion_clothing_f": {
        "categories": ["عبايات جملة", "فساتين جملة", "بلايز جملة", "حجاب جملة"],
        "products": [
            {"name": "عبايات سوداء — دستة",     "category": "عبايات جملة", "price": 2400.0, "unit": "دستة"},
            {"name": "فساتين سهرة — دستة",      "category": "فساتين جملة", "price": 3600.0, "unit": "دستة"},
            {"name": "بلايز شيفون — دستة",      "category": "بلايز جملة",  "price": 960.0,  "unit": "دستة"},
            {"name": "حجاب شيفون — ربطة 12",   "category": "حجاب جملة",   "price": 300.0,  "unit": "ربطة"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WCF"},
    },
    "wholesale_fashion_clothing_k": {
        "categories": ["ملابس مواليد", "ملابس أطفال صغار", "زي مدرسي جملة"],
        "products": [
            {"name": "لبس أطفال 0-2 — ربطة 6",  "category": "ملابس مواليد",      "price": 240.0, "unit": "ربطة"},
            {"name": "طقم أطفال 2-6 — دستة",    "category": "ملابس أطفال صغار",  "price": 720.0, "unit": "دستة"},
            {"name": "زي مدرسي — دستة",         "category": "زي مدرسي جملة",    "price": 960.0, "unit": "دستة"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WCK"},
    },
    "wholesale_fashion_fabric": {
        "categories": ["قماش قطني جملة", "شيفون جملة", "أقمشة فاخرة جملة"],
        "products": [
            {"name": "قطن أبيض — رولة 50 متر",   "category": "قماش قطني جملة",   "price": 750.0,  "unit": "رولة"},
            {"name": "شيفون ملون — رولة 50 متر", "category": "شيفون جملة",       "price": 1100.0, "unit": "رولة"},
            {"name": "قماش عباية — رولة 30 متر", "category": "أقمشة فاخرة جملة", "price": 1200.0, "unit": "رولة"},
            {"name": "كتان طبيعي — رولة 50 متر", "category": "قماش قطني جملة",   "price": 1400.0, "unit": "رولة"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WFB"},
    },
    "wholesale_fashion_shoes": {
        "categories": ["أحذية رجالي جملة", "أحذية نسائي جملة", "أحذية أطفال جملة"],
        "products": [
            {"name": "أحذية رجالي رسمي — كرتون 12 زوج","category": "أحذية رجالي جملة", "price": 2400.0,"unit": "كرتون"},
            {"name": "أحذية رياضي — كرتون 12 زوج",     "category": "أحذية رجالي جملة", "price": 1800.0,"unit": "كرتون"},
            {"name": "أحذية نسائي — كرتون 12 زوج",     "category": "أحذية نسائي جملة", "price": 2100.0,"unit": "كرتون"},
            {"name": "أحذية أطفال — كرتون 12 زوج",     "category": "أحذية أطفال جملة", "price": 960.0, "unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WSH"},
    },
    "wholesale_fashion_bags": {
        "categories": ["حقائب نسائي جملة", "حقائب رجالي جملة", "حقائب سفر جملة"],
        "products": [
            {"name": "حقائب نسائي مشكلة — كرتون 12",  "category": "حقائب نسائي جملة", "price": 1800.0,"unit": "كرتون"},
            {"name": "شنط ظهر رجالي — كرتون 12",      "category": "حقائب رجالي جملة", "price": 1680.0,"unit": "كرتون"},
            {"name": "حقائب سفر — كرتون 6",           "category": "حقائب سفر جملة",   "price": 1800.0,"unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WBG"},
    },
    "wholesale_fashion_watches": {
        "categories": ["ساعات رجالي جملة", "ساعات نسائي جملة", "ساعات ذكية جملة"],
        "products": [
            {"name": "ساعات رجالي كلاسيك — كرتون 12", "category": "ساعات رجالي جملة", "price": 4800.0,"unit": "كرتون"},
            {"name": "ساعات ذكية — كرتون 10",          "category": "ساعات ذكية جملة",  "price": 7500.0,"unit": "كرتون"},
            {"name": "ساعات نسائي — كرتون 12",         "category": "ساعات نسائي جملة", "price": 4200.0,"unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WWT"},
    },
    "wholesale_fashion_optics": {
        "categories": ["نظارات طبية جملة", "نظارات شمسية جملة", "عدسات لاصقة جملة"],
        "products": [
            {"name": "إطارات نظارة طبية — كرتون 12", "category": "نظارات طبية جملة",  "price": 2400.0,"unit": "كرتون"},
            {"name": "نظارات شمسية — كرتون 12",      "category": "نظارات شمسية جملة", "price": 1800.0,"unit": "كرتون"},
            {"name": "عدسات لاصقة — كرتون 24 علبة",  "category": "عدسات لاصقة جملة", "price": 1320.0,"unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WOP"},
    },

    "wholesale_construction_materials": {
        "categories": ["إسمنت وجبس جملة", "حديد وصلب جملة", "رمل وبحص جملة", "عزل جملة"],
        "products": [
            {"name": "إسمنت — طن (20 كيس)",  "category": "إسمنت وجبس جملة", "price": 480.0,  "unit": "طن"},
            {"name": "حديد تسليح — طن",       "category": "حديد وصلب جملة",  "price": 2800.0, "unit": "طن"},
            {"name": "رمل بناء — متر مكعب",   "category": "رمل وبحص جملة",  "price": 180.0,  "unit": "متر مكعب"},
            {"name": "بلاط سيراميك — باليت م²","category": "إسمنت وجبس جملة","price": 2500.0, "unit": "باليت"},
            {"name": "لفة عازل مائي",         "category": "عزل جملة",        "price": 110.0,  "unit": "لفة"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WCN"},
    },
    "wholesale_construction_timber": {
        "categories": ["أخشاب بناء", "ألواح خشبية", "أخشاب ديكور"],
        "products": [
            {"name": "خشب لبن 5×10 — متر",     "category": "أخشاب بناء",    "price": 18.0,  "unit": "متر"},
            {"name": "ألواح خشب MDF 18مم",     "category": "ألواح خشبية",   "price": 85.0,  "unit": "لوح"},
            {"name": "خشب ديكور جاهز",         "category": "أخشاب ديكور",   "price": 45.0,  "unit": "متر"},
            {"name": "ألواح نجارة جملة — م٣",  "category": "أخشاب بناء",    "price": 1200.0,"unit": "متر مكعب"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WTM"},
    },
    "wholesale_construction_plumbing": {
        "categories": ["مواسير جملة", "خلاطات جملة", "تجهيزات حمام جملة"],
        "products": [
            {"name": "ماسورة PVC 4 بوصة — حزمة 6 متر","category": "مواسير جملة",         "price": 95.0,  "unit": "حزمة"},
            {"name": "خلاطات باردة وسخنة — كرتون 6",  "category": "خلاطات جملة",         "price": 480.0, "unit": "كرتون"},
            {"name": "مراحيض فرنجي — كرتون 3",        "category": "تجهيزات حمام جملة",   "price": 950.0, "unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WPL"},
    },
    "wholesale_construction_electrical": {
        "categories": ["كابلات جملة", "لوحات توزيع", "إضاءة جملة", "قواطع جملة"],
        "products": [
            {"name": "سلك 2.5 مم — بكرة 100 متر",   "category": "كابلات جملة",    "price": 220.0, "unit": "بكرة"},
            {"name": "لوحة توزيع 12 قاطع",           "category": "لوحات توزيع",    "price": 180.0, "unit": "قطعة"},
            {"name": "لمبة LED 12W — كرتون 50",       "category": "إضاءة جملة",    "price": 480.0, "unit": "كرتون"},
            {"name": "قواطع 16 أمبير — كرتون 20",    "category": "قواطع جملة",    "price": 380.0, "unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WEL"},
    },
    "wholesale_construction_paints": {
        "categories": ["دهان داخلي جملة", "دهان خارجي جملة", "ملحقات دهان جملة"],
        "products": [
            {"name": "دهان داخلي أبيض — 18 لتر",      "category": "دهان داخلي جملة",  "price": 220.0, "unit": "سطل"},
            {"name": "دهان خارجي مقاوم — 18 لتر",     "category": "دهان خارجي جملة",  "price": 320.0, "unit": "سطل"},
            {"name": "فرشاة دهان — كرتون 50",         "category": "ملحقات دهان جملة", "price": 300.0, "unit": "كرتون"},
            {"name": "رول دهان — كرتون 50",           "category": "ملحقات دهان جملة", "price": 450.0, "unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WPN"},
    },
    "wholesale_construction_flooring": {
        "categories": ["سيراميك جملة", "بورسلان جملة", "رخام جملة", "باركيه جملة"],
        "products": [
            {"name": "سيراميك 60×60 — باليت 50م²",  "category": "سيراميك جملة", "price": 3200.0,"unit": "باليت"},
            {"name": "بورسلان 80×80 — باليت 40م²",  "category": "بورسلان جملة", "price": 4400.0,"unit": "باليت"},
            {"name": "رخام أبيض — م²",               "category": "رخام جملة",    "price": 250.0, "unit": "م²"},
            {"name": "باركيه 12مم — كرتون 2م²",      "category": "باركيه جملة",  "price": 180.0, "unit": "كرتون"},
            {"name": "غراء سيراميك — كيس 25 كيلو",  "category": "سيراميك جملة", "price": 28.0,  "unit": "كيس"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WFL"},
    },

    "wholesale_electronics_mobile": {
        "categories": ["جوالات جملة", "إكسسوارات جوال جملة", "سماعات جملة"],
        "products": [
            {"name": "جوالات سامسونج — كرتون 10",     "category": "جوالات جملة",            "price": 16000.0,"unit": "كرتون"},
            {"name": "كفرات حماية — كرتون 50",        "category": "إكسسوارات جوال جملة",    "price": 1250.0, "unit": "كرتون"},
            {"name": "شواحن سريعة — كرتون 30",        "category": "إكسسوارات جوال جملة",    "price": 1350.0, "unit": "كرتون"},
            {"name": "سماعات لاسلكية — كرتون 12",     "category": "سماعات جملة",            "price": 2400.0, "unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WMB"},
    },
    "wholesale_electronics_computers": {
        "categories": ["لابتوب جملة", "قطع كمبيوتر جملة", "شبكات جملة"],
        "products": [
            {"name": "لابتوب HP Core i5 — كرتون 5",  "category": "لابتوب جملة",       "price": 14000.0,"unit": "كرتون"},
            {"name": "ذاكرة RAM 8GB — كرتون 20",     "category": "قطع كمبيوتر جملة", "price": 4000.0, "unit": "كرتون"},
            {"name": "هارد SSD 256GB — كرتون 20",    "category": "قطع كمبيوتر جملة", "price": 4200.0, "unit": "كرتون"},
            {"name": "سويتش شبكة 24 بورت — صندوق 5","category": "شبكات جملة",        "price": 5500.0, "unit": "صندوق"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WCP"},
    },
    "wholesale_electronics_appliances": {
        "categories": ["غسالات جملة", "مكيفات جملة", "تلفزيونات جملة", "ثلاجات جملة"],
        "products": [
            {"name": "غسالة أوتوماتيك — وحدة",  "category": "غسالات جملة",     "price": 1600.0,"unit": "جهاز"},
            {"name": "مكيف سبليت 18000 — وحدة",  "category": "مكيفات جملة",     "price": 3200.0,"unit": "جهاز"},
            {"name": "تلفزيون 55 بوصة — وحدة",   "category": "تلفزيونات جملة",  "price": 2500.0,"unit": "جهاز"},
            {"name": "ثلاجة دبل دور — وحدة",     "category": "ثلاجات جملة",     "price": 2000.0,"unit": "جهاز"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WAP"},
    },
    "wholesale_electronics_entertainment": {
        "categories": ["أجهزة ألعاب جملة", "سبيكرات جملة", "أجهزة بث جملة"],
        "products": [
            {"name": "PS5 جملة — صندوق 3",         "category": "أجهزة ألعاب جملة", "price": 6000.0,"unit": "صندوق"},
            {"name": "سبيكر بلوتوث — كرتون 12",    "category": "سبيكرات جملة",     "price": 2160.0,"unit": "كرتون"},
            {"name": "Apple TV — كرتون 6",          "category": "أجهزة بث جملة",   "price": 3600.0,"unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WET"},
    },

    "wholesale_health_medical": {
        "categories": ["أجهزة طبية جملة", "مستلزمات مستشفيات", "تجهيزات عيادات"],
        "products": [
            {"name": "قفازات طبية — كرتون 10 علب", "category": "مستلزمات مستشفيات", "price": 180.0, "unit": "كرتون"},
            {"name": "ضمادات طبية — كرتون 50 علبة","category": "مستلزمات مستشفيات", "price": 550.0, "unit": "كرتون"},
            {"name": "أجهزة ضغط الدم — صندوق 10",  "category": "أجهزة طبية جملة",  "price": 1800.0,"unit": "صندوق"},
            {"name": "سماعات طبية — صندوق 10",      "category": "تجهيزات عيادات",   "price": 2000.0,"unit": "صندوق"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WHM"},
    },
    "wholesale_health_pharmacy": {
        "categories": ["أدوية جملة", "فيتامينات جملة", "مستلزمات صيدليات"],
        "products": [
            {"name": "بانادول — كرتون 50 علبة",    "category": "أدوية جملة",      "price": 550.0, "unit": "كرتون"},
            {"name": "فيتامين C — كرتون 24 علبة",  "category": "فيتامينات جملة",  "price": 720.0, "unit": "كرتون"},
            {"name": "شرائط قياس سكر — كرتون 20",  "category": "مستلزمات صيدليات","price": 900.0, "unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WPH"},
    },
    "wholesale_health_perfume": {
        "categories": ["عطور رجالي جملة", "عطور نسائي جملة", "بخور وعود جملة"],
        "products": [
            {"name": "عطر رجالي — كرتون 12 زجاجة",  "category": "عطور رجالي جملة",  "price": 2400.0,"unit": "كرتون"},
            {"name": "عطر نسائي — كرتون 12 زجاجة",  "category": "عطور نسائي جملة",  "price": 2160.0,"unit": "كرتون"},
            {"name": "عود كمبودي — كيلو",            "category": "بخور وعود جملة",   "price": 3500.0,"unit": "كيلو"},
            {"name": "مبخرات — كرتون 12",            "category": "بخور وعود جملة",   "price": 840.0, "unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WPF"},
    },
    "wholesale_health_cosmetics": {
        "categories": ["كريمات جملة", "مكياج جملة", "شامبو وعناية جملة"],
        "products": [
            {"name": "كريم ترطيب — كرتون 24 عبوة",  "category": "كريمات جملة",        "price": 1320.0,"unit": "كرتون"},
            {"name": "أحمر شفاه — كرتون 24",         "category": "مكياج جملة",         "price": 720.0, "unit": "كرتون"},
            {"name": "شامبو مرطب — كرتون 12 زجاجة", "category": "شامبو وعناية جملة", "price": 360.0, "unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WCS"},
    },
    "wholesale_health_supplements": {
        "categories": ["بروتين جملة", "فيتامينات جملة", "حارقات دهون جملة"],
        "products": [
            {"name": "بروتين واي — كرتون 12 علبة",   "category": "بروتين جملة",         "price": 1800.0,"unit": "كرتون"},
            {"name": "فيتامين D3 — كرتون 24 علبة",   "category": "فيتامينات جملة",      "price": 900.0, "unit": "كرتون"},
            {"name": "أوميغا 3 — كرتون 24 علبة",     "category": "فيتامينات جملة",      "price": 1100.0,"unit": "كرتون"},
            {"name": "حارق دهون — كرتون 12 علبة",    "category": "حارقات دهون جملة",   "price": 1200.0,"unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WSP"},
    },

    "wholesale_home_furniture": {
        "categories": ["غرف نوم جملة", "أثاث معيشة جملة", "مكاتب وكراسي جملة"],
        "products": [
            {"name": "طقم غرفة نوم كاملة",  "category": "غرف نوم جملة",      "price": 4200.0,"unit": "طقم"},
            {"name": "كنبة 3 مقاعد",        "category": "أثاث معيشة جملة",   "price": 2000.0,"unit": "قطعة"},
            {"name": "مكتب + كرسي مديري",   "category": "مكاتب وكراسي جملة", "price": 1800.0,"unit": "طقم"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WHF"},
    },
    "wholesale_home_carpet": {
        "categories": ["سجاد إيراني جملة", "موكيت جملة", "سجاد ممرات جملة"],
        "products": [
            {"name": "سجادة إيرانية 2×3 — لفة",   "category": "سجاد إيراني جملة", "price": 7500.0,"unit": "لفة"},
            {"name": "موكيت عرض 4م — لفة 100م",   "category": "موكيت جملة",       "price": 3600.0,"unit": "لفة"},
            {"name": "سجادة صلاة — كرتون 12",      "category": "سجاد ممرات جملة", "price": 660.0, "unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WHC"},
    },
    "wholesale_home_kitchenware": {
        "categories": ["أواني طبخ جملة", "أجهزة مطبخ جملة", "أدوات مائدة جملة"],
        "products": [
            {"name": "طقم أواني طبخ — كرتون 6 طقم",  "category": "أواني طبخ جملة",   "price": 1200.0,"unit": "كرتون"},
            {"name": "خلاط كهربائي — كرتون 6",        "category": "أجهزة مطبخ جملة", "price": 900.0, "unit": "كرتون"},
            {"name": "طقم أكواب — كرتون 12 طقم",      "category": "أدوات مائدة جملة", "price": 900.0, "unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WHK"},
    },
    "wholesale_home_stationery": {
        "categories": ["قرطاسية مكاتب جملة", "ورق طباعة جملة", "أقلام جملة"],
        "products": [
            {"name": "ورق A4 — كرتون 5 رزم",         "category": "ورق طباعة جملة",    "price": 100.0, "unit": "كرتون"},
            {"name": "أقلام جاف — كرتون 200",         "category": "أقلام جملة",         "price": 180.0, "unit": "كرتون"},
            {"name": "دفاتر A4 — كرتون 50",           "category": "قرطاسية مكاتب جملة","price": 350.0, "unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WHS"},
    },
    "wholesale_home_office": {
        "categories": ["مكاتب جملة", "كراسي مكتبية جملة", "خزائن جملة"],
        "products": [
            {"name": "مكتب مدير — وحدة",        "category": "مكاتب جملة",          "price": 2500.0,"unit": "قطعة"},
            {"name": "كرسي مكتبي — وحدة",       "category": "كراسي مكتبية جملة",  "price": 850.0, "unit": "قطعة"},
            {"name": "خزانة ملفات 4 أدراج",     "category": "خزائن جملة",          "price": 1200.0,"unit": "قطعة"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WHO"},
    },

    "wholesale_auto_tires": {
        "categories": ["إطارات جملة", "بطاريات جملة", "جنوط جملة"],
        "products": [
            {"name": "إطار 205/55R16 — كرتون 4",  "category": "إطارات جملة",  "price": 1000.0,"unit": "كرتون"},
            {"name": "إطار 225/65R17 — كرتون 4",  "category": "إطارات جملة",  "price": 1280.0,"unit": "كرتون"},
            {"name": "بطارية 70 أمبير — كرتون 4", "category": "بطاريات جملة", "price": 1300.0,"unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WTR"},
    },
    "wholesale_auto_accessories": {
        "categories": ["شاشات وكاميرات جملة", "إكسسوارات خارجية جملة", "صوتيات جملة"],
        "products": [
            {"name": "شاشة أندرويد 9 بوصة — صندوق 5","category": "شاشات وكاميرات جملة",  "price": 2750.0,"unit": "صندوق"},
            {"name": "كاميرا رؤية خلفية — كرتون 10",  "category": "شاشات وكاميرات جملة",  "price": 1500.0,"unit": "كرتون"},
            {"name": "سبيكر سيارة — كرتون 10 زوج",    "category": "صوتيات جملة",           "price": 2000.0,"unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WAC"},
    },
    "wholesale_auto_workshop": {
        "categories": ["رافعات جملة", "معدات تشخيص جملة", "كمبروسرات جملة"],
        "products": [
            {"name": "رافعة هيدروليك 2 طن — وحدة",  "category": "رافعات جملة",        "price": 1600.0,"unit": "قطعة"},
            {"name": "جهاز قراءة أعطال — صندوق 3",  "category": "معدات تشخيص جملة", "price": 2400.0,"unit": "صندوق"},
            {"name": "كمبروسر 50 لتر — وحدة",        "category": "كمبروسرات جملة",    "price": 1100.0,"unit": "قطعة"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WWK"},
    },

    "wholesale_specialized_tobacco": {
        "categories": ["معسل جملة", "أدوات نارجيلة جملة", "فحم جملة"],
        "products": [
            {"name": "معسل تفاح 50 جم — كرتون 50",   "category": "معسل جملة",               "price": 800.0, "unit": "كرتون"},
            {"name": "معسل مشكل — كرتون 50",          "category": "معسل جملة",               "price": 900.0, "unit": "كرتون"},
            {"name": "فحم طبيعي — كرتون 50 علبة",    "category": "فحم جملة",                "price": 500.0, "unit": "كرتون"},
            {"name": "رأس نارجيلة — كرتون 12",        "category": "أدوات نارجيلة جملة",     "price": 360.0, "unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WTB"},
    },
    "wholesale_specialized_flowers": {
        "categories": ["ورود جملة", "زهور صناعية جملة", "لوازم تغليف"],
        "products": [
            {"name": "ورود طبيعية — صندوق 100 زهرة", "category": "ورود جملة",        "price": 850.0, "unit": "صندوق"},
            {"name": "ورد صناعي — كرتون 12 باقة",    "category": "زهور صناعية جملة", "price": 1200.0,"unit": "كرتون"},
            {"name": "شريط تغليف — بكرة",             "category": "لوازم تغليف",      "price": 8.0,   "unit": "بكرة"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WFL"},
    },
    "wholesale_specialized_toys": {
        "categories": ["ألعاب أطفال جملة", "ألعاب تعليمية جملة", "هدايا جملة"],
        "products": [
            {"name": "سيارات لعبة — كرتون 24",        "category": "ألعاب أطفال جملة",   "price": 720.0, "unit": "كرتون"},
            {"name": "دمى أطفال — كرتون 12",           "category": "ألعاب أطفال جملة",   "price": 660.0, "unit": "كرتون"},
            {"name": "ليجو تعليمي — كرتون 12 علبة",   "category": "ألعاب تعليمية جملة", "price": 960.0, "unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WTY"},
    },
    "wholesale_specialized_pets": {
        "categories": ["طعام حيوانات جملة", "لوازم عناية جملة", "إكسسوارات جملة"],
        "products": [
            {"name": "طعام قطط 1 كيلو — كرتون 12",  "category": "طعام حيوانات جملة", "price": 360.0, "unit": "كرتون"},
            {"name": "طعام كلاب 3 كيلو — كرتون 6",  "category": "طعام حيوانات جملة", "price": 330.0, "unit": "كرتون"},
            {"name": "شامبو حيوانات — كرتون 12",     "category": "لوازم عناية جملة",  "price": 300.0, "unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WPT"},
    },
    "wholesale_specialized_sports": {
        "categories": ["معدات رياضية جملة", "ملابس رياضية جملة", "كرات جملة"],
        "products": [
            {"name": "تيشيرت رياضي — دستة",          "category": "ملابس رياضية جملة", "price": 660.0, "unit": "دستة"},
            {"name": "كرة قدم — كرتون 12",            "category": "كرات جملة",         "price": 900.0, "unit": "كرتون"},
            {"name": "حبل قفز — كرتون 50",            "category": "معدات رياضية جملة", "price": 1000.0,"unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WSR"},
    },
    "wholesale_specialized_camping": {
        "categories": ["خيام جملة", "لوازم صيد جملة", "معدات رحلات جملة"],
        "products": [
            {"name": "خيمة عائلية 4 أشخاص — صندوق 5","category": "خيام جملة",           "price": 2000.0,"unit": "صندوق"},
            {"name": "كيس نوم — كرتون 10",            "category": "معدات رحلات جملة",  "price": 1100.0,"unit": "كرتون"},
            {"name": "سنارة صيد — كرتون 24",          "category": "لوازم صيد جملة",    "price": 1800.0,"unit": "كرتون"},
            {"name": "مصباح LED تخييم — كرتون 12",    "category": "معدات رحلات جملة",  "price": 660.0, "unit": "كرتون"},
        ],
        "settings": {"pos_mode": "wholesale", "invoice_prefix": "WCP"},
    },
}

# ─── بذور افتراضية للأنشطة غير المعرّفة ──────────────────────────────────────
_DEFAULT_SEEDS: dict = {
    "categories": ["منتجات", "خدمات", "أخرى"],
    "products": [
        {"name": "منتج نموذجي",  "category": "منتجات", "price": 50.0,  "unit": "قطعة"},
        {"name": "خدمة نموذجية", "category": "خدمات",  "price": 100.0, "unit": "خدمة",
         "product_type": "service"},
    ],
    "settings": {"pos_mode": "standard", "invoice_prefix": "INV"},
}

# مجموعات مشتركة (كل أنشطة الجملة من نفس نشاط يرث نفس البذور)
_GROUP_MAP: dict[str, str] = {}
for _src, _dst in [
    ("wholesale_fnb_beverages", "wholesale_fnb_distribution"),
    ("wholesale_fnb_roaster",   "wholesale_fnb_distribution"),
    ("wholesale_fnb_bakery",    "wholesale_fnb_distribution"),
    ("wholesale_fnb_butcher",   "wholesale_fnb_distribution"),
    ("wholesale_fnb_produce",   "wholesale_fnb_distribution"),
    ("wholesale_fnb_dates",     "wholesale_fnb_distribution"),
    ("wholesale_fashion_clothing","wholesale_fnb_general"),
    ("wholesale_fashion_fabric",  "wholesale_fnb_general"),
    ("wholesale_fashion_shoes",   "wholesale_fnb_general"),
    ("wholesale_fashion_bags",    "wholesale_fnb_general"),
    ("wholesale_fashion_clothing_m", "wholesale_fnb_general"),
    ("wholesale_fashion_clothing_f", "wholesale_fnb_general"),
    ("wholesale_fashion_clothing_k", "wholesale_fnb_general"),
    ("wholesale_fashion_watches",    "wholesale_fnb_general"),
    ("wholesale_fashion_optics",     "wholesale_fnb_general"),
    ("wholesale_construction_materials", "wholesale_fnb_general"),
    ("wholesale_construction_timber",    "wholesale_fnb_general"),
    ("wholesale_construction_plumbing",  "wholesale_fnb_general"),
    ("wholesale_construction_electrical","wholesale_fnb_general"),
    ("wholesale_construction_paints",    "wholesale_fnb_general"),
    ("wholesale_construction_flooring",  "wholesale_fnb_general"),
    ("wholesale_electronics_mobile",      "wholesale_electronics_general"),
    ("wholesale_electronics_computers",   "wholesale_electronics_general"),
    ("wholesale_electronics_appliances",  "wholesale_electronics_general"),
    ("wholesale_electronics_entertainment","wholesale_electronics_general"),
    ("wholesale_health_medical",         "wholesale_fnb_general"),
    ("wholesale_health_pharmacy",        "wholesale_fnb_general"),
    ("wholesale_health_perfume",         "wholesale_fnb_general"),
    ("wholesale_health_cosmetics",       "wholesale_fnb_general"),
    ("wholesale_health_supplements",     "wholesale_fnb_general"),
    ("wholesale_home_furniture",         "wholesale_fnb_general"),
    ("wholesale_home_carpet",            "wholesale_fnb_general"),
    ("wholesale_home_kitchenware",       "wholesale_fnb_general"),
    ("wholesale_home_stationery",        "wholesale_fnb_general"),
    ("wholesale_home_office",            "wholesale_fnb_general"),
    ("wholesale_auto_tires",             "wholesale_auto_parts"),
    ("wholesale_auto_accessories",       "wholesale_auto_parts"),
    ("wholesale_auto_workshop",          "wholesale_auto_parts"),
    ("wholesale_specialized_tobacco",    "wholesale_fnb_general"),
    ("wholesale_specialized_flowers",    "wholesale_fnb_general"),
    ("wholesale_specialized_toys",       "wholesale_fnb_general"),
    ("wholesale_specialized_pets",       "wholesale_fnb_general"),
    ("wholesale_specialized_sports",     "wholesale_fnb_general"),
    ("wholesale_specialized_camping",    "wholesale_fnb_general"),
    # legacy keys
    ("retail",      "retail_fnb_grocery"),
    ("wholesale",   "wholesale_fnb_general"),
    ("restaurant",  "food_restaurant"),
    ("cafe",        "food_cafe"),
    ("coffeeshop",  "food_coffeeshop"),
    # missing retail
    ("retail_fnb_produce",  "retail_fnb_grocery"),
    ("retail_fnb_dates",    "retail_fnb_roaster"),
    ("retail_fnb_beverages","retail_fnb_grocery"),
    ("retail_fashion_bags", "retail_fashion_shoes"),
    ("retail_fashion_optics","retail_fashion_watches"),
    ("retail_fashion_fabric","retail_home_stationery"),
    ("retail_fashion_tailoring","retail_home_stationery"),
    ("retail_construction_flooring","retail_construction_materials"),
    ("retail_auto_accessories","retail_auto_parts"),
    ("retail_auto_workshop","retail_auto_parts"),
    ("retail_home_carpet","retail_home_furniture"),
    ("retail_home_office","retail_home_stationery"),
    ("retail_specialized_camping","retail_specialized_sports"),
    ("retail_electronics_entertainment","retail_electronics_computers"),
    ("retail_health_medical","retail_health_pharmacy"),
    ("medical_complex", "medical"),
]:
    _GROUP_MAP[_src] = _dst

for _src, _dst in list(_GROUP_MAP.items()):
    if _dst not in _SEEDS:
        _GROUP_MAP[_src] = "default"


def _get_seed(industry_type: str) -> dict:
    """إرجاع بذور النشاط أو أقرب بديل متاح"""
    if industry_type in _SEEDS:
        return _SEEDS[industry_type]
    if industry_type in _GROUP_MAP:
        mapped = _GROUP_MAP[industry_type]
        if mapped in _SEEDS:
            return _SEEDS[mapped]
    # fallback prefix-based
    if industry_type.startswith("food_"):
        return _SEEDS["food_restaurant"]
    if industry_type.startswith("wholesale_"):
        return _SEEDS["wholesale_fnb_general"]
    if industry_type.startswith("retail_fnb"):
        return _SEEDS["retail_fnb_grocery"]
    if industry_type.startswith("retail_fashion"):
        return _SEEDS["retail_fashion_clothing_m"]
    if industry_type.startswith("retail_construction"):
        return _SEEDS["retail_construction_materials"]
    if industry_type.startswith("retail_electronics"):
        return _SEEDS["retail_electronics_mobile"]
    if industry_type.startswith("retail_auto"):
        return _SEEDS["retail_auto_parts"]
    if industry_type.startswith("retail_home"):
        return _SEEDS["retail_home_furniture"]
    if industry_type.startswith("retail_health"):
        return _SEEDS["retail_health_pharmacy"]
    if industry_type.startswith("retail_specialized"):
        return _SEEDS["retail_specialized_sports"]
    return _DEFAULT_SEEDS


# ═══════════════════════════════════════════════════════════════════════════════
# 2. دالة التهيئة الرئيسية
# ═══════════════════════════════════════════════════════════════════════════════

def seed_industry_defaults(
    db: sqlite3.Connection,
    biz_id: int,
    industry_type: str,
) -> None:
    """
    تُهيّئ البيانات الأولية للمنشأة حسب نوع نشاطها:
      - تصنيفات المنتجات
      - منتجات/خدمات نموذجية
      - إعدادات النشاط (POS mode، بادئة الفاتورة)

    يُستدعى مرة واحدة فقط عند اكتمال onboarding.
    """
    try:
        seed = _get_seed(industry_type)
        _seed_categories_and_products(db, biz_id, seed)
        _seed_settings(db, biz_id, seed.get("settings", {}))
        _seed_trade_mode_settings(db, biz_id, industry_type)
    except Exception as exc:
        logger.warning("industry_seeds: فشل التهيئة للنشاط %s — %s", industry_type, exc)
        # لا نوقف العملية — النظام يعمل بدون بذور أفضل من توقفه


def _seed_trade_mode_settings(
    db: sqlite3.Connection,
    biz_id: int,
    industry_type: str,
) -> None:
    """إعدادات تشغيلية تمنع تداخل نمط الجملة والتجزئة."""
    if industry_type.startswith("wholesale_") or industry_type == "wholesale":
        mode_settings = {
            "trade_mode": "wholesale",
            "quantity_decimals": "3",
            "allow_fractional_qty": "1",
            "enable_bulk_pricing": "1",
            "prefer_weight_units": "1",
            "show_retail_pos": "0",
        }
    elif industry_type.startswith("retail_") or industry_type == "retail":
        mode_settings = {
            "trade_mode": "retail",
            "quantity_decimals": "0",
            "allow_fractional_qty": "0",
            "enable_bulk_pricing": "0",
            "prefer_weight_units": "0",
            "show_retail_pos": "1",
        }
    else:
        mode_settings = {
            "trade_mode": "specialized",
            "quantity_decimals": "2",
            "allow_fractional_qty": "1",
            "enable_bulk_pricing": "0",
            "prefer_weight_units": "0",
            "show_retail_pos": "0",
        }

    _seed_settings(db, biz_id, mode_settings)


def _seed_categories_and_products(
    db: sqlite3.Connection,
    biz_id: int,
    seed: dict,
) -> None:
    """يُنشئ التصنيفات والمنتجات النموذجية إذا لم تكن موجودة"""
    categories = seed.get("categories", [])
    products   = seed.get("products",   [])

    # ── التصنيفات ──────────────────────────────────────────────────────────
    cat_id_map: dict[str, int] = {}  # name → id

    for cat_name in categories:
        existing = db.execute(
            "SELECT id FROM product_categories WHERE business_id=? AND name=?",
            (biz_id, cat_name)
        ).fetchone()
        if existing:
            cat_id_map[cat_name] = existing["id"]
        else:
            cur = db.execute(
                "INSERT INTO product_categories (business_id, name) VALUES (?,?)",
                (biz_id, cat_name)
            )
            cat_id_map[cat_name] = cur.lastrowid

    # ── المنتجات ──────────────────────────────────────────────────────────
    for p in products:
        name         = p.get("name", "")
        category     = p.get("category", "")
        price        = float(p.get("price", 0))
        unit         = p.get("unit", "قطعة")
        product_type = p.get("product_type", "product")
        is_pos       = int(p.get("is_pos", 1))
        cat_id       = cat_id_map.get(category)

        if not name:
            continue

        # لا تُضف منتجاً موجوداً بنفس الاسم
        exists = db.execute(
            "SELECT id FROM products WHERE business_id=? AND name=?",
            (biz_id, name)
        ).fetchone()
        if exists:
            continue

        db.execute(
            """INSERT INTO products
               (business_id, name, product_type, category_id, category_name,
                sale_price, purchase_price, track_stock, is_pos, is_active)
               VALUES (?,?,?,?,?,?,?,?,?,1)""",
            (
                biz_id, name, product_type,
                cat_id, category,
                price, round(price * 0.7, 2),   # تكلفة تقريبية = 70% من السعر
                1 if product_type == "product" else 0,   # الخدمات لا تتبع مخزون
                is_pos,
            )
        )

        # إذا كان منتجاً (وليس خدمة)، أضف رصيد صفري في المستودع الافتراضي
        if product_type == "product":
            warehouse = db.execute(
                "SELECT id FROM warehouses WHERE business_id=? AND is_default=1 LIMIT 1",
                (biz_id,)
            ).fetchone()
            if warehouse:
                product_id = db.execute(
                    "SELECT id FROM products WHERE business_id=? AND name=? LIMIT 1",
                    (biz_id, name)
                ).fetchone()
                if product_id:
                    db.execute(
                        """INSERT OR IGNORE INTO stock
                           (business_id, product_id, warehouse_id, quantity, avg_cost)
                           VALUES (?,?,?,0,0)""",
                        (biz_id, product_id["id"], warehouse["id"])
                    )


def _seed_settings(
    db: sqlite3.Connection,
    biz_id: int,
    settings: dict,
) -> None:
    """يُدرج إعدادات النشاط في جدول settings"""
    for key, value in settings.items():
        db.execute(
            "INSERT OR IGNORE INTO settings (business_id, key, value) VALUES (?,?,?)",
            (biz_id, key, str(value))
        )
