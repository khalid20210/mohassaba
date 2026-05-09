"""
modules/config.py — ثوابت وإعدادات النظام
"""
import json
import os
import secrets
from datetime import timedelta
from pathlib import Path

# ── تحميل .env تلقائياً إذا توفر python-dotenv ──────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env", override=False)
except ImportError:
    pass  # python-dotenv اختياري — يعمل بدونه أيضاً

BASE_DIR    = Path(__file__).parent.parent
FLASK_ENV   = os.environ.get("FLASK_ENV", "development").lower()
IS_PROD     = FLASK_ENV == "production"

# ─── SaaS Platform Settings (Saudi-first, Gulf-ready) ───────────────────────
PLATFORM_NAME = os.environ.get("PLATFORM_NAME", "Jinan Biz")
SAAS_REGION   = os.environ.get("SAAS_REGION", "sa")
RATE_LIMIT_WINDOW_SEC  = int(os.environ.get("RATE_LIMIT_WINDOW_SEC", "60"))
RATE_LIMIT_MAX_REQUEST = int(os.environ.get("RATE_LIMIT_MAX_REQUEST", "240"))
HEALTH_DB_TIMEOUT_MS   = int(os.environ.get("HEALTH_DB_TIMEOUT_MS", "1500"))
MAX_INFLIGHT_REQUESTS  = int(os.environ.get("MAX_INFLIGHT_REQUESTS", "300"))
OVERLOAD_RETRY_AFTER_SEC = int(os.environ.get("OVERLOAD_RETRY_AFTER_SEC", "2"))

# ─── Runtime Services (Redis / Session / Queue) ─────────────────────────────
REDIS_URL = os.environ.get("REDIS_URL", "")
SESSION_BACKEND = os.environ.get("SESSION_BACKEND", "filesystem").lower()
SESSION_REDIS_PREFIX = os.environ.get("SESSION_REDIS_PREFIX", "jenan:sess:")
SESSION_FILE_DIR = os.environ.get("SESSION_FILE_DIR", str(BASE_DIR / "instance" / "sessions"))
USE_REDIS_RATE_LIMIT = os.environ.get("USE_REDIS_RATE_LIMIT", "false").lower() in ("1", "true", "yes")
RATE_LIMIT_PREFIX = os.environ.get("RATE_LIMIT_PREFIX", "jenan:rl")
QUEUE_BACKEND = os.environ.get("QUEUE_BACKEND", "sqlite").lower()
RQ_DEFAULT_QUEUE = os.environ.get("RQ_DEFAULT_QUEUE", "default")
QUEUE_REQUIRED = os.environ.get("QUEUE_REQUIRED", "false").lower() in ("1", "true", "yes")
REDIS_REQUIRED = os.environ.get("REDIS_REQUIRED", "false").lower() in ("1", "true", "yes")
FAIL_FAST_ON_STARTUP = os.environ.get("FAIL_FAST_ON_STARTUP", "false").lower() in ("1", "true", "yes")

# ─── تحسينات SQLite للتزامن (مفيدة قبل الانتقال لـ PostgreSQL) ───────────────
SQLITE_BUSY_TIMEOUT_MS     = int(os.environ.get("SQLITE_BUSY_TIMEOUT_MS", "30000"))
SQLITE_JOURNAL_MODE        = os.environ.get("SQLITE_JOURNAL_MODE", "WAL")
SQLITE_SYNCHRONOUS         = os.environ.get("SQLITE_SYNCHRONOUS", "NORMAL")
SQLITE_CACHE_SIZE          = int(os.environ.get("SQLITE_CACHE_SIZE", "-65536"))   # 64 MB
SQLITE_MMAP_SIZE           = int(os.environ.get("SQLITE_MMAP_SIZE", "268435456"))   # 256 MB
SQLITE_WAL_AUTOCHECKPOINT  = int(os.environ.get("SQLITE_WAL_AUTOCHECKPOINT", "10000"))
SQLITE_LOCK_RETRY_COUNT    = int(os.environ.get("SQLITE_LOCK_RETRY_COUNT", "3"))
SQLITE_LOCK_RETRY_DELAY_MS = int(os.environ.get("SQLITE_LOCK_RETRY_DELAY_MS", "30"))

# ─── خيارات Checkout lock (للضغط العالي على نقطة البيع) ───────────────
CHECKOUT_LOCK_TIMEOUT_MS = int(os.environ.get("CHECKOUT_LOCK_TIMEOUT_MS", "30000"))
CHECKOUT_LOCK_TTL_MS     = int(os.environ.get("CHECKOUT_LOCK_TTL_MS", "30000"))
CHECKOUT_MAX_RETRIES     = int(os.environ.get("CHECKOUT_MAX_RETRIES", "10"))

# ─── قاعدة البيانات: منفصلة حسب البيئة ────────────────────────────────────────
_db_from_env = os.environ.get("DB_PATH")
if _db_from_env:
    DB_PATH = Path(_db_from_env)
elif IS_PROD:
    DB_PATH = BASE_DIR / "database" / "accounting_prod.db"
else:
    DB_PATH = BASE_DIR / "database" / "accounting_dev.db"

# إذا لم يكن ملف Dev موجوداً لكن الـ prod موجود، انسخه للـ dev (أول مرة فقط)
_prod_db = BASE_DIR / "database" / "accounting_prod.db"
_legacy  = BASE_DIR / "database" / "accounting.db"
if not IS_PROD and not DB_PATH.exists():
    import shutil
    if _legacy.exists():
        shutil.copy2(_legacy, DB_PATH)
    elif _prod_db.exists():
        shutil.copy2(_prod_db, DB_PATH)

