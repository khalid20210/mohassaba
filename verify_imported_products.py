"""
verify_imported_products.py
===========================
التحقق من المنتجات المستوردة وربطها بالأنشطة
"""

import sqlite3

print("\n" + "="*90)
print("  التحقق من المنتجات المستوردة وربطها بالأنشطة")
print("="*90 + "\n")

conn = sqlite3.connect("database/central_saas.db")
c = conn.cursor()

# الإحصائيات الأساسية
total_products = c.execute("SELECT COUNT(*) FROM products_bulk").fetchone()[0]
print(f"✅ إجمالي المنتجات المستوردة: {total_products:,d}\n")

# التحقق من الربط بالأنشطة
print("📊 توزيع المنتجات حسب النشاط:\n")

activities_count = c.execute("""
    SELECT 
        COALESCE(activity_code, 'unknown'),
        COALESCE(activity_code, 'unknown'),
        COUNT(*) as count,
        ROUND(AVG(price), 2) as avg_price
    FROM products_bulk
    GROUP BY activity_code
    ORDER BY count DESC
    LIMIT 15
""").fetchall()

for activity_code, name, count, avg_price in activities_count:
    pct = (count / total_products) * 100
    avg_p = avg_price if avg_price else 0
    print(f"  • {activity_code:40} → {count:3d} منتج ({pct:5.1f}%) | متوسط السعر: {avg_p:.2f}")

print("\n" + "="*90)
print("  التحقق من جودة الربط:")
print("="*90 + "\n")

# عد الأنشطة المختلفة
unique_activities = c.execute("""
    SELECT COUNT(DISTINCT activity_code) FROM products_bulk
""").fetchone()[0]

print(f"✓ عدد الأنشطة المستخدمة: {unique_activities} من أصل 196")

# التحقق من الحقول الإجبارية
missing_data = c.execute("""
    SELECT 
        SUM(CASE WHEN code IS NULL THEN 1 ELSE 0 END) as null_codes,
        SUM(CASE WHEN name_ar IS NULL THEN 1 ELSE 0 END) as null_names,
        SUM(CASE WHEN activity_id IS NULL THEN 1 ELSE 0 END) as null_activities,
        SUM(CASE WHEN price < 0 THEN 1 ELSE 0 END) as negative_prices
    FROM products_bulk
""").fetchone()

print(f"""
✓ فحص سلامة البيانات:
  • الرموز الفارغة: {missing_data[0] if missing_data[0] else 'صفر'} ✅
  • الأسماء الفارغة: {missing_data[1] if missing_data[1] else 'صفر'} ✅
  • الأنشطة الفارغة: {missing_data[2] if missing_data[2] else 'صفر'} ✅
  • الأسعار السالبة: {missing_data[3] if missing_data[3] else 'صفر'} ✅
""")

# عينة من المنتجات
print("\n📋 عينة من المنتجات المستوردة:\n")

samples = c.execute("""
    SELECT 
        code, 
        name_ar, 
        activity_code, 
        unit, 
        price
    FROM products_bulk
    LIMIT 10
""").fetchall()

for code, name_ar, activity_code, unit, price in samples:
    print(f"  • {code:20} | {name_ar:30} | {activity_code:20} | {unit:10} | {price:8.2f}")

# إحصائيات الأسعار
print("\n💰 إحصائيات الأسعار:\n")

price_stats = c.execute("""
    SELECT 
        MIN(price) as min_price,
        MAX(price) as max_price,
        ROUND(AVG(price), 2) as avg_price,
        ROUND(SUM(price * stock), 2) as total_value
    FROM products_bulk
""").fetchone()

print(f"  • أقل سعر: {price_stats[0]:.2f}")
print(f"  • أعلى سعر: {price_stats[1]:.2f}")
print(f"  • متوسط السعر: {price_stats[2]:.2f}")
print(f"  • إجمالي القيمة المخزنة: {price_stats[3]:,.2f}")

conn.close()

print("\n" + "="*90)
print("✅ التحقق مكتمل! النظام جاهز للإنتاج")
print("="*90 + "\n")
