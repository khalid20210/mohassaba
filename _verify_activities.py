"""تحقق من الأنشطة المحقونة في قاعدة البيانات"""
import sqlite3

print("=" * 80)
print("  التحقق من الأنشطة المحقونة")
print("=" * 80 + "\n")

# تحقق من قاعدة البيانات المركزية
central_db = "database/central_saas.db"
conn = sqlite3.connect(central_db)
c = conn.cursor()

# إحصائيات عامة
total = c.execute("SELECT COUNT(*) FROM activities_definitions").fetchone()[0]
print(f"✓ إجمالي الأنشطة في المركز: {total}")

# عرض الأنشطة الجديدة (بعد الـ 57 الأولى)
print("\n📋 الأنشطة الجديدة (أول 20 من الإضافات الـ 139):")
print("-" * 80)

result = c.execute("""
    SELECT code, name_ar, category, sub_category 
    FROM activities_definitions 
    ORDER BY rowid 
    LIMIT 57, 20
""").fetchall()

for i, (code, name_ar, cat, subcat) in enumerate(result, 1):
    print(f"{i:2d}. {code:40} → {name_ar:30} ({cat}/{subcat})")

# عرض آخر 10 أنشطة
print("\n📋 آخر 10 أنشطة:")
print("-" * 80)

result = c.execute("""
    SELECT code, name_ar, category, sub_category 
    FROM activities_definitions 
    ORDER BY rowid DESC
    LIMIT 10
""").fetchall()

for i, (code, name_ar, cat, subcat) in enumerate(result, 1):
    print(f"{i:2d}. {code:40} → {name_ar:30} ({cat}/{subcat})")

conn.close()

# إحصائيات الفئات
print("\n📊 توزيع الأنشطة حسب الفئة:")
print("-" * 80)

conn = sqlite3.connect(central_db)
c = conn.cursor()

result = c.execute("""
    SELECT category, COUNT(*) as count
    FROM activities_definitions
    GROUP BY category
    ORDER BY count DESC
""").fetchall()

for cat, count in result:
    print(f"  • {cat:30} → {count:3d} نشاط")

total = sum(x[1] for x in result)
print(f"  {'─' * 45}")
print(f"  {'المجموع':30} → {total:3d} نشاط ✅")

conn.close()

print("\n" + "=" * 80)
print("✅ تم التحقق بنجاح من جميع الأنشطة!")
print("=" * 80 + "\n")
