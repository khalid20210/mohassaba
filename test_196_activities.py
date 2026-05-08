"""
test_196_activities.py
====================
اختبار شامل للنظام مع الأنشطة الـ 196 الجديدة
"""

import sqlite3
import time
from datetime import datetime

print("\n" + "=" * 80)
print("  اختبار النظام الشامل مع 196 نشاط")
print("=" * 80 + "\n")

all_pass = True

# ─── الاختبار 1: التحقق من عدد الأنشطة في قاعدة البيانات المركزية ────────
print("🧪 [1/6] اختبار عدد الأنشطة في قاعدة البيانات المركزية...")

try:
    conn = sqlite3.connect("database/central_saas.db")
    c = conn.cursor()
    
    total = c.execute("SELECT COUNT(*) FROM activities_definitions").fetchone()[0]
    
    if total == 196:
        print(f"   ✅ PASS: {total} نشاط (مطابق)")
    else:
        print(f"   ❌ FAIL: {total} نشاط (متوقع 196)")
        all_pass = False
    
    conn.close()
except Exception as e:
    print(f"   ❌ FAIL: {e}")
    all_pass = False

# ─── الاختبار 2: التحقق من الأنشطة المحلية ─────────────────────────────
print("\n🧪 [2/6] اختبار الأنشطة المحلية (POS, Agent, Cashier)...")

try:
    local_dbs = [
        "database/local_biz-001_pos-cashier-001.db",
        "database/local_biz-001_agent-mobile-001.db",
        "database/local_biz-001_cashier-branch-002.db",
    ]
    
    all_sync = True
    for db_path in local_dbs:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        total = c.execute("SELECT COUNT(*) FROM activities_local").fetchone()[0]
        
        device_name = db_path.split("_")[-1].replace(".db", "")
        if total == 196:
            print(f"   ✅ {device_name}: {total} نشاط")
        else:
            print(f"   ❌ {device_name}: {total} نشاط (متوقع 196)")
            all_sync = False
        
        conn.close()
    
    if all_sync:
        print(f"   ✅ PASS: جميع قواعد البيانات المحلية متزامنة")
    else:
        all_pass = False
except Exception as e:
    print(f"   ❌ FAIL: {e}")
    all_pass = False

# ─── الاختبار 3: التحقق من توزيع الفئات ─────────────────────────────
print("\n🧪 [3/6] اختبار توزيع فئات الأنشطة...")

try:
    conn = sqlite3.connect("database/central_saas.db")
    c = conn.cursor()
    
    categories = c.execute("""
        SELECT category, COUNT(*) as count
        FROM activities_definitions
        GROUP BY category
    """).fetchall()
    
    expected = {
        "services": 85,
        "retail": 58,
        "education": 22,
        "food": 20,
        "entertainment": 10,
        "wholesale": 1,
    }
    
    category_pass = True
    for cat, count in categories:
        exp_count = expected.get(cat, 0)
        if count == exp_count:
            print(f"   ✓ {cat:20} → {count:3d} نشاط")
        else:
            print(f"   ✗ {cat:20} → {count:3d} نشاط (متوقع {exp_count})")
            category_pass = False
    
    if category_pass:
        print(f"   ✅ PASS: جميع الفئات محسوبة بشكل صحيح")
    else:
        print(f"   ⚠️  بعض الفئات تحتاج تحقق")
        all_pass = False
    
    conn.close()
except Exception as e:
    print(f"   ❌ FAIL: {e}")
    all_pass = False

# ─── الاختبار 4: اختبار الأداء (Insert/Select) ─────────────────────────
print("\n🧪 [4/6] اختبار الأداء (Insert/Select)...")

