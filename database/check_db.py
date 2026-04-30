import sqlite3
conn = sqlite3.connect('accounting.db')
cur = conn.cursor()

print('=== إحصائيات قاعدة البيانات ===')
cur.execute('SELECT COUNT(*) FROM products')
print('المنتجات:', cur.fetchone()[0])
cur.execute('SELECT COUNT(*) FROM accounts')
print('الحسابات:', cur.fetchone()[0])
cur.execute('SELECT COUNT(*) FROM product_categories')
print('التصنيفات:', cur.fetchone()[0])
cur.execute('SELECT COUNT(*) FROM stock')
print('أرصدة المخزون:', cur.fetchone()[0])
cur.execute('SELECT COUNT(*) FROM settings')
print('الإعدادات:', cur.fetchone()[0])

print()
print('=== توزيع المنتجات حسب الصنف (أعلى 10) ===')
cur.execute("""
    SELECT category_name, COUNT(*) as cnt 
    FROM products WHERE business_id=1 
    GROUP BY category_name ORDER BY cnt DESC LIMIT 10
""")
for row in cur.fetchall():
    cat = row[0] if row[0] else '(بدون صنف)'
    print(f'  {cat}: {row[1]}')

print()
print('=== نماذج من المنتجات ===')
cur.execute('SELECT barcode, name, sale_price, category_name FROM products LIMIT 8')
for row in cur.fetchall():
    print(f'  {row[0]}: {row[1]} | {row[2]} | {row[3]}')

conn.close()
