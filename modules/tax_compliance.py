"""
modules/tax_compliance.py
محرك امتثال ضريبي متعدد الدول قبل اعتماد/تحصيل الفاتورة.
"""
from __future__ import annotations

import re
from typing import Any

from modules.country_engine import get_business_country


def _clean(val: Any) -> str:
    return str(val or "").strip()


def _is_sa_vat_number(v: str) -> bool:
    # تنسيق ZATCA الشائع: 15 رقم ويبدأ/ينتهي بـ 3.
    return bool(re.fullmatch(r"3\d{13}3", v))


def _is_numeric_len(v: str, min_len: int, max_len: int) -> bool:
    return v.isdigit() and min_len <= len(v) <= max_len


def _is_alnum_len(v: str, min_len: int, max_len: int) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9\-]+", v)) and min_len <= len(v) <= max_len


def _country_rule(country_code: str, tax_system: str) -> dict:
    code = (country_code or "SA").upper()
    system = (tax_system or "none").lower()

    # قاعدة عامة حسب النظام.
    base = {
        "must_have_seller_tax_number": system in {"zatca", "vat", "sales_tax"},
        "must_have_party_name": True,
        "must_have_tax_for_paid_when_taxed": system in {"zatca", "vat", "sales_tax"},
        "invoice_archive_years": 5,
        "platform_compliance_hint": "نوصي بالتوقيع الرقمي وسجل تدقيق غير قابل للعبث للإصدارات المؤسسية.",
    }

    # تخصيصات دولة.
    if code == "SA":
        base.update({
            "must_have_seller_tax_number": True,
            "seller_tax_validation": "sa_vat_15",
            "must_have_party_tax_number_for_b2b": False,
            "invoice_archive_years": 6,
            "authority_name": "هيئة الزكاة والضريبة والجمارك",
            "platform_compliance_hint": "للسعودية: تأكد من اكتمال متطلبات ZATCA عند التكامل الإلكتروني.",
        })
    elif code in {"AE", "BH", "OM", "EG", "MA", "TN", "GB"}:
        base.update({
            "seller_tax_validation": "alnum_8_20",
            "authority_name": "الهيئة الضريبية المحلية",
        })
    elif code == "US":
        base.update({
            "seller_tax_validation": "alnum_6_20",
            "authority_name": "Tax Authority",
            "must_have_party_tax_number_for_b2b": False,
            "invoice_archive_years": 7,
        })
    else:
        base.update({
            "seller_tax_validation": "generic",
            "authority_name": "الجهة الضريبية المختصة",
        })

    return base


def get_compliance_profile(db, business_id: int, country_profile: dict | None = None) -> dict:
    cp = country_profile or get_business_country(db, int(business_id))
    cc = (cp.get("country_code") or "SA").upper()
    tax_system = (cp.get("tax_system") or "none").lower()
    tax_label_ar = cp.get("tax_label_ar", "الضريبة")
    tax_number_label = cp.get("tax_number_label", "الرقم الضريبي")
    default_tax_rate = float(cp.get("default_tax_rate", 0) or 0)

    rule = _country_rule(cc, tax_system)
    return {
        "country_code": cc,
        "country_name_ar": cp.get("country_name_ar", "غير محدد"),
        "tax_system": tax_system,
        "tax_label_ar": tax_label_ar,
        "tax_number_label": tax_number_label,
        "default_tax_rate": default_tax_rate,
        "currency_symbol": cp.get("currency_symbol", ""),
        "requires_zatca": bool(cp.get("requires_zatca", 0)),
        "rule": rule,
    }


def _validate_seller_tax_number(raw: str, rule_name: str) -> bool:
    val = _clean(raw)
    if not val:
        return False
    if rule_name == "sa_vat_15":
        return _is_sa_vat_number(val)
    if rule_name == "numeric_8_20":
        return _is_numeric_len(val, 8, 20)
    if rule_name == "alnum_8_20":
        return _is_alnum_len(val, 8, 20)
    if rule_name == "alnum_6_20":
        return _is_alnum_len(val, 6, 20)
    return len(val) >= 4


