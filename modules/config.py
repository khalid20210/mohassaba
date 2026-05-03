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
    ("retail_specialized_tobacco", "معسلات ومستلزمات تدخين"),
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
    ("wholesale_specialized_tobacco", "جملة معسلات ومستلزمات تدخين"),
    ("wholesale_specialized_flowers", "جملة زهور وتغليف هدايا"),
    ("wholesale_specialized_toys",    "جملة ألعاب أطفال وهدايا"),
    ("wholesale_specialized_pets",    "جملة مستلزمات حيوانات أليفة"),
    ("wholesale_specialized_sports",  "جملة معدات رياضية"),
    ("wholesale_specialized_camping", "جملة لوازم رحلات وصيد"),
    # ── تقديم الطعام ─────────────────────────────────────────────────
    ("food_restaurant", "مطعم"),
    ("food_cafe",       "كافيه"),
    ("food_coffeeshop", "مقهى"),
    # ── قطاعات خدمية ─────────────────────────────────────────────────
    ("medical_complex", "مجمع طبي / عيادات"),
    ("construction", "مقاولات وتشغيل"),
    ("car_rental",   "تأجير سيارات"),
    ("medical",      "خدمات صحية"),
    ("services",     "خدمات عامة"),
]


def get_sidebar_key(industry_type: str) -> str:
    """تُحوّل الكود التفصيلي إلى مفتاح السيدبار"""
    if industry_type.startswith("retail_"):    return "retail"
    if industry_type.startswith("wholesale_"): return "wholesale"
    if industry_type.startswith("food_"):      return "restaurant"
    if industry_type.startswith("medical_"):   return "medical"
    if industry_type in ("restaurant", "cafe", "coffeeshop"): return "restaurant"
    if industry_type == "medical_complex":     return "medical"
    return industry_type


SIDEBAR_CONFIG = {
    "_common": [
        {"key": "dashboard", "label": "لوحة التحكم",      "icon": "🏠", "url": "/dashboard"},
        {"key": "contacts",  "label": "العملاء والموردين", "icon": "👥", "url": "/contacts"},
        {"key": "analytics", "label": "تحليل المبيعات",   "icon": "📊", "url": "/analytics"},
        {"key": "reports",   "label": "التقارير",          "icon": "📈", "url": "/reports"},
        {"key": "reminders", "label": "التنبيهات",        "icon": "🔔", "url": "/reminders"},
        {"key": "settings",  "label": "الإعدادات",        "icon": "⚙️", "url": "/settings"},
    ],
    "retail": [
        {"key": "pos",       "label": "نقاط البيع",    "icon": "🛒", "url": "/pos"},
        {"key": "inventory", "label": "المخزون",       "icon": "📦", "url": "/inventory"},
        {"key": "purchases", "label": "المشتريات",     "icon": "🛍️", "url": "/purchases"},
        {"key": "expenses",  "label": "المصاريف",      "icon": "💸", "url": "/expenses"},
        {"key": "barcode",   "label": "إدارة الباركود","icon": "📷", "url": "/barcode"},
        {"key": "invoices",  "label": "الفواتير",      "icon": "🧾", "url": "/invoices"},
    ],
    "restaurant": [
        {"key": "kitchen",  "label": "شاشة المطبخ",   "icon": "👨‍🍳", "url": "/kitchen"},
        {"key": "tables",   "label": "إدارة الطاولات", "icon": "🍽️",  "url": "/tables"},
        {"key": "recipes",  "label": "الوصفات",        "icon": "📋",  "url": "/recipes"},
        {"key": "invoices", "label": "الفواتير",       "icon": "🧾",  "url": "/invoices"},
    ],
    "construction": [
        {"key": "projects",   "label": "المشاريع",     "icon": "🏗️",  "url": "/projects/"},
        {"key": "equipment",  "label": "المعدات",      "icon": "🔧",  "url": "/projects/equipment"},
        {"key": "extracts",   "label": "المستخلصات",   "icon": "🧾",  "url": "/extracts"},
        {"key": "invoices",   "label": "الفواتير",     "icon": "🧾",  "url": "/invoices/"},
    ],
    "car_rental": [
        {"key": "fleet",      "label": "الأسطول",       "icon": "🚗", "url": "/rental/fleet"},
        {"key": "contracts",  "label": "عقود الإيجار",  "icon": "📄", "url": "/rental/contracts"},
        {"key": "maintenance","label": "الصيانة",       "icon": "🔧", "url": "/rental/maintenance"},
        {"key": "invoices",   "label": "الفواتير",      "icon": "🧾", "url": "/invoices/"},
    ],
    "medical": [
        {"key": "patients",      "label": "المرضى",       "icon": "🏥", "url": "/medical/patients"},
        {"key": "appointments",  "label": "المواعيد",     "icon": "📅", "url": "/medical/appointments"},
        {"key": "prescriptions", "label": "الوصفات الطبية", "icon": "💊", "url": "/medical/patients"},
        {"key": "invoices",      "label": "الفواتير",     "icon": "🧾", "url": "/invoices/"},
    ],
    "wholesale": [
        {"key": "wholesale_orders", "label": "الطلبات",       "icon": "🛒", "url": "/wholesale/orders"},
        {"key": "quotes",           "label": "عروض الأسعار",   "icon": "🧮", "url": "/wholesale/quotes"},
        {"key": "receipts",         "label": "سندات القبض",    "icon": "💵", "url": "/wholesale/receipts"},
        {"key": "inventory",        "label": "المخزون",       "icon": "📦", "url": "/inventory/"},
        {"key": "purchases",        "label": "المشتريات",     "icon": "🛍️", "url": "/purchases"},
        {"key": "expenses",         "label": "المصاريف",      "icon": "💸", "url": "/expenses"},
        {"key": "invoices",         "label": "الفواتير",      "icon": "🧾", "url": "/invoices/"},
        {"key": "pricing",          "label": "قوائم الأسعار", "icon": "💰", "url": "/wholesale/pricing"},
    ],
    "services": [
        {"key": "jobs",      "label": "أوامر العمل",   "icon": "📋", "url": "/services/jobs"},
        {"key": "invoices",  "label": "الفواتير",      "icon": "🧾", "url": "/invoices/"},
        {"key": "contracts", "label": "العقود",        "icon": "📄", "url": "/services/contracts"},
    ],
}
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
    return {
        "/medical":   medical_types,
        "/rental":    {"car_rental"},
        "/projects":  {"construction"},
        "/extracts":  {"construction"},
        "/services":  {"services"},
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
