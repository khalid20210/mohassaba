"""
modules/extensions.py — مساعدات مشتركة: قاعدة البيانات، المصادقة، ZATCA، محاسبة
"""
import base64
import hashlib
import json
import re
import secrets
import sqlite3
from datetime import datetime
from pathlib import Path

try:
    import bcrypt as _bcrypt
    _BCRYPT_AVAILABLE = True
except ImportError:
    _bcrypt = None
    _BCRYPT_AVAILABLE = False

from flask import g, request, session, redirect, url_for, flash

from .config import (
    DB_PATH,
    UPLOAD_FOLDER,
    ALLOWED_EXT,
    SQLITE_BUSY_TIMEOUT_MS,
    SQLITE_JOURNAL_MODE,
    SQLITE_SYNCHRONOUS,
    SQLITE_CACHE_SIZE,
)


# ─── قاعدة البيانات ───────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(
            DB_PATH,
            timeout=max(1, SQLITE_BUSY_TIMEOUT_MS // 1000),
            check_same_thread=False,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
        g.db.execute(f"PRAGMA journal_mode = {SQLITE_JOURNAL_MODE}")
        g.db.execute(f"PRAGMA synchronous = {SQLITE_SYNCHRONOUS}")
        g.db.execute(f"PRAGMA cache_size = {SQLITE_CACHE_SIZE}")
        g.db.execute("PRAGMA temp_store = MEMORY")
        g.db.execute("PRAGMA wal_autocheckpoint = 10000")
        g.db.execute("PRAGMA mmap_size = 268435456")
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ─── كلمة المرور ──────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """bcrypt إن كان متوفراً، وإلا SHA-256+salt"""
    if _BCRYPT_AVAILABLE:
        hashed = _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt(rounds=12))
        return hashed.decode("utf-8")
    salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{h}"


def check_password(stored: str, password: str) -> bool:
    """يدعم bcrypt الجديد + SHA-256+salt القديم"""
    try:
        if stored.startswith("$2") and _BCRYPT_AVAILABLE:
            return _bcrypt.checkpw(password.encode("utf-8"), stored.encode("utf-8"))
        if ":" in stored:
            salt, h = stored.split(":", 1)
            return hashlib.sha256(f"{salt}{password}".encode()).hexdigest() == h
        return False
    except Exception:
        return False


# ─── CSRF ─────────────────────────────────────────────────────────────────────

def generate_csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]


def validate_csrf() -> bool:
    token_session = session.get("csrf_token")
    token_form    = (request.form.get("csrf_token")
                     or request.headers.get("X-CSRF-Token"))
    if not token_session or not token_form:
        return False
    return secrets.compare_digest(token_session, token_form)


def csrf_protect():
    """يُستدعى في أي route يقبل POST بيانات form. يُعيد None إن كان آمناً."""
    if request.method == "POST" and not request.is_json:
        if not validate_csrf():
            flash("طلب غير صالح — يرجى إعادة المحاولة", "error")
            return redirect(request.referrer or url_for("core.dashboard"))
    return None


# ─── تشفير النسخ الاحتياطية (AES-256-GCM عبر Fernet/cryptography) ─────────────

def encrypt_backup(data_bytes: bytes, password: str) -> bytes:
    """
    يشفر النسخة الاحتياطية بـ AES-256-GCM (عبر مكتبة cryptography).
    يُنتج ملف: [salt(16)] + [iv(12)] + [tag(16)] + [ciphertext].
    المفتاح يُشتق بـ PBKDF2-HMAC-SHA256 (310000 iteration).
    يُعيد bytes جاهزة للتحميل.
    الرسالة الافتراضية بدون تشفير إن لم تتوفر المكتبة.
    """
    if not password:
        return data_bytes  # لا تشفير بدون كلمة مرور

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes
        import os as _os

        salt = _os.urandom(16)
        kdf  = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=310_000,
        )
        key = kdf.derive(password.encode("utf-8"))
        iv  = _os.urandom(12)
        aesgcm     = AESGCM(key)
        ciphertext = aesgcm.encrypt(iv, data_bytes, None)  # includes tag (last 16 bytes)

        return salt + iv + ciphertext

    except ImportError:
        # fallback: حزمة cryptography غير مثبّتة — بدون تشفير مع تحذير في الـ header
        _warning = b"\x00UNENCRYPTED_BACKUP\x00"
        return _warning + data_bytes


