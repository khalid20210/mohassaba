"""
final_system_test.py
====================
اختبار شامل لنظام الاستيراد المتقدم
"""

import sqlite3
import os
from datetime import datetime

print("\n" + "="*80)
print("  🧪 الاختبار الشامل لنظام الاستيراد المتقدم")
print("="*80 + "\n")

# الاتصال بقاعدة البيانات
conn = sqlite3.connect("database/central_saas.db")
c = conn.cursor()

results = {
    "passed": [],
    "failed": [],
    "warnings": []
}

# ================== الاختبار 1: وجود الجداول ==================
print("1️⃣  اختبار 1: فحص وجود الجداول...")
try:
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='products_bulk'")
    if c.fetchone():
        results["passed"].append("جدول products_bulk موجود ✅")
    else:
        results["failed"].append("جدول products_bulk غير موجود ❌")
except Exception as e:
    results["failed"].append(f"خطأ في فحص الجدول: {e}")

# ================== الاختبار 2: عدد المنتجات ==================
print("2️⃣  اختبار 2: فحص عدد المنتجات...")
try:
    count = c.execute("SELECT COUNT(*) FROM products_bulk").fetchone()[0]
    if count >= 1000:
        results["passed"].append(f"عدد المنتجات: {count:,d} ✅")
    elif count >= 100:
        results["warnings"].append(f"عدد المنتجات: {count:,d} (أقل من 1,000)")
    else:
        results["failed"].append(f"عدد المنتجات: {count} (قليل جداً)")
except Exception as e:
    results["failed"].append(f"خطأ في عد المنتجات: {e}")

# ================== الاختبار 3: جودة البيانات ==================
print("3️⃣  اختبار 3: فحص جودة البيانات...")
try:
    # الرموز الفارغة
    empty_codes = c.execute("SELECT COUNT(*) FROM products_bulk WHERE code IS NULL OR code=''").fetchone()[0]
    if empty_codes == 0:
        results["passed"].append("لا توجد رموز فارغة ✅")
    else:
        results["failed"].append(f"عدد الرموز الفارغة: {empty_codes}")
    
    # الأسماء الفارغة
    empty_names = c.execute("SELECT COUNT(*) FROM products_bulk WHERE name_ar IS NULL OR name_ar=''").fetchone()[0]
    if empty_names == 0:
        results["passed"].append("لا توجد أسماء فارغة ✅")
    else:
        results["failed"].append(f"عدد الأسماء الفارغة: {empty_names}")
    
    # الأسعار السالبة
    negative_prices = c.execute("SELECT COUNT(*) FROM products_bulk WHERE price < 0").fetchone()[0]
    if negative_prices == 0:
        results["passed"].append("لا توجد أسعار سالبة ✅")
    else:
        results["failed"].append(f"عدد الأسعار السالبة: {negative_prices}")

except Exception as e:
    results["failed"].append(f"خطأ في فحص الجودة: {e}")

# ================== الاختبار 4: Relational Mapping ==================
print("4️⃣  اختبار 4: فحص ربط الأنشطة...")
try:
    # النشاطات الفارغة
    null_activities = c.execute("SELECT COUNT(*) FROM products_bulk WHERE activity_id IS NULL").fetchone()[0]
    if null_activities == 0:
        results["passed"].append("جميع المنتجات لها activity_id ✅")
    else:
        results["failed"].append(f"عدد المنتجات بدون activity_id: {null_activities}")
    
    # activity_code
    null_codes = c.execute("SELECT COUNT(*) FROM products_bulk WHERE activity_code IS NULL OR activity_code=''").fetchone()[0]
    if null_codes == 0:
        results["passed"].append("جميع المنتجات لها activity_code ✅")
    else:
        results["failed"].append(f"عدد المنتجات بدون activity_code: {null_codes}")
    
    # عدد الأنشطة المختلفة
    unique_activities = c.execute("SELECT COUNT(DISTINCT activity_code) FROM products_bulk").fetchone()[0]
    results["passed"].append(f"عدد الأنشطة المختلفة: {unique_activities} ✅")

