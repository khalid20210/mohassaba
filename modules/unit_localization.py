"""
modules/unit_localization.py
توحيد أسماء وحدات البيع/التعبئة عبر الدول مع الحفاظ على كود داخلي ثابت.
"""

from __future__ import annotations


# أكواد موحّدة (لا تتغير بين الدول)
_UNIT_DISPLAY = {
    "piece": {
        "ar": "قطعة",
        "en": "Piece",
    },
    "carton": {
        "ar": "كرتون",
        "en": "Carton",
    },
    "case": {
        "ar": "صندوق",
        "en": "Case",
    },
    "pack": {
        "ar": "باك",
        "en": "Pack",
    },
    "bundle": {
        "ar": "ربطة",
        "en": "Bundle",
    },
    "pallet": {
        "ar": "باليت",
        "en": "Pallet",
    },
    "roll": {
        "ar": "رولة",
        "en": "Roll",
    },
}


# aliases متعددة لنفس الوحدة (عالمي + عربي)
_ALIAS_TO_CODE = {
    # piece
    "قطعة": "piece",
    "حبة": "piece",
    "وحدة": "piece",
    "piece": "piece",
    "pcs": "piece",
    "pc": "piece",
    "unit": "piece",
    # carton
    "كرتون": "carton",
    "carton": "carton",
    "ctn": "carton",
    # case
    "صندوق": "case",
    "case": "case",
    "cs": "case",
    "crate": "case",
    # pack
    "باك": "pack",
    "عبوة": "pack",
    "pack": "pack",
    "pk": "pack",
    # bundle
    "ربطة": "bundle",
    "حزمة": "bundle",
    "bundle": "bundle",
    "bdl": "bundle",
    # pallet
    "باليت": "pallet",
    "طبليه": "pallet",
    "palette": "pallet",
    "pallet": "pallet",
    "plt": "pallet",
    # roll
    "رولة": "roll",
    "لفة": "roll",
    "roll": "roll",
    "rl": "roll",
}


# الوحدات النشطة الفقط لكل بلد (الباقي يختفي نهائياً من الواجهة)
_COUNTRY_ACTIVE_UNITS = {
    # دول الخليج
    "SA": ["piece", "carton", "case", "pallet"],
    "AE": ["piece", "carton", "case", "pallet"],
    "KW": ["piece", "carton", "case", "pallet"],
    "QA": ["piece", "carton", "case", "pallet"],
    "BH": ["piece", "carton", "case", "pallet"],
    "OM": ["piece", "carton", "case", "pallet"],
    # دول عربية أخرى
    "EG": ["piece", "carton", "case", "pallet"],
    "JO": ["piece", "carton", "case", "pallet"],
    "IQ": ["piece", "carton", "case", "pallet"],
    "LB": ["piece", "carton", "case", "pallet"],
    "SY": ["piece", "carton", "case", "pallet"],
    "PS": ["piece", "carton", "case", "pallet"],
    "YE": ["piece", "carton", "case", "pallet"],
    "SD": ["piece", "carton", "case", "pallet"],
    "LY": ["piece", "carton", "case", "pallet"],
    "TN": ["piece", "carton", "case", "pallet"],
    "DZ": ["piece", "carton", "case", "pallet"],
    "MA": ["piece", "carton", "case", "pallet"],
    # دول أجنبية
    "US": ["piece", "case", "pack", "pallet"],
    "GB": ["piece", "case", "pack", "pallet"],
    "EU": ["piece", "case", "pack", "pallet"],
    "CA": ["piece", "case", "pack", "pallet"],
    "AU": ["piece", "case", "pack", "pallet"],
}

# أسماء عرض مفضلة حسب الدولة (لتجربة مستخدم محلية) - الآن يشير للوحدات النشطة
_COUNTRY_UNIT_PREFERENCES = {
    "SA": ["carton", "case", "pallet", "piece"],
    "AE": ["carton", "case", "pallet", "piece"],
    "KW": ["carton", "case", "pallet", "piece"],
    "QA": ["carton", "case", "pallet", "piece"],
    "BH": ["carton", "case", "pallet", "piece"],
    "OM": ["carton", "case", "pallet", "piece"],
    "US": ["case", "pack", "pallet", "piece"],
    "GB": ["case", "pack", "pallet", "piece"],
    "EU": ["case", "pack", "pallet", "piece"],
}

_GCC_COUNTRIES = {"SA", "AE", "KW", "QA", "BH", "OM"}
_ARAB_COUNTRIES = {
    "EG", "JO", "IQ", "LB", "SY", "PS", "YE", "SD", "LY", "TN", "DZ", "MA", "MR", "SO", "DJ", "KM"
}


def normalize_unit_code(raw_value: str | None) -> str:
    """تحويل أي اسم وحدة/اختصار إلى كود موحّد."""
    key = (raw_value or "").strip().lower()
    if not key:
        return "piece"
    return _ALIAS_TO_CODE.get(key, "piece")


