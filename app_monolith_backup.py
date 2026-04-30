"""
app.py — تطبيق Flask الرئيسي
نظام المحاسبة SaaS — Backend مع Auth + Onboarding + Dynamic UI
"""

import os
try:
    import bcrypt as _bcrypt
    _BCRYPT_AVAILABLE = True
except ImportError:
    _bcrypt = None
    _BCRYPT_AVAILABLE = False
import hashlib
import secrets
import sqlite3
import json
import re
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, jsonify, flash, g
)

# ─── إعداد التطبيق ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DB_PATH  = BASE_DIR / "database" / "accounting.db"

# ─── SECRET_KEY ثابت — يُحفظ في ملف محلي إن لم يُوجد بـ env ──────────────────
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

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = _load_secret_key()

# ─── إعدادات الأمان ───────────────────────────────────────────────────────────
app.config.update(
    MAX_CONTENT_LENGTH         = 10 * 1024 * 1024,   # 10 MB حد أقصى للرفع
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8),
    SESSION_COOKIE_HTTPONLY    = True,
    SESSION_COOKIE_SAMESITE    = "Lax",
    # SESSION_COOKIE_SECURE = True,  # فعّل عند تشغيل HTTPS
)

# ─── Rate limiting بسيط في الذاكرة للحماية من Brute Force ───────────────────
_login_attempts: dict = {}   # {ip: [timestamp, ...]}
_MAX_ATTEMPTS   = 10         # محاولات
_WINDOW_SECONDS = 300        # 5 دقائق


# ─── أنواع الأنشطة — نظام هرمي ثلاثي المستويات ───────────────────────────────
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

# دالة مساعدة: تُحوّل الكود التفصيلي إلى مفتاح السيدبار
def get_sidebar_key(industry_type: str) -> str:
    if industry_type.startswith("retail_"):    return "retail"
    if industry_type.startswith("wholesale_"): return "wholesale"
    if industry_type.startswith("food_"):      return "restaurant"
    if industry_type in ("restaurant", "cafe", "coffeeshop"): return "restaurant"
    return industry_type

# القائمة الجانبية الديناميكية حسب نوع النشاط
SIDEBAR_CONFIG = {
    # عناصر ثابتة لجميع الأنشطة
    "_common": [
        {"key": "dashboard",        "label": "لوحة التحكم",       "icon": "🏠", "url": "/dashboard"},
        {"key": "analytics",        "label": "تحليل المبيعات",    "icon": "📊", "url": "/analytics"},
        {"key": "contacts",         "label": "العملاء والموردين",  "icon": "👥", "url": "/contacts"},
        {"key": "accounting",       "label": "المحاسبة",           "icon": "📒", "url": "/accounting"},
        {"key": "purchase-import",  "label": "استيراد فاتورة",    "icon": "📥", "url": "/purchase-import"},
        {"key": "reports",          "label": "التقارير",           "icon": "📈", "url": "/reports"},
        {"key": "settings",         "label": "الإعدادات",         "icon": "⚙️",  "url": "/settings"},
    ],
    # عناصر خاصة بكل نشاط
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
# كافيه ومقهى وتقديم الطعام يرثان سيدبار المطعم
SIDEBAR_CONFIG["cafe"]          = SIDEBAR_CONFIG["restaurant"]
SIDEBAR_CONFIG["coffeeshop"]    = SIDEBAR_CONFIG["restaurant"]
SIDEBAR_CONFIG["food_restaurant"]= SIDEBAR_CONFIG["restaurant"]
SIDEBAR_CONFIG["food_cafe"]     = SIDEBAR_CONFIG["restaurant"]
SIDEBAR_CONFIG["food_coffeeshop"]= SIDEBAR_CONFIG["restaurant"]


# ─── مساعدات قاعدة البيانات ───────────────────────────────────────────────────
def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def hash_password(password: str) -> str:
    """bcrypt إن كان متوفراً (أفضل)، وإلا SHA-256+salt."""
    if _BCRYPT_AVAILABLE:
        hashed = _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt(rounds=12))
        return hashed.decode("utf-8")
    # fallback: SHA-256 + salt
    salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{h}"

def check_password(stored: str, password: str) -> bool:
    """يدعم bcrypt الجديد + SHA-256+salt القديم."""
    try:
        if stored.startswith("$2") and _BCRYPT_AVAILABLE:
            return _bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
        if ":" in stored:
            salt, h = stored.split(":", 1)
            return hashlib.sha256(f"{salt}{password}".encode()).hexdigest() == h
        return False
    except Exception:
        return False


# ─── CSRF Protection — توليد والتحقق من الـ token ──────────────────────────
def generate_csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]

def validate_csrf() -> bool:
    """يتحقق من CSRF token في كل طلب POST من المتصفح (ليس JSON API)."""
    token_session = session.get("csrf_token")
    token_form    = (request.form.get("csrf_token")
                     or request.headers.get("X-CSRF-Token"))
    if not token_session or not token_form:
        return False
    return secrets.compare_digest(token_session, token_form)

def csrf_protect():
    """يستدعَى في أي route يقبل POST بيانات form. يُعيد None إن كان آمناً."""
    if request.method == "POST" and not request.is_json:
        if not validate_csrf():
            flash("طلب غير صالح — يرجى إعادة المحاولة", "error")
            return redirect(request.referrer or url_for("dashboard"))
    return None


# ─── ZATCA QR — المرحلة الأولى (TLV Base64) ────────────────────────────────
def zatca_qr_b64(seller: str, vat_number: str, timestamp: str,
                  total: float, vat: float) -> str:
    """
    يولّد بيانات QR Code المتوافق مع ZATCA المرحلة الأولى.
    الترميز: TLV (Tag–Length–Value) مُشفَّر Base64.
    Tags:
      1 = اسم البائع   2 = الرقم الضريبي
      3 = وقت الفاتورة  4 = الإجمالي شامل الضريبة
      5 = قيمة ضريبة القيمة المضافة
    """
    def tlv(tag: int, value: str) -> bytes:
        encoded = value.encode("utf-8")
        return bytes([tag, len(encoded)]) + encoded

    payload = (
        tlv(1, seller or "غير محدد") +
        tlv(2, vat_number or "300000000000003") +
        tlv(3, timestamp) +
        tlv(4, f"{total:.2f}") +
        tlv(5, f"{vat:.2f}")
    )
    return base64.b64encode(payload).decode("ascii")


def zatca_xml(inv: dict, seller: str, vat_number: str) -> str:
    """يولّد XML مبسَّط متوافق مع UBL 2.1 لـ ZATCA المرحلة الأولى"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:UBLVersionID>2.1</cbc:UBLVersionID>
  <cbc:ProfileID>reporting:1.0</cbc:ProfileID>
  <cbc:ID>{inv.get('invoice_number','')}</cbc:ID>
  <cbc:IssueDate>{str(inv.get('invoice_date',''))[:10]}</cbc:IssueDate>
  <cbc:IssueTime>{str(inv.get('created_at',''))[-8:] or '00:00:00'}</cbc:IssueTime>
  <cbc:InvoiceTypeCode name="0200000">388</cbc:InvoiceTypeCode>
  <cbc:DocumentCurrencyCode>SAR</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyName><cbc:Name>{seller}</cbc:Name></cac:PartyName>
      <cac:PartyTaxScheme>
        <cbc:CompanyID>{vat_number or '300000000000003'}</cbc:CompanyID>
        <cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme>
      </cac:PartyTaxScheme>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:LegalMonetaryTotal>
    <cbc:LineExtensionAmount currencyID="SAR">{inv.get('subtotal',0):.2f}</cbc:LineExtensionAmount>
    <cbc:TaxExclusiveAmount currencyID="SAR">{inv.get('subtotal',0):.2f}</cbc:TaxExclusiveAmount>
    <cbc:TaxInclusiveAmount currencyID="SAR">{inv.get('total',0):.2f}</cbc:TaxInclusiveAmount>
    <cbc:PayableAmount currencyID="SAR">{inv.get('total',0):.2f}</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
  <cac:TaxTotal>
    <cbc:TaxAmount currencyID="SAR">{inv.get('tax_amount',0):.2f}</cbc:TaxAmount>
  </cac:TaxTotal>
</Invoice>"""


# ─── مساعدات محاسبية ──────────────────────────────────────────────────────────

def get_account_id(db: sqlite3.Connection, business_id: int, code: str):
    """إرجاع id الحساب بالكود — أو None إذا لم يوجد"""
    row = db.execute(
        "SELECT id FROM accounts WHERE business_id=? AND code=?",
        (business_id, code)
    ).fetchone()
    return row["id"] if row else None


def next_invoice_number(db: sqlite3.Connection, business_id: int) -> str:
    """توليد رقم فاتورة مبيعات تسلسلي"""
    prefix_row = db.execute(
        "SELECT value FROM settings WHERE business_id=? AND key='invoice_prefix_sale'",
        (business_id,)
    ).fetchone()
    prefix = prefix_row["value"] if prefix_row else "INV"
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM invoices WHERE business_id=? AND invoice_type='sale'",
        (business_id,)
    ).fetchone()
    seq = (row["cnt"] or 0) + 1
    return f"{prefix}-{seq:05d}"


def next_entry_number(db: sqlite3.Connection, business_id: int) -> str:
    """توليد رقم قيد يومية تسلسلي"""
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM journal_entries WHERE business_id=?",
        (business_id,)
    ).fetchone()
    seq = (row["cnt"] or 0) + 1
    return f"JE-{seq:06d}"


def seed_business_accounts(db: sqlite3.Connection, business_id: int):
    """إنشاء شجرة حسابات افتراضية + أدوار النظام الثلاثة لمنشأة جديدة (idempotent)"""
    # ─ أدوار النظام ─────────────────────────────────────
    system_roles = [
        ("مدير",       json.dumps({"all": True}, ensure_ascii=False),           "owner"),
        ("مدير فرع",  json.dumps({"sales":True,"pos":True,"reports":True,
                                   "accounting":True,"purchases":True,
                                   "warehouse":True,"analytics":True,
                                   "contacts":True,"settings":False},
                                   ensure_ascii=False),                          "manager"),
        ("كاشير",     json.dumps({"pos":True,"sales":True},
                                   ensure_ascii=False),                          "cashier"),
        ("محاسب",     json.dumps({"accounting":True,"reports":True,"sales":True,
                                   "purchases":True,"analytics":True,
                                   "contacts":True}, ensure_ascii=False),        "manager"),
        ("أمين مخزن", json.dumps({"warehouse":True,"purchases":True,
                                   "inventory":True}, ensure_ascii=False),       "manager"),
    ]
    for name, perms, _lvl in system_roles:
        db.execute(
            """INSERT OR IGNORE INTO roles (business_id, name, permissions, is_system)
               VALUES (?,?,?,1)""",
            (business_id, name, perms)
        )
    default_rows = [
        ('1',    'الأصول',                'Assets',              'asset',     'debit',  1),
        ('11',   'الأصول المتداولة',      'Current Assets',      'asset',     'debit',  1),
        ('1101', 'الصندوق',              'Cash',                'asset',     'debit',  0),
        ('1102', 'البنك',                'Bank',                'asset',     'debit',  0),
        ('1103', 'ذمم مدينة - عملاء',    'Accounts Receivable', 'asset',     'debit',  0),
        ('1104', 'مخزون البضاعة',         'Inventory',           'asset',     'debit',  0),
        ('2',    'الخصوم',               'Liabilities',         'liability', 'credit', 1),
        ('21',   'الخصوم المتداولة',      'Current Liabilities', 'liability', 'credit', 1),
        ('2101', 'ذمم دائنة - موردون',   'Accounts Payable',    'liability', 'credit', 0),
        ('2102', 'ضريبة القيمة المضافة', 'VAT Payable',         'liability', 'credit', 0),
        ('3',    'حقوق الملكية',          'Equity',              'equity',    'credit', 1),
        ('3101', 'رأس المال',             'Capital',             'equity',    'credit', 0),
        ('4',    'الإيرادات',            'Revenue',             'revenue',   'credit', 1),
        ('4101', 'إيرادات المبيعات',      'Sales Revenue',       'revenue',   'credit', 0),
        ('4102', 'مردودات المبيعات',      'Sales Returns',       'revenue',   'debit',  0),
        ('5',    'المصاريف',             'Expenses',            'expense',   'debit',  1),
        ('5101', 'تكلفة البضاعة المباعة','COGS',                'expense',   'debit',  0),
    ]
    for r in default_rows:
        db.execute(
            """INSERT OR IGNORE INTO accounts
               (business_id, code, name, name_en, account_type, account_nature, is_header)
               VALUES (?,?,?,?,?,?,?)""",
            (business_id, *r)
        )
    db.execute(
        "INSERT OR IGNORE INTO tax_settings (business_id, name, rate, applies_to) VALUES (?,?,?,?)",
        (business_id, 'بدون ضريبة', 0, 'all')
    )
    db.execute(
        "INSERT OR IGNORE INTO settings (business_id, key, value) VALUES (?,?,?)",
        (business_id, 'invoice_prefix_sale', 'INV')
    )


