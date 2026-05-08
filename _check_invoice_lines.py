import sqlite3
conn = sqlite3.connect('database/accounting_dev.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# آخر فاتورة
inv = cur.execute('SELECT id FROM invoices ORDER BY id DESC LIMIT 1').fetchone()
inv_id = inv['id']

# أسطر الفاتورة مع اسم المنتج
lines = cur.execute('''
  SELECT il.id, p.name, il.description, il.quantity, il.unit_price, il.total, il.tax_rate, il.tax_amount
  FROM invoice_lines il
  LEFT JOIN products p ON il.product_id = p.id
  WHERE il.invoice_id = ?
''', (inv_id,)).fetchall()

for i, line in enumerate(lines, 1):
    print("السطر #{}:".format(i))
    print("  المنتج: {}".format(line['name'][:50] if line['name'] else line['description'][:50]))
    print("  الكمية: {:,} وحدة".format(int(line['quantity'])))
    print("  السعر الفردي: {:,.2f} ر.س".format(line['unit_price']))
    print("  الخصم: 0.00 ر.س")
    print("  الضريبة ({}%): {:,.2f} ر.س".format(int(line['tax_rate']) if line['tax_rate'] else 0, line['tax_amount']))
    print("  الإجمالي: {:,.2f} ر.س".format(line['total']))
    print()
conn.close()
