import sqlite3

db = sqlite3.connect('database/accounting_dev.db')
c = db.cursor()

# الحصول على جميع الجداول
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = c.fetchall()

print(f'\nاجمالي الجداول: {len(tables)}\n')

for table in tables:
    table_name = table[0]
    c.execute(f"SELECT COUNT(*) FROM {table_name}")
    count = c.fetchone()[0]
    print(f'{table_name:30s} | عدد السجلات: {count}')

print('\n' + '='*60)
print('البحث عن جداول الانشطة...\n')

# جداول محتملة
for keyword in ['activity', 'sector', 'industry', 'business']:
    c.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%{keyword}%'")
    result = c.fetchall()
    if result:
        print(f'\nجداول تحتوي على "{keyword}":')
        for row in result:
            print(f'  - {row[0]}')

db.close()
