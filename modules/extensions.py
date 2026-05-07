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

from .config import DB_PATH, UPLOAD_FOLDER, ALLOWED_EXT


# ─── قاعدة البيانات ───────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=5)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA busy_timeout = 5000")
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


class InsufficientStockError(ValueError):
    def __init__(self, product_name: str, available_qty: float, requested_qty: float):
        self.product_name = product_name
        self.available_qty = float(available_qty or 0)
        self.requested_qty = float(requested_qty or 0)
        super().__init__(product_name)


def get_stock_quantity(
    db: sqlite3.Connection,
    business_id: int,
    product_id: int,
    warehouse_id: int | None,
) -> float:
    if not warehouse_id:
        return 0.0
    row = db.execute(
        """SELECT quantity FROM stock
           WHERE business_id=? AND product_id=? AND warehouse_id=?""",
        (business_id, product_id, warehouse_id),
    ).fetchone()
    return float(row["quantity"] or 0) if row else 0.0


def assert_stock_available(
    db: sqlite3.Connection,
    business_id: int,
    product_id: int,
    warehouse_id: int | None,
    requested_qty: float,
    product_name: str,
) -> float:
    available_qty = get_stock_quantity(db, business_id, product_id, warehouse_id)
    if warehouse_id and available_qty < requested_qty:
        raise InsufficientStockError(product_name, available_qty, requested_qty)
    return available_qty


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
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM invoices WHERE business_id=? AND invoice_type='sale'",
        (business_id,)
    ).fetchone()
    seq = (row["cnt"] or 0) + 1
    return f"{prefix}-{seq:05d}"


def next_entry_number(db: sqlite3.Connection, business_id: int) -> str:
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM journal_entries WHERE business_id=?",
        (business_id,)
    ).fetchone()
    seq = (row["cnt"] or 0) + 1
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
