from modules.terminology import _SECTOR_TERMS

print(f'\nاجمالي الانشطة: {len(_SECTOR_TERMS)}')
print(f'{"="*60}\n')

for i, (key, term) in enumerate(_SECTOR_TERMS.items(), 1):
    label = term.get('industry_label', 'N/A')
    print(f'{i:3d}. {key:30s} | {label}')

print(f'\n{"="*60}')
print(f'المجموع: {len(_SECTOR_TERMS)}')
