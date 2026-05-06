"""
import_products_advanced.py
==========================
استيراد المنتجات مع:
  • Bulk Insert لتسريع العملية
  • Relational Mapping لربط الأنشطة الصحيحة
  • Transaction Handling للتعامل مع الأخطاء
  • Error Logging في ملف منفصل
  • Handling للبيانات الناقصة والمكررة
"""

import sqlite3
import csv
import os
import json
import sys
import io
from datetime import datetime
from collections import defaultdict

if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

class ProductImporter:
    def __init__(self, csv_file, db_file="database/central_saas.db"):
        self.csv_file = csv_file
        self.db_file = db_file
        self.errors = []
        self.warnings = []
        self.stats = {
            'total_rows': 0,
            'imported': 0,
            'skipped': 0,
            'duplicates': 0,
            'errors': 0,
        }
        self.activity_mapping = {}
        self.products_imported = set()
        self.error_log_file = f"logs/import_errors_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        
        # إنشاء مجلد السجلات
        os.makedirs("logs", exist_ok=True)
    
    def load_activity_mapping(self):
        """تحميل خريطة الأنشطة من قاعدة البيانات"""
        print("  📊 تحميل خريطة الأنشطة...")
        
        try:
            conn = sqlite3.connect(self.db_file)
            c = conn.cursor()
            
            # قراءة جميع الأنشطة
            activities = c.execute("""
                SELECT id, code, name_ar, category, sub_category
                FROM activities_definitions
            """).fetchall()
            
            for act_id, code, name_ar, category, sub_category in activities:
                self.activity_mapping[code] = {
                    'id': act_id,
                    'code': code,
                    'name_ar': name_ar,
                    'category': category,
                    'sub_category': sub_category,
                }
            
            conn.close()
            print(f"  ✓ تم تحميل {len(self.activity_mapping)} نشاط")
            
        except Exception as e:
            self.errors.append(f"خطأ في تحميل الأنشطة: {e}")
            print(f"  ❌ خطأ: {e}")
    
    def map_product_to_activity(self, product_code, category_name, business_type):
        """
        ربط المنتج بالنشاط الصحيح
        اعتماداً على: category_name أو business_type
        """
        
        # خريطة ربط الفئات بالأنشطة
        category_to_activity = {
            'مطعم': 'food_restaurant',
            'مقهى': 'food_cafe',
            'معسلات': 'food_hookah',
            'سوبر ماركت': 'retail_fnb_supermarket',
            'بقالة': 'retail_fnb_grocery',
            'ملحمة': 'retail_fnb_butcher',
            'صيدلية': 'retail_health_pharmacy',
            'صالة رياضية': 'wellness_gym',
            'ورشة سيارات': 'retail_auto_workshop',
            'محل ملابس': 'retail_fashion_clothing_m',
            'متجر أثاث': 'retail_home_furniture',
            'خدمات': 'services',
            'تجارة': 'wholesale',
        }
        
        # البحث بناءً على الفئة
        for cat_key, activity_code in category_to_activity.items():
            if category_name and cat_key in category_name:
                if activity_code in self.activity_mapping:
                    return self.activity_mapping[activity_code]
        
        # إذا لم يجد تطابق، استخدم النشاط الافتراضي
        if 'services' in self.activity_mapping:
            return self.activity_mapping['services']
        
        # إذا لم يوجد أي نشاط، استخدم أول نشاط متاح
        if self.activity_mapping:
            return list(self.activity_mapping.values())[0]
        
        return None
    
    def validate_product(self, row):
        """التحقق من صحة بيانات المنتج"""
        errors = []
        
        try:
            product_id = row.get('ID')
            code = row.get('Code', '').strip()
            name_ar = row.get('Name (AR)', '').strip()
            unit = row.get('Unit', '').strip()
            
            # التحقق من الحقول الإجبارية
            if not code:
                errors.append("رمز المنتج فارغ")
            
            if not name_ar:
                errors.append("الاسم العربي فارغ")
            
            if not unit:
                errors.append("الوحدة فارغة")
            
            # التحقق من الأسعار
            try:
                price = float(row.get('Price', 0))
                if price < 0:
                    errors.append("السعر سالب")
            except ValueError:
                errors.append("السعر غير صحيح")
            
            return len(errors) == 0, errors
            
        except Exception as e:
            return False, [str(e)]
    
    def import_products(self):
        """استيراد المنتجات مع Bulk Insert والمعاملات"""
        
        print("\n" + "="*90)
        print("  استيراد المنتجات مع Relational Mapping")
        print("="*90 + "\n")
        
        # تحميل خريطة الأنشطة
        self.load_activity_mapping()
        
        if not self.activity_mapping:
            print("❌ فشل: لم يتم العثور على أي أنشطة!")
            return False
        
        print(f"\n  📂 قراءة الملف: {self.csv_file}...")
        
        try:
            # فتح قاعدة البيانات
            conn = sqlite3.connect(self.db_file)
            c = conn.cursor()
            conn.isolation_level = None  # لتفعيل الـ transactions يدوياً
            
            # قراءة ملف CSV
            with open(self.csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            
            self.stats['total_rows'] = len(rows)
            print(f"  ✓ تم قراءة {len(rows)} صف\n")
            
            # تحضير البيانات للحقن الجماعي
            print("  🔄 معالجة البيانات ورب الأنشطة...\n")
            
            products_to_insert = []
            batch_size = 100
            
            for idx, row in enumerate(rows, 1):
                try:
                    # التحقق من الصحة
                    is_valid, validation_errors = self.validate_product(row)
                    
                    if not is_valid:
                        self.log_error(row.get('ID', '?'), 'بيانات ناقصة', validation_errors)
                        self.stats['errors'] += 1
                        continue
                    
                    # استخراج البيانات
                    product_code = row.get('Code', '').strip()
                    name_ar = row.get('Name (AR)', '').strip()
                    name_en = row.get('Name (EN)', '').strip()
                    unit = row.get('Unit', '').strip()
                    
                    # التحقق من التكرار
                    if product_code in self.products_imported:
                        self.warnings.append(f"تحذير: منتج مكرر {product_code}")
                        self.stats['duplicates'] += 1
                        continue
                    
                    # ربط النشاط
                    activity = self.map_product_to_activity(
                        product_code,
                        row.get('Category Name', ''),
                        row.get('Business Type', '')
                    )
                    
                    if not activity:
                        self.log_error(product_code, 'لم يتم ربط النشاط', ['لا يوجد نشاط مناسب'])
                        self.stats['skipped'] += 1
                        continue
                    
                    # محاولة تحويل السعر
                    try:
                        price = float(row.get('Price', 0))
                    except:
                        price = 0
                    
                    # إضافة المنتج إلى قائمة الحقن
                    products_to_insert.append({
                        'code': product_code,
                        'name_ar': name_ar,
                        'name_en': name_en or product_code,
                        'activity_id': activity['id'],
                        'activity_code': activity['code'],
                        'category': activity['category'],
                        'sub_category': activity['sub_category'],
                        'unit': unit,
                        'price': price,
                        'stock': 0,
                    })
                    
                    self.products_imported.add(product_code)
                    
                    # حقن الـ Batch عند الامتلاء
                    if len(products_to_insert) >= batch_size:
                        imported = self.bulk_insert(c, products_to_insert)
                        self.stats['imported'] += imported
                        products_to_insert = []
                        print(f"  ✓ تم حقن {imported} منتج (المعالجة: {min(idx, len(rows))}/{len(rows)})")
                
                except Exception as e:
                    self.log_error(row.get('ID', '?'), 'خطأ في المعالجة', [str(e)])
                    self.stats['errors'] += 1
                    continue
            
            # حقن البيانات المتبقية
            if products_to_insert:
                try:
                    c.execute("BEGIN TRANSACTION")
                    imported = self.bulk_insert(c, products_to_insert)
                    c.execute("COMMIT")
                    self.stats['imported'] += imported
                    print(f"  ✓ تم حقن {imported} منتج (البيانات المتبقية)")
                except Exception as e:
                    c.execute("ROLLBACK")
                    self.log_error('batch', 'خطأ في حقن الـ Batch', [str(e)])
            
            conn.commit()
            conn.close()
            
            return True
            
        except Exception as e:
            self.log_error('main', 'خطأ رئيسي', [str(e)])
            print(f"  ❌ خطأ: {e}")
            return False
    
    def bulk_insert(self, cursor, products):
        """حقن جماعي للمنتجات مع معاملات"""
        
        try:
            cursor.execute("BEGIN TRANSACTION")
            
            inserted = 0
            for product in products:
                try:
                    cursor.execute("""
                        INSERT OR REPLACE INTO products_bulk 
                        (code, name_ar, name_en, activity_id, category, sub_category, unit, price)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        product['code'],
                        product['name_ar'],
                        product['name_en'],
                        product['activity_id'],
                        product['category'],
                        product['sub_category'],
                        product['unit'],
                        product['price'],
                    ))
                    inserted += 1
                
                except Exception as e:
                    self.log_error(product['code'], 'خطأ في الحقن', [str(e)])
                    continue
            
            cursor.execute("COMMIT")
            return inserted
            
        except Exception as e:
            try:
                cursor.execute("ROLLBACK")
            except:
                pass
            self.log_error('bulk_insert', 'خطأ في الحقن الجماعي', [str(e)])
            return 0
    
    def log_error(self, product_id, error_type, details):
        """تسجيل الأخطاء في ملف منفصل"""
        
        error_entry = {
            'timestamp': datetime.now().isoformat(),
            'product_id': product_id,
            'error_type': error_type,
            'details': details,
        }
        
        try:
            with open(self.error_log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(error_entry, ensure_ascii=False) + '\n')
        except Exception as e:
            print(f"  ⚠️  فشل تسجيل الخطأ: {e}")
    
    def print_report(self):
        """طباعة التقرير النهائي"""
        
        print("\n" + "="*90)
        print("  📊 التقرير النهائي للاستيراد")
        print("="*90 + "\n")
        
        print(f"""
📈 الإحصائيات:
  • إجمالي الصفوف: {self.stats['total_rows']}
  • المنتجات المستوردة: {self.stats['imported']} ✅
  • المنتجات المكررة: {self.stats['duplicates']} ⚠️
  • الأخطاء: {self.stats['errors']} ❌
  • المتخطى: {self.stats['skipped']}
  
  معدل النجاح: {(self.stats['imported']/max(self.stats['total_rows'],1)*100):.1f}%

🚨 التحذيرات ({len(self.warnings)}):
""")
        
        for warning in self.warnings[:5]:
            print(f"  ⚠️  {warning}")
        
        if len(self.warnings) > 5:
            print(f"  ... و{len(self.warnings)-5} تحذيرات أخرى")
        
        print(f"""
📝 السجل:
  • ملف الأخطاء: {self.error_log_file}
  • عدد الأخطاء المسجلة: {len(self.errors)}
""")
        
        print("="*90 + "\n")


def main():
    print("\n" + "="*90)
    print("  نظام استيراد المنتجات المتقدم")
    print("="*90)
    
    csv_file = "منتجات/products_export.csv"
    
    # التحقق من وجود الملف
    if not os.path.exists(csv_file):
        print(f"\n❌ الملف غير موجود: {csv_file}")
        print("   قم بتشغيل extract_products.py أولاً")
        return
    
    # إنشاء مثيل من المستورد
    importer = ProductImporter(csv_file)
    
    # تنفيذ الاستيراد
    success = importer.import_products()
    
    # طباعة التقرير
    importer.print_report()
    
    if success:
        print("✅ تم الاستيراد بنجاح!\n")
    else:
        print("❌ فشل الاستيراد\n")


if __name__ == "__main__":
    main()
