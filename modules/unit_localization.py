"""
modules/unit_localization.py
توحيد أسماء وحدات البيع/التعبئة عبر الدول مع الحفاظ على كود داخلي ثابت.
"""

from __future__ import annotations


# أكواد موحّدة (لا تتغير بين الدول)
_UNIT_DISPLAY = {
    # ── مشتركة عالمياً ─────────────────────────────────────────────────────────────
    "piece":       {"ar": "قطعة",        "en": "Piece"},
    "carton":      {"ar": "كرتون",        "en": "Carton"},
    "case":        {"ar": "صندوق",        "en": "Case"},
    "pack":        {"ar": "باك",           "en": "Pack"},
    "bundle":      {"ar": "ربطة",          "en": "Bundle"},
    "pallet":      {"ar": "باليت",         "en": "Pallet"},
    "roll":        {"ar": "رولة",          "en": "Roll"},
    # ── خليجي / جزيرة العرب ──────────────────────────────────────────────────
    "sheda":       {"ar": "شدة",           "en": "Sheda"},       # 12 حبة (كالدرزن)
    "sack":        {"ar": "خيشة",          "en": "Sack"},        # جوال/بوري خيش كبير
    "bag":         {"ar": "كيس",           "en": "Bag"},         # كيس بلاستيك/ورق
    "gallon":      {"ar": "جالون",         "en": "Gallon"},      # سوائل، 4 لتر
    "half_carton": {"ar": "نص كرتون",    "en": "Half Carton"},
    "half_dozen":  {"ar": "نص درزن",     "en": "Half Dozen"},
    # ── مصري ─────────────────────────────────────────────────────────────────
    "bale":        {"ar": "بالة",          "en": "Bale"},        # بالة قماش/بضاعة
    "basatla":     {"ar": "بسطلة",         "en": "Basatla"},     # مصري: عبوة صغيرة
    # ── شامي (levانت) ─────────────────────────────────────────────────────────
    "tin":         {"ar": "تنكة",          "en": "Tin"},         # تنكة معدنية
    "bidon":       {"ar": "بيدون",         "en": "Bidon"},       # جريكان/عبوة دهنية
    "waqiya":      {"ar": "وقية",          "en": "Waqiya"},      # ~200ج وحدة وزن شامي
    "sahara":      {"ar": "سحارة",         "en": "Crate"},       # جابية/صندوق خشبي
    "shwal":       {"ar": "شوال",          "en": "Shwal"},       # بوري كبير (مصري/شامي)
}


