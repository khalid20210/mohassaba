import sqlite3
conn = sqlite3.connect('database/accounting_dev.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# الفاتورة الأخيرة
inv = cur.execute('SELECT id, invoice_number, status, total, tax_amount FROM invoices ORDER BY id DESC LIMIT 1').fetchone()
print(f"✅ الفاتورة: {inv['invoice_number']} | الحالة: {inv['status']} | الإجمالي: {inv['total']:,.2f} ر.س | الضريبة: {inv['tax_amount']:,.2f} ر.س")

# فحص الجداول المتاحة
tables = cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
print("\nالجداول المتعلقة بالفواتير:")
for t in tables:
    if 'inv' in t[0].lower() or 'item' in t[0].lower() or 'line' in t[0].lower():
        print(f"  - {t[0]}")

conn.close()