# ─── تحميل SECRET_KEY ─────────────────────────────────────────────────────────
def _load_secret_key() -> str:
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key
    key_file = BASE_DIR / ".secret_key"
    if key_file.exists():
        return key_file.read_text().strip()
    key = secrets.token_hex(32)
    key_file.write_text(key)
    return key


# ─── إعدادات Flask (تتغير حسب البيئة) ───────────────────────────────────────
FLASK_CONFIG: dict = {
    "MAX_CONTENT_LENGTH":         10 * 1024 * 1024,
    "PERMANENT_SESSION_LIFETIME": timedelta(hours=8),
    "SESSION_COOKIE_HTTPONLY":    True,
    "SESSION_COOKIE_SAMESITE":    "Lax",
    "DEBUG":                      not IS_PROD,
    "TESTING":                    False,
    "ENV":                        FLASK_ENV,
}
if IS_PROD:
    # في الإنتاج: فعّل SECURE فقط مع HTTPS
    _secure = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
    FLASK_CONFIG["SESSION_COOKIE_SECURE"] = _secure


MAX_LOGIN_ATTEMPTS = 10
LOGIN_WINDOW_SECONDS = 300

# ─── أنواع الأنشطة ────────────────────────────────────────────────────────────
INDUSTRY_TYPES = [
    # ── مفاتيح legacy (لحسابات قديمة) ─────────────────────────────────
    ("retail", "تجزئة (عام)"),
    ("wholesale", "جملة (عام)"),
    ("restaurant", "مطعم / كافيه (عام)"),

    # ── تجزئة — غذاء وتموين ──────────────────────────────────────────
    ("retail_fnb_supermarket",  "سوبر ماركت / هايبر ماركت"),
    ("retail_fnb_grocery",      "تموينات وبقالات"),
    ("retail_fnb_roaster",      "محامص (قهوة، بهارات، مكسرات)"),
    ("retail_fnb_bakery",       "مخابز وحلويات"),
    ("retail_fnb_butcher",      "ملاحم وجزارة"),
    ("retail_fnb_produce",      "خضار وفواكه"),
    ("retail_fnb_dates",        "تجار التمور"),
    ("retail_fnb_beverages",    "مياه ومشروبات — تجزئة"),
    # ── تجزئة — موضة وملبوسات ────────────────────────────────────────
    ("retail_fashion_clothing_m",  "ملابس رجالي"),
    ("retail_fashion_clothing_f",  "ملابس نسائي"),
    ("retail_fashion_clothing_k",  "ملابس أطفال"),
    ("retail_fashion_shoes",       "أحذية ومنتجات جلدية"),
    ("retail_fashion_bags",        "حقائب وإكسسوارات"),
    ("retail_fashion_watches",     "ساعات ومجوهرات"),
    ("retail_fashion_optics",      "نظارات وبصريات"),
    ("retail_fashion_fabric",      "أقمشة ومنسوجات"),
    ("retail_fashion_tailoring",   "مستلزمات خياطة"),
    # ── تجزئة — مواد بناء وأدوات ─────────────────────────────────────
    ("retail_construction_materials",  "مواد بناء — إسمنت وحديد"),
    ("retail_construction_plumbing",   "سباكة وأدوات صحية"),
    ("retail_construction_electrical", "كهرباء وإنارة"),
    ("retail_construction_paints",     "دهانات وبوادئ"),
    ("retail_construction_flooring",   "أرضيات وسيراميك ورخام"),
    ("retail_construction_hardware",   "عدد وآلات (Hardware)"),
    # ── تجزئة — إلكترونيات وتقنية ────────────────────────────────────
    ("retail_electronics_mobile",        "جوالات وإكسسوارات"),
    ("retail_electronics_computers",     "كمبيوتر ولابتوب وشبكات"),
    ("retail_electronics_appliances",    "أجهزة منزلية كبيرة"),
    ("retail_electronics_entertainment", "إلكترونيات ترفيهية وألعاب"),
    ("retail_electronics_security",      "كاميرات مراقبة وأنظمة أمنية"),
    # ── تجزئة — صحة وعناية ───────────────────────────────────────────
    ("retail_health_pharmacy",    "صيدلية"),
    ("retail_health_perfume",     "عطور وبخور وعود"),
    ("retail_health_cosmetics",   "مستحضرات تجميل"),
    ("retail_health_medical",     "مستلزمات طبية — تجزئة"),
    ("retail_health_supplements", "أغذية صحية ومكملات غذائية"),
    # ── تجزئة — سيارات ومعدات ────────────────────────────────────────
    ("retail_auto_parts",       "قطع غيار سيارات"),
    ("retail_auto_tires",       "إطارات وبطاريات"),
    ("retail_auto_accessories", "زينة وإكسسوارات سيارات"),
    ("retail_auto_workshop",    "معدات ورش صيانة"),
    # ── تجزئة — منزل ومكتب ───────────────────────────────────────────
    ("retail_home_furniture",   "أثاث ومفروشات"),
    ("retail_home_carpet",      "سجاد وموكيت"),
    ("retail_home_kitchenware", "أواني ولوازم منزلية"),
    ("retail_home_stationery",  "مكتبات وقرطاسية"),
    ("retail_home_office",      "تجهيزات مكاتب وأثاث مكتبي"),
    # ── تجزئة — أنشطة متخصصة ─────────────────────────────────────────
    ("retail_specialized_flowers", "زهور وتغليف هدايا"),
    ("retail_specialized_toys",    "ألعاب أطفال وهدايا"),
    ("retail_specialized_pets",    "مستلزمات حيوانات أليفة"),
    ("retail_specialized_sports",  "معدات رياضية"),
    ("retail_specialized_camping", "لوازم رحلات وصيد"),
    # ── جملة — غذاء وتموين ───────────────────────────────────────────
    ("wholesale_fnb_distribution", "مراكز توزيع مواد غذائية"),
    ("wholesale_fnb_beverages",    "مستودعات مياه ومشروبات"),
    ("wholesale_fnb_roaster",      "محامص وبهارات ومكسرات — جملة"),
    ("wholesale_fnb_general",      "جملة غذائية عامة"),
    ("wholesale_fnb_bakery",       "مخابز وحلويات — جملة"),
    ("wholesale_fnb_butcher",      "ملاحم وجزارة — جملة"),
    ("wholesale_fnb_produce",      "خضار وفواكه — جملة"),
    ("wholesale_fnb_dates",        "تمور — جملة"),
    # ── جملة — موضة وملبوسات ─────────────────────────────────────────
    ("wholesale_fashion_clothing",   "جملة ملابس"),
    ("wholesale_fashion_fabric",     "جملة أقمشة ومنسوجات"),
    ("wholesale_fashion_shoes",      "جملة أحذية"),
    ("wholesale_fashion_bags",       "جملة حقائب وإكسسوارات"),
    ("wholesale_fashion_clothing_m", "جملة ملابس رجالي"),
    ("wholesale_fashion_clothing_f", "جملة ملابس نسائي"),
    ("wholesale_fashion_clothing_k", "جملة ملابس أطفال"),
    ("wholesale_fashion_watches",    "جملة ساعات ومجوهرات"),
    ("wholesale_fashion_optics",     "جملة نظارات وبصريات"),
    # ── جملة — مواد بناء ─────────────────────────────────────────────
    ("wholesale_construction_materials",  "جملة مواد بناء"),
    ("wholesale_construction_timber",     "جملة أخشاب"),
    ("wholesale_construction_plumbing",   "جملة سباكة وكهرباء"),
    ("wholesale_construction_electrical", "جملة كهرباء وإنارة"),
    ("wholesale_construction_paints",     "جملة دهانات وبوادئ"),
    ("wholesale_construction_flooring",   "جملة أرضيات وسيراميك"),
    # ── جملة — إلكترونيات ────────────────────────────────────────────
    ("wholesale_electronics_general",     "جملة إلكترونيات"),
    ("wholesale_electronics_mobile",      "جملة جوالات وإكسسوارات"),
    ("wholesale_electronics_computers",   "جملة كمبيوتر ولابتوب"),
    ("wholesale_electronics_appliances",  "جملة أجهزة منزلية"),
    ("wholesale_electronics_entertainment","جملة إلكترونيات ترفيهية"),
    # ── جملة — صحة ───────────────────────────────────────────────────
    ("wholesale_health_medical",  "جملة مستلزمات طبية"),
    ("wholesale_health_pharmacy", "توزيع أدوية"),
    ("wholesale_health_perfume",  "جملة عطور وبخور"),
    ("wholesale_health_cosmetics","جملة مستحضرات تجميل"),
    ("wholesale_health_supplements", "جملة مكملات غذائية"),
    # ── جملة — سيارات ────────────────────────────────────────────────
    ("wholesale_auto_parts",      "جملة قطع غيار"),
    ("wholesale_auto_tires",      "جملة إطارات وبطاريات"),
    ("wholesale_auto_accessories", "جملة زينة وإكسسوارات سيارات"),
    ("wholesale_auto_workshop",   "جملة معدات ورش صيانة"),
    # ── جملة — منزل ومكتب ────────────────────────────────────────────
    ("wholesale_home_furniture",  "جملة أثاث"),
    ("wholesale_home_carpet",     "جملة سجاد وموكيت"),
    ("wholesale_home_kitchenware", "جملة أواني ولوازم منزلية"),
    ("wholesale_home_stationery", "جملة قرطاسية ومستلزمات مكتبية"),
    ("wholesale_home_office",     "جملة تجهيزات مكاتب"),
    # ── جملة — أنشطة متخصصة ─────────────────────────────────────────
    ("wholesale_specialized_flowers", "جملة زهور وتغليف هدايا"),
    ("wholesale_specialized_toys",    "جملة ألعاب أطفال وهدايا"),
    ("wholesale_specialized_pets",    "جملة مستلزمات حيوانات أليفة"),
    ("wholesale_specialized_sports",  "جملة معدات رياضية"),
    ("wholesale_specialized_camping", "جملة لوازم رحلات وصيد"),
    # ── تقديم الطعام ─────────────────────────────────────────────────
    ("food_restaurant", "مطعم"),
    ("food_cafe",       "كافيه"),
    ("food_coffeeshop", "مقهى"),
    # ── قطاعات خدمية — أساسية ────────────────────────────────────────
    ("medical_complex", "مجمع طبي / عيادات"),
    ("construction", "مقاولات وتشغيل"),
    ("car_rental",   "تأجير سيارات"),
    ("medical",      "خدمات صحية"),
    ("services",     "خدمات عامة"),

    # ── تجزئة — غذاء (إضافات) ─────────────────────────────────────────
    ("retail_fnb_fish",     "محلات أسماك ومأكولات بحرية"),
    ("retail_fnb_poultry",  "محلات دجاج وطيور"),

    # ── تجزئة — منزل (إضافات) ────────────────────────────────────────
    ("retail_home_curtains",  "ستائر وديكور نوافذ"),
    ("retail_home_lighting",  "إنارة وثريات منزلية"),

    # ── تجزئة — متخصص (إضافات) ───────────────────────────────────────
    ("retail_specialized_books",   "مكتبات وكتب"),
    ("retail_specialized_art",     "أدوات فنية ورسم"),
    ("retail_specialized_music",   "آلات موسيقية"),
    ("retail_specialized_baby",    "مستلزمات أطفال رضع"),
    ("retail_specialized_wedding", "تجهيزات أفراح ومناسبات"),

    # ── تجزئة — سيارات (إضافات) ──────────────────────────────────────
    ("retail_auto_showroom", "معرض سيارات"),

    # ── جملة — غذاء (إضافات) ─────────────────────────────────────────
    ("wholesale_fnb_fish",    "سمك وأسماك — جملة"),
    ("wholesale_fnb_frozen",  "مجمدات وأغذية مجمدة — جملة"),
    ("wholesale_fnb_dairy",   "ألبان وأجبان — جملة"),
    ("wholesale_fnb_poultry", "دجاج وطيور — جملة"),

    # ── جملة — بناء (إضافات) ─────────────────────────────────────────
    ("wholesale_construction_steel", "حديد وصلب — جملة"),
    ("wholesale_construction_glass", "زجاج وألمنيوم — جملة"),

    # ── جملة — منزل (إضافات) ─────────────────────────────────────────
    ("wholesale_home_lighting",   "إنارة وثريات — جملة"),
    ("wholesale_specialized_baby", "مستلزمات أطفال — جملة"),

    # ── تقديم الطعام (إضافات) ────────────────────────────────────────
    ("food_fast_food",   "وجبات سريعة"),
    ("food_shawarma",    "شاورما ومشاوي"),
    ("food_pizza",       "بيتزا ومأكولات إيطالية"),
    ("food_catering",    "خدمات ضيافة وتموين"),
    ("food_cloud_kitchen", "مطبخ سحابي"),
    ("food_pastry",      "حلويات ومعجنات"),
    ("food_juice",       "عصائر ومشروبات طازجة"),
    ("food_ice_cream",   "آيس كريم وحلويات مثلجة"),
    ("food_food_court",  "فود كورت ومجمع أكل"),

    # ── خدمات متخصصة ─────────────────────────────────────────────────
    ("services_cleaning",      "نظافة وتنظيف"),
    ("services_laundry",       "غسيل ومصبغة"),
    ("services_printing",      "طباعة ونسخ وتصوير"),
    ("services_photography",   "تصوير وأستوديو"),
    ("services_advertising",   "إعلانات وتسويق"),
    ("services_it_support",    "دعم تقني وشبكات"),
    ("services_software",      "برمجيات وتطبيقات"),
    ("services_accounting_firm", "مكتب محاسبة وتدقيق"),
    ("services_legal",         "مكتب محاماة واستشارات قانونية"),
    ("services_consulting",    "استشارات إدارية وأعمال"),
    ("services_training",      "تدريب وتطوير مهني"),
    ("services_translation",   "ترجمة ولغات"),
    ("services_travel",        "سياحة وسفر"),
    ("services_hajj_umrah",    "خدمات حج وعمرة"),
    ("services_event",         "تنظيم فعاليات ومناسبات"),
    ("services_security_guard", "حراسة وأمن"),
    ("services_maintenance",   "صيانة عامة وإصلاح"),
    ("services_landscaping",   "زراعة وتنسيق حدائق"),
    ("services_pest_control",  "مكافحة حشرات وقوارض"),
    ("services_beauty_salon_f", "صالون نسائي"),
    ("services_beauty_salon_m", "صالون رجالي وحلاقة"),
    ("services_spa",           "سبا ومراكز عناية"),
    ("services_fitness",       "نوادي رياضية ولياقة بدنية"),
    ("services_driving_school", "مدارس تعليم قيادة"),
    ("services_manpower",      "استقدام واستخدام عمالة"),

    # ── رعاية صحية متخصصة ───────────────────────────────────────────
    ("medical_dental",          "عيادة أسنان"),
    ("medical_optical_clinic",  "عيادة بصريات وعيون"),
    ("medical_physiotherapy",   "علاج طبيعي وإعادة تأهيل"),
    ("medical_veterinary",      "طب بيطري"),
    ("medical_laboratory",      "مختبر تحاليل طبية"),
    ("medical_radiology",       "مركز أشعة وتصوير طبي"),
    ("medical_pharmacy_clinic", "صيدلية وعيادة"),

    # ── تعليم وتدريب ─────────────────────────────────────────────────
    ("education_school",          "مدرسة أهلية"),
    ("education_nursery",         "حضانة وروضة أطفال"),
    ("education_training_center", "مركز تدريب مهني"),
    ("education_tutoring",        "مركز تقوية دراسية"),
    ("education_language",        "مركز تعليم لغات"),
    ("education_quran",           "مركز تحفيظ قرآن"),    ("education_university",      "جامعة وكلية أهلية"),
    ("education_online",          "تعليم إلكتروني عن بعد"),
    ("education_vocational",      "معهد تقني وحرفي"),
    ("education_arts",            "مركز فنون وموسيقى"),
    ("education_sports_academy",  "أكاديمية رياضية"),
    ("education_coding",          "مركز تعليم برمجة وتقنية"),
    # ── عقارات ───────────────────────────────────────────────────────
    ("real_estate_agency",     "وساطة عقارية"),
    ("real_estate_developer",  "تطوير عقاري"),
    ("real_estate_management", "إدارة عقارات وأملاك"),

    # ── نقل ومواصلات ─────────────────────────────────────────────────
    ("transport_freight",    "شحن ونقل بضائع"),
    ("transport_courier",    "بريد سريع وتوصيل"),
    ("transport_moving",     "نقل عفش وأثاث"),
    ("transport_passenger",  "نقل ركاب وحافلات"),
    ("transport_taxi",       "تاكسي ونقل خاص"),

    # ── ضيافة وسياحة ─────────────────────────────────────────────────
    ("hospitality_hotel",         "فندق وإقامة"),
    ("hospitality_furnished_apt", "شقق مفروشة"),
    ("hospitality_resort",        "منتجع سياحي"),
    ("hospitality_chalet",        "استراحة وشاليه"),

    # ── خدمات سيارات ─────────────────────────────────────────────────
    ("auto_service_carwash", "غسيل سيارات"),
    ("auto_service_repair",  "تصليح وصيانة سيارات"),
    ("auto_service_paint",   "دهان وهيكلة سيارات"),

    # ── صناعة ووُرش ──────────────────────────────────────────────────
    ("industrial_factory",  "مصنع وتصنيع"),
    ("industrial_workshop", "ورشة صناعية"),

    # ── زراعة وإنتاج ─────────────────────────────────────────────────
    ("agriculture_general",   "مزارع وإنتاج زراعي"),
    ("agriculture_dates",     "مزارع النخيل والتمور"),
    ("agriculture_poultry",   "مزارع الدواجن والبيض"),
    ("agriculture_fish",      "مزارع الأسماك والأحياء البحرية"),
    ("agriculture_greenhouses","البيوت المحمية والخضار المائية"),
    ("agriculture_honey",     "تربية النحل وإنتاج العسل"),
    ("agriculture_supply",    "مستلزمات زراعية ومبيدات"),

    # ── تجزئة — إضافات متخصصة ────────────────────────────────────────
    ("retail_specialized_quran",       "مستلزمات دينية ومصاحف"),
    ("retail_specialized_organic",     "منتجات عضوية وطبيعية"),
    ("retail_specialized_gift_shop",   "محل هدايا وتحف"),
    ("retail_specialized_car_care",    "مستلزمات العناية بالسيارات"),
    ("retail_specialized_printing",    "طباعة وتصميم — تجزئة"),
    ("retail_specialized_craft",       "أدوات حرف يدوية"),
    ("retail_specialized_aquarium",    "مستلزمات أسماك وديكور مائي"),

    # ── جملة — إضافات متخصصة ─────────────────────────────────────────
    ("wholesale_fnb_oil",              "زيوت وسمن — جملة"),
    ("wholesale_fnb_sugar_flour",      "سكر ودقيق — جملة"),
    ("wholesale_fnb_spices",           "بهارات وتوابل — جملة"),
    ("wholesale_construction_cement",  "إسمنت وجبس — جملة"),
    ("wholesale_construction_tiles",   "بلاط وسيراميك — جملة"),
    ("wholesale_specialized_gifts",    "هدايا وتحف — جملة"),
    ("wholesale_specialized_medical",  "مستلزمات طبية — جملة"),
    ("wholesale_specialized_cleaning", "مواد تنظيف وعقيم — جملة"),
    ("wholesale_specialized_paper",    "ورق وتغليف — جملة"),

    # ── خدمات — إضافات ───────────────────────────────────────────────
    ("services_recruitment",          "خدمات توظيف واستشارات HR"),
    ("services_architecture",         "هندسة وتصميم معماري"),
    ("services_interior_design",      "تصميم داخلي وديكور"),
    ("services_engineering",          "مكاتب استشارات هندسية"),
    ("services_surveying",            "مساحة وتقييم عقاري"),
    ("services_medical_equipment",    "صيانة أجهزة طبية"),
    ("services_funeral",              "خدمات جنائزية ومقابر"),
    ("services_charity",              "جمعيات خيرية وغير ربحية"),
    ("services_government",           "جهات حكومية وشبه حكومية"),
    ("services_embassies",            "سفارات وقنصليات"),
    ("services_media",                "إعلام وإنتاج تلفزيوني"),
    ("services_music_studio",         "استوديو موسيقى وتسجيل"),
    ("services_gaming",               "ألعاب إلكترونية وE-Sports"),
    ("services_telecom",              "اتصالات وخدمات رقمية"),
    ("services_insurance",            "تأمين ووساطة مالية"),
    ("services_finance",              "خدمات مالية ومصرفية"),
    ("services_exchange",             "صرافة وحوالات مالية"),
    ("services_egovernment",          "مكتب خدمات حكومية إلكترونية"),
    ("services_feasibility",          "دراسات جدوى اقتصادية"),
    ("services_property_mgmt",        "إدارة أملاك وتشغيل"),
    ("services_facilities",           "مقاولات صيانة وتشغيل"),
    ("services_vehicle_inspection",   "فحص ومعاينة سيارات"),
    ("services_notary",               "كتابة عدل وتوثيق"),

    # ── صحة — إضافات ─────────────────────────────────────────────────
    ("medical_dermatology",           "عيادة جلدية وتجميل"),
    ("medical_orthopedic",            "عيادة عظام"),
    ("medical_pediatrics",            "عيادة أطفال"),
    ("medical_gynaecology",           "نساء وتوليد"),
    ("medical_psychiatry",            "طب نفسي وإرشاد"),
    ("medical_cardiology",            "قلب وأوعية دموية"),
    ("medical_ent",                   "أنف وأذن وحنجرة"),
    ("medical_urology",               "مسالك بولية"),
    ("medical_nutrition",             "تغذية وإيتكس سمنة"),
    ("medical_home_care",             "رعاية صحية منزلية"),

    # ── نقل ومواصلات — إضافات ────────────────────────────────────────
    ("transport_logistics",           "لوجستيات وإدارة سلسلة التوريد"),
    ("transport_customs",             "تخليص جمركي"),
    ("transport_shipping",            "شحن بحري وجوي"),
    ("transport_rental_trucks",       "تأجير شاحنات ومعدات ثقيلة"),

    # ── ضيافة وسياحة — إضافات ────────────────────────────────────────
    ("hospitality_camping",           "مخيمات وسياحة برية"),
    ("hospitality_motel",             "موتيل واستراحات الطريق"),
    ("hospitality_tourism_office",    "مكتب سياحة وحجوزات"),

    # ── تجارة إلكترونية ───────────────────────────────────────────────────
    ("ecommerce_general",             "متجر إلكتروني عام"),
    ("ecommerce_fashion",             "متجر أزياء وملابس أونلاين"),
    ("ecommerce_electronics",         "إلكترونيات وتقنية أونلاين"),
    ("ecommerce_food",                "طلبات طعام وتوصيل"),
    ("ecommerce_health_beauty",       "صحة وجمال أونلاين"),
    ("ecommerce_home_decor",          "أثاث وديكور أونلاين"),
    ("ecommerce_books_courses",       "كتب ودورات رقمية"),
    ("ecommerce_handmade",            "منتجات يدوية وحرف"),
    ("ecommerce_dropshipping",        "دروب شيبينج"),
    ("ecommerce_marketplace",         "سوق إلكتروني متعدد البائعين"),
    ("ecommerce_subscription",        "خدمات اشتراك شهري / صناديق"),
    ("ecommerce_digital_products",    "منتجات رقمية وتطبيقات"),

    # ── صناعة — إضافات ───────────────────────────────────────────────────
    ("industrial_printing_press",     "مطبعة وطباعة صناعية"),
    ("industrial_packaging",          "تعبئة وتغليف صناعي"),
    ("industrial_recycling",          "تدوير ونفايات"),
    ("industrial_food_production",    "إنتاج غذائي وتصنيع"),
    ("industrial_chemical",           "صناعات كيماوية"),
    ("industrial_metal",              "حدادة وتشكيل معادن"),
    ("industrial_wood",               "نجارة وصناعة أثاث"),
    ("industrial_construction_contracting", "مقاولات وتشييد"),
]


