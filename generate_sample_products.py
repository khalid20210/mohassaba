"""
generate_sample_products.py
===========================
إنشاء بيانات تجريبية مع 1000 منتج
مرتبطة بالأنشطة الـ 196 الموجودة
"""

import csv
import random
import sqlite3

print("\n" + "="*90)
print("  إنشاء بيانات تجريبية للمنتجات")
print("="*90 + "\n")

# الحصول على قائمة الأنشطة
conn = sqlite3.connect("database/central_saas.db")
c = conn.cursor()

activities = c.execute("SELECT id, code, name_ar FROM activities_definitions").fetchall()
conn.close()

print(f"✓ تم تحميل {len(activities)} نشاط")

# بيانات تجريبية
products_data = []

units = ['قطعة', 'كيس', 'زجاجة', 'كرتونة', 'كيلو', 'متر', 'ساعة', 'جلسة', 'حصة', 'خدمة']

# أسماء منتجات تجريبية
product_names_ar = [
    # أطعمة
    'أرز', 'دقيق', 'زيت', 'حليب', 'جبن', 'لحم', 'دجاج', 'سمك', 'خضار', 'فواكه',
    'خبز', 'حلويات', 'شوكولاتة', 'قهوة', 'شاي', 'عصير', 'مياه معدنية', 'حليب منكهة',
    
    # ملابس
    'قميص', 'بنطلون', 'فستان', 'حذاء', 'جوارب', 'قبعة', 'حقيبة', 'حزام', 'ساعة', 'نظارة',
    
    # إلكترونيات
    'جوال', 'لابتوب', 'تابلت', 'سماعات', 'شاحن', 'كابل', 'باور بانك', 'شاشة', 'لوحة مفاتيح',
    
    # صحة
    'فيتامين', 'أدوية', 'مرهم', 'شراب سعال', 'مسكن', 'خافض حرارة', 'مطهر', 'ضمادات',
    
    # منزليات
    'سرير', 'كرسي', 'طاولة', 'خزانة', 'مرتبة', 'وسادة', 'غطاء سرير', 'منديل', 'صابون', 'شامبو',
    
    # خدمات
    'استشارة', 'فحص', 'علاج', 'تنظيف', 'إصلاح', 'صيانة', 'تدريب', 'توصيل', 'تركيب', 'تصليح'
]

print("\n📦 إنشاء 1000 منتج تجريبي...\n")

for i in range(1000):
    activity = random.choice(activities)
    activity_id, activity_code, activity_name = activity
    
    name_ar = f"{random.choice(product_names_ar)} {i+1}"
    name_en = f"Product_{i+1:04d}"
    code = f"PRD-{activity_code[:4]}-{i+1:04d}"
    price = round(random.uniform(10, 500), 2)
    cost = round(price * random.uniform(0.3, 0.8), 2)
    
    products_data.append({
        'ID': i + 1,
        'Code': code,
        'Name (AR)': name_ar,
        'Name (EN)': name_en,
        'Category ID': activity_id,
        'Category Name': activity_name,
        'Business Type': activity_code,
        'Unit': random.choice(units),
        'Price': price,
        'Cost': cost,
        'Stock': random.randint(0, 500),
    })
    
    if (i + 1) % 100 == 0:
        print(f"   ✓ تم إنشاء {i + 1:,d} منتج")

print(f"   ✓ تم إنشاء {len(products_data):,d} منتج كلياً")

# حفظ إلى CSV
csv_file = "منتجات/products_export.csv"

print(f"\n💾 حفظ البيانات في: {csv_file}...\n")

try:
    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'ID', 'Code', 'Name (AR)', 'Name (EN)', 
            'Category ID', 'Category Name', 'Business Type',
            'Unit', 'Price', 'Cost', 'Stock'
        ])
        
        writer.writeheader()
        writer.writerows(products_data)
    
    print(f"✅ تم حفظ {len(products_data):,d} منتج في CSV")
    
    # إحصائيات
    total_value = sum(p['Price'] * p['Stock'] for p in products_data)
    avg_price = sum(p['Price'] for p in products_data) / len(products_data)
    
    print(f"""
📊 إحصائيات البيانات:
  • عدد المنتجات: {len(products_data):,d}
  • متوسط السعر: {avg_price:.2f}
  • إجمالي القيمة المخزنة: {total_value:,.2f}
  • الأنشطة المغطاة: {len(set(p['Business Type'] for p in products_data))} من أصل {len(activities)}
""")

except Exception as e:
    print(f"❌ خطأ: {e}")

print("="*90 + "\n")
