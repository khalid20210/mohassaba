"""
extract_products.py
===================
استخراج المنتجات من قاعدة البيانات الأصلية إلى ملف CSV
مع معلومات الأنشطة والفئات
"""

import sqlite3
import csv
import sys
import io

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

print("\n" + "="*90)
print("  استخراج المنتجات من قاعدة البيانات")
print("="*90 + "\n")

# قراءة من قاعدة البيانات الأصلية
conn = sqlite3.connect("accounting_dev.db")
c = conn.cursor()

print("📊 استخراج البيانات...")

# الاستعلام الرئيسي
c.execute("""
    SELECT 
        p.id,
        p.code,
        p.name_ar,
        p.name_en,
        p.category_id,
        p.unit,
        p.price,
        p.cost,
        p.stock_qty,
        pc.name_ar as category_name,
        pc.business_type
    FROM products p
    LEFT JOIN product_categories pc ON p.category_id = pc.id
    LIMIT 500
""")

products = c.fetchall()
total = len(products)
conn.close()

print(f"✓ تم قراءة {total} منتج\n")

# كتابة إلى ملف CSV
csv_file = "منتجات/products_export.csv"

try:
    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        
        # كتابة رؤوس الأعمدة
        writer.writerow([
            'ID',
            'Code',
            'Name (AR)',
            'Name (EN)',
            'Category ID',
            'Category Name',
            'Business Type',
            'Unit',
            'Price',
            'Cost',
            'Stock'
        ])
        
        # كتابة البيانات
        for row in products:
            writer.writerow(row)
    
    print(f"✅ تم حفظ {total} منتج في: {csv_file}")
    
    # إحصائيات
    print(f"""
📋 إحصائيات الملف:
  • عدد المنتجات: {total}
  • الملف: {csv_file}
  • الحجم: {round(open(csv_file).read().__sizeof__() / 1024, 2)} KB
""")

except Exception as e:
    print(f"❌ خطأ في كتابة الملف: {e}")

print("="*90 + "\n")