def get_sidebar_key(industry_type: str) -> str:
    """تُحوّل الكود التفصيلي (القديم والجديد) إلى مفتاح السيدبار."""
    code = (industry_type or "").strip().lower()

    # أكواد التهيئة الجديدة (مشهد onboarding التفصيلي)
    if code.startswith("svc_mnt_auto") or code.startswith("svc_trv_car"):
        return "car_rental"
    if code.startswith("svc_trv_hotel"):
        return "restaurant"
    if code.startswith("svc_"):
        return "services"
    if code.startswith("con_") or code.startswith("mfg_"):
        return "construction"
    if code.startswith("hos_cafe") or code.startswith(("hos_fastfood", "hos_traditional", "hos_cloud", "hos_buffet", "hos_truck")):
        return "restaurant"
    if code.startswith(("hos_hotel", "hos_apartments", "hos_resort", "hos_events")):
        return "services"
    if code.startswith("hlt_pharmacy"):
        return "retail"
    if code.startswith("hlt_"):
        return "medical"
    if code.startswith("lgx_"):
        return "services"

    # الأكواد القياسية
    if code.startswith("retail_"):       return "retail"
    if code.startswith("wholesale_"):    return "wholesale"
    if code.startswith("food_"):         return "restaurant"
    if code.startswith("medical_"):      return "medical"
    if code.startswith("ecommerce_"):    return "ecommerce"
    if code.startswith("education_"):    return "education"
    if code.startswith("services_"):     return "services"
    if code.startswith("education_"):    return "services"
    if code.startswith("real_estate_"):  return "services"
    if code.startswith("transport_"):    return "services"
    if code.startswith("hospitality_"):  return "services"
    if code.startswith("auto_service_"): return "services"
    if code.startswith("industrial_"):   return "services"
    if code.startswith("agriculture_"):  return "services"
    if code in ("restaurant", "cafe", "coffeeshop"): return "restaurant"
    if code == "medical_complex":        return "medical"
    return code