# ─── خريطة الصلاحيات لكل Route ───────────────────────────────────────────────
# مفتاح الصلاحية → مجموعة routes التي تتطلبها
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
# الصلاحية الواحدة → عدد الروابط في السيدبار التي تحتاجها
SIDEBAR_PERM = {
    "dashboard":       None,          # متاح للجميع
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

# ─── دالة مساعدة: هل المستخدم يملك صلاحية معينة؟ ────────────────────────────
def user_has_perm(perm_key: str) -> bool:
    """يرجع True إذا كان المستخدم الحالي يملك الصلاحية المطلوبة."""
    if not g.user:
        return False
    try:
        perms = json.loads(g.user["permissions"] or "{}")
    except Exception:
        perms = {}
    return bool(perms.get("all") or perms.get(perm_key))

# ─── ديكوراتور: تتطلب تسجيل دخول ────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth_login"))
        return f(*args, **kwargs)
    return decorated

def onboarding_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth_login"))
        if not session.get("business_id"):
            return redirect(url_for("onboarding"))
        return f(*args, **kwargs)
    return decorated

def require_perm(perm_key: str):
    """ديكوراتور: يحجب الوصول إن لم تكن للمستخدم الصلاحية المطلوبة."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("auth_login"))
            if not session.get("business_id"):
                return redirect(url_for("onboarding"))
            if not user_has_perm(perm_key):
                flash("ليس لديك صلاحية للوصول لهذه الصفحة", "error")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return decorated
    return decorator


# ─── حقن بيانات المستخدم في كل request ───────────────────────────────────────
@app.before_request
def load_user():
    g.user    = None
    g.business = None
    g.sidebar_items = []
    g.user_perms = {}

    user_id = session.get("user_id")
    if user_id:
        db = get_db()
        g.user = db.execute(
            """SELECT u.*, r.name as role_name, r.permissions
               FROM users u
               LEFT JOIN roles r ON r.id = u.role_id
               WHERE u.id = ?""",
            (user_id,)
        ).fetchone()

        if g.user:
            try:
                g.user_perms = json.loads(g.user["permissions"] or "{}")
            except Exception:
                g.user_perms = {}

        biz_id = session.get("business_id")
        if biz_id:
            g.business = db.execute(
                "SELECT * FROM businesses WHERE id = ?", (biz_id,)
            ).fetchone()

            if g.business:
                itype = g.business["industry_type"] or "retail_other"
                sidebar_key = get_sidebar_key(itype)
                common  = SIDEBAR_CONFIG.get("_common", [])
                dynamic = SIDEBAR_CONFIG.get(sidebar_key, SIDEBAR_CONFIG.get("retail", []))
                all_items = common + dynamic

                # ─ فلترة السيدبار بناءً على صلاحيات المستخدم ─
                has_all = bool(g.user_perms.get("all"))
                filtered = []
                for item in all_items:
                    perm_needed = SIDEBAR_PERM.get(item["key"])
                    if perm_needed is None or has_all or g.user_perms.get(perm_needed):
                        filtered.append(item)

                # الإعدادات تبقى آخراً وتُظهر للمدير فقط
                settings_item = [x for x in filtered if x["key"] == "settings"]
                rest_items    = [x for x in filtered if x["key"] != "settings"]
                g.sidebar_items = rest_items + settings_item


# ─── Context processor لتمرير البيانات للقوالب ───────────────────────────────
@app.context_processor
def inject_globals():
    return {
        "current_user":    g.user,
        "current_business": g.business,
        "sidebar_items":   g.sidebar_items,
        "user_perms":      g.user_perms,
        "industry_types":  INDUSTRY_TYPES,
        "request":         request,
        "now_date":        datetime.now().strftime("%Y-%m-%d"),
        "csrf_token":      generate_csrf_token(),
    }


# ─── Security Headers على كل استجابة ──────────────────────────────────────────
@app.after_request
def add_security_headers(response):
    response.headers["X-Frame-Options"]        = "SAMEORIGIN"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"]       = "1; mode=block"
    response.headers["Referrer-Policy"]        = "strict-origin-when-cross-origin"
    # CSP بسيط — يسمح بالـ scripts/styles من نفس المصدر + CDN المستخدمة
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' cdn.jsdelivr.net unpkg.com; "
        "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net fonts.googleapis.com; "
        "font-src 'self' fonts.gstatic.com data:; "
        "img-src 'self' data: blob:; "
        "connect-src 'self';"
    )
    return response


# ════════════════════════════════════════════════════════════════════════════════
# AUTH ROUTES
# ════════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    if session.get("user_id") and session.get("business_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("auth_login"))


@app.route("/auth/login", methods=["GET", "POST"])
def auth_login():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        # ─── CSRF ────────────────────────────────────────────────────────────
        guard = csrf_protect()
        if guard:
            return guard
        # ─── Rate Limiting: 10 محاولات / 5 دقائق لكل IP ──────────────────────
        ip  = request.remote_addr or "unknown"
        now = datetime.now().timestamp()
        _login_attempts.setdefault(ip, [])
        # تنظيف المحاولات القديمة
        _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < _WINDOW_SECONDS]
        if len(_login_attempts[ip]) >= _MAX_ATTEMPTS:
            flash("تم تجاوز الحد المسموح به من المحاولات. حاول بعد 5 دقائق.", "error")
            return render_template("auth/login.html")

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("يرجى إدخال اسم المستخدم وكلمة المرور", "error")
            return render_template("auth/login.html")

        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username = ? AND is_active = 1",
            (username,)
        ).fetchone()

        if not user or not check_password(user["password_hash"], password):
            _login_attempts[ip].append(now)   # سجّل المحاولة الفاشلة
            flash("اسم المستخدم أو كلمة المرور غير صحيحة", "error")
            return render_template("auth/login.html")

        # نجح الدخول — امسح سجل المحاولات
        _login_attempts.pop(ip, None)

        session.clear()
        session["user_id"]     = user["id"]
        session["business_id"] = user["business_id"]
        session.permanent      = True

        db.execute("UPDATE users SET last_login=datetime('now') WHERE id=?", (user["id"],))
        db.commit()

        return redirect(url_for("dashboard"))

    return render_template("auth/login.html")


@app.route("/auth/register", methods=["GET", "POST"])
def auth_register():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard
        username  = request.form.get("username", "").strip()

        errors = []
        if not username:   errors.append("اسم المستخدم مطلوب")
        if not full_name:  errors.append("الاسم الكامل مطلوب")
        if not password:   errors.append("كلمة المرور مطلوبة")
        if len(password) < 6:  errors.append("كلمة المرور يجب أن تكون 6 أحرف على الأقل")
        if password != confirm: errors.append("كلمتا المرور غير متطابقتين")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("auth/register.html")

        db = get_db()
        existing = db.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            flash("اسم المستخدم مستخدم بالفعل", "error")
            return render_template("auth/register.html")

        # إنشاء منشأة مؤقتة (سيتم تعبئتها في Onboarding)
        db.execute(
            "INSERT INTO businesses (name, is_active) VALUES (?, 0)",
            (f"منشأة {username}",)
        )
        biz_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # دور مدير افتراضي
        db.execute(
            "INSERT INTO roles (business_id, name, permissions, is_system) VALUES (?,?,?,1)",
            (biz_id, "مدير", '{"all":true}')
        )
        role_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        db.execute(
            """INSERT INTO users
                (business_id, role_id, username, full_name, email, password_hash)
               VALUES (?,?,?,?,?,?)""",
            (biz_id, role_id, username, full_name, email, hash_password(password))
        )
        user_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()

        session.clear()
        session["user_id"]     = user_id
        session["business_id"] = biz_id
        session["needs_onboarding"] = True

        return redirect(url_for("onboarding"))

    return render_template("auth/register.html")


@app.route("/auth/forgot-password", methods=["GET", "POST"])
def auth_forgot_password():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    step = request.form.get("step", "1")

    if request.method == "POST":
        db = get_db()

        # ── الخطوة الأولى: التحقق من الهوية ──────────────────────────────
        if step == "1":
            username = request.form.get("username", "").strip()
            email    = request.form.get("email", "").strip().lower()

            if not username or not email:
                flash("يرجى إدخال اسم المستخدم والبريد الإلكتروني", "error")
                return render_template("auth/forgot_password.html", step=1)

            user = db.execute(
                "SELECT id FROM users WHERE username = ? AND LOWER(email) = ? AND is_active = 1",
                (username, email)
            ).fetchone()

            if not user:
                flash("لم يتم العثور على حساب بهذه البيانات", "error")
                return render_template("auth/forgot_password.html", step=1)

            # تخزين مؤقت في الجلسة للخطوة الثانية
            session["reset_uid"] = user["id"]
            return render_template("auth/forgot_password.html", step=2)

        # ── الخطوة الثانية: تعيين كلمة المرور الجديدة ──────────────────
        elif step == "2":
            uid      = session.pop("reset_uid", None)
            new_pass = request.form.get("new_password", "")
            confirm  = request.form.get("confirm_password", "")

            if not uid:
                flash("انتهت صلاحية الجلسة، يرجى المحاولة مجدداً", "error")
                return redirect(url_for("auth_forgot_password"))

            if len(new_pass) < 6:
                session["reset_uid"] = uid
                flash("كلمة المرور يجب أن تكون 6 أحرف على الأقل", "error")
                return render_template("auth/forgot_password.html", step=2)

            if new_pass != confirm:
                session["reset_uid"] = uid
                flash("كلمتا المرور غير متطابقتين", "error")
                return render_template("auth/forgot_password.html", step=2)

            db.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (hash_password(new_pass), uid)
            )
            db.commit()
            flash("تم تغيير كلمة المرور بنجاح، يمكنك تسجيل الدخول الآن", "success")
            return redirect(url_for("auth_login"))

    return render_template("auth/forgot_password.html", step=1)


@app.route("/auth/logout")
def auth_logout():
    session.clear()
    flash("تم تسجيل الخروج بنجاح", "info")
    return redirect(url_for("auth_login"))


# ════════════════════════════════════════════════════════════════════════════════
# ONBOARDING
# ════════════════════════════════════════════════════════════════════════════════

@app.route("/onboarding", methods=["GET", "POST"])
@login_required
def onboarding():
    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard
        biz_name      = request.form.get("business_name", "").strip()
        tax_number    = request.form.get("tax_number", "").strip()
        city          = request.form.get("city", "").strip()

        if not biz_name:
            flash("اسم المنشأة مطلوب", "error")
            return render_template("onboarding.html")

        valid_types = [t[0] for t in INDUSTRY_TYPES]
        if industry_type not in valid_types:
            industry_type = "retail_other"

        db  = get_db()
        biz_id = session["business_id"]

        db.execute(
            """UPDATE businesses
               SET name=?, industry_type=?, tax_number=?, city=?,
                   is_active=1, updated_at=datetime('now')
               WHERE id=?""",
            (biz_name, industry_type, tax_number, city, biz_id)
        )

        # بيانات أساسية: مستودع + شجرة حسابات + إعدادات
        db.execute(
            "INSERT OR IGNORE INTO warehouses (business_id, name, is_default) VALUES (?,?,1)",
            (biz_id, "المستودع الرئيسي")
        )
        seed_business_accounts(db, biz_id)
        db.execute(
            "INSERT OR IGNORE INTO settings (business_id, key, value) VALUES (?,?,?)",
            (biz_id, "onboarding_complete", "1")
        )
        db.commit()

        session.pop("needs_onboarding", None)
        flash(f"مرحباً! تم إنشاء منشأة «{biz_name}» بنجاح ✓", "success")
        return redirect(url_for("dashboard"))

    return render_template("onboarding.html")


# ════════════════════════════════════════════════════════════════════════════════
# MAIN PAGES
# ════════════════════════════════════════════════════════════════════════════════

@app.route("/dashboard")
@onboarding_required
def dashboard():
    db     = get_db()
    biz_id = session["business_id"]

    stats = {
        "products":  db.execute("SELECT COUNT(*) FROM products WHERE business_id=?", (biz_id,)).fetchone()[0],
        "contacts":  db.execute("SELECT COUNT(*) FROM contacts  WHERE business_id=?", (biz_id,)).fetchone()[0],
        "journals":  db.execute("SELECT COUNT(*) FROM journal_entries WHERE business_id=?", (biz_id,)).fetchone()[0],
        "accounts":  db.execute("SELECT COUNT(*) FROM accounts  WHERE business_id=?", (biz_id,)).fetchone()[0],
    }

    since7  = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    since30 = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    # ── مبيعات آخر 7 أيام (يومي) ────────────────────────
    daily_sales = db.execute("""
        SELECT DATE(created_at) AS day, COALESCE(SUM(total),0) AS rev
        FROM invoices
        WHERE business_id=? AND invoice_type IN ('sale','table')
          AND status='paid' AND DATE(created_at) >= ?
        GROUP BY DATE(created_at) ORDER BY day
    """, (biz_id, since7)).fetchall()

    # ── أكثر 5 منتجات مبيعاً (30 يوم) ───────────────────
    top5 = db.execute("""
        SELECT il.description, SUM(il.quantity) AS qty
        FROM invoice_lines il
        JOIN invoices i ON i.id = il.invoice_id
        WHERE i.business_id=? AND i.invoice_type IN ('sale','table')
          AND i.status='paid' AND DATE(i.created_at) >= ?
        GROUP BY il.description ORDER BY qty DESC LIMIT 5
    """, (biz_id, since30)).fetchall()

    # ── مقارنة الإيرادات vs المصروفات (30 يوم) ───────────
    rev_exp = db.execute("""
        SELECT
          COALESCE(SUM(CASE WHEN invoice_type IN ('sale','table') AND status='paid' THEN total ELSE 0 END),0) AS revenue,
          COALESCE(SUM(CASE WHEN invoice_type='purchase'          AND status='paid' THEN total ELSE 0 END),0) AS expenses
        FROM invoices WHERE business_id=? AND DATE(created_at) >= ?
    """, (biz_id, since30)).fetchone()

    # ── آخر 5 قيود محاسبية ───────────────────────────────
    last_entries = db.execute("""
        SELECT je.entry_number, je.entry_date, je.description,
               COALESCE(SUM(CASE WHEN jel.debit_amount>0 THEN jel.debit_amount ELSE 0 END),0) AS total_debit
        FROM journal_entries je
        LEFT JOIN journal_entry_lines jel ON jel.entry_id = je.id
        WHERE je.business_id=?
        GROUP BY je.id ORDER BY je.entry_date DESC, je.id DESC LIMIT 5
    """, (biz_id,)).fetchall()

    chart_daily = json.dumps({
        "labels": [r["day"]  for r in daily_sales],
        "values": [float(r["rev"]) for r in daily_sales],
    }, ensure_ascii=False)

    chart_top5 = json.dumps({
        "labels": [r["description"] for r in top5],
        "values": [float(r["qty"])   for r in top5],
    }, ensure_ascii=False)

    chart_revexp = json.dumps({
        "revenue":  float(rev_exp["revenue"]  if rev_exp else 0),
        "expenses": float(rev_exp["expenses"] if rev_exp else 0),
    }, ensure_ascii=False)

    # ── تنبيهات المخزون (للمدير والمالك فقط) ────────────
    stock_alerts = []
    if user_has_perm("reports") or user_has_perm("warehouse"):
        # المنتجات التي وصل مخزونها للحد الأدنى أو أقل
        stock_alerts = db.execute("""
            SELECT p.name AS product_name, p.barcode AS sku, p.min_stock,
                   COALESCE(SUM(s.quantity), 0) AS total_qty,
                   w.name AS warehouse_name
            FROM products p
            JOIN stock s ON s.product_id = p.id
            JOIN warehouses w ON w.id = s.warehouse_id
            WHERE p.business_id = ?
              AND p.min_stock > 0
              AND s.quantity <= p.min_stock
            GROUP BY p.id
            ORDER BY (COALESCE(SUM(s.quantity),0) - p.min_stock) ASC
            LIMIT 15
        """, (biz_id,)).fetchall()
        stock_alerts = [dict(r) for r in stock_alerts]

    return render_template(
        "dashboard.html",
        stats=stats,
        last_entries=[dict(r) for r in last_entries],
        chart_daily=chart_daily,
        chart_top5=chart_top5,
        chart_revexp=chart_revexp,
        stock_alerts=stock_alerts,
    )


# ════════════════════════════════════════════════════════════════════════════════
# ANALYTICS — تحليل المبيعات
# ════════════════════════════════════════════════════════════════════════════════

@app.route("/analytics")
@require_perm("analytics")
def analytics():
    db     = get_db()
    biz_id = session["business_id"]
    period = request.args.get("period", "30")  # 7 | 30 | 90 | 365
    try:
        days = int(period)
    except ValueError:
        days = 30

    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    # ── إجماليات المبيعات ───────────────────────────
    totals = db.execute("""
        SELECT
          COALESCE(SUM(CASE WHEN invoice_type IN ('sale','table') AND status='paid' THEN total ELSE 0 END),0) AS revenue,
          COALESCE(SUM(CASE WHEN invoice_type='purchase'                            AND status='paid' THEN total ELSE 0 END),0) AS purchases,
          COUNT(DISTINCT CASE WHEN invoice_type IN ('sale','table') AND status='paid' THEN id END) AS invoices_count
        FROM invoices
        WHERE business_id=? AND DATE(created_at) >= ?
    """, (biz_id, since)).fetchone()

    # ── أكثر المنتجات طلباً ─────────────────────────
    top_products = db.execute("""
        SELECT il.description,
               SUM(il.quantity) AS total_qty,
               SUM(il.total)    AS total_rev
        FROM invoice_lines il
        JOIN invoices i ON i.id = il.invoice_id
        WHERE i.business_id=?
          AND i.invoice_type IN ('sale','table')
          AND i.status = 'paid'
          AND DATE(i.created_at) >= ?
        GROUP BY il.description
        ORDER BY total_qty DESC
        LIMIT 10
    """, (biz_id, since)).fetchall()

    # ── مبيعات يومية (chart) ─────────────────────
    daily = db.execute("""
        SELECT DATE(created_at) AS day, SUM(total) AS revenue
        FROM invoices
        WHERE business_id=?
          AND invoice_type IN ('sale','table')
          AND status='paid'
          AND DATE(created_at) >= ?
        GROUP BY DATE(created_at)
        ORDER BY day ASC
    """, (biz_id, since)).fetchall()

    # ── مبيعات حسب الفئة ───────────────────────
    by_category = db.execute("""
        SELECT p.category_name, SUM(il.total) AS total_rev
        FROM invoice_lines il
        JOIN invoices i ON i.id = il.invoice_id
        JOIN products p ON p.name = il.description AND p.business_id = i.business_id
        WHERE i.business_id=?
          AND i.invoice_type IN ('sale','table')
          AND i.status = 'paid'
          AND DATE(i.created_at) >= ?
        GROUP BY p.category_name
        ORDER BY total_rev DESC
        LIMIT 8
    """, (biz_id, since)).fetchall()

    # ── تحويل ل_JSON لل_charts ────────────────────
    chart_daily = {
        "labels":   [r["day"]     for r in daily],
        "values":   [float(r["revenue"]) for r in daily],
    }
    chart_cat = {
        "labels":   [r["category_name"] or "غير محدد" for r in by_category],
        "values":   [float(r["total_rev"]) for r in by_category],
    }
    chart_top = {
        "labels":   [r["description"] for r in top_products],
        "values":   [float(r["total_qty"]) for r in top_products],
    }

    return render_template(
        "analytics.html",
        period=str(days),
        totals=dict(totals),
        top_products=[dict(r) for r in top_products],
        chart_daily=json.dumps(chart_daily, ensure_ascii=False),
        chart_cat=json.dumps(chart_cat, ensure_ascii=False),
        chart_top=json.dumps(chart_top, ensure_ascii=False),
    )


# ════════════════════════════════════════════════════════════════════════════════
# INVOICE UPLOAD — رفع فاتورة شراء (PDF / صورة) + مزامنة المخزون
# ════════════════════════════════════════════════════════════════════════════════

UPLOAD_FOLDER = BASE_DIR / "uploads"
UPLOAD_FOLDER.mkdir(exist_ok=True)
ALLOWED_EXT   = {"pdf", "png", "jpg", "jpeg", "webp"}


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def _extract_text_from_pdf(path: Path) -> str:
    """استخراج النص من PDF بدون مكتبات ثقيلة (fallback بسيط)"""
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except ImportError:
        pass
    # fallback: قراءة نص خام من الملف
    try:
        raw = path.read_bytes()
        text = raw.decode("latin-1", errors="ignore")
        # استخراج أي نصوص بين BT ... ET (PDF streams)
        parts = re.findall(r"BT(.+?)ET", text, re.DOTALL)
        return " ".join(parts)
    except Exception:
        return ""


def _extract_text_from_image(path: Path) -> str:
    """OCR للصورة باستخدام pytesseract إذا متوفر"""
    try:
        import pytesseract
        from PIL import Image
        img  = Image.open(path)
        return pytesseract.image_to_string(img, lang="ara+eng")
    except ImportError:
        return ""
    except Exception:
        return ""


def _parse_invoice_lines(text: str, products: list) -> list:
    """
    يحاول مطابقة أسطر النص مع المنتجات المعروفة.
    يُرجع قائمة من dicts: {product_id, name, qty, price}
    """
    lines    = []
    prod_map = {p["name"].strip(): p for p in products}

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # ابحث عن كميات وأسعار: رقم، فراغ، وصف، رقم
        nums = re.findall(r"[\d.,]+", line)
        # مطابقة اسم المنتج
        matched_prod = None
        for prod_name, prod in prod_map.items():
            if prod_name in line or prod_name.split()[0] in line:
                matched_prod = prod
                break
        if matched_prod and len(nums) >= 1:
            try:
                qty   = float(nums[0].replace(",", "")) if nums else 1.0
                price = float(nums[-1].replace(",", "")) if len(nums) > 1 else float(matched_prod["purchase_price"] or 0)
                lines.append({
                    "product_id": matched_prod["id"],
                    "name":       matched_prod["name"],
                    "qty":        qty,
                    "price":      price,
                })
            except (ValueError, KeyError):
                continue
    return lines


@app.route("/purchase-import")
@require_perm("purchases")
def purchase_import():
    """صفحة رفع فاتورة الشراء"""
    return render_template("purchase_import.html")


@app.route("/api/purchase-import/upload", methods=["POST"])
@onboarding_required
def api_purchase_import_upload():
    """رفع الملف (PDF/صورة) واستخراج البنود"""
    biz_id = session["business_id"]
    db     = get_db()

    if "file" not in request.files:
        return jsonify({"success": False, "error": "لم يتم اختيار ملف"}), 400

    f = request.files["file"]
    if not f.filename or not _allowed_file(f.filename):
        return jsonify({"success": False, "error": "نوع الملف غير مدعوم (PDF, PNG, JPG)"}), 400

    # حفظ الملف بشكل آمن
    ext      = f.filename.rsplit(".", 1)[1].lower()
    safe     = f"{biz_id}_{secrets.token_hex(8)}.{ext}"
    save_path = UPLOAD_FOLDER / safe
    f.save(save_path)

    # استخراج النص
    if ext == "pdf":
        text = _extract_text_from_pdf(save_path)
    else:
        text = _extract_text_from_image(save_path)

    # جلب منتجات المنشأة
    products = [
        dict(r) for r in db.execute(
            "SELECT id, name, purchase_price FROM products WHERE business_id=? AND is_active=1",
            (biz_id,)
        ).fetchall()
    ]

    # مطابقة البنود
    lines = _parse_invoice_lines(text, products)

    return jsonify({
        "success":   True,
        "file_ref":  safe,
        "text_len":  len(text),
        "lines":     lines,
        "raw_text":  text[:800],  # أول 800 حرف للمعاينة
    })


@app.route("/api/purchase-import/confirm", methods=["POST"])
@onboarding_required
def api_purchase_import_confirm():
    """
    تأكيد البنود المُراجعة وإنشاء فاتورة شراء + تحديث المخزون
    payload: { supplier_name, lines: [{product_id, qty, price}] }
    """
    data     = request.get_json(force=True) or {}
    biz_id   = session["business_id"]
    db       = get_db()

    supplier = (data.get("supplier_name") or "موردغير محدد").strip()
    lines    = data.get("lines", [])

    if not lines:
        return jsonify({"success": False, "error": "لا توجد بنود"}), 400

    # ─ رقم الفاتورة
    inv_num = next_invoice_number(db, biz_id).replace("INV", "PUR")

    # ─ إنشاء الفاتورة
    subtotal = sum(float(l.get("qty", 0)) * float(l.get("price", 0)) for l in lines)
    db.execute(
        """INSERT INTO invoices
           (business_id, invoice_type, invoice_number, party_name,
            subtotal, tax_amount, total, status, created_at)
           VALUES (?,?,?,?,?,0,?,?,?)""",
        (biz_id, "purchase", inv_num, supplier,
         subtotal, subtotal, "paid",
         datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    inv_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    # ─ البنود + تحديث المخزون
    wh = db.execute(
        "SELECT id FROM warehouses WHERE business_id=? LIMIT 1", (biz_id,)
    ).fetchone()
    wh_id = wh["id"] if wh else None

    for idx, line in enumerate(lines, 1):
        pid   = line.get("product_id")
        qty   = float(line.get("qty", 0))
        price = float(line.get("price", 0))
        name  = line.get("name", "")

        if not pid or qty <= 0:
            continue

        # verify ownership
        prod = db.execute(
            "SELECT id, name FROM products WHERE id=? AND business_id=?",
            (int(pid), biz_id)
        ).fetchone()
        if not prod:
            continue

        db.execute(
            """INSERT INTO invoice_lines
               (invoice_id, product_id, description, quantity, unit_price, total, line_order)
               VALUES (?,?,?,?,?,?,?)""",
            (inv_id, pid, prod["name"], qty, price, qty * price, idx)
        )

        # مزامنة المخزون
        if wh_id:
            existing = db.execute(
                "SELECT id, quantity FROM stock WHERE product_id=? AND warehouse_id=?",
                (pid, wh_id)
            ).fetchone()
            if existing:
                db.execute(
                    "UPDATE stock SET quantity = quantity + ? WHERE id=?",
                    (qty, existing["id"])
                )
            else:
                db.execute(
                    "INSERT INTO stock (business_id, product_id, warehouse_id, quantity) VALUES (?,?,?,?)",
                    (biz_id, pid, wh_id, qty)
                )
            db.execute(
                """INSERT INTO stock_movements
                   (business_id, product_id, warehouse_id, movement_type, quantity, reference_id, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (biz_id, pid, wh_id, "purchase", qty, inv_id,
                 datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )

        # تحديث سعر الشراء في المنتج
        db.execute(
            "UPDATE products SET purchase_price=? WHERE id=? AND business_id=?",
            (price, pid, biz_id)
        )

    db.commit()
    return jsonify({
        "success":       True,
        "invoice_id":    inv_id,
        "invoice_number": inv_num,
        "message":       f"✓ تم إنشاء فاتورة {inv_num} وتحديث المخزون",
    })


# ════════════════════════════════════════════════════════════════════════════════
# ZATCA — فوترة إلكترونية
# ════════════════════════════════════════════════════════════════════════════════

@app.route("/api/invoice/<int:inv_id>/zatca-qr")
@onboarding_required
def api_zatca_qr(inv_id: int):
    """يعيد بيانات QR ZATCA المرحلة الأولى (TLV Base64)"""
    biz_id = session["business_id"]
    db     = get_db()

    inv = db.execute(
        "SELECT * FROM invoices WHERE id=? AND business_id=?", (inv_id, biz_id)
    ).fetchone()
    if not inv:
        return jsonify({"success": False, "error": "الفاتورة غير موجودة"}), 404

    biz = g.business
    seller     = biz["name"] if biz else "غير محدد"
    vat_number = biz["tax_number"] if biz else ""
    ts         = str(inv["created_at"] or inv["invoice_date"] or datetime.now().isoformat())
    if len(ts) == 10:
        ts += "T00:00:00Z"

    total = float(inv["total"]      or 0)
    vat   = float(inv["tax_amount"] or 0)

    qr_data = zatca_qr_b64(seller, vat_number, ts, total, vat)

    return jsonify({
        "success":    True,
        "qr_data":    qr_data,
        "seller":     seller,
        "vat_number": vat_number,
        "timestamp":  ts[:19].replace("T", " "),
        "total":      total,
        "vat":        vat,
    })


@app.route("/api/invoice/<int:inv_id>/zatca-xml")
@onboarding_required
def api_zatca_xml(inv_id: int):
    """يُنزّل ملف XML متوافق مع ZATCA UBL 2.1"""
    biz_id = session["business_id"]
    db     = get_db()

    inv = db.execute(
        "SELECT * FROM invoices WHERE id=? AND business_id=?", (inv_id, biz_id)
    ).fetchone()
    if not inv:
        return jsonify({"success": False, "error": "الفاتورة غير موجودة"}), 404

    biz        = g.business
    seller     = biz["name"]       if biz else "غير محدد"
    vat_number = biz["tax_number"] if biz else ""

    xml_content = zatca_xml(dict(inv), seller, vat_number)
    inv_num     = inv["invoice_number"] or f"INV-{inv_id}"

    from flask import Response
    return Response(
        xml_content,
        mimetype="application/xml",
        headers={"Content-Disposition": f"attachment; filename=ZATCA_{inv_num}.xml"}
    )


# ════════════════════════════════════════════════════════════════════════════════
# OFFLINE PAGE
# ════════════════════════════════════════════════════════════════════════════════

@app.route("/offline")
def offline():
    return render_template("offline.html")


# تحميل ملف service worker من /static/sw.js
@app.route("/sw.js")
def service_worker():
    from flask import send_from_directory
    resp = send_from_directory(app.static_folder, "sw.js")
    resp.headers["Content-Type"]  = "application/javascript"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


# صفحات stub (placeholder) تُبنى لاحقاً حسب النشاط
STUB_PAGES = [
    "inventory", "invoices", "contacts",
    "barcode",
    "recipes", "projects", "extracts",
    "equipment", "fleet", "contracts", "maintenance",
    "patients", "appointments", "prescriptions",
    "jobs",
]

@app.route("/<page>")
@onboarding_required
def stub_page(page):
    if page not in STUB_PAGES:
        return render_template("404.html"), 404
    return render_template("stub_page.html", page_name=page)


# ════════════════════════════════════════════════════════════════════════════════
# SETTINGS — إعدادات المنشأة
# ════════════════════════════════════════════════════════════════════════════════

LOGO_FOLDER = BASE_DIR / "static" / "logos"
LOGO_FOLDER.mkdir(exist_ok=True)
ALLOWED_LOGO_EXT = {"png", "jpg", "jpeg", "webp"}  # SVG محذوف: يحتوي JS → XSS


@app.route("/settings", methods=["GET", "POST"])
@require_perm("settings")
def settings():
    db     = get_db()
    biz_id = session["business_id"]

    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard
        name       = request.form.get("business_name",  "").strip()
        phone      = request.form.get("phone",          "").strip()
        email      = request.form.get("email",          "").strip()
        address    = request.form.get("address",        "").strip()
        city       = request.form.get("city",           "").strip()
        cr_number  = request.form.get("cr_number",      "").strip()
        currency   = request.form.get("currency",       "SAR")
        inv_prefix = request.form.get("invoice_prefix", "INV").strip()

        if not name:
            flash("اسم المنشأة مطلوب", "error")
            return redirect(url_for("settings"))

        # ─ رفع اللوجو ─
        logo_path = None
        if "logo" in request.files:
            logo_file = request.files["logo"]
            if logo_file and logo_file.filename:
                ext = logo_file.filename.rsplit(".", 1)[-1].lower()
                if ext in ALLOWED_LOGO_EXT:
                    safe_name = f"logo_{biz_id}.{ext}"
                    logo_file.save(LOGO_FOLDER / safe_name)
                    logo_path = f"/static/logos/{safe_name}"

        # ─ حفظ بيانات المنشأة ─
        if logo_path:
            db.execute(
                """UPDATE businesses
                   SET name=?, tax_number=?, phone=?, email=?, address=?, city=?,
                       cr_number=?, currency=?, logo_path=?, updated_at=datetime('now')
                   WHERE id=?""",
                (name, tax_number, phone, email, address, city,
                 cr_number, currency, logo_path, biz_id)
            )
        else:
            db.execute(
                """UPDATE businesses
                   SET name=?, tax_number=?, phone=?, email=?, address=?, city=?,
                       cr_number=?, currency=?, updated_at=datetime('now')
                   WHERE id=?""",
                (name, tax_number, phone, email, address, city,
                 cr_number, currency, biz_id)
            )

        # ─ حفظ بادئة الفاتورة ─
        db.execute(
            "INSERT OR REPLACE INTO settings (business_id, key, value) VALUES (?,?,?)",
            (biz_id, "invoice_prefix_sale", inv_prefix or "INV")
        )
        db.commit()

        # تحديث g.business للجلسة الحالية
        g.business = db.execute("SELECT * FROM businesses WHERE id=?", (biz_id,)).fetchone()
        flash("✅ تم حفظ الإعدادات بنجاح", "success")
        return redirect(url_for("settings"))

    biz = db.execute("SELECT * FROM businesses WHERE id=?", (biz_id,)).fetchone()
    inv_prefix = db.execute(
        "SELECT value FROM settings WHERE business_id=? AND key='invoice_prefix_sale'",
        (biz_id,)
    ).fetchone()

    return render_template(
        "settings.html",
        biz=dict(biz) if biz else {},
        inv_prefix=inv_prefix["value"] if inv_prefix else "INV",
    )


# ════════════════════════════════════════════════════════════════════════════════
# VAT REPORT — تقرير ضريبة القيمة المضافة
# ════════════════════════════════════════════════════════════════════════════════

@app.route("/reports")
@app.route("/reports/vat")
@require_perm("reports")
def reports():
    db     = get_db()
    biz_id = session["business_id"]

    # فترة التقرير (افتراضي: الشهر الحالي)
    date_from = request.args.get("from", datetime.now().strftime("%Y-%m-01"))
    date_to   = request.args.get("to",   datetime.now().strftime("%Y-%m-%d"))

    try:
        datetime.strptime(date_from, "%Y-%m-%d")
        datetime.strptime(date_to,   "%Y-%m-%d")
    except ValueError:
        date_from = datetime.now().strftime("%Y-%m-01")
        date_to   = datetime.now().strftime("%Y-%m-%d")

    # ── ضريبة المبيعات (المخرجات) ─────────────────────────
    sales_vat = db.execute("""
        SELECT
          COUNT(*)                         AS count,
          COALESCE(SUM(subtotal),  0)      AS subtotal,
          COALESCE(SUM(tax_amount),0)      AS vat,
          COALESCE(SUM(total),     0)      AS total
        FROM invoices
        WHERE business_id=?
          AND invoice_type IN ('sale','table')
          AND status = 'paid'
          AND DATE(invoice_date) BETWEEN ? AND ?
    """, (biz_id, date_from, date_to)).fetchone()

    # ── ضريبة المشتريات (المدخلات) ────────────────────────
    purch_vat = db.execute("""
        SELECT
          COUNT(*)                         AS count,
          COALESCE(SUM(subtotal),  0)      AS subtotal,
          COALESCE(SUM(tax_amount),0)      AS vat,
          COALESCE(SUM(total),     0)      AS total
        FROM invoices
        WHERE business_id=?
          AND invoice_type = 'purchase'
          AND status = 'paid'
          AND DATE(invoice_date) BETWEEN ? AND ?
    """, (biz_id, date_from, date_to)).fetchone()

    # ── فواتير المبيعات التفصيلية ─────────────────────────
    sale_invoices = db.execute("""
        SELECT invoice_number, invoice_date, party_name,
               subtotal, tax_amount, total
        FROM invoices
        WHERE business_id=?
          AND invoice_type IN ('sale','table')
          AND status='paid'
          AND DATE(invoice_date) BETWEEN ? AND ?
        ORDER BY invoice_date DESC
        LIMIT 100
    """, (biz_id, date_from, date_to)).fetchall()

    # ── فواتير المشتريات التفصيلية ───────────────────────
    purch_invoices = db.execute("""
        SELECT invoice_number, invoice_date, party_name,
               subtotal, tax_amount, total
        FROM invoices
        WHERE business_id=?
          AND invoice_type = 'purchase'
          AND status='paid'
          AND DATE(invoice_date) BETWEEN ? AND ?
        ORDER BY invoice_date DESC
        LIMIT 100
    """, (biz_id, date_from, date_to)).fetchall()

    net_vat = float(sales_vat["vat"] or 0) - float(purch_vat["vat"] or 0)

    return render_template(
        "reports_vat.html",
        date_from=date_from,
        date_to=date_to,
        sales_vat=dict(sales_vat),
        purch_vat=dict(purch_vat),
        net_vat=net_vat,
        sale_invoices=[dict(r) for r in sale_invoices],
        purch_invoices=[dict(r) for r in purch_invoices],
    )


# ── طباعة الفاتورة ───────────────────────────────────────────────────────────

@app.route("/invoice/<int:inv_id>/print")
@onboarding_required
def invoice_print(inv_id: int):
    db     = get_db()
    biz_id = session["business_id"]

    inv = db.execute(
        "SELECT * FROM invoices WHERE id=? AND business_id=?", (inv_id, biz_id)
    ).fetchone()
    if not inv:
        return render_template("404.html"), 404

    lines = db.execute(
        """SELECT il.*, p.name AS product_name
           FROM invoice_lines il
           LEFT JOIN products p ON p.id = il.product_id
           WHERE il.invoice_id=? ORDER BY il.line_order""",
        (inv_id,)
    ).fetchall()

    biz = db.execute("SELECT * FROM businesses WHERE id=?", (biz_id,)).fetchone()

    # توليد QR ZATCA
    seller     = biz["name"]       if biz else "غير محدد"
    vat_number = biz["tax_number"] if biz else ""
    ts = str(inv["created_at"] or inv["invoice_date"] or datetime.now().isoformat())
    if len(ts) == 10:
        ts += "T00:00:00Z"

    qr_b64 = zatca_qr_b64(
        seller, vat_number, ts,
        float(inv["total"] or 0),
        float(inv["tax_amount"] or 0)
    )

    mode = request.args.get("mode", "a4")  # a4 | thermal

    return render_template(
        "invoice_print.html",
        inv=dict(inv),
        lines=[dict(r) for r in lines],
        biz=dict(biz) if biz else {},
        qr_b64=qr_b64,
        mode=mode,
    )


# ════════════════════════════════════════════════════════════════════════════════
# ACCOUNTING — دفتر القيود اليومية
# ════════════════════════════════════════════════════════════════════════════════

@app.route("/accounting")
@require_perm("accounting")
def accounting():
    db     = get_db()
    biz_id = session["business_id"]

    page     = max(1, int(request.args.get("page", 1)))
    per_page = 20
    offset   = (page - 1) * per_page
    q        = request.args.get("q", "").strip()

    base_where = "WHERE je.business_id = ?"
    params     = [biz_id]
    if q:
        base_where += " AND (je.entry_number LIKE ? OR je.description LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]

    total = db.execute(
        f"SELECT COUNT(*) FROM journal_entries je {base_where}", params
    ).fetchone()[0]

    entries = db.execute(
        f"""SELECT je.id, je.entry_number, je.entry_date, je.description,
                   je.total_debit, je.total_credit, je.is_posted,
                   je.reference_type, je.reference_id,
                   u.full_name AS created_by_name
            FROM journal_entries je
            LEFT JOIN users u ON u.id = je.created_by
            {base_where}
            ORDER BY je.id DESC
            LIMIT ? OFFSET ?""",
        params + [per_page, offset]
    ).fetchall()

    # جلب بنود كل قيد
    entries_with_lines = []
    for e in entries:
        lines = db.execute(
            """SELECT jel.debit, jel.credit, jel.description AS line_desc,
                      a.code, a.name AS account_name
               FROM journal_entry_lines jel
               JOIN accounts a ON a.id = jel.account_id
               WHERE jel.entry_id = ?
               ORDER BY jel.line_order""",
            (e["id"],)
        ).fetchall()
        entries_with_lines.append({"entry": dict(e), "lines": [dict(l) for l in lines]})

    total_pages = max(1, (total + per_page - 1) // per_page)
    return render_template(
        "accounting.html",
        entries=entries_with_lines,
        page=page,
        total_pages=total_pages,
        total=total,
        q=q,
    )


# ════════════════════════════════════════════════════════════════════════════════
# PURCHASES — المشتريات
# ════════════════════════════════════════════════════════════════════════════════

@app.route("/purchases", methods=["GET", "POST"])
@require_perm("purchases")
def purchases():
    db     = get_db()
    biz_id = session["business_id"]

    if request.method == "GET":
        # قائمة فواتير المشتريات السابقة
        page     = max(1, int(request.args.get("page", 1)))
        per_page = 20
        offset   = (page - 1) * per_page

        invoices_list = db.execute(
            """SELECT i.id, i.invoice_number, i.invoice_date, i.party_name,
                      i.subtotal, i.tax_amount, i.total, i.status,
                      i.notes, i.created_at
               FROM invoices i
               WHERE i.business_id = ? AND i.invoice_type = 'purchase'
               ORDER BY i.id DESC
               LIMIT ? OFFSET ?""",
            (biz_id, per_page, offset)
        ).fetchall()

        total = db.execute(
            "SELECT COUNT(*) FROM invoices WHERE business_id=? AND invoice_type='purchase'",
            (biz_id,)
        ).fetchone()[0]

        total_pages = max(1, (total + per_page - 1) // per_page)

        # جلب المنتجات لنموذج الإدخال اليدوي
        products = db.execute(
            """SELECT id, name, barcode, purchase_price, category_name
               FROM products WHERE business_id=? AND is_active=1
               ORDER BY name LIMIT 500""",
            (biz_id,)
        ).fetchall()

        return render_template(
            "purchases.html",
            invoices=invoices_list,
            products=products,
            page=page,
            total_pages=total_pages,
            total=total,
        )

    # ─── POST: حفظ فاتورة شراء ───────────────────────────────────────────────
    # TODO: Integrate OCR — parse uploaded PDF/image here using AI to extract
    #       supplier_name, invoice_date, line items, tax amount automatically.
    #       Expected fields: supplier_name, invoice_date, items[], tax_amount
    # ─────────────────────────────────────────────────────────────────────────

    supplier_name  = request.form.get("supplier_name", "").strip()
    invoice_date   = request.form.get("invoice_date", "").strip()
    tax_pct        = float(request.form.get("tax_pct", 0) or 0)
    notes          = request.form.get("notes", "").strip()
    payment_method = request.form.get("payment_method", "cash")

    # بنود الفاتورة (حقول متعددة)
    product_ids  = request.form.getlist("product_id[]")
    quantities   = request.form.getlist("quantity[]")
    unit_costs   = request.form.getlist("unit_cost[]")

    if not invoice_date:
        flash("تاريخ الفاتورة مطلوب", "error")
        return redirect(url_for("purchases"))

    if not product_ids:
        flash("يجب إضافة منتج واحد على الأقل", "error")
        return redirect(url_for("purchases"))

    # ─── معالجة الملف المرفوع ────────────────────────────────────────────────
    # TODO: Integrate OCR — after saving file, send to AI service for parsing
    uploaded_file = request.files.get("invoice_file")
    saved_filename = None
    if uploaded_file and uploaded_file.filename:
        import re as _re
        safe = _re.sub(r"[^\w.\-]", "_", uploaded_file.filename)
        upload_dir = BASE_DIR / "static" / "uploads"
        upload_dir.mkdir(exist_ok=True)
        saved_filename = f"{biz_id}_{secrets.token_hex(6)}_{safe}"
        # نحفظ فقط PDF وصور (OWASP: تحقق من نوع الملف)
        allowed = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
        ext = Path(safe).suffix.lower()
        if ext not in allowed:
            flash("نوع الملف غير مدعوم — يُسمح بـ PDF والصور فقط", "error")
            return redirect(url_for("purchases"))
        uploaded_file.save(str(upload_dir / saved_filename))

    # ─── التحقق من البنود وحساب الإجماليات ────────────────────────────────────
    user_id = session["user_id"]
    subtotal = tax_total = 0.0
    validated = []

    for pid, qty_s, cost_s in zip(product_ids, quantities, unit_costs):
        try:
            qty  = float(qty_s)
            cost = float(cost_s)
        except ValueError:
            continue
        if qty <= 0 or cost < 0:
            continue
        product = db.execute(
            "SELECT * FROM products WHERE id=? AND business_id=?",
            (int(pid), biz_id)
        ).fetchone()
        if not product:
            continue
        line_sub = round(qty * cost, 4)
        line_tax = round(line_sub * tax_pct / 100, 4)
        subtotal  += line_sub
        tax_total += line_tax
        validated.append({
            "product_id": int(pid),
            "name":       product["name"],
            "quantity":   qty,
            "unit_cost":  cost,
            "tax_amount": line_tax,
            "total":      round(line_sub + line_tax, 4),
        })

    if not validated:
        flash("البنود غير صالحة — تحقق من الكميات والأسعار", "error")
        return redirect(url_for("purchases"))

    subtotal    = round(subtotal,    2)
    tax_total   = round(tax_total,   2)
    grand_total = round(subtotal + tax_total, 2)

    # ─── حسابات الطرف الدائن ────────────────────────────────────────────────
    if payment_method == "cash":
        credit_acc_id = get_account_id(db, biz_id, "1101")   # الصندوق
    elif payment_method == "bank":
        credit_acc_id = get_account_id(db, biz_id, "1102")   # البنك
    else:
        credit_acc_id = get_account_id(db, biz_id, "2101")   # ذمم دائنة - موردون

    inv_acc_id    = get_account_id(db, biz_id, "1104")       # مخزون البضاعة
    tax_input_id  = get_account_id(db, biz_id, "2102")       # ضريبة (نعيد تسجيلها مدينة)

    if not credit_acc_id or not inv_acc_id:
        flash("شجرة الحسابات غير مكتملة — راجع الإعدادات", "error")
        return redirect(url_for("purchases"))

    # ─── Transaction ──────────────────────────────────────────────────────────
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # رقم الفاتورة
        prefix_row = db.execute(
            "SELECT value FROM settings WHERE business_id=? AND key='invoice_prefix_purchase'",
            (biz_id,)
        ).fetchone()
        prefix = prefix_row["value"] if prefix_row else "PUR"
        cnt = db.execute(
            "SELECT COUNT(*) FROM invoices WHERE business_id=? AND invoice_type='purchase'",
            (biz_id,)
        ).fetchone()[0]
        pur_number = f"{prefix}-{cnt + 1:05d}"

        # المستودع الافتراضي
        wh = db.execute(
            "SELECT id FROM warehouses WHERE business_id=? AND is_default=1 LIMIT 1",
            (biz_id,)
        ).fetchone()
        warehouse_id = wh["id"] if wh else None

        # 1. حفظ الفاتورة
        db.execute(
            """INSERT INTO invoices
               (business_id, invoice_number, invoice_type, invoice_date,
                party_name, subtotal, tax_amount, total, paid_amount,
                status, warehouse_id, notes, created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (biz_id, pur_number, "purchase", invoice_date,
             supplier_name or None, subtotal, tax_total, grand_total,
             grand_total if payment_method != "credit" else 0,
             "paid" if payment_method != "credit" else "partial",
             warehouse_id, notes or None, user_id)
        )
        inv_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # 2. بنود الفاتورة + رفع المخزون + تحديث متوسط التكلفة
        for idx, item in enumerate(validated):
            db.execute(
                """INSERT INTO invoice_lines
                   (invoice_id, product_id, description, quantity, unit_price,
                    tax_rate, tax_amount, total, line_order)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (inv_id, item["product_id"], item["name"],
                 item["quantity"], item["unit_cost"],
                 tax_pct, item["tax_amount"], item["total"], idx + 1)
            )
            if warehouse_id:
                # إنشاء سجل مخزون إن لم يكن
                db.execute(
                    """INSERT OR IGNORE INTO stock
                       (business_id, product_id, warehouse_id, quantity, avg_cost)
                       VALUES (?,?,?,0,0)""",
                    (biz_id, item["product_id"], warehouse_id)
                )
                # تحديث الكمية ومتوسط التكلفة المرجّح
                st = db.execute(
                    "SELECT quantity, avg_cost FROM stock WHERE product_id=? AND warehouse_id=?",
                    (item["product_id"], warehouse_id)
                ).fetchone()
                old_qty  = float(st["quantity"])
                old_cost = float(st["avg_cost"])
                new_qty  = old_qty + item["quantity"]
                new_cost = ((old_qty * old_cost) + (item["quantity"] * item["unit_cost"])) / new_qty if new_qty else item["unit_cost"]
                db.execute(
                    """UPDATE stock SET quantity=?, avg_cost=?, last_updated=?
                       WHERE product_id=? AND warehouse_id=?""",
                    (new_qty, round(new_cost, 4), now, item["product_id"], warehouse_id)
                )
                db.execute(
                    """INSERT INTO stock_movements
                       (business_id, product_id, warehouse_id, movement_type,
                        quantity, unit_cost, reference_type, reference_id, created_by)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (biz_id, item["product_id"], warehouse_id, "purchase",
                     item["quantity"], item["unit_cost"],
                     "invoice", inv_id, user_id)
                )

        # 3. قيد المشتريات المحاسبي
        # د/ مخزون البضاعة   (+ د/ ضريبة المدخلات إن وُجدت)
        # ك/ الصندوق أو البنك أو ذمم دائنة
        je_num = next_entry_number(db, biz_id)
        db.execute(
            """INSERT INTO journal_entries
               (business_id, entry_number, entry_date, description,
                reference_type, reference_id, total_debit, total_credit,
                is_posted, created_by)
               VALUES (?,?,?,?,?,?,?,?,1,?)""",
            (biz_id, je_num, invoice_date,
             f"قيد مشتريات — فاتورة {pur_number}" + (f" | {supplier_name}" if supplier_name else ""),
             "invoice", inv_id, grand_total, grand_total, user_id)
        )
        je_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # مدين: المخزون
        db.execute(
            """INSERT INTO journal_entry_lines
               (entry_id, account_id, description, debit, credit, line_order)
               VALUES (?,?,?,?,?,?)""",
            (je_id, inv_acc_id, "إضافة للمخزون", subtotal, 0, 1)
        )
        order = 2
        # مدين: ضريبة المدخلات (إن وجدت)
        if tax_total > 0 and tax_input_id:
            db.execute(
                """INSERT INTO journal_entry_lines
                   (entry_id, account_id, description, debit, credit, line_order)
                   VALUES (?,?,?,?,?,?)""",
                (je_id, tax_input_id, "ضريبة المدخلات", tax_total, 0, order)
            )
            order += 1

        # دائن: الصندوق/البنك/المورد
        credit_label = {
            "cash":   "نقداً من الصندوق",
            "bank":   "تحويل بنكي",
            "credit": f"بالآجل — {supplier_name or 'مورد'}",
        }.get(payment_method, "نقداً من الصندوق")

        db.execute(
            """INSERT INTO journal_entry_lines
               (entry_id, account_id, description, debit, credit, line_order)
               VALUES (?,?,?,?,?,?)""",
            (je_id, credit_acc_id, credit_label, 0, grand_total, order)
        )

        db.execute("UPDATE invoices SET journal_entry_id=? WHERE id=?", (je_id, inv_id))
        db.commit()

        flash(f"✓ تم حفظ فاتورة الشراء {pur_number} وتوليد القيد المحاسبي", "success")
        return redirect(url_for("purchases"))

    except Exception as e:
        db.rollback()
        app.logger.error(f"Purchase save error: {e}")
        flash("حدث خطأ أثناء الحفظ — يرجى المحاولة مرة أخرى", "error")
        return redirect(url_for("purchases"))


# ════════════════════════════════════════════════════════════════════════════════
# POS — نقاط البيع
# ════════════════════════════════════════════════════════════════════════════════

@app.route("/pos")
@require_perm("pos")
def pos():
    db     = get_db()
    biz_id = session["business_id"]
    # جلب الفرع المخصص للمستخدم الحالي (الكاشير مقيّد بفرعه)
    user_branch_id = g.user["branch_id"] if g.user else None
    warehouses = db.execute(
        "SELECT id, name FROM warehouses WHERE business_id=? AND is_active=1 ORDER BY is_default DESC",
        (biz_id,)
    ).fetchall()
    return render_template("pos.html",
                           user_branch_id=user_branch_id,
                           warehouses=[dict(w) for w in warehouses])


@app.route("/api/pos/search")
@onboarding_required
def api_pos_search():
    """البحث عن منتجات POS بالاسم أو الباركود"""
    q      = request.args.get("q", "").strip()
    biz_id = session["business_id"]
    if not q:
        return jsonify([])

    db = get_db()
    rows = db.execute(
        """SELECT p.id, p.name, p.barcode, p.sale_price,
                  p.category_name, p.purchase_price,
                  COALESCE(s.quantity, 0) AS stock_qty
           FROM products p
           LEFT JOIN stock s ON s.product_id = p.id
           WHERE p.business_id = ? AND p.is_active = 1 AND p.is_pos = 1
             AND (p.name LIKE ? OR p.barcode LIKE ?)
           ORDER BY p.name
           LIMIT 30""",
        (biz_id, f"%{q}%", f"%{q}%")
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/pos/checkout", methods=["POST"])
@onboarding_required
def api_pos_checkout():
    """
    إتمام عملية البيع في نقطة البيع:
      1. حفظ الفاتورة وبنودها
      2. خصم الكميات من المخزون + تسجيل حركة
      3. قيد مبيعات: د/الصندوق — ك/إيرادات + ك/ضريبة
      4. قيد تكلفة:  د/COGS      — ك/مخزون
    كل العمليات في transaction واحدة.
    """
    data    = request.get_json(force=True) or {}
    biz_id  = session["business_id"]
    user_id = session["user_id"]
    db      = get_db()

    items          = data.get("items", [])
    payment_method = data.get("payment_method", "cash")

    if not items:
        return jsonify({"success": False, "error": "السلة فارغة"}), 400

    # ─── جلب الحسابات المطلوبة ───────────────────────
    cash_acc_id  = get_account_id(db, biz_id, "1102" if payment_method == "bank" else "1101")
    sales_acc_id = get_account_id(db, biz_id, "4101")
    tax_acc_id   = get_account_id(db, biz_id, "2102")
    cogs_acc_id  = get_account_id(db, biz_id, "5101")
    inv_acc_id   = get_account_id(db, biz_id, "1104")

    if not all([cash_acc_id, sales_acc_id, cogs_acc_id, inv_acc_id]):
        return jsonify({
            "success": False,
            "error": "شجرة الحسابات غير مكتملة — أكمل إعداد المنشأة أولاً"
        }), 400

    # ─── المستودع: الكاشير مقيّد بفرعه — المدير يختار ──────────────────────────
    # إذا كان المستخدم مرتبطاً بـ branch_id → استخدمه
    user_branch_id = g.user["branch_id"] if g.user else None
    requested_wh   = data.get("warehouse_id")

    if user_branch_id:
        # كاشير: مخزنه الوحيد هو مخزن فرعه
        wh = db.execute(
            "SELECT id FROM warehouses WHERE id=? AND business_id=? AND is_active=1",
            (user_branch_id, biz_id)
        ).fetchone()
    elif requested_wh:
        wh = db.execute(
            "SELECT id FROM warehouses WHERE id=? AND business_id=? AND is_active=1",
            (int(requested_wh), biz_id)
        ).fetchone()
    else:
        wh = db.execute(
            "SELECT id FROM warehouses WHERE business_id=? AND is_default=1 LIMIT 1",
            (biz_id,)
        ).fetchone()
    if not wh:
        wh = db.execute(
            "SELECT id FROM warehouses WHERE business_id=? LIMIT 1", (biz_id,)
        ).fetchone()
    warehouse_id = wh["id"] if wh else None

    # ─── التحقق من البنود وحساب الإجماليات ──────────
    today = datetime.now().strftime("%Y-%m-%d")
    now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    subtotal = tax_total = cogs_total = 0.0
    validated = []

    for item in items:
        try:
            product_id = int(item["product_id"])
            qty        = float(item["quantity"])
            unit_price = float(item["unit_price"])
            tax_rate   = float(item.get("tax_rate", 0))
        except (KeyError, ValueError, TypeError):
            return jsonify({"success": False, "error": "بيانات البنود غير صالحة"}), 400

        if qty <= 0 or unit_price < 0:
            return jsonify({"success": False, "error": "الكمية والسعر يجب أن يكونا موجبين"}), 400

        product = db.execute(
            "SELECT * FROM products WHERE id=? AND business_id=? AND is_active=1",
            (product_id, biz_id)
        ).fetchone()
        if not product:
            return jsonify({"success": False, "error": f"المنتج ID={product_id} غير موجود"}), 400

        line_sub  = round(qty * unit_price, 4)
        line_tax  = round(line_sub * tax_rate / 100, 4)
        line_tot  = round(line_sub + line_tax, 4)
        line_cost = round(qty * float(product["purchase_price"] or 0), 4)

        subtotal   += line_sub
        tax_total  += line_tax
        cogs_total += line_cost

        validated.append({
            "product_id":     product_id,
            "description":    product["name"],
            "quantity":       qty,
            "unit_price":     unit_price,
            "tax_rate":       tax_rate,
            "tax_amount":     line_tax,
            "total":          line_tot,
            "purchase_price": float(product["purchase_price"] or 0),
        })

    subtotal    = round(subtotal,    2)
    tax_total   = round(tax_total,   2)
    grand_total = round(subtotal + tax_total, 2)
    cogs_total  = round(cogs_total,  2)

    # ════════════════════════════════════════════════
    # Transaction الكامل: كل العمليات أو لا شيء
    # ════════════════════════════════════════════════
    try:
        inv_number  = next_invoice_number(db, biz_id)
        je_sale_num = next_entry_number(db, biz_id)

        # 1. حفظ الفاتورة
        db.execute(
            """INSERT INTO invoices
               (business_id, invoice_number, invoice_type, invoice_date,
                subtotal, tax_amount, total, paid_amount,
                status, warehouse_id, created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (biz_id, inv_number, "sale", today,
             subtotal, tax_total, grand_total, grand_total,
             "paid", warehouse_id, user_id)
        )
        invoice_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # 2. بنود الفاتورة + خصم المخزون
        for idx, item in enumerate(validated):
            db.execute(
                """INSERT INTO invoice_lines
                   (invoice_id, product_id, description, quantity, unit_price,
                    tax_rate, tax_amount, total, line_order)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (invoice_id, item["product_id"], item["description"],
                 item["quantity"], item["unit_price"],
                 item["tax_rate"], item["tax_amount"], item["total"], idx + 1)
            )
            if warehouse_id:
                # إنشاء سجل المخزون إن لم يكن موجوداً
                db.execute(
                    """INSERT OR IGNORE INTO stock
                       (business_id, product_id, warehouse_id, quantity, avg_cost)
                       VALUES (?,?,?,0,0)""",
                    (biz_id, item["product_id"], warehouse_id)
                )
                db.execute(
                    """UPDATE stock SET quantity = quantity - ?, last_updated = ?
                       WHERE product_id=? AND warehouse_id=?""",
                    (item["quantity"], now, item["product_id"], warehouse_id)
                )
                db.execute(
                    """INSERT INTO stock_movements
                       (business_id, product_id, warehouse_id, movement_type,
                        quantity, unit_cost, reference_type, reference_id, created_by)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (biz_id, item["product_id"], warehouse_id, "sale",
                     -item["quantity"], item["purchase_price"],
                     "invoice", invoice_id, user_id)
                )

        # 3. قيد المبيعات: د/الصندوق — ك/إيرادات (+ ك/ضريبة)
        db.execute(
            """INSERT INTO journal_entries
               (business_id, entry_number, entry_date, description,
                reference_type, reference_id, total_debit, total_credit,
                is_posted, created_by)
               VALUES (?,?,?,?,?,?,?,?,1,?)""",
            (biz_id, je_sale_num, today,
             f"قيد مبيعات نقدية — فاتورة {inv_number}",
             "invoice", invoice_id, grand_total, grand_total, user_id)
        )
        je_sale_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        cash_label = "نقدية مقبوضة" if payment_method == "cash" else "تحويل بنكي"
        db.execute(
            """INSERT INTO journal_entry_lines
               (entry_id, account_id, description, debit, credit, line_order)
               VALUES (?,?,?,?,?,?)""",
            (je_sale_id, cash_acc_id, cash_label, grand_total, 0, 1)
        )
        db.execute(
            """INSERT INTO journal_entry_lines
               (entry_id, account_id, description, debit, credit, line_order)
               VALUES (?,?,?,?,?,?)""",
            (je_sale_id, sales_acc_id, f"إيرادات مبيعات — {inv_number}", 0, subtotal, 2)
        )
        if tax_total > 0 and tax_acc_id:
            db.execute(
                """INSERT INTO journal_entry_lines
                   (entry_id, account_id, description, debit, credit, line_order)
                   VALUES (?,?,?,?,?,?)""",
                (je_sale_id, tax_acc_id, "ضريبة القيمة المضافة", 0, tax_total, 3)
            )

        db.execute(
            "UPDATE invoices SET journal_entry_id=? WHERE id=?",
            (je_sale_id, invoice_id)
        )

        # 4. قيد تكلفة البضاعة المباعة: د/COGS — ك/مخزون
        if cogs_total > 0:
            je_cogs_num = next_entry_number(db, biz_id)
            db.execute(
                """INSERT INTO journal_entries
                   (business_id, entry_number, entry_date, description,
                    reference_type, reference_id, total_debit, total_credit,
                    is_posted, created_by)
                   VALUES (?,?,?,?,?,?,?,?,1,?)""",
                (biz_id, je_cogs_num, today,
                 f"قيد تكلفة البضاعة المباعة — فاتورة {inv_number}",
                 "invoice", invoice_id, cogs_total, cogs_total, user_id)
            )
            je_cogs_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

            db.execute(
                """INSERT INTO journal_entry_lines
                   (entry_id, account_id, description, debit, credit, line_order)
                   VALUES (?,?,?,?,?,?)""",
                (je_cogs_id, cogs_acc_id, "تكلفة البضاعة المباعة", cogs_total, 0, 1)
            )
            db.execute(
                """INSERT INTO journal_entry_lines
                   (entry_id, account_id, description, debit, credit, line_order)
                   VALUES (?,?,?,?,?,?)""",
                (je_cogs_id, inv_acc_id, "إقفال مخزون مباع", 0, cogs_total, 2)
            )

        db.commit()

        return jsonify({
            "success":        True,
            "invoice_number": inv_number,
            "invoice_id":     invoice_id,
            "total":          grand_total,
            "message":        f"تمت عملية البيع بنجاح — فاتورة {inv_number}",
        })

    except Exception as e:
        db.rollback()
        app.logger.error(f"POS checkout error: {e}")
        return jsonify({
            "success": False,
            "error": "حدث خطأ أثناء حفظ الفاتورة — يرجى المحاولة مرة أخرى"
        }), 500


# ════════════════════════════════════════════════════════════════════════════════
# ORDERS — أوامر بيع الجملة
# ════════════════════════════════════════════════════════════════════════════════

@app.route("/orders", methods=["GET", "POST"])
@onboarding_required
def orders():
    db     = get_db()
    biz_id = session["business_id"]

    if request.method == "GET":
        page     = max(1, int(request.args.get("page", 1)))
        per_page = 20
        offset   = (page - 1) * per_page
        q        = request.args.get("q", "").strip()

        where  = "WHERE i.business_id=? AND i.invoice_type='sale'"
        params = [biz_id]
        if q:
            where  += " AND (i.invoice_number LIKE ? OR i.party_name LIKE ?)"
            params += [f"%{q}%", f"%{q}%"]

        invoices_list = db.execute(
            f"""SELECT i.id, i.invoice_number, i.invoice_date, i.due_date,
                       i.party_name, i.subtotal, i.discount_amount,
                       i.tax_amount, i.total, i.paid_amount, i.status,
                       u.full_name AS created_by_name
                FROM invoices i
                LEFT JOIN users u ON u.id = i.created_by
                {where}
                ORDER BY i.id DESC
                LIMIT ? OFFSET ?""",
            params + [per_page, offset]
        ).fetchall()

        total = db.execute(
            f"SELECT COUNT(*) FROM invoices i {where}", params
        ).fetchone()[0]

        customers = db.execute(
            """SELECT id, name, phone FROM contacts
               WHERE business_id=? AND contact_type IN ('customer','both') AND is_active=1
               ORDER BY name""",
            (biz_id,)
        ).fetchall()

        products = db.execute(
            """SELECT p.id, p.name, p.barcode, p.sale_price, p.purchase_price, p.category_name,
                      COALESCE(s.quantity, 0) AS stock_qty
               FROM products p
               LEFT JOIN stock s ON s.product_id = p.id
               WHERE p.business_id=? AND p.is_active=1
               ORDER BY p.name LIMIT 500""",
            (biz_id,)
        ).fetchall()

        total_pages = max(1, (total + per_page - 1) // per_page)
        return render_template(
            "orders.html",
            invoices=invoices_list,
            customers=customers,
            products=products,
            page=page,
            total_pages=total_pages,
            total=total,
            q=q,
        )

    # ─── POST: حفظ أمر بيع جملة ──────────────────────────────────────────────
    customer_id    = request.form.get("customer_id", "").strip()
    customer_name  = request.form.get("customer_name", "").strip()
    order_date     = request.form.get("order_date", "").strip()
    due_date       = request.form.get("due_date", "").strip()
    payment_method = request.form.get("payment_method", "cash")
    discount_pct   = float(request.form.get("discount_pct", 0) or 0)
    tax_pct        = float(request.form.get("tax_pct", 0) or 0)
    notes          = request.form.get("notes", "").strip()

    product_ids    = request.form.getlist("product_id[]")
    quantities     = request.form.getlist("quantity[]")
    unit_prices    = request.form.getlist("unit_price[]")
    line_discounts = request.form.getlist("line_discount[]")

    if not order_date:
        flash("تاريخ الأمر مطلوب", "error")
        return redirect(url_for("orders"))
    if not product_ids:
        flash("يجب إضافة منتج واحد على الأقل", "error")
        return redirect(url_for("orders"))

    user_id    = session["user_id"]
    subtotal   = 0.0
    cogs_total = 0.0
    validated  = []

    for i, (pid, qty_s, price_s) in enumerate(zip(product_ids, quantities, unit_prices)):
        try:
            qty       = float(qty_s)
            price     = float(price_s)
            line_disc = float(line_discounts[i]) if i < len(line_discounts) else 0.0
        except (ValueError, TypeError):
            continue
        if qty <= 0 or price < 0:
            continue
        product = db.execute(
            "SELECT * FROM products WHERE id=? AND business_id=?",
            (int(pid), biz_id)
        ).fetchone()
        if not product:
            continue

        line_sub      = round(qty * price, 4)
        line_disc_amt = round(line_sub * line_disc / 100, 4)
        line_net      = round(line_sub - line_disc_amt, 4)
        line_cost     = round(qty * float(product["purchase_price"] or 0), 4)

        subtotal   += line_net
        cogs_total += line_cost
        validated.append({
            "product_id":      int(pid),
            "name":            product["name"],
            "quantity":        qty,
            "unit_price":      price,
            "discount_pct":    line_disc,
            "discount_amount": line_disc_amt,
            "line_net":        line_net,
            "purchase_price":  float(product["purchase_price"] or 0),
        })

    if not validated:
        flash("البنود غير صالحة — تحقق من الكميات والأسعار", "error")
        return redirect(url_for("orders"))

    subtotal           = round(subtotal, 2)
    overall_disc_amt   = round(subtotal * discount_pct / 100, 2)
    subtotal_after_disc= round(subtotal - overall_disc_amt, 2)
    tax_total          = round(subtotal_after_disc * tax_pct / 100, 2)
    grand_total        = round(subtotal_after_disc + tax_total, 2)
    cogs_total         = round(cogs_total, 2)

    # تحديد حساب الطرف المدين
    debit_code = {"cash": "1101", "bank": "1102", "credit": "1103"}.get(payment_method, "1101")
    debit_acc_id  = get_account_id(db, biz_id, debit_code)
    sales_acc_id  = get_account_id(db, biz_id, "4101")
    tax_acc_id    = get_account_id(db, biz_id, "2102")
    cogs_acc_id   = get_account_id(db, biz_id, "5101")
    inv_acc_id    = get_account_id(db, biz_id, "1104")

    if not all([debit_acc_id, sales_acc_id, cogs_acc_id, inv_acc_id]):
        flash("شجرة الحسابات غير مكتملة — راجع الإعدادات", "error")
        return redirect(url_for("orders"))

    wh = db.execute(
        "SELECT id FROM warehouses WHERE business_id=? AND is_default=1 LIMIT 1",
        (biz_id,)
    ).fetchone()
    warehouse_id = wh["id"] if wh else None

    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # توليد رقم أمر البيع
        cnt = db.execute(
            "SELECT COUNT(*) FROM invoices WHERE business_id=? AND invoice_type='sale'",
            (biz_id,)
        ).fetchone()[0]
        order_number = f"ORD-{cnt + 1:05d}"

        # حل اسم العميل
        cust_id = int(customer_id) if customer_id else None
        if cust_id:
            row = db.execute(
                "SELECT name FROM contacts WHERE id=? AND business_id=?", (cust_id, biz_id)
            ).fetchone()
            if row:
                customer_name = row["name"]

        # 1. حفظ الفاتورة
        db.execute(
            """INSERT INTO invoices
               (business_id, invoice_number, invoice_type, invoice_date, due_date,
                party_id, party_name, subtotal, discount_pct, discount_amount,
                tax_amount, total, paid_amount, status, warehouse_id, notes, created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (biz_id, order_number, "sale", order_date, due_date or None,
             cust_id, customer_name or None,
             round(subtotal + overall_disc_amt, 2), discount_pct, overall_disc_amt,
             tax_total, grand_total,
             grand_total if payment_method != "credit" else 0,
             "paid" if payment_method != "credit" else "partial",
             warehouse_id, notes or None, user_id)
        )
        inv_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # 2. بنود الفاتورة + خصم المخزون
        for idx, item in enumerate(validated):
            line_tax = round(item["line_net"] * tax_pct / 100, 4)
            db.execute(
                """INSERT INTO invoice_lines
                   (invoice_id, product_id, description, quantity, unit_price,
                    discount_pct, discount_amount, tax_rate, tax_amount, total, line_order)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (inv_id, item["product_id"], item["name"],
                 item["quantity"], item["unit_price"],
                 item["discount_pct"], item["discount_amount"],
                 tax_pct, line_tax,
                 round(item["line_net"] + line_tax, 4), idx + 1)
            )
            if warehouse_id:
                db.execute(
                    """INSERT OR IGNORE INTO stock
                       (business_id, product_id, warehouse_id, quantity, avg_cost)
                       VALUES (?,?,?,0,0)""",
                    (biz_id, item["product_id"], warehouse_id)
                )
                db.execute(
                    """UPDATE stock SET quantity = quantity - ?, last_updated = ?
                       WHERE product_id=? AND warehouse_id=?""",
                    (item["quantity"], now, item["product_id"], warehouse_id)
                )
                db.execute(
                    """INSERT INTO stock_movements
                       (business_id, product_id, warehouse_id, movement_type,
                        quantity, unit_cost, reference_type, reference_id, created_by)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (biz_id, item["product_id"], warehouse_id, "sale",
                     -item["quantity"], item["purchase_price"],
                     "invoice", inv_id, user_id)
                )

        # 3. قيد المبيعات
        je_num     = next_entry_number(db, biz_id)
        debit_label = {
            "cash":   "نقداً من العميل",
            "bank":   "تحويل بنكي",
            "credit": f"بالآجل — {customer_name or 'عميل'}",
        }.get(payment_method, "نقداً")

        db.execute(
            """INSERT INTO journal_entries
               (business_id, entry_number, entry_date, description,
                reference_type, reference_id, total_debit, total_credit,
                is_posted, created_by)
               VALUES (?,?,?,?,?,?,?,?,1,?)""",
            (biz_id, je_num, order_date,
             f"قيد مبيعات جملة — {order_number}" + (f" | {customer_name}" if customer_name else ""),
             "invoice", inv_id, grand_total, grand_total, user_id)
        )
        je_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        db.execute(
            """INSERT INTO journal_entry_lines
               (entry_id, account_id, description, debit, credit, line_order)
               VALUES (?,?,?,?,?,?)""",
            (je_id, debit_acc_id, debit_label, grand_total, 0, 1)
        )
        db.execute(
            """INSERT INTO journal_entry_lines
               (entry_id, account_id, description, debit, credit, line_order)
               VALUES (?,?,?,?,?,?)""",
            (je_id, sales_acc_id, f"إيرادات مبيعات جملة — {order_number}", 0, subtotal_after_disc, 2)
        )
        if tax_total > 0 and tax_acc_id:
            db.execute(
                """INSERT INTO journal_entry_lines
                   (entry_id, account_id, description, debit, credit, line_order)
                   VALUES (?,?,?,?,?,?)""",
                (je_id, tax_acc_id, "ضريبة القيمة المضافة", 0, tax_total, 3)
            )

        db.execute("UPDATE invoices SET journal_entry_id=? WHERE id=?", (je_id, inv_id))

        # 4. قيد تكلفة البضاعة المباعة
        if cogs_total > 0:
            je_cogs_num = next_entry_number(db, biz_id)
            db.execute(
                """INSERT INTO journal_entries
                   (business_id, entry_number, entry_date, description,
                    reference_type, reference_id, total_debit, total_credit,
                    is_posted, created_by)
                   VALUES (?,?,?,?,?,?,?,?,1,?)""",
                (biz_id, je_cogs_num, order_date,
                 f"قيد تكلفة مبيعات جملة — {order_number}",
                 "invoice", inv_id, cogs_total, cogs_total, user_id)
            )
            je_cogs_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.execute(
                """INSERT INTO journal_entry_lines
                   (entry_id, account_id, description, debit, credit, line_order)
                   VALUES (?,?,?,?,?,?)""",
                (je_cogs_id, cogs_acc_id, "تكلفة مبيعات جملة", cogs_total, 0, 1)
            )
            db.execute(
                """INSERT INTO journal_entry_lines
                   (entry_id, account_id, description, debit, credit, line_order)
                   VALUES (?,?,?,?,?,?)""",
                (je_cogs_id, inv_acc_id, "إقفال مخزون مباع جملة", 0, cogs_total, 2)
            )

        db.commit()
        flash(f"✓ تم إنشاء أمر البيع {order_number} وتوليد القيد المحاسبي", "success")
        return redirect(url_for("orders"))

    except Exception as e:
        db.rollback()
        app.logger.error(f"Orders save error: {e}")
        flash("حدث خطأ أثناء الحفظ — يرجى المحاولة مرة أخرى", "error")
        return redirect(url_for("orders"))


# ════════════════════════════════════════════════════════════════════════════════
# PRICING — إدارة قوائم الأسعار
# ════════════════════════════════════════════════════════════════════════════════

@app.route("/pricing", methods=["GET"])
@onboarding_required
def pricing():
    db     = get_db()
    biz_id = session["business_id"]

    page        = max(1, int(request.args.get("page", 1)))
    per_page    = 50
    offset      = (page - 1) * per_page
    q           = request.args.get("q", "").strip()
    category_id = request.args.get("cat", "").strip()

    where  = "WHERE p.business_id=? AND p.is_active=1"
    params = [biz_id]
    if category_id:
        where  += " AND p.category_id=?"
        params.append(int(category_id))
    if q:
        where  += " AND (p.name LIKE ? OR p.barcode LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]

    products = db.execute(
        f"""SELECT p.id, p.name, p.barcode, p.category_name,
                   p.purchase_price, p.sale_price,
                   COALESCE(s.quantity, 0) AS stock_qty
            FROM products p
            LEFT JOIN stock s ON s.product_id = p.id
            {where}
            ORDER BY p.category_name, p.name
            LIMIT ? OFFSET ?""",
        params + [per_page, offset]
    ).fetchall()

    total = db.execute(
        f"SELECT COUNT(*) FROM products p {where}", params
    ).fetchone()[0]

    categories = db.execute(
        "SELECT id, name FROM product_categories WHERE business_id=? AND is_active=1 ORDER BY name",
        (biz_id,)
    ).fetchall()

    total_pages = max(1, (total + per_page - 1) // per_page)
    return render_template(
        "pricing.html",
        products=products,
        categories=categories,
        page=page,
        total_pages=total_pages,
        total=total,
        q=q,
        selected_cat=category_id,
    )


@app.route("/api/pricing/update", methods=["POST"])
@onboarding_required
def api_pricing_update():
    """تحديث سعر بيع منتج واحد (AJAX)"""
    data       = request.get_json(force=True) or {}
    biz_id     = session["business_id"]
    product_id = data.get("product_id")
    sale_price = data.get("sale_price")

    if product_id is None or sale_price is None:
        return jsonify({"success": False, "error": "بيانات ناقصة"}), 400

    try:
        sale_price = round(float(sale_price), 4)
        if sale_price < 0:
            return jsonify({"success": False, "error": "السعر لا يمكن أن يكون سالباً"}), 400
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "سعر غير صالح"}), 400

    db  = get_db()
    row = db.execute(
        "SELECT id, name, purchase_price FROM products WHERE id=? AND business_id=?",
        (int(product_id), biz_id)
    ).fetchone()
    if not row:
        return jsonify({"success": False, "error": "المنتج غير موجود"}), 404

    db.execute(
        "UPDATE products SET sale_price=?, updated_at=datetime('now') WHERE id=? AND business_id=?",
        (sale_price, int(product_id), biz_id)
    )
    db.commit()

    purchase = float(row["purchase_price"] or 0)
    margin   = round(((sale_price - purchase) / sale_price * 100), 1) if sale_price > 0 else 0
    return jsonify({
        "success":    True,
        "name":       row["name"],
        "sale_price": sale_price,
        "margin":     margin,
    })


# ════════════════════════════════════════════════════════════════════════════════
# RESTAURANT — إدارة الطاولات والمطبخ
# ════════════════════════════════════════════════════════════════════════════════

@app.route("/tables")
@onboarding_required
def tables():
    db     = get_db()
    biz_id = session["business_id"]

    row = db.execute(
        "SELECT value FROM settings WHERE business_id=? AND key='table_count'",
        (biz_id,)
    ).fetchone()
    table_count = int(row["value"]) if row else 10

    open_orders = db.execute(
        """SELECT i.id, i.party_name, i.status, i.subtotal, i.total, i.created_at,
                  COUNT(il.id) AS items_count
           FROM invoices i
           LEFT JOIN invoice_lines il ON il.invoice_id = i.id
           WHERE i.business_id=? AND i.invoice_type='table'
             AND i.status IN ('draft','partial','issued')
           GROUP BY i.id""",
        (biz_id,)
    ).fetchall()

    open_map = {o["party_name"]: dict(o) for o in open_orders}

    products = db.execute(
        """SELECT p.id, p.name, p.sale_price, p.category_name, p.barcode,
                  COALESCE(s.quantity, 0) AS stock_qty
           FROM products p
           LEFT JOIN stock s ON s.product_id = p.id
           WHERE p.business_id=? AND p.is_active=1 AND p.is_pos=1
           ORDER BY p.category_name, p.name LIMIT 300""",
        (biz_id,)
    ).fetchall()

    tables_list = []
    for i in range(1, table_count + 1):
        name  = f"طاولة {i}"
        order = open_map.get(name)
        tables_list.append({
            "number": i,
            "name":   name,
            "status": ("ready"    if order and order["status"] == "issued"
                       else "occupied" if order else "free"),
            "order":  order,
        })

    stats = {
        "free":     sum(1 for t in tables_list if t["status"] == "free"),
        "occupied": sum(1 for t in tables_list if t["status"] == "occupied"),
        "ready":    sum(1 for t in tables_list if t["status"] == "ready"),
    }

    return render_template(
        "tables.html",
        tables=tables_list,
        products=[dict(p) for p in products],
        stats=stats,
        table_count=table_count,
    )


@app.route("/api/tables/open", methods=["POST"])
@onboarding_required
def api_tables_open():
    data       = request.get_json(force=True) or {}
    biz_id     = session["business_id"]
    user_id    = session["user_id"]
    table_name = data.get("table_name", "").strip()

    if not table_name:
        return jsonify({"success": False, "error": "اسم الطاولة مطلوب"}), 400

    db = get_db()
    existing = db.execute(
        """SELECT id FROM invoices
           WHERE business_id=? AND party_name=? AND invoice_type='table'
             AND status IN ('draft','partial','issued')""",
        (biz_id, table_name)
    ).fetchone()
    if existing:
        return jsonify({
            "success": False, "error": "الطاولة مشغولة",
            "invoice_id": existing["id"]
        }), 409

    today = datetime.now().strftime("%Y-%m-%d")
    cnt   = db.execute(
        "SELECT COUNT(*) FROM invoices WHERE business_id=? AND invoice_type='table'",
        (biz_id,)
    ).fetchone()[0]
    inv_number = f"TBL-{cnt + 1:05d}"

    wh = db.execute(
        "SELECT id FROM warehouses WHERE business_id=? AND is_default=1 LIMIT 1",
        (biz_id,)
    ).fetchone()
    warehouse_id = wh["id"] if wh else None

    db.execute(
        """INSERT INTO invoices
           (business_id, invoice_number, invoice_type, invoice_date,
            party_name, subtotal, tax_amount, total, paid_amount,
            status, warehouse_id, created_by)
           VALUES (?,?,'table',?,?,0,0,0,0,'draft',?,?)""",
        (biz_id, inv_number, today, table_name, warehouse_id, user_id)
    )
    inv_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    db.commit()
    return jsonify({"success": True, "invoice_id": inv_id, "invoice_number": inv_number})


@app.route("/api/tables/add-item", methods=["POST"])
@onboarding_required
def api_tables_add_item():
    data       = request.get_json(force=True) or {}
    biz_id     = session["business_id"]
    invoice_id = data.get("invoice_id")
    product_id = data.get("product_id")
    quantity   = float(data.get("quantity", 1))

    if not invoice_id or not product_id:
        return jsonify({"success": False, "error": "بيانات ناقصة"}), 400

    db  = get_db()
    inv = db.execute(
        "SELECT * FROM invoices WHERE id=? AND business_id=? AND invoice_type='table' AND status IN ('draft','partial')",
        (int(invoice_id), biz_id)
    ).fetchone()
    if not inv:
        return jsonify({"success": False, "error": "الطلب غير موجود أو لا يمكن تعديله"}), 404

    product = db.execute(
        "SELECT * FROM products WHERE id=? AND business_id=? AND is_active=1",
        (int(product_id), biz_id)
    ).fetchone()
    if not product:
        return jsonify({"success": False, "error": "المنتج غير موجود"}), 404

    unit_price = float(product["sale_price"])
    existing   = db.execute(
        "SELECT id, quantity FROM invoice_lines WHERE invoice_id=? AND product_id=?",
        (int(invoice_id), int(product_id))
    ).fetchone()

    if existing:
        new_qty = float(existing["quantity"]) + quantity
        db.execute(
            "UPDATE invoice_lines SET quantity=?, total=? WHERE id=?",
            (new_qty, round(new_qty * unit_price, 4), existing["id"])
        )
    else:
        order_cnt = db.execute(
            "SELECT COUNT(*) FROM invoice_lines WHERE invoice_id=?", (int(invoice_id),)
        ).fetchone()[0]
        db.execute(
            """INSERT INTO invoice_lines
               (invoice_id, product_id, description, quantity, unit_price, total, line_order)
               VALUES (?,?,?,?,?,?,?)""",
            (int(invoice_id), int(product_id), product["name"],
             quantity, unit_price, round(quantity * unit_price, 4), order_cnt + 1)
        )

    totals   = db.execute(
        "SELECT SUM(total) AS s FROM invoice_lines WHERE invoice_id=?", (int(invoice_id),)
    ).fetchone()
    subtotal = round(float(totals["s"] or 0), 2)
    db.execute(
        "UPDATE invoices SET subtotal=?, total=? WHERE id=?",
        (subtotal, subtotal, int(invoice_id))
    )
    db.commit()
    return jsonify({"success": True, "subtotal": subtotal, "item_name": product["name"]})


@app.route("/api/tables/remove-item", methods=["POST"])
@onboarding_required
def api_tables_remove_item():
    data       = request.get_json(force=True) or {}
    biz_id     = session["business_id"]
    line_id    = data.get("line_id")
    invoice_id = data.get("invoice_id")

    if not line_id or not invoice_id:
        return jsonify({"success": False, "error": "بيانات ناقصة"}), 400

    db  = get_db()
    inv = db.execute(
        "SELECT id FROM invoices WHERE id=? AND business_id=? AND status='draft'",
        (int(invoice_id), biz_id)
    ).fetchone()
    if not inv:
        return jsonify({"success": False, "error": "لا يمكن تعديل طلب أُرسل للمطبخ"}), 403

    db.execute(
        "DELETE FROM invoice_lines WHERE id=? AND invoice_id=?",
        (int(line_id), int(invoice_id))
    )
    totals   = db.execute(
        "SELECT SUM(total) AS s FROM invoice_lines WHERE invoice_id=?", (int(invoice_id),)
    ).fetchone()
    subtotal = round(float(totals["s"] or 0), 2)
    db.execute(
        "UPDATE invoices SET subtotal=?, total=? WHERE id=?",
        (subtotal, subtotal, int(invoice_id))
    )
    db.commit()
    return jsonify({"success": True, "subtotal": subtotal})


@app.route("/api/tables/send-kitchen", methods=["POST"])
@onboarding_required
def api_tables_send_kitchen():
    data       = request.get_json(force=True) or {}
    biz_id     = session["business_id"]
    invoice_id = data.get("invoice_id")

    if not invoice_id:
        return jsonify({"success": False, "error": "معرّف الطلب مطلوب"}), 400

    db  = get_db()
    inv = db.execute(
        "SELECT * FROM invoices WHERE id=? AND business_id=? AND status='draft'",
        (int(invoice_id), biz_id)
    ).fetchone()
    if not inv:
        return jsonify({"success": False, "error": "الطلب غير موجود أو أُرسل مسبقاً"}), 404

    cnt = db.execute(
        "SELECT COUNT(*) FROM invoice_lines WHERE invoice_id=?", (int(invoice_id),)
    ).fetchone()[0]
    if cnt == 0:
        return jsonify({"success": False, "error": "الطلب فارغ — أضف أصنافاً أولاً"}), 400

    db.execute(
        "UPDATE invoices SET status='partial' WHERE id=? AND business_id=?",
        (int(invoice_id), biz_id)
    )
    db.commit()
    return jsonify({"success": True, "message": "تم إرسال الطلب للمطبخ"})


@app.route("/api/tables/checkout", methods=["POST"])
@onboarding_required
def api_tables_checkout():
    """إغلاق الطاولة + توليد القيد المحاسبي آلياً"""
    data           = request.get_json(force=True) or {}
    biz_id         = session["business_id"]
    user_id        = session["user_id"]
    invoice_id     = data.get("invoice_id")
    payment_method = data.get("payment_method", "cash")

    if not invoice_id:
        return jsonify({"success": False, "error": "معرّف الطلب مطلوب"}), 400

    db  = get_db()
    inv = db.execute(
        """SELECT * FROM invoices
           WHERE id=? AND business_id=? AND invoice_type='table'
             AND status IN ('draft','partial','issued')""",
        (int(invoice_id), biz_id)
    ).fetchone()
    if not inv:
        return jsonify({"success": False, "error": "الطلب غير موجود أو مغلق مسبقاً"}), 404

    lines = db.execute(
        """SELECT il.*, p.purchase_price
           FROM invoice_lines il
           LEFT JOIN products p ON p.id = il.product_id
           WHERE il.invoice_id=?""",
        (int(invoice_id),)
    ).fetchall()

    if not lines:
        return jsonify({"success": False, "error": "الطلب فارغ"}), 400

    grand_total = float(inv["total"])
    if grand_total <= 0:
        return jsonify({"success": False, "error": "إجمالي الطلب صفر"}), 400

    cash_code    = "1102" if payment_method == "bank" else "1101"
    cash_acc_id  = get_account_id(db, biz_id, cash_code)
    sales_acc_id = get_account_id(db, biz_id, "4101")
    cogs_acc_id  = get_account_id(db, biz_id, "5101")
    inv_acc_id   = get_account_id(db, biz_id, "1104")

    if not all([cash_acc_id, sales_acc_id]):
        return jsonify({"success": False, "error": "شجرة الحسابات غير مكتملة"}), 400

    wh_id      = inv["warehouse_id"]
    today      = datetime.now().strftime("%Y-%m-%d")
    now        = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subtotal   = float(inv["subtotal"])
    cogs_total = round(
        sum(float(l["quantity"]) * float(l["purchase_price"] or 0) for l in lines), 2
    )

    try:
        # خصم المخزون + تسجيل الحركات
        if wh_id:
            for line in lines:
                if not line["product_id"]:
                    continue
                db.execute(
                    "INSERT OR IGNORE INTO stock (business_id,product_id,warehouse_id,quantity,avg_cost) VALUES (?,?,?,0,0)",
                    (biz_id, line["product_id"], wh_id)
                )
                db.execute(
                    "UPDATE stock SET quantity=quantity-?,last_updated=? WHERE product_id=? AND warehouse_id=?",
                    (float(line["quantity"]), now, line["product_id"], wh_id)
                )
                db.execute(
                    """INSERT INTO stock_movements
                       (business_id,product_id,warehouse_id,movement_type,
                        quantity,unit_cost,reference_type,reference_id,created_by)
                       VALUES (?,?,?,'sale',?,?,'invoice',?,?)""",
                    (biz_id, line["product_id"], wh_id, -float(line["quantity"]),
                     float(line["purchase_price"] or 0), int(invoice_id), user_id)
                )

        # قيد المبيعات: د/الصندوق — ك/إيرادات
        je_num = next_entry_number(db, biz_id)
        db.execute(
            """INSERT INTO journal_entries
               (business_id,entry_number,entry_date,description,
                reference_type,reference_id,total_debit,total_credit,is_posted,created_by)
               VALUES (?,?,?,?,?,?,?,?,1,?)""",
            (biz_id, je_num, today,
             f"مبيعات مطعم — {inv['party_name']} — {inv['invoice_number']}",
             "invoice", int(invoice_id), grand_total, grand_total, user_id)
        )
        je_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        cash_label = "نقداً" if payment_method == "cash" else "بطاقة/تحويل"
        db.execute(
            "INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
            (je_id, cash_acc_id, cash_label, grand_total, 0, 1)
        )
        db.execute(
            "INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
            (je_id, sales_acc_id, f"إيرادات مطعم — {inv['party_name']}", 0, subtotal, 2)
        )

        # قيد تكلفة البضاعة المباعة
        if cogs_total > 0 and cogs_acc_id and inv_acc_id:
            je_cogs_num = next_entry_number(db, biz_id)
            db.execute(
                """INSERT INTO journal_entries
                   (business_id,entry_number,entry_date,description,
                    reference_type,reference_id,total_debit,total_credit,is_posted,created_by)
                   VALUES (?,?,?,?,?,?,?,?,1,?)""",
                (biz_id, je_cogs_num, today,
                 f"تكلفة مبيعات مطعم — {inv['party_name']}",
                 "invoice", int(invoice_id), cogs_total, cogs_total, user_id)
            )
            je_cogs_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.execute(
                "INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
                (je_cogs_id, cogs_acc_id, "تكلفة مبيعات مطعم", cogs_total, 0, 1)
            )
            db.execute(
                "INSERT INTO journal_entry_lines (entry_id,account_id,description,debit,credit,line_order) VALUES (?,?,?,?,?,?)",
                (je_cogs_id, inv_acc_id, "إقفال مخزون مطعم", 0, cogs_total, 2)
            )

        db.execute(
            "UPDATE invoices SET status='paid',paid_amount=?,journal_entry_id=? WHERE id=?",
            (grand_total, je_id, int(invoice_id))
        )
        db.commit()

        return jsonify({
            "success":        True,
            "total":          grand_total,
            "invoice_number": inv["invoice_number"],
            "table_name":     inv["party_name"],
            "message":        f"تم إغلاق {inv['party_name']} وتوليد القيد المحاسبي ✓",
        })

    except Exception as e:
        db.rollback()
        app.logger.error(f"Table checkout error: {e}")
        return jsonify({"success": False, "error": "حدث خطأ — يرجى المحاولة مرة أخرى"}), 500


@app.route("/api/tables/order-lines/<int:invoice_id>")
@onboarding_required
def api_tables_order_lines(invoice_id):
    """جلب بنود طلب طاولة (AJAX)"""
    biz_id = session["business_id"]
    db     = get_db()

    inv = db.execute(
        "SELECT * FROM invoices WHERE id=? AND business_id=? AND invoice_type='table'",
        (invoice_id, biz_id)
    ).fetchone()
    if not inv:
        return jsonify({"success": False, "error": "الطلب غير موجود"}), 404

    lines = db.execute(
        """SELECT il.id, il.product_id, il.description, il.quantity, il.unit_price, il.total
           FROM invoice_lines il
           WHERE il.invoice_id=? ORDER BY il.line_order""",
        (invoice_id,)
    ).fetchall()

    return jsonify({
        "success": True,
        "invoice": dict(inv),
        "lines":   [dict(l) for l in lines],
    })


# ════════════════════════════════════════════════════════════════════════════════
# KITCHEN — شاشة المطبخ KDS
# ════════════════════════════════════════════════════════════════════════════════

@app.route("/kitchen")
@onboarding_required
def kitchen():
    db     = get_db()
    biz_id = session["business_id"]

    orders = db.execute(
        """SELECT i.id, i.invoice_number, i.party_name, i.status, i.created_at, i.total
           FROM invoices i
           WHERE i.business_id=? AND i.invoice_type='table'
             AND i.status IN ('partial','issued')
           ORDER BY i.created_at ASC""",
        (biz_id,)
    ).fetchall()

    orders_with_lines = []
    for o in orders:
        lines = db.execute(
            """SELECT il.id, il.description, il.quantity, il.unit_price
               FROM invoice_lines il
               WHERE il.invoice_id=? ORDER BY il.line_order""",
            (o["id"],)
        ).fetchall()
        orders_with_lines.append({"order": dict(o), "lines": [dict(l) for l in lines]})

    return render_template("kitchen.html", orders=orders_with_lines)


@app.route("/api/kitchen/done", methods=["POST"])
@onboarding_required
def api_kitchen_done():
    data       = request.get_json(force=True) or {}
    biz_id     = session["business_id"]
    invoice_id = data.get("invoice_id")

    if not invoice_id:
        return jsonify({"success": False, "error": "معرّف الطلب مطلوب"}), 400

    db  = get_db()
    inv = db.execute(
        "SELECT id, party_name FROM invoices WHERE id=? AND business_id=? AND status='partial'",
        (int(invoice_id), biz_id)
    ).fetchone()
    if not inv:
        return jsonify({"success": False, "error": "الطلب غير موجود أو تم تجهيزه مسبقاً"}), 404

    db.execute(
        "UPDATE invoices SET status='issued' WHERE id=? AND business_id=?",
        (int(invoice_id), biz_id)
    )
    db.commit()
    return jsonify({"success": True, "message": f"✓ تم تجهيز {inv['party_name']}"})


# ─── API: معلومات المستخدم الحالي ─────────────────────────────────────────────
@app.route("/api/me")
@login_required
def api_me():
    if not g.user or not g.business:
        return jsonify({"error": "غير مصرح"}), 401
    return jsonify({
        "user": {
            "id":        g.user["id"],
            "username":  g.user["username"],
            "full_name": g.user["full_name"],
            "role":      g.user["role_name"],
        },
        "business": {
            "id":            g.business["id"],
            "name":          g.business["name"],
            "industry_type": g.business["industry_type"],
            "currency":      g.business["currency"],
        },
        "sidebar": g.sidebar_items,
    })


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)