# aliases متعددة لنفس الوحدة (عالمي + إقليمي + عربي)
_ALIAS_TO_CODE = {
    # ── قطعة (piece) — مشترك عالمي ──────────────────────────────────────────
    "قطعة": "piece",
    "حبة": "piece",
    "حتة": "piece",       # مصري
    "وحدة": "piece",
    "طلب": "piece",      # خدمات
    "زيارة": "piece",    # طبي
    "جلسة": "piece",     # خدمات
    "piece": "piece",
    "pcs": "piece",
    "pc": "piece",
    "unit": "piece",
    # ── كرتون (carton) — خليجي/مشرقي ────────────────────────────────────────
    "كرتون": "carton",
    "كرتونة": "carton",    # مصري
    "carton": "carton",
    "ctn": "carton",
    "crt": "carton",
    # ── صندوق (case) — مشترك ────────────────────────────────────────────────
    "صندوق": "case",
    "قفص": "case",
    "سلة": "case",
    "سحارة": "sahara",    # شامي: صندوق خشب للخضار والفواكه
    "case": "case",
    "cs": "case",
    "crate": "case",
    "box": "case",
    # ── باك / طرد (pack) — مصري / مغاربي ───────────────────────────────────
    "باك": "pack",
    "عبوة": "pack",
    "طرد": "pack",       # مصري / مغاربي
    "علبة": "pack",      # مصري / مغاربي
    "بستلة": "basatla",  # مصري: عبوة صغيرة خفيفة
    "باكت": "pack",      # مصري عامي
    "paquet": "pack",    # فرانكوفوني
    "pack": "pack",
    "pk": "pack",
    "pkg": "pack",
    # ── شدة (sheda) — خليجي: 12 حبة ─────────────────────────────────────────
    "شدة": "sheda",
    "شده": "sheda",
    "sheda": "sheda",
    # ── ربطة (bundle) — خليجي / مشرقي ──────────────────────────────────────
    "ربطة": "bundle",
    "حزمة": "bundle",
    "درزن": "bundle",
    "دزينة": "bundle",
    "دستة": "bundle",     # مصري (alias لـ bundle/sheda)
    "شبكة": "bundle",    # عراقي
    "dozen": "bundle",
    "dzn": "bundle",
    "bundle": "bundle",
    "bdl": "bundle",
    # ── نص كرتون (half_carton) — خليجي ──────────────────────────────────────
    "نص كرتون": "half_carton",
    "نصف كرتون": "half_carton",
    "half_carton": "half_carton",
    "half carton": "half_carton",
    # ── نص درزن (half_dozen) — خليجي ──────────────────────────────────────
    "نص درزن": "half_dozen",
    "نصف درزن": "half_dozen",
    "نص دستة": "half_dozen",
    "half_dozen": "half_dozen",
    # ── خيشة (sack) — خليجي: جوال/بوري خيش ─────────────────────────────────
    "خيشة": "sack",
    "جوال": "sack",
    "بوري": "sack",
    "sack": "sack",
    # ── شوال (shwal) — مصري/شامي: كيس كبير ─────────────────────────────────
    "شوال": "shwal",
    "شواله": "shwal",
    "shwal": "shwal",
    # ── كيس (bag) — خليجي: كيس بلاستيك ──────────────────────────────────────
    "كيس": "bag",
    "كيسة": "bag",
    "bag": "bag",
    # ── جالون (gallon) — سوائل خليجي ───────────────────────────────────────
    "جالون": "gallon",
    "جالونة": "gallon",
    "gallon": "gallon",
    "gal": "gallon",
    # ── بالة (bale) — مصري: قماش/بضائع ────────────────────────────────────
    "بالة": "bale",
    "باله": "bale",
    "bale": "bale",
    # ── تنكة (tin) — شامي: تنكة معدنية ─────────────────────────────────────
    "تنكة": "tin",
    "تنك": "tin",
    "جردل": "tin",
    "tin": "tin",
    # ── بيدون (bidon) — شامي/مغاربي ──────────────────────────────────────
    "بيدون": "bidon",
    "جريكان": "bidon",
    "بدون": "bidon",
    "bidon": "bidon",
    "jerrycan": "bidon",
    # ── وقية (waqiya) — شامي: ~200ج وزن تقليدي ──────────────────────────────
    "وقية": "waqiya",
    "وقيه": "waqiya",
    "waqiya": "waqiya",
    # ── باليت (pallet) — مشترك صناعي ────────────────────────────────────────
    "باليت": "pallet",
    "طبليه": "pallet",
    "طبلية": "pallet",    # عراقي
    "بلوك": "pallet",    # عراقي
    "بالي": "pallet",    # مغاربي
    "palette": "pallet",
    "pallet": "pallet",
    "plt": "pallet",
    "pal": "pallet",
    # ── رولة (roll) — نسيج / ورق / بلاستيك ─────────────────────────────────
    "رولة": "roll",
    "لفة": "roll",
    "بكرة": "roll",
    "roll": "roll",
    "rl": "roll",
}


# ────────────────────────────────────────────────────────────────────────────
# أسماء عرض مخصصة لكل دولة — تُطبَّق بدلاً من الاسم الافتراضي عند الحاجة
# ────────────────────────────────────────────────────────────────────────────
_COUNTRY_UNIT_LABELS: dict[str, dict[str, str]] = {
    # مصر: كرتونة بدل كرتون، حتة بدل قطعة، طرد بدل باك، شوال بدل خيشة
    "EG": {
        "piece":  "حتة",
        "carton": "كرتونة",
        "pack":   "طرد",
        "bundle": "دستة",
        "sack":   "شوال",
        "bale":   "بالة",
    },
    # المغرب/تونس/الجزائر: تأثير فرنسي — طرد
    "MA": {"pack": "طرد"},
    "TN": {"pack": "طرد"},
    "DZ": {"pack": "طرد"},
    # العراق: طبلية بدل باليت
    "IQ": {"pallet": "طبلية"},
    # الشام: سحارة وتنكة وبيدون
    "JO": {"sahara": "سحارة", "shwal": "شوال"},
    "LB": {"sahara": "سحارة", "shwal": "شوال"},
    "SY": {"sahara": "سحارة", "shwal": "شوال"},
    "PS": {"sahara": "سحارة"},
    # الخليج: شدة لـ 12 حبة / خيشة / طبلية
    "SA": {"sheda": "شدة", "sack": "خيشة", "bag": "كيس", "half_carton": "نص كرتون", "half_dozen": "نص درزن", "pallet": "طبلية"},
    "AE": {"sheda": "شدة", "sack": "خيشة", "bag": "كيس", "half_carton": "نص كرتون"},
    "KW": {"sheda": "شدة", "sack": "خيشة", "bag": "كيس", "half_carton": "نص كرتون"},
    "QA": {"sheda": "شدة", "sack": "خيشة", "bag": "كيس", "half_carton": "نص كرتون"},
    "BH": {"sheda": "شدة", "sack": "خيشة", "bag": "كيس", "half_carton": "نص كرتون"},
    "OM": {"sheda": "شدة", "sack": "خيشة", "bag": "كيس", "half_carton": "نص كرتون"},
    # الغرب: أسماء إنجليزية افتراضية (لا تغيير)
}

