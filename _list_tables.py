import sqlite3

conn = sqlite3.connect('accounting_dev.db')
c = conn.cursor()

# الحصول على قائمة الجداول
tables = c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()

print("الجداول في accounting_dev.db:")
for idx, table in enumerate(tables, 1):
    print(f"{idx:2d}. {table[0]}")

# البحث عن جداول المنتجات
print("\nالجداول المتعلقة بالمنتجات:")
for table in tables:
    name = table[0].lower()
    if 'product' in name or 'item' in name or 'stock' in name:
        print(f"\n>>> {table[0]}")
        cols = c.execute(f"PRAGMA table_info({table[0]})").fetchall()
        for col in cols:
            print(f"    {col[1]:20} - {col[2]}")

conn.close()
