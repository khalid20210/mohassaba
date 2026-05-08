#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""التحقق من الأرقام التسلصلية"""

import sqlite3

conn = sqlite3.connect("database/accounting_dev.db")
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Check product_inventory structure
cur.execute("PRAGMA table_info(product_inventory)")
cols = cur.fetchall()
print("=" * 70)
print("أعمدة جدول product_inventory:")
print("=" * 70)
for col in cols:
    print(f"  ✓ {col[1]:25} ({col[2]})")

# Check if SKU is there
print("\n" + "=" * 70)
print("عينة من product_inventory (مع SKU الأرقام التسلصلية):")
print("=" * 70)
cur.execute("""
    SELECT p.id, p.name, pi.sku, pi.unit_price, pi.current_qty
    FROM product_inventory pi
    JOIN products p ON p.id = pi.product_id
    WHERE pi.business_id=225 
    LIMIT 10
""")

for p in cur.fetchall():
    print(f"\n  📦 {p['name']}")
    print(f"      SKU (الرقم التسلصلي): {p['sku']}")
    print(f"      السعر: {p['unit_price']} ر.س")
    print(f"      الكمية: {p['current_qty']} وحدة")

# إحصائيات SKU
cur.execute("""
    SELECT COUNT(*), 
           COUNT(DISTINCT sku) as unique_skus,
           MIN(CAST(SUBSTR(sku, -6) AS INTEGER)) as min_num,
           MAX(CAST(SUBSTR(sku, -6) AS INTEGER)) as max_num
    FROM product_inventory 
    WHERE business_id=225 AND sku LIKE 'SPM-%'
""")

row = cur.fetchone()
print("\n" + "=" * 70)
print("📊 إحصائيات الأرقام التسلصلية:")
print("=" * 70)
print(f"  • إجمالي المنتجات: {row[0]:,}")
print(f"  • أرقام تسلصلية فريدة: {row[1]:,}")
print(f"  • أول رقم تسلصلي: SPM-{row[2]:06d}")
print(f"  • آخر رقم تسلصلي: SPM-{row[3]:06d}")

conn.close()