# ────────────────────────────────────────────────────────────────────────────
# الوحدات النشطة فقط لكل دولة — الباقي يختفي نهائياً من الواجهة
# المنطق: كل دولة لها وحدات متعارف عليها في سوقها فقط
# ────────────────────────────────────────────────────────────────────────────
_COUNTRY_ACTIVE_UNITS = {
    # ── دول مجلس التعاون الخليجي ────────────────────────────────────────────
    # حبة | كرتون | صندوق | شدة | ربطة | درزن | طبلية | خيشة | كيس | رولة | جالون | نص كرتون | نص درزن
    "SA": ["piece", "carton", "case", "sheda", "bundle", "half_dozen", "pallet", "sack", "bag", "roll", "gallon", "half_carton"],
    "AE": ["piece", "carton", "case", "sheda", "bundle", "half_dozen", "pallet", "sack", "bag", "roll", "gallon", "half_carton"],
    "KW": ["piece", "carton", "case", "sheda", "bundle", "half_dozen", "pallet", "sack", "bag", "roll", "gallon", "half_carton"],
    "QA": ["piece", "carton", "case", "sheda", "bundle", "half_dozen", "pallet", "sack", "bag", "roll", "gallon", "half_carton"],
    "BH": ["piece", "carton", "case", "sheda", "bundle", "half_dozen", "pallet", "sack", "bag", "roll", "gallon", "half_carton"],
    "OM": ["piece", "carton", "case", "sheda", "bundle", "half_dozen", "pallet", "sack", "bag", "roll", "gallon", "half_carton"],
    # ── المشرق العربي ────────────────────────────────────────────────────────
    # حتة | كرتونة | دستة | شوال | طرد | بالة | بستلة | باليت
    "EG": ["piece", "carton", "case", "bundle", "pack", "sack", "bale", "basatla", "pallet"],
    # سحارة | تنكة | بيدون | وقية | شوال | صندوق | كرتون
    "JO": ["piece", "carton", "case", "sahara", "bundle", "tin", "bidon", "shwal", "waqiya", "pallet"],
    "LB": ["piece", "carton", "case", "sahara", "bundle", "tin", "bidon", "shwal", "waqiya", "pallet"],
    "SY": ["piece", "carton", "case", "sahara", "bundle", "tin", "bidon", "shwal", "waqiya", "pallet"],
    "PS": ["piece", "carton", "case", "sahara", "bundle", "tin", "bidon", "pallet"],
    # العراق: كرتون + صندوق + ربطة + طبلية
    "IQ": ["piece", "carton", "case", "bundle", "pallet"],
    # اليمن: أسواق بسيطة
    "YE": ["piece", "carton", "case"],
    # السودان: كرتون + صندوق + باليت
    "SD": ["piece", "carton", "case", "pallet"],
    # ليبيا: مشابه للشام
    "LY": ["piece", "carton", "case", "bundle", "pallet"],
    # ── المغرب العربي (تأثير فرنسي) ─────────────────────────────────────────
    "MA": ["piece", "carton", "case", "pack", "pallet"],
    "TN": ["piece", "carton", "case", "pack", "pallet"],
    "DZ": ["piece", "carton", "case", "pack", "pallet"],
    # موريتانيا/الصومال/جيبوتي/القمر: أسواق بسيطة
    "MR": ["piece", "carton", "case", "pallet"],
    "SO": ["piece", "carton", "case"],
    "DJ": ["piece", "carton", "case", "pallet"],
    "KM": ["piece", "carton", "case"],
    # ── الغرب ────────────────────────────────────────────────────────────────
    "US": ["piece", "case", "pack", "pallet"],
    "CA": ["piece", "case", "pack", "pallet"],
    "GB": ["piece", "case", "pack", "pallet", "roll"],
    "EU": ["piece", "case", "pack", "pallet"],
    "AU": ["piece", "case", "pack", "pallet"],
    "IN": ["piece", "carton", "case", "pack", "pallet"],
    "CN": ["piece", "carton", "case", "pallet"],
    "JP": ["piece", "case", "pack", "pallet"],
    "KR": ["piece", "case", "pack", "pallet"],
}

