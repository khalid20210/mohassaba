import sqlite3
conn = sqlite3.connect('database/accounting_dev.db')
cur = conn.cursor()

# الجداول المتعلقة بالمنتجات والوحدات
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cur.fetchall()]
print('جداول المنتجات/الوحدات:')
for t in tables:
    if any(x in t.lower() for x in ['product', 'unit', 'item', 'catalog']):
        print(' ', t)

print('\nكل الجداول:')
print(tables)

# هل هناك جدول product_units أو units؟
for t in tables:
    if 'unit' in t.lower():
        cur.execute(f'PRAGMA table_info({t})')
        cols = [c[1] for c in cur.fetchall()]
        cur.execute(f'SELECT COUNT(*) FROM {t}')
        cnt = cur.fetchone()[0]
        print(f'\nجدول {t} ({cnt} سجل): {cols}')

# أعمدة products
cur.execute('PRAGMA table_info(products)')
cols = [c[1] for c in cur.fetchall()]
print('\nأعمدة products:', cols)

# فحص business_id=1 منتجاته
cur.execute("SELECT COUNT(*) FROM products WHERE business_id=1 AND is_active=1")
print('\nمنتجات نشطة للنشاط 1:', cur.fetchone()[0])

conn.close()
