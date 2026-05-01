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
    # ── جملة — موضة وملبوسات ─────────────────────────────────────────
    ("wholesale_fashion_clothing", "جملة ملابس"),
    ("wholesale_fashion_fabric",   "جملة أقمشة ومنسوجات"),
    ("wholesale_fashion_shoes",    "جملة أحذية"),
    ("wholesale_fashion_bags",     "جملة حقائب وإكسسوارات"),
    # ── جملة — مواد بناء ─────────────────────────────────────────────
    ("wholesale_construction_materials", "جملة مواد بناء"),
    ("wholesale_construction_timber",    "جملة أخشاب"),
    ("wholesale_construction_plumbing",  "جملة سباكة وكهرباء"),
    # ── جملة — إلكترونيات ────────────────────────────────────────────
    ("wholesale_electronics_general", "جملة إلكترونيات"),
    ("wholesale_electronics_mobile",  "جملة جوالات وإكسسوارات"),
    # ── جملة — صحة ───────────────────────────────────────────────────
    ("wholesale_health_medical",  "جملة مستلزمات طبية"),
    ("wholesale_health_pharmacy", "توزيع أدوية"),
    # ── جملة — سيارات ────────────────────────────────────────────────
    ("wholesale_auto_parts",    "جملة قطع غيار"),
    # ── جملة — منزل ومكتب ────────────────────────────────────────────
    ("wholesale_home_furniture",  "جملة أثاث"),
    ("wholesale_home_stationery", "جملة قرطاسية ومستلزمات مكتبية"),
    # ── تقديم الطعام ─────────────────────────────────────────────────
    ("food_restaurant", "مطعم"),
    ("food_cafe",       "كافيه"),
    ("food_coffeeshop", "مقهى"),
    # ── قطاعات خدمية ─────────────────────────────────────────────────
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
    if industry_type in ("restaurant", "cafe", "coffeeshop"): return "restaurant"
    return industry_type


SIDEBAR_CONFIG = {
    "_common": [
        {"key": "dashboard",        "label": "لوحة التحكم",       "icon": "🏠", "url": "/dashboard"},
        {"key": "analytics",        "label": "تحليل المبيعات",    "icon": "📊", "url": "/analytics"},
        {"key": "contacts",         "label": "العملاء والموردين",  "icon": "👥", "url": "/contacts"},
        {"key": "accounting",       "label": "المحاسبة",           "icon": "📒", "url": "/accounting"},
        {"key": "purchase-import",  "label": "استيراد فاتورة",    "icon": "📥", "url": "/purchase-import"},
        {"key": "reports",          "label": "التقارير",           "icon": "📈", "url": "/reports"},
        {"key": "settings",         "label": "الإعدادات",         "icon": "⚙️",  "url": "/settings"},
    ],
    "retail": [
        {"key": "pos",       "label": "نقاط البيع",    "icon": "🛒", "url": "/pos"},
        {"key": "inventory", "label": "المخزون",       "icon": "📦", "url": "/inventory"},
        {"key": "purchases", "label": "المشتريات",     "icon": "🛍️", "url": "/purchases"},
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
        {"key": "projects",   "label": "المشاريع",     "icon": "🏗️",  "url": "/projects"},
        {"key": "extracts",   "label": "المستخلصات",   "icon": "📄",  "url": "/extracts"},
        {"key": "equipment",  "label": "المعدات",      "icon": "🔧",  "url": "/equipment"},
        {"key": "invoices",   "label": "الفواتير",     "icon": "🧾",  "url": "/invoices"},
    ],
    "car_rental": [
        {"key": "fleet",      "label": "الأسطول",       "icon": "🚗", "url": "/fleet"},
        {"key": "contracts",  "label": "عقود الإيجار",  "icon": "📄", "url": "/contracts"},
        {"key": "maintenance","label": "الصيانة",       "icon": "🔧", "url": "/maintenance"},
        {"key": "invoices",   "label": "الفواتير",      "icon": "🧾", "url": "/invoices"},
    ],
    "medical": [
        {"key": "patients",      "label": "المرضى",       "icon": "🏥", "url": "/patients"},
        {"key": "appointments",  "label": "المواعيد",     "icon": "📅", "url": "/appointments"},
        {"key": "prescriptions", "label": "الوصفات",      "icon": "💊", "url": "/prescriptions"},
        {"key": "invoices",      "label": "الفواتير",     "icon": "🧾", "url": "/invoices"},
    ],
    "wholesale": [
        {"key": "pos",       "label": "الطلبات",       "icon": "🛒", "url": "/orders"},
        {"key": "inventory", "label": "المخزون",       "icon": "📦", "url": "/inventory"},
        {"key": "purchases", "label": "المشتريات",     "icon": "🛗️", "url": "/purchases"},
        {"key": "invoices",  "label": "الفواتير",      "icon": "🧾", "url": "/invoices"},
        {"key": "pricing",   "label": "قوائم الأسعار", "icon": "💰", "url": "/pricing"},
    ],
    "services": [
        {"key": "jobs",      "label": "أوامر العمل",   "icon": "📋", "url": "/jobs"},
        {"key": "invoices",  "label": "الفواتير",      "icon": "🧾", "url": "/invoices"},
        {"key": "contracts", "label": "العقود",        "icon": "📄", "url": "/contracts"},
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
}

# صفحات stub
STUB_PAGES = [
    "inventory", "invoices", "contacts",
    "barcode",
    "recipes", "projects", "extracts",
    "equipment", "fleet", "contracts", "maintenance",
    "patients", "appointments", "prescriptions",
    "jobs",
]

# مجلدات
UPLOAD_FOLDER = BASE_DIR / "uploads"
LOGO_FOLDER   = BASE_DIR / "static" / "logos"
ALLOWED_EXT   = {"pdf", "png", "jpg", "jpeg", "webp"}
ALLOWED_LOGO_EXT = {"png", "jpg", "jpeg", "webp"}