SIDEBAR_CONFIG = {
    "_common": [
        {"key": "dashboard",  "label": "لوحة التحكم",       "label_en": "Dashboard",          "icon": "🏠", "url": "/dashboard"},
        {"key": "contacts",  "label": "العملاء والموردين",  "label_en": "Contacts",           "icon": "👥", "url": "/contacts"},
        {"key": "hr",        "label": "الموارد البشرية",    "label_en": "Human Resources",    "icon": "👨‍💼", "url": "/hr/"},
        {"key": "accounting","label": "المحاسبة",           "label_en": "Accounting",         "icon": "📒", "url": "/accounting"},
        {"key": "analytics", "label": "تحليل المبيعات",    "label_en": "Sales Analytics",    "icon": "📊", "url": "/analytics"},
        {"key": "reports",   "label": "التقارير",           "label_en": "Reports",            "icon": "📈", "url": "/reports"},
        {"key": "reminders", "label": "التنبيهات",          "label_en": "Reminders",          "icon": "🔔", "url": "/reminders"},
        {"key": "settings",  "label": "الإعدادات",          "label_en": "Settings",           "icon": "⚙️", "url": "/settings"},
    ],
    "retail": [
        {"key": "pos",       "label": "نقاط البيع",     "label_en": "Point of Sale",      "icon": "🛒", "url": "/pos"},
        {"key": "inventory", "label": "المخزون",        "label_en": "Inventory",          "icon": "📦", "url": "/inventory"},
        {"key": "purchases", "label": "المشتريات",      "label_en": "Purchases",          "icon": "🛍️", "url": "/purchases"},
        {"key": "expenses",  "label": "المصاريف",       "label_en": "Expenses",           "icon": "💸", "url": "/expenses"},
        {"key": "barcode",   "label": "إدارة الباركود", "label_en": "Barcode",            "icon": "📷", "url": "/barcode"},
        {"key": "invoices",  "label": "الفواتير",       "label_en": "Invoices",           "icon": "🧾", "url": "/invoices"},
    ],
    "restaurant": [
        {"key": "kitchen",  "label": "شاشة المطبخ",    "label_en": "Kitchen Display",    "icon": "👨‍🍳", "url": "/kitchen"},
        {"key": "tables",   "label": "إدارة الطاولات",  "label_en": "Tables",             "icon": "🍽️",  "url": "/tables"},
        {"key": "recipes",  "label": "الوصفات",         "label_en": "Recipes",            "icon": "📋",  "url": "/recipes"},
        {"key": "invoices", "label": "الفواتير",        "label_en": "Invoices",           "icon": "🧾",  "url": "/invoices"},
    ],
    "construction": [
        {"key": "projects",   "label": "المشاريع",      "label_en": "Projects",           "icon": "🏗️",  "url": "/projects/"},
        {"key": "equipment",  "label": "المعدات",       "label_en": "Equipment",          "icon": "🔧",  "url": "/projects/equipment"},
        {"key": "extracts",   "label": "المستخلصات",    "label_en": "Extracts",           "icon": "🧾",  "url": "/extracts"},
        {"key": "invoices",   "label": "الفواتير",      "label_en": "Invoices",           "icon": "🧾",  "url": "/invoices/"},
    ],
    "car_rental": [
        {"key": "fleet",       "label": "الأسطول",      "label_en": "Fleet",              "icon": "🚗", "url": "/rental/fleet"},
        {"key": "contracts",   "label": "عقود الإيجار", "label_en": "Rental Contracts",   "icon": "📄", "url": "/rental/contracts"},
        {"key": "maintenance", "label": "الصيانة",      "label_en": "Maintenance",        "icon": "🔧", "url": "/rental/maintenance"},
        {"key": "invoices",    "label": "الفواتير",     "label_en": "Invoices",           "icon": "🧾", "url": "/invoices/"},
    ],
    "medical": [
        {"key": "patients",      "label": "المرضى",          "label_en": "Patients",       "icon": "🏥", "url": "/medical/patients"},
        {"key": "appointments",  "label": "المواعيد",        "label_en": "Appointments",   "icon": "📅", "url": "/medical/appointments"},
        {"key": "prescriptions", "label": "الوصفات الطبية",  "label_en": "Prescriptions",  "icon": "💊", "url": "/medical/patients"},
        {"key": "invoices",      "label": "الفواتير",        "label_en": "Invoices",       "icon": "🧾", "url": "/invoices/"},
    ],
    "wholesale": [
        {"key": "wholesale_orders", "label": "الطلبات",       "label_en": "Orders",         "icon": "🛒", "url": "/wholesale/orders"},
        {"key": "quotes",           "label": "عروض الأسعار",   "label_en": "Quotations",     "icon": "🧮", "url": "/wholesale/quotes"},
        {"key": "receipts",         "label": "سندات القبض",    "label_en": "Receipts",       "icon": "💵", "url": "/wholesale/receipts"},
        {"key": "inventory",        "label": "المخزون",        "label_en": "Inventory",      "icon": "📦", "url": "/inventory/"},
        {"key": "purchases",        "label": "المشتريات",      "label_en": "Purchases",      "icon": "🛍️", "url": "/purchases"},
        {"key": "expenses",         "label": "المصاريف",       "label_en": "Expenses",       "icon": "💸", "url": "/expenses"},
        {"key": "invoices",         "label": "الفواتير",       "label_en": "Invoices",       "icon": "🧾", "url": "/invoices/"},
        {"key": "pricing",          "label": "قوائم الأسعار",  "label_en": "Price Lists",    "icon": "💰", "url": "/wholesale/pricing"},
    ],
    "services": [
        {"key": "jobs",      "label": "أوامر العمل",   "label_en": "Work Orders",        "icon": "📋", "url": "/services/jobs"},
        {"key": "invoices",  "label": "الفواتير",      "label_en": "Invoices",           "icon": "🧾", "url": "/invoices/"},
        {"key": "contracts", "label": "العقود",        "label_en": "Contracts",          "icon": "📄", "url": "/services/contracts"},
    ],
    "ecommerce": [
        {"key": "pos",       "label": "الطلبات",         "label_en": "Orders",             "icon": "🛒", "url": "/pos"},
        {"key": "inventory", "label": "المخزون",         "label_en": "Inventory",          "icon": "📦", "url": "/inventory"},
        {"key": "invoices",  "label": "الفواتير",        "label_en": "Invoices",           "icon": "🧾", "url": "/invoices/"},
        {"key": "purchases", "label": "المشتريات",       "label_en": "Purchases",          "icon": "🛍️", "url": "/purchases"},
        {"key": "expenses",  "label": "المصاريف",        "label_en": "Expenses",           "icon": "💸", "url": "/expenses"},
        {"key": "barcode",   "label": "الباركود / SKU",  "label_en": "Barcode",            "icon": "📷", "url": "/barcode"},
    ],    "education": [
        {"key": "invoices",  "label": "الفواتير / الرسوم",  "label_en": "Invoices",           "icon": "🧾", "url": "/invoices/"},
        {"key": "contacts",  "label": "الطلاب / الولياء",  "label_en": "Students",           "icon": "👨‍💼", "url": "/contacts"},
        {"key": "expenses",  "label": "المصاريف التشغيلية",   "label_en": "Expenses",           "icon": "💸", "url": "/expenses"},
        {"key": "jobs",      "label": "جدول الحصص",       "label_en": "Schedules",          "icon": "📅", "url": "/services/jobs"},
    ],}