def is_unit_active_for_country(unit_code: str, country_code: str | None) -> bool:
    """التحقق من أن وحدة معينة نشطة في بلد معين."""
    code = (country_code or "SA").upper()
    active_units = get_active_units_for_country(code)
    return unit_code.lower() in [u.lower() for u in active_units]


def get_active_units_for_country(country_code: str | None) -> list[str]:
    """
    إرجاع الوحدات النشطة فقط للبلد - الباقي يختفي نهائياً من الواجهة.
    هذا يضمن أن المستخدم لا يرى إلا الوحدات المتعارف عليها في سوقه.
    """
    code = (country_code or "SA").upper()
    return _COUNTRY_ACTIVE_UNITS.get(code, _COUNTRY_ACTIVE_UNITS["SA"])


def unit_display_name(unit_code: str, language: str = "ar") -> str:
    """اسم عرض الوحدة حسب اللغة."""
    lang = "ar" if language.lower().startswith("ar") else "en"
    return _UNIT_DISPLAY.get(unit_code, _UNIT_DISPLAY["piece"]).get(lang, _UNIT_DISPLAY["piece"][lang])


def get_market_packaging_terms(country_code: str | None, language: str = "ar") -> list[dict]:
    """
    إرجاع مصطلحات وحدات التعبئة النشطة فقط لسوق معين.
    يتم ترتيبها حسب الأولويات المحلية.
    الوحدات غير النشطة تختفي نهائياً من الواجهة.
    """
    code = (country_code or "SA").upper()
    active_units = get_active_units_for_country(code)
    preferred = _COUNTRY_UNIT_PREFERENCES.get(code, _COUNTRY_UNIT_PREFERENCES["SA"])
    
    # ترتيب حسب الأولويات + اختيار فقط الوحدات النشطة
    result = []
    for unit_code in preferred:
        if unit_code in active_units:
            result.append({
                "code": unit_code,
                "label": unit_display_name(unit_code, language=language),
            })
    
    return result


def resolve_market_segment(country_code: str | None) -> str:
    """تصنيف السوق القياسي: gcc | arab | global"""
    code = (country_code or "SA").upper()
    if code in _GCC_COUNTRIES:
        return "gcc"
    if code in _ARAB_COUNTRIES:
        return "arab"
    return "global"


def default_unit_language(country_code: str | None) -> str:
    """اللغة الافتراضية لعرض وحدات السوق."""
    segment = resolve_market_segment(country_code)
    return "ar" if segment in {"gcc", "arab"} else "en"


def get_market_profile(country_code: str | None, language: str | None = None) -> dict:
    """بروفايل سوق جاهز للاستخدام في القوالب والـ APIs."""
    code = (country_code or "SA").upper()
    lang = (language or default_unit_language(code)).lower()
    segment = resolve_market_segment(code)
    active_units = get_active_units_for_country(code)
    return {
        "country_code": code,
        "market_segment": segment,
        "unit_language": lang,
        "active_units": active_units,
        "packaging_terms": get_market_packaging_terms(code, language=lang),
    }


def get_business_market_profile(db, business_id: int, country_code: str | None = None) -> dict:
    """
    بناء بروفايل السوق للمنشأة مع fallback آمن.
    لا يعتمد على وجود إعدادات مسبقة لضمان العمل بلا استثناء.
    """
    code = (country_code or "SA").upper()
    language = None
    try:
        rows = db.execute(
            "SELECT key, value FROM settings WHERE business_id=? AND key IN ('unit_display_language')",
            (business_id,),
        ).fetchall()
        kv = {r["key"]: r["value"] for r in rows}
        language = (kv.get("unit_display_language") or "").strip().lower() or None
    except Exception:
        language = None
    return get_market_profile(code, language=language)


def ensure_unit_localization_defaults(db, business_id: int, country_code: str | None = None) -> None:
    """
    تهيئة إعدادات الوحدات العالمية للمنشأة مرة واحدة من البداية.
    تحفظ السياسة في settings حتى تكون المنصة جاهزة للتوسع دون ترقيع لاحق.
    """
    code = (country_code or "SA").upper()
    segment = resolve_market_segment(code)
    language = default_unit_language(code)

    db.execute(
        "INSERT OR IGNORE INTO settings (business_id, key, value) VALUES (?,?,?)",
        (business_id, "unit_localization_enabled", "1"),
    )
    db.execute(
        "INSERT OR IGNORE INTO settings (business_id, key, value) VALUES (?,?,?)",
        (business_id, "unit_market_country", code),
    )
    db.execute(
        "INSERT OR IGNORE INTO settings (business_id, key, value) VALUES (?,?,?)",
        (business_id, "unit_market_segment", segment),
    )
    db.execute(
        "INSERT OR IGNORE INTO settings (business_id, key, value) VALUES (?,?,?)",
        (business_id, "unit_display_language", language),
    )
