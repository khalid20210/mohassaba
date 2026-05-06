from modules.unit_localization import get_market_packaging_terms

regions = [
    ("SA", "السعودية"),
    ("AE", "الإمارات"),
    ("KW", "الكويت"),
    ("QA", "قطر"),
    ("BH", "البحرين"),
    ("OM", "عُمان"),
    ("EG", "مصر"),
    ("JO", "الأردن"),
    ("LB", "لبنان"),
    ("SY", "سوريا"),
    ("PS", "فلسطين"),
    ("IQ", "العراق"),
    ("YE", "اليمن"),
    ("SD", "السودان"),
    ("LY", "ليبيا"),
    ("MA", "المغرب"),
    ("TN", "تونس"),
    ("DZ", "الجزائر"),
    ("MR", "موريتانيا"),
    ("SO", "الصومال"),
    ("DJ", "جيبوتي"),
    ("KM", "جزر القمر"),
]

for cc, name in regions:
    terms = get_market_packaging_terms(cc, "ar")
    print(f"{name:25s} ({cc}): {' | '.join(d['label'] for d in terms)}")