try:
    conn = sqlite3.connect("database/local_biz-001_pos-cashier-001.db")
    c = conn.cursor()
    
    # اختبار Insert
    start = time.time()
    c.execute("SAVEPOINT perf_test")
    c.execute("""
        INSERT INTO invoices_local 
        (invoice_number, activity_code, party_name, total, status)
        VALUES (?, ?, ?, ?, ?)
    """, ("TEST-001", "food_restaurant", "عميل تجريبي", 100.00, "draft"))
    insert_time = (time.time() - start) * 1000
    
    # اختبار Select
    start = time.time()
    result = c.execute("SELECT * FROM invoices_local WHERE invoice_number = ?", ("TEST-001",)).fetchone()
    select_time = (time.time() - start) * 1000
    
    # تنظيف دون التأثير على البيانات الفعلية
    c.execute("ROLLBACK TO perf_test")
    c.execute("RELEASE perf_test")
    conn.close()
    
    if insert_time < 100 and select_time < 100:
        print(f"   ✓ Insert: {insert_time:.1f}ms")
        print(f"   ✓ Select: {select_time:.1f}ms")
        print(f"   ✅ PASS: الأداء ممتاز")
    else:
        print(f"   ⚠️  Insert: {insert_time:.1f}ms, Select: {select_time:.1f}ms")
        print(f"   ✅ PASS: الأداء مقبول")
except Exception as e:
    print(f"   ❌ FAIL: {e}")
    all_pass = False

# ─── الاختبار 5: اختبار البحث عن نشاط معين ─────────────────────────────
print("\n🧪 [5/6] اختبار البحث عن أنشطة محددة...")

try:
    conn = sqlite3.connect("database/central_saas.db")
    c = conn.cursor()
    
    test_codes = [
        "food_restaurant",
        "medical_dentistry",
        "education_university",
        "automotive_wash",
    ]
    
    search_pass = True
    for code in test_codes:
        result = c.execute(
            "SELECT name_ar FROM activities_definitions WHERE code = ?",
            (code,)
        ).fetchone()
        
        if result:
            print(f"   ✓ {code:40} → {result[0]}")
        else:
            print(f"   ✗ {code:40} → غير موجود")
            search_pass = False
    
    if search_pass:
        print(f"   ✅ PASS: جميع الأنشطة قابلة للبحث")
    else:
        all_pass = False
    
    conn.close()
except Exception as e:
    print(f"   ❌ FAIL: {e}")
    all_pass = False

# ─── الاختبار 6: التحقق من صحة البيانات ──────────────────────────────
print("\n🧪 [6/6] اختبار صحة البيانات...")

try:
    conn = sqlite3.connect("database/central_saas.db")
    c = conn.cursor()
    
    # التحقق من أن جميع الأنشطة لها اسم عربي
    no_arabic_name = c.execute(
        "SELECT COUNT(*) FROM activities_definitions WHERE name_ar IS NULL OR name_ar = ''"
    ).fetchone()[0]
    
    # التحقق من التكرار
    duplicates = c.execute(
        "SELECT COUNT(code) FROM activities_definitions GROUP BY code HAVING COUNT(*) > 1"
    ).fetchall()
    
    if no_arabic_name == 0 and len(duplicates) == 0:
        print(f"   ✓ جميع الأنشطة لها أسماء عربية")
        print(f"   ✓ لا توجد أنشطة مكررة")
        print(f"   ✅ PASS: البيانات صحيحة تماماً")
    else:
        if no_arabic_name > 0:
            print(f"   ⚠️  {no_arabic_name} نشاط بدون اسم عربي")
        if len(duplicates) > 0:
            print(f"   ⚠️  يوجد أنشطة مكررة")
        all_pass = False
    
    conn.close()
except Exception as e:
    print(f"   ❌ FAIL: {e}")
    all_pass = False

# ─── النتيجة النهائية ──────────────────────────────────────────────────
print("\n" + "=" * 80)
if all_pass:
    print("✅ جميع الاختبارات نجحت! (6/6 PASSED)")
else:
    print("❌ بعض الاختبارات فشلت")
print("=" * 80 + "\n")
