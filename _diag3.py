import sqlite3
conn = sqlite3.connect('database/accounting_dev.db')
cur = conn.cursor()

# فحص البيزنيسات
cur.execute('SELECT id, name, country, activity_type FROM businesses ORDER BY id')
biznses = cur.fetchall()
print('البيزنيسات:')
for b in biznses[:15]:
    cur.execute('SELECT COUNT(*) FROM products WHERE business_id=?', (b[0],))
    cnt = cur.fetchone()[0]
    print(f'  [{b[0]}] {b[1]} | بلد={b[2]} | نشاط={b[3]} | منتجات={cnt}')

print()

# فحص جدول settings
cur.execute('PRAGMA table_info(settings)')
settings_cols = [c[1] for c in cur.fetchall()]
print('أعمدة settings:', settings_cols)

cur.execute('SELECT * FROM settings WHERE business_id=1 LIMIT 10')
rows = cur.fetchall()
print('settings لـ business 1:')
for r in rows:
    print(' ', r)

# فحص business_settings_ext
cur.execute('PRAGMA table_info(business_settings_ext)')
ext_cols = [c[1] for c in cur.fetchall()]
print('\nأعمدة business_settings_ext:', ext_cols)

cur.execute("SELECT key, value FROM business_settings_ext WHERE business_id=1 AND key LIKE '%unit%' LIMIT 10")
for r in cur.fetchall():
    print(' ', r)

conn.close()
