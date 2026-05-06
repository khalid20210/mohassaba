"""
extract_and_import_real_products.py
==================================
سكريبت لاستخراج واستيراد المنتجات الحقيقية من ملف CSV أو قاعدة بيانات
"""

import sqlite3
import csv
import json
from datetime import datetime
from pathlib import Path

def extract_from_csv(csv_path):
    """استخراج المنتجات من ملف CSV"""
    products = []
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                products.append({
                    'code': row.get('code', ''),
                    'name_ar': row.get('name_ar', row.get('اسم المنتج', '')),
                    'name_en': row.get('name_en', ''),
                    'category': row.get('category', row.get('الفئة', '')),
                    'unit': row.get('unit', row.get('الوحدة', 'قطعة')),
                    'price': row.get('price', row.get('السعر', '0')),
                    'cost': row.get('cost', '0'),
                    'stock': row.get('stock', row.get('المخزون', '0')),
                    'barcode': row.get('barcode', ''),
                    'sku': row.get('sku', ''),
                    'description': row.get('description', '')
                })
        return products
    except Exception as e:
        print(f"❌ خطأ في قراءة CSV: {e}")
        return []

def extract_from_database(db_path, table_name):
    """استخراج المنتجات من قاعدة بيانات"""
    products = []
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        
        # محاولة استخراج من جدول معروف
        c.execute(f"SELECT * FROM {table_name} LIMIT 100")
        columns = [desc[0] for desc in c.description]
        
        rows = c.fetchall()
        for row in rows:
            product = {col: row[i] for i, col in enumerate(columns)}
            products.append(product)
        
        conn.close()
        return products
    except Exception as e:
        print(f"❌ خطأ في استخراج من قاعدة البيانات: {e}")
        return []

def import_products(products):
    """
    استيراد المنتجات باستخدام نفس منطق import_products_advanced.py
    لكن مع تحسينات الأداء
    """
    print("\n" + "="*80)
    print("  استيراد المنتجات الحقيقية")
    print("="*80 + "\n")
    
    # إذا لم تشغل setup_products_table.py من قبل، قم بتشغيله الآن
    try:
        import setup_products_table
        print("✓ جداول قاعدة البيانات جاهزة")
    except:
        pass
    
    # تشغيل نظام الاستيراد
    try:
        from import_products_advanced import ProductImporter
        
        importer = ProductImporter()
        
        # إنشاء ملف CSV مؤقت
        csv_path = "منتجات/temp_import.csv"
        Path("منتجات").mkdir(exist_ok=True)
        
        with open(csv_path, 'w', encoding='utf-8', newline='') as f:
            if products:
                fieldnames = products[0].keys()
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(products)
        
        print(f"✓ تم إنشاء ملف CSV مؤقت: {csv_path}")
        print(f"📦 عدد المنتجات: {len(products)}\n")
        
        # تشغيل الاستيراد
        importer.import_from_csv(csv_path)
        
    except Exception as e:
        print(f"❌ خطأ في الاستيراد: {e}")

def main():
    """
    استخدام سريع:
    
    1. لاستيراد من CSV:
       extract_and_import_real_products.py --csv "path/to/products.csv"
    
    2. لاستيراد من قاعدة بيانات:
       extract_and_import_real_products.py --db "path/to/db.db" --table "products"
    
    3. للاختبار مع 100 منتج فقط:
       extract_and_import_real_products.py --test
    """
    
    print("\n" + "="*80)
    print("  أداة الاستيراد والاستخراج")
    print("="*80 + "\n")
    
    import sys
    
    if len(sys.argv) < 2:
        print(__doc__)
        return
    
    if sys.argv[1] == '--csv':
        csv_path = sys.argv[2] if len(sys.argv) > 2 else "منتجات/products_export.csv"
        print(f"📄 استخراج من CSV: {csv_path}\n")
        products = extract_from_csv(csv_path)
        import_products(products)
        
    elif sys.argv[1] == '--db':
        db_path = sys.argv[2] if len(sys.argv) > 2 else "database/central_saas.db"
        table_name = sys.argv[4] if len(sys.argv) > 4 else "products"
        print(f"🗄️  استخراج من قاعدة البيانات: {db_path} → {table_name}\n")
        products = extract_from_database(db_path, table_name)
        import_products(products)
        
    elif sys.argv[1] == '--test':
        print("🧪 اختبار مع 100 منتج فقط\n")
        from generate_sample_products import generate_test_products
        products = generate_test_products(100)
        import_products(products)
    
    print("\n" + "="*80 + "\n")

if __name__ == "__main__":
    main()