except Exception as e:
    results["failed"].append(f"خطأ في فحص الربط: {e}")

# ================== الاختبار 5: Duplicate Detection ==================
print("5️⃣  اختبار 5: فحص كشف التكرار...")
try:
    # تكرار الرموز
    duplicates = c.execute("""
        SELECT COUNT(*) FROM (
            SELECT code FROM products_bulk GROUP BY code HAVING COUNT(*) > 1
        )
    """).fetchone()[0]
    
    if duplicates == 0:
        results["passed"].append("لا توجد رموز مكررة ✅")
    else:
        results["warnings"].append(f"عدد الرموز المكررة: {duplicates}")

except Exception as e:
    results["failed"].append(f"خطأ في فحص التكرار: {e}")

# ================== الاختبار 6: FOREIGN KEY Integrity ==================
print("6️⃣  اختبار 6: فحص سلامة المفاتيح الأجنبية...")
try:
    # التحقق من أن جميع activity_id موجودة في activities_definitions
    orphaned = c.execute("""
        SELECT COUNT(*) FROM products_bulk pb
        WHERE pb.activity_id NOT IN (SELECT id FROM activities_definitions)
    """).fetchone()[0]
    
    if orphaned == 0:
        results["passed"].append("جميع المفاتيح الأجنبية صحيحة ✅")
    else:
        results["failed"].append(f"عدد السجلات اليتيمة: {orphaned}")

except Exception as e:
    results["failed"].append(f"خطأ في فحص المفاتيح: {e}")

# ================== الاختبار 7: الإحصائيات ==================
print("7️⃣  اختبار 7: حساب الإحصائيات...")
try:
    stats = c.execute("""
        SELECT 
            MIN(price) as min_price,
            MAX(price) as max_price,
            AVG(price) as avg_price,
            SUM(stock) as total_stock
        FROM products_bulk
    """).fetchone()
    
    results["passed"].append(f"أقل سعر: {stats[0]:.2f} ✅")
    results["passed"].append(f"أعلى سعر: {stats[1]:.2f} ✅")
    results["passed"].append(f"متوسط السعر: {stats[2]:.2f} ✅")
    results["passed"].append(f"إجمالي المخزون: {stats[3]:,d} ✅")

except Exception as e:
    results["failed"].append(f"خطأ في الإحصائيات: {e}")

# ================== الاختبار 8: الملفات المساعدة ==================
print("8️⃣  اختبار 8: فحص الملفات المساعدة...")
files_to_check = [
    "setup_products_table.py",
    "import_products_advanced.py",
    "generate_sample_products.py",
    "fix_activity_mapping.py",
    "verify_imported_products.py",
    "extract_and_import_real_products.py",
    "منتجات/products_export.csv"
]

for file in files_to_check:
    if os.path.exists(file):
        results["passed"].append(f"الملف {file} موجود ✅")
    else:
        results["warnings"].append(f"الملف {file} غير موجود")

# ================== النتائج النهائية ==================
print("\n" + "="*80)
print("  📊 نتائج الاختبار الشامل")
print("="*80 + "\n")

print("✅ الاختبارات الناجحة:")
for msg in results["passed"]:
    print(f"   {msg}")

if results["warnings"]:
    print("\n⚠️  تحذيرات:")
    for msg in results["warnings"]:
        print(f"   {msg}")

if results["failed"]:
    print("\n❌ الاختبارات الفاشلة:")
    for msg in results["failed"]:
        print(f"   {msg}")

# ================== الملخص النهائي ==================
print("\n" + "="*80)
total_passed = len(results["passed"])
total_failed = len(results["failed"])
pass_rate = (total_passed / (total_passed + total_failed) * 100) if (total_passed + total_failed) > 0 else 0

print(f"📈 معدل النجاح: {pass_rate:.1f}% ({total_passed}/{total_passed + total_failed})")
print("="*80 + "\n")

if total_failed == 0:
    print("🎉 جميع الاختبارات نجحت! النظام جاهز للإنتاج! 🚀\n")
else:
    print(f"⚠️  هناك {total_failed} اختبارات فاشلة. يرجى التحقق من المشاكل.\n")

conn.close()
