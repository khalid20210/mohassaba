import sqlite3
conn = sqlite3.connect('database/accounting_dev.db')
cur = conn.cursor()

cur.execute("SELECT id, name, industry_type FROM businesses WHERE industry_type LIKE '%wholesale%' ORDER BY id")
for b in cur.fetchall():
    cur.execute('SELECT COUNT(*) FROM products WHERE business_id=?', (b[0],))
    cnt = cur.fetchone()[0]
    print(f'[{b[0]}] {b[1]} ({b[2]}): {cnt} منتج')

# وحدات ففف الآن
print('\nمنتجات ففف (id=23):')
cur.execute("SELECT name, category_name FROM products WHERE business_id=23 ORDER BY category_name, name")
for r in cur.fetchall():
    print(f'  - {r[0]} [{r[1]}]')

conn.close()