SIDEBAR_CONFIG["cafe"]           = SIDEBAR_CONFIG["restaurant"]
SIDEBAR_CONFIG["coffeeshop"]     = SIDEBAR_CONFIG["restaurant"]
SIDEBAR_CONFIG["food_restaurant"]= SIDEBAR_CONFIG["restaurant"]
SIDEBAR_CONFIG["food_cafe"]      = SIDEBAR_CONFIG["restaurant"]
SIDEBAR_CONFIG["food_coffeeshop"]= SIDEBAR_CONFIG["restaurant"]


# ─── خريطة الصلاحيات ─────────────────────────────────────────────────────────
ROUTE_PERMS = {
    "reports":    {"reports", "reports_vat"},
    "settings":   {"settings"},
    "accounting": {"accounting", "journal_entry_new", "journal_entry_view"},
    "analytics":  {"analytics"},
    "purchases":  {"purchases", "purchase_import"},
    "warehouse":  {"inventory", "barcode", "stock_movement"},
    "contacts":   {"contacts", "contact_view"},
    "pos":        {"pos", "tables", "kitchen"},
}

SIDEBAR_PERM = {
    "dashboard":       None,
    "analytics":       "analytics",
    "contacts":        "contacts",
    "workforce":       "settings",
    "team":            "all",
    "audit-log":       "all",
    "recycle-bin":     "all",
    "reminders":       "all",
    "backup":          "all",
    "owner":           "all",
    "accounting":      "accounting",
    "purchase-import": "purchases",
    "reports":         "reports",
    "settings":        "settings",
    "pos":             "pos",
    "inventory":       "warehouse",
    "purchases":       "purchases",
    "barcode":         "warehouse",
    "invoices":        "sales",
    "kitchen":         "pos",
    "tables":          "pos",
    "recipes":         "pos",
    "pricing":         "purchases",
    "wholesale_orders": "sales",
    "quotes":          "sales",
    "receipts":        "sales",
    "expenses":        "purchases",
    "projects":        "sales",
    "equipment":       "sales",
    "extracts":        "sales",
    "fleet":           "sales",
    "contracts":       "sales",
    "maintenance":     "sales",
    "patients":        "sales",
    "appointments":    "sales",
    "prescriptions":   "sales",
    "jobs":            "sales",
    "hr":              None,
    "accounting":      "accounting",
}