def validate_invoice_compliance(
    db,
    business_id: int,
    *,
    invoice_data: dict,
    stage: str,
    country_profile: dict | None = None,
) -> dict:
    """
    stage:
      - issue: قبل إصدار/حفظ فاتورة تشغيلية (pending/paid)
      - pay: قبل تغيير الحالة إلى paid
    """
    profile = get_compliance_profile(db, int(business_id), country_profile=country_profile)
    rule = profile["rule"]

    errors: list[str] = []
    warnings: list[str] = []

    biz = db.execute(
        "SELECT name, tax_number, country_code FROM businesses WHERE id=?",
        (business_id,),
    ).fetchone()

    seller_name = _clean((biz or {}).get("name") if biz else "")
    seller_tax_number = _clean((biz or {}).get("tax_number") if biz else "")

    party_name = _clean(invoice_data.get("party_name"))
    party_tax_number = _clean(invoice_data.get("party_vat"))
    tax_amount = float(invoice_data.get("tax_amount") or 0)

    if not seller_name:
        errors.append("اسم المنشأة مفقود. أكمل بيانات المنشأة من الإعدادات.")

    if rule.get("must_have_party_name", True) and not party_name:
        errors.append("اسم العميل/الطرف مطلوب لإصدار الفاتورة.")

    if rule.get("must_have_seller_tax_number"):
        if not seller_tax_number:
            errors.append(f"{profile['tax_number_label']} للمنشأة مطلوب وفق نظام {profile['tax_label_ar']}.")
        else:
            rule_name = rule.get("seller_tax_validation", "generic")
            if not _validate_seller_tax_number(seller_tax_number, rule_name):
                errors.append(f"تنسيق {profile['tax_number_label']} للمنشأة غير صحيح لدولة {profile['country_name_ar']}.")

    # عندما الفاتورة تحتوي ضريبة فعلية يجب أن تكون بيانات الضريبة مكتملة.
    if tax_amount > 0 and rule.get("must_have_tax_for_paid_when_taxed"):
        if not seller_tax_number:
            errors.append(f"لا يمكن اعتماد فاتورة بضريبة بدون {profile['tax_number_label']} للمنشأة.")

    if stage == "pay" and tax_amount > 0 and rule.get("must_have_party_tax_number_for_b2b", False):
        if not party_tax_number:
            warnings.append(f"يُفضّل إدخال {profile['tax_number_label']} للطرف المقابل للفواتير B2B.")

    # ملاحظة امتثال عامة لمنصات الشركات الكبرى.
    warnings.append(rule.get("platform_compliance_hint", ""))

    warnings = [w for w in warnings if _clean(w)]

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "profile": profile,
    }


def validate_seller_tax_number_for_business(
    db,
    business_id: int,
    tax_number: str,
    country_profile: dict | None = None,
) -> tuple[bool, str]:
    profile = get_compliance_profile(db, int(business_id), country_profile=country_profile)
    rule = profile["rule"]

    val = _clean(tax_number)
    if not val:
        if rule.get("must_have_seller_tax_number"):
            return False, f"{profile['tax_number_label']} مطلوب وفق نظام {profile['tax_label_ar']}."
        return True, ""

    rule_name = rule.get("seller_tax_validation", "generic")
    if not _validate_seller_tax_number(val, rule_name):
        return False, f"تنسيق {profile['tax_number_label']} غير صحيح لدولة {profile['country_name_ar']}."

    return True, ""


def build_business_compliance_report(
    db,
    business_id: int,
    country_profile: dict | None = None,
) -> dict:
    profile = get_compliance_profile(db, int(business_id), country_profile=country_profile)

    biz = db.execute(
        "SELECT name, tax_number, cr_number, address, city, phone, email FROM businesses WHERE id=?",
        (business_id,),
    ).fetchone()
    biz = dict(biz) if biz else {}

    checks: list[dict] = []

    def add_check(code: str, label: str, ok: bool, severity: str = "high", note: str = ""):
        checks.append({
            "code": code,
            "label": label,
            "ok": bool(ok),
            "severity": severity,
            "note": note,
        })

    add_check("business_name", "اسم المنشأة", bool(_clean(biz.get("name"))), "high")

    tax_ok, tax_msg = validate_seller_tax_number_for_business(
        db,
        int(business_id),
        _clean(biz.get("tax_number")),
        country_profile=country_profile,
    )
    add_check("tax_number", profile["tax_number_label"], tax_ok, "high", tax_msg)

    cr_ok = bool(_clean(biz.get("cr_number")))
    add_check("cr_number", "رقم السجل/التسجيل التجاري", cr_ok, "medium")

    add_check("address", "العنوان", bool(_clean(biz.get("address"))), "medium")
    add_check("city", "المدينة", bool(_clean(biz.get("city"))), "low")
    add_check("phone", "رقم الاتصال", bool(_clean(biz.get("phone"))), "low")
    add_check("email", "البريد الإلكتروني", bool(_clean(biz.get("email"))), "low")

    high_missing = sum(1 for c in checks if (not c["ok"] and c["severity"] == "high"))
    medium_missing = sum(1 for c in checks if (not c["ok"] and c["severity"] == "medium"))
    low_missing = sum(1 for c in checks if (not c["ok"] and c["severity"] == "low"))

    score = 100
    score -= high_missing * 25
    score -= medium_missing * 10
    score -= low_missing * 5
    score = max(0, min(100, score))

    if high_missing > 0:
        level = "critical"
    elif medium_missing > 0:
        level = "warning"
    else:
        level = "good"

    return {
        "profile": profile,
        "checks": checks,
        "score": score,
        "level": level,
        "missing": {
            "high": high_missing,
            "medium": medium_missing,
            "low": low_missing,
        },
    }