# ترتيب العرض المفضل لكل دولة (الأكثر استخداماً أولاً في الـ dropdowns)
_COUNTRY_UNIT_PREFERENCES = {
    # الخليج: كرتون ← صندوق ← شدة ← درزن ← ربطة ← طبلية ← خيشة ← كيس ← رولة ← جالون ← نص كرتون ← نص درزن ← حبة
    "SA": ["carton", "case", "sheda", "half_dozen", "bundle", "pallet", "sack", "bag", "roll", "gallon", "half_carton", "piece"],
    "AE": ["carton", "case", "sheda", "half_dozen", "bundle", "pallet", "sack", "bag", "roll", "gallon", "half_carton", "piece"],
    "KW": ["carton", "case", "sheda", "half_dozen", "bundle", "pallet", "sack", "bag", "roll", "gallon", "half_carton", "piece"],
    "QA": ["carton", "case", "sheda", "half_dozen", "bundle", "pallet", "sack", "bag", "roll", "gallon", "half_carton", "piece"],
    "BH": ["carton", "case", "sheda", "half_dozen", "bundle", "pallet", "sack", "bag", "roll", "gallon", "half_carton", "piece"],
    "OM": ["carton", "case", "sheda", "half_dozen", "bundle", "pallet", "sack", "bag", "roll", "gallon", "half_carton", "piece"],
    # مصر: كرتونة ← دستة ← طرد ← شوال ← بالة ← بستلة
    "EG": ["carton", "bundle", "pack", "sack", "bale", "basatla", "case", "pallet", "piece"],
    # الشام: كرتون ← صندوق ← سحارة ← ربطة ← تنكة ← بيدون ← شوال ← وقية
    "JO": ["carton", "case", "sahara", "bundle", "tin", "bidon", "shwal", "waqiya", "pallet", "piece"],
    "LB": ["carton", "case", "sahara", "bundle", "tin", "bidon", "shwal", "waqiya", "pallet", "piece"],
    "SY": ["carton", "case", "sahara", "bundle", "tin", "bidon", "shwal", "waqiya", "pallet", "piece"],
    "PS": ["carton", "case", "sahara", "bundle", "tin", "bidon", "pallet", "piece"],
    "IQ": ["carton", "case", "bundle", "pallet", "piece"],
    "LY": ["carton", "case", "bundle", "pallet", "piece"],
    "SD": ["carton", "case", "pallet", "piece"],
    "YE": ["carton", "case", "piece"],
    # المغرب العربي: طرد ثاني بعد كرتون
    "MA": ["carton", "case", "pack", "pallet", "piece"],
    "TN": ["carton", "case", "pack", "pallet", "piece"],
    "DZ": ["carton", "case", "pack", "pallet", "piece"],
    # الغرب
    "US": ["case", "pack", "pallet", "piece"],
    "CA": ["case", "pack", "pallet", "piece"],
    "GB": ["case", "pack", "pallet", "roll", "piece"],
    "EU": ["case", "pack", "pallet", "piece"],
    "AU": ["case", "pack", "pallet", "piece"],
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


def unit_display_name(unit_code: str, language: str = "ar", country_code: str | None = None) -> str:
    """اسم عرض الوحدة حسب اللغة والدولة (يطبق الاسم المحلي إن وجد)."""
    lang = "ar" if language.lower().startswith("ar") else "en"
    if lang == "ar" and country_code:
        country_labels = _COUNTRY_UNIT_LABELS.get(country_code.upper(), {})
        if unit_code in country_labels:
            return country_labels[unit_code]
    return _UNIT_DISPLAY.get(unit_code, _UNIT_DISPLAY["piece"]).get(lang, _UNIT_DISPLAY["piece"][lang])


def get_market_packaging_terms(country_code: str | None, language: str = "ar") -> list[dict]:
    """
    إرجاع مصطلحات وحدات التعبئة النشطة فقط لسوق معين.
    — مرتبة حسب أولويات الدولة
    — مسماة بالاسم المحلي المتعارف عليه
    — الوحدات غير المتعارف عليها في هذا السوق لا تظهر إطلاقاً
    """
    code = (country_code or "SA").upper()
    active_units   = get_active_units_for_country(code)
    preferred_order = _COUNTRY_UNIT_PREFERENCES.get(code, list(active_units))

    seen   = set()
    result = []

    # أولاً: الوحدات بترتيبها المفضل للدولة
    for unit_code in preferred_order:
        if unit_code in active_units and unit_code not in seen:
            seen.add(unit_code)
            result.append({
                "code":  unit_code,
                "label": unit_display_name(unit_code, language=language, country_code=code),
            })

    # ثانياً: أي وحدات نشطة لم تُذكر في القائمة المفضلة (احتياطي)
    for unit_code in active_units:
        if unit_code not in seen:
            result.append({
                "code":  unit_code,
                "label": unit_display_name(unit_code, language=language, country_code=code),
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