# صفحات stub — فقط الصفحات التي لم يُبنَ لها blueprint بعد
STUB_PAGES = [
    "extracts",   # تحت /projects/<id>/extracts
]

# ─── حماية المسارات حسب نوع النشاط ──────────────────────────────────────────
# key = بادئة URL   value = مجموعة أنواع النشاط المسموح لها
# None = مفتوح لجميع الأنشطة
INDUSTRY_ROUTE_GUARD: dict[str, set | None] = {
    "/medical":       {"medical"},
    "/rental":        {"car_rental"},
    "/projects":      {"construction"},
    "/services":      {"services"},
    "/wholesale":     {t for t, _ in [] },  # يُملأ لاحقاً
    "/kitchen":       set(),   # مطاعم فقط — يُملأ لاحقاً
    "/tables":        set(),
    "/recipes":       set(),
    "/orders":        set(),
    "/pos":           set(),
}

def _build_industry_route_guards() -> dict[str, set | None]:
    """يبني خريطة الحماية بعد تحميل INDUSTRY_TYPES."""
    restaurant_types = {t for t, _ in INDUSTRY_TYPES if t.startswith("food_") or t in ("restaurant", "cafe", "coffeeshop")}
    retail_types     = {t for t, _ in INDUSTRY_TYPES if t.startswith("retail_")} | {"retail"}
    wholesale_types  = {t for t, _ in INDUSTRY_TYPES if t.startswith("wholesale_")} | {"wholesale"}
    medical_types    = {t for t, _ in INDUSTRY_TYPES if t == "medical" or t.startswith("medical_")}
    services_types   = (
        {t for t, _ in INDUSTRY_TYPES if t == "services" or t.startswith("services_")}
        | {t for t, _ in INDUSTRY_TYPES if t.startswith("education_")}
        | {t for t, _ in INDUSTRY_TYPES if t.startswith("real_estate_")}
        | {t for t, _ in INDUSTRY_TYPES if t.startswith("transport_")}
        | {t for t, _ in INDUSTRY_TYPES if t.startswith("hospitality_")}
        | {t for t, _ in INDUSTRY_TYPES if t.startswith("auto_service_")}
        | {t for t, _ in INDUSTRY_TYPES if t.startswith("industrial_")}
        | {t for t, _ in INDUSTRY_TYPES if t.startswith("agriculture_")}
    )
    return {
        "/medical":   medical_types,
        "/rental":    {"car_rental"},
        "/projects":  {"construction"},
        "/extracts":  {"construction"},
        "/services":  services_types,
        "/wholesale": wholesale_types,
        "/kitchen":   restaurant_types,
        "/tables":    restaurant_types,
        "/recipes":   restaurant_types,
        "/orders":    restaurant_types,
        "/pos":       retail_types,
        "/barcode":   retail_types,
    }

INDUSTRY_ROUTE_GUARDS = _build_industry_route_guards()

# مجلدات
UPLOAD_FOLDER = BASE_DIR / "uploads"
LOGO_FOLDER   = BASE_DIR / "static" / "logos"
ALLOWED_EXT   = {"pdf", "png", "jpg", "jpeg", "webp"}
ALLOWED_LOGO_EXT = {"png", "jpg", "jpeg", "webp"}
