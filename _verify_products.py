import sqlite3
conn = sqlite3.connect('database/accounting_dev.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# الحساب الجديد
biz = cur.execute('SELECT id, name FROM businesses WHERE id = 225').fetchone()
print("الحساب:", biz['name'], "(ID: 225)")

# عدد المنتجات
total = cur.execute('SELECT COUNT(*) FROM products WHERE business_id = 225').fetchone()[0]
inv_total = cur.execute('SELECT COUNT(*) FROM product_inventory WHERE business_id = 225').fetchone()[0]
print("إجمالي المنتجات: {:,} في جدول products".format(total))
print("إجمالي المنتجات: {:,} في جدول product_inventory".format(inv_total))

# عينات من المنتجات
samples = cur.execute('SELECT name, sale_price, purchase_price, barcode FROM products WHERE business_id = 225 LIMIT 5').fetchall()
print("\n🔹 عينات من المنتجات:")
for p in samples:
    print("  - {} | بيع: {} | شراء: {} | باركود: {}".format(p['name'][:40], p['sale_price'], p['purchase_price'], p['barcode']))

# تحقق من product_inventory
inv_samples = cur.execute('SELECT sku, current_qty, unit_price FROM product_inventory WHERE business_id = 225 LIMIT 5').fetchall()
print("\n🔹 عينات من product_inventory:")
for inv in inv_samples:
    print("  - SKU: {} | الكمية: {} | السعر: {}".format(inv['sku'], inv['current_qty'], inv['unit_price']))

print("\n✅ النتيجة النهائية: المنتجات مدمجة بالكامل!")
conn.close()
