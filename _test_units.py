import sys; sys.path.insert(0, '.')
from modules.unit_localization import get_market_packaging_terms, get_active_units_for_country

countries = {
    'SA': 'السعودية',
    'AE': 'الإمارات',
    'KW': 'الكويت',
    'EG': 'مصر',
    'JO': 'الأردن',
    'IQ': 'العراق',
    'LB': 'لبنان',
    'LY': 'ليبيا',
    'YE': 'اليمن',
    'SD': 'السودان',
    'MA': 'المغرب',
    'TN': 'تونس',
    'DZ': 'الجزائر',
    'US': 'أمريكا',
    'GB': 'بريطانيا',
    'EU': 'أوروبا',
    'CA': 'كندا',
    'AU': 'أستراليا',
}

print('=== وحدات كل دولة ===\n')
for code, name in countries.items():
    terms = get_market_packaging_terms(code, language='ar')
    labels = ' | '.join(f"{t['label']}({t['code']})" for t in terms)
    print(f'{name:12} ({code}): {labels}')
