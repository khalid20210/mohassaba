"""
modules/country_engine.py — محرك التوسع الإقليمي
===================================================
يُوفر بروفايل كل دولة (عملة، ضريبة، نظام ضريبي) من قاعدة البيانات.
إضافة دولة جديدة = INSERT في country_configs فقط، لا تعديل كود.

الاستخدام:
    from modules.country_engine import get_country, get_business_country

    # جلب بروفايل دولة مباشرة
    sa = get_country("SA")   # {'currency_symbol': 'ر.س', 'default_tax_rate': 15, ...}

    # جلب بروفايل منشأة حالية (من الجلسة)
    profile = get_business_country(db, biz_id)
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional


# ── قيم افتراضية آمنة إذا لم تُوجد الدولة في DB ───────────────────────────
_FALLBACK: dict = {
    "country_code":     "SA",
    "country_name_ar":  "غير محدد",
    "country_name_en":  "Unknown",
    "currency_code":    "SAR",
    "currency_symbol":  "ر.س",
    "currency_name_ar": "ريال سعودي",
    "default_tax_rate": 15.0,
    "tax_system":       "zatca",
    "tax_label_ar":     "ضريبة القيمة المضافة",
    "tax_label_en":     "VAT",
    "tax_number_label": "الرقم الضريبي",
    "invoice_prefix":   "INV",
    "date_format":      "YYYY-MM-DD",
    "phone_prefix":     "+966",
    "requires_zatca":   1,
    "is_active":        1,
    "extra_config":     "{}",
}


def get_country(db, country_code: str) -> dict:
    """
    إرجاع بروفايل دولة من قاعدة البيانات.
    إذا لم توجد الدولة، يُرجع السعودية كافتراضي.
    """
    row = db.execute(
        "SELECT * FROM country_configs WHERE country_code=? AND is_active=1",
        (country_code.upper(),)
    ).fetchone()
    if row:
        return dict(row)
    # fallback: جرّب السعودية
    row = db.execute(
        "SELECT * FROM country_configs WHERE country_code='SA' AND is_active=1"
    ).fetchone()
    return dict(row) if row else _FALLBACK.copy()


def get_business_country(db, business_id: int) -> dict:
    """
    جلب بروفايل الدولة المرتبطة بمنشأة معينة.
    """
    biz = db.execute(
        "SELECT country_code FROM businesses WHERE id=?", (business_id,)
    ).fetchone()
    code = (biz["country_code"] if biz and biz["country_code"] else "SA")
    return get_country(db, code)


def list_countries(db) -> list[dict]:
    """إرجاع قائمة الدول المدعومة (للـ dropdowns)"""
    rows = db.execute(
        "SELECT country_code, country_name_ar, country_name_en, "
        "currency_symbol, currency_code, default_tax_rate, tax_system "
        "FROM country_configs WHERE is_active=1 ORDER BY country_name_ar"
    ).fetchall()
    return [dict(r) for r in rows]


def get_tax_rate(db, business_id: int) -> float:
    """
    إرجاع نسبة الضريبة للمنشأة:
    1. من tax_settings إذا ضُبطت يدوياً
    2. من country_configs كافتراضي
    """
    # أولاً: من إعدادات الضريبة الخاصة بالمنشأة
    row = db.execute(
        "SELECT rate FROM tax_settings WHERE business_id=? AND is_active=1 ORDER BY id LIMIT 1",
        (business_id,)
    ).fetchone()
    if row:
        return float(row["rate"])
    # ثانياً: من بروفايل الدولة
    profile = get_business_country(db, business_id)
    return float(profile.get("default_tax_rate", 15))


def requires_zatca(db, business_id: int) -> bool:
    """هل تحتاج هذه المنشأة لإصدار ZATCA؟"""
    profile = get_business_country(db, business_id)
    return bool(profile.get("requires_zatca", 0))


def format_currency(amount: float, profile: dict, decimals: int = 2) -> str:
    """تنسيق المبلغ مع رمز العملة"""
    symbol = profile.get("currency_symbol", "ر.س")
    return f"{amount:,.{decimals}f} {symbol}"
