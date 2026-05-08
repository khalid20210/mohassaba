"""
fix_activity_mapping.py
=======================
إصلاح عمود activity_code الذي لم يتم حفظه
"""

import sqlite3

print("\n" + "="*80)
print("  إصلاح تعيين الأنشطة (Activity Mapping)")
print("="*80 + "\n")

conn = sqlite3.connect("database/central_saas.db")
c = conn.cursor()

try:
    # تحديث activity_code من جدول activities_definitions
    c.execute("""
        UPDATE products_bulk
        SET activity_code = (
            SELECT code FROM activities_definitions 
            WHERE activities_definitions.id = products_bulk.activity_id
        )
        WHERE activity_code IS NULL
    """)
    
    updated = c.rowcount
    conn.commit()
    
    print(f"✅ تم تحديث {updated:,d} منتج مع activity_code\n")
    
    # التحقق من النتيجة
    check = c.execute("SELECT COUNT(*) FROM products_bulk WHERE activity_code IS NULL").fetchone()[0]
    
    if check == 0:
        print("✅ جميع المنتجات لديها activity_code الآن\n")
        
        # إحصائيات نهائية
        stats = c.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(DISTINCT activity_code) as unique_activities,
                ROUND(AVG(price), 2) as avg_price,
                ROUND(SUM(price * stock), 2) as total_value
            FROM products_bulk
        """).fetchone()
        
        print(f"📊 إحصائيات نهائية:")
        print(f"  • إجمالي المنتجات: {stats[0]:,d}")
        print(f"  • الأنشطة المختلفة: {stats[1]}")
        print(f"  • متوسط السعر: {stats[2]:.2f}")
        print(f"  • إجمالي القيمة: {stats[3]:,.2f}")
    else:
        print(f"⚠️  لا يزال {check} منتج بدون activity_code")
    
except Exception as e:
    print(f"❌ خطأ: {e}")
    conn.rollback()
finally:
    conn.close()

print("\n" + "="*80 + "\n")