def decrypt_backup(data_bytes: bytes, password: str) -> bytes:
    """
    يفك تشفير ملف نسخ احتياطية مشفر بـ encrypt_backup.
    يُعيد bytes الأصلية.
    """
    if not password:
        return data_bytes

    if data_bytes[:20] == b"\x00UNENCRYPTED_BACKUP\x00":
        return data_bytes[20:]

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        from cryptography.hazmat.primitives import hashes

        salt       = data_bytes[:16]
        iv         = data_bytes[16:28]
        ciphertext = data_bytes[28:]

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=310_000,
        )
        key    = kdf.derive(password.encode("utf-8"))
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(iv, ciphertext, None)

    except Exception as exc:
        raise ValueError(f"فشل فك التشفير — كلمة المرور غير صحيحة أو الملف تالف: {exc}") from exc


# ─── ZATCA QR — المرحلة الأولى (TLV Base64) ──────────────────────────────────

def zatca_qr_b64(seller: str, vat_number: str, timestamp: str,
                  total: float, vat: float) -> str:
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
    row = db.execute(
        "SELECT id FROM accounts WHERE business_id=? AND code=?",
        (business_id, code)
    ).fetchone()
    return row["id"] if row else None


def next_invoice_number(db: sqlite3.Connection, business_id: int) -> str:
    prefix_row = db.execute(
        "SELECT value FROM settings WHERE business_id=? AND key='invoice_prefix_sale'",
        (business_id,)
    ).fetchone()
    prefix = prefix_row["value"] if prefix_row else "INV"

    # ── جدول عدادات سريع (O(1)) ────────────────────────────────────────────
    db.execute(
        """CREATE TABLE IF NOT EXISTS biz_counters (
               business_id INTEGER NOT NULL,
               counter_key TEXT NOT NULL,
               seq         INTEGER NOT NULL DEFAULT 0,
               PRIMARY KEY (business_id, counter_key)
           )"""
    )
    key = f"invoice_sale_{prefix}"
    db.execute(
        "INSERT OR IGNORE INTO biz_counters (business_id, counter_key, seq) VALUES (?,?,0)",
        (business_id, key)
    )
    db.execute(
        "UPDATE biz_counters SET seq=seq+1 WHERE business_id=? AND counter_key=?",
        (business_id, key)
    )
    row = db.execute(
        "SELECT seq FROM biz_counters WHERE business_id=? AND counter_key=?",
        (business_id, key)
    ).fetchone()
    seq = row["seq"] if row else 1
    return f"{prefix}-{seq:05d}"


def next_entry_number(db: sqlite3.Connection, business_id: int) -> str:
    # ── جدول عدادات سريع (O(1)) ────────────────────────────────────────────
    db.execute(
        """CREATE TABLE IF NOT EXISTS biz_counters (
               business_id INTEGER NOT NULL,
               counter_key TEXT NOT NULL,
               seq         INTEGER NOT NULL DEFAULT 0,
               PRIMARY KEY (business_id, counter_key)
           )"""
    )
    key = "journal_entry"
    db.execute(
        "INSERT OR IGNORE INTO biz_counters (business_id, counter_key, seq) VALUES (?,?,0)",
        (business_id, key)
    )
    db.execute(
        "UPDATE biz_counters SET seq=seq+1 WHERE business_id=? AND counter_key=?",
        (business_id, key)
    )
    row = db.execute(
        "SELECT seq FROM biz_counters WHERE business_id=? AND counter_key=?",
        (business_id, key)
    ).fetchone()
    seq = row["seq"] if row else 1
    return f"JE-{seq:06d}"


def seed_business_accounts(db: sqlite3.Connection, business_id: int):
    """إنشاء شجرة حسابات + أدوار النظام لمنشأة جديدة (idempotent)"""
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
            "INSERT OR IGNORE INTO roles (business_id, name, permissions, is_system) VALUES (?,?,?,1)",
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


# ─── مساعدات OCR / رفع الملفات ───────────────────────────────────────────────

def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def _extract_text_from_pdf(path: Path) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except ImportError:
        pass
    try:
        raw = path.read_bytes()
        text = raw.decode("latin-1", errors="ignore")
        parts = re.findall(r"BT(.+?)ET", text, re.DOTALL)
        return " ".join(parts)
    except Exception:
        return ""


def _extract_text_from_image(path: Path) -> str:
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(path)
        return pytesseract.image_to_string(img, lang="ara+eng")
    except ImportError:
        return ""
    except Exception:
        return ""


def _parse_invoice_lines(text: str, products: list) -> list:
    lines    = []
    prod_map = {p["name"].strip(): p for p in products}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        nums = re.findall(r"[\d.,]+", line)
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
