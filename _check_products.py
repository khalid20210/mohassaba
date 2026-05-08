import sqlite3
import random

conn = sqlite3.connect('database/accounting_dev.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# تحديث unit_price و unit_cost في product_inventory من جدول products
cur.execute("""
    UPDATE product_inventory
    SET unit_price = (SELECT sale_price FROM products WHERE products.id = product_inventory.product_id),
        unit_cost  = (SELECT purchase_price FROM products WHERE products.id = product_inventory.product_id),
        updated_at = datetime('now')
    WHERE business_id = 30
""")
conn.commit()
print(f"تم تحديث {cur.rowcount} سجل في product_inventory")

# تحقق نهائي
rows = cur.execute("""
    SELECT p.id, p.barcode, p.name, p.sale_price, pi.current_qty, pi.unit_price, pi.unit_cost
    FROM products p
    LEFT JOIN product_inventory pi ON p.id=pi.product_id AND pi.business_id=30
    WHERE p.business_id=30
    ORDER BY p.id
""").fetchall()

print("\nالمنتجات النهائية مع الباركود والمخزون:")
for r in rows:
    print(f"  [{r[0]}] باركود={r[1]} | {r[2]} | سعر بيع={r[5]} | تكلفة={r[6]} | كمية={r[4]}")

conn.close()
