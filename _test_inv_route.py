import sqlite3
db = sqlite3.connect('database/accounting_dev.db')
db.row_factory = sqlite3.Row

biz_id = 31  # wholesale2026

# اختبار استعلام العملاء
try:
    r = db.execute("SELECT name FROM contacts WHERE business_id=? AND type IN ('customer','both') ORDER BY name", (biz_id,)).fetchall()
    print('contacts OK:', len(r))
except Exception as e:
    print('contacts ERROR:', e)

# اختبار استعلام المنتجات
try:
    r = db.execute("""
        SELECT p.name, pi.unit_price AS sell_price
        FROM products p
        LEFT JOIN product_inventory pi ON pi.product_id = p.id AND pi.business_id = p.business_id
        WHERE p.business_id=? AND p.is_active=1
        ORDER BY p.name""", (biz_id,)).fetchall()
    print('products OK:', len(r))
except Exception as e:
    print('products ERROR:', e)

# اختبار استعلام tax_number
try:
    r = db.execute('SELECT tax_number FROM businesses WHERE id=?', (biz_id,)).fetchone()
    print('tax_number OK:', dict(r) if r else None)
except Exception as e:
    print('tax_number ERROR:', e)

# تحقق من وجود العمود type في جدول contacts
try:
    cols = db.execute("PRAGMA table_info(contacts)").fetchall()
    print('contacts columns:', [c['name'] for c in cols])
except Exception as e:
    print('PRAGMA ERROR:', e)
