import sqlite3
conn = sqlite3.connect('accounting_dev.db')
c = conn.cursor()
tables = c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
print('الجداول في accounting_dev.db:')
for table in tables:
    print(f'  • {table[0]}')

# البحث عن جدول يحتوي على المنتجات
print('\nالجداول التي قد تحتوي على المنتجات:')
for table in tables:
    name = table[0]
    if 'product' in name.lower() or 'item' in name.lower():
        print(f'\n  >> {name}')
        cols = c.execute(f"PRAGMA table_info({name})").fetchall()
        for col in cols[:10]:
            print(f'     - {col[1]}')

conn.close()
