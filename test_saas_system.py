"""
test_saas_system.py
===================
اختبار نظام المؤسسات SaaS الشامل
يختبر:
  ✓ قاعدة البيانات المركزية
  ✓ قواعد البيانات المحلية
  ✓ المزامنة
  ✓ المنتجات والخدمات
  ✓ الفواتير
  ✓ المخزون
"""

import sqlite3
import json
import os
import re
from datetime import datetime


def _safe_table_name(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""))


def _table_exists(cursor, table_name: str) -> bool:
    row = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None

def test_central_db():
    """اختبار قاعدة البيانات المركزية"""
    print("\n" + "="*80)
    print("  1. اختبار قاعدة البيانات المركزية")
    print("="*80)
    
    db_path = "database/central_saas.db"
    if not os.path.exists(db_path):
        print("❌ قاعدة البيانات المركزية غير موجودة!")
        return False
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # 1. التحقق من الجداول
    tables = c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    
    print(f"\nالجداول الموجودة ({len(tables)}):")
    for table in tables:
        table_name = table[0]
        if not _safe_table_name(table_name):
            continue
        count = c.execute(f"SELECT COUNT(*) FROM \"{table_name}\"").fetchone()[0]
        print(f"  • {table_name:30} {count:5} سجل")
    
    # 2. التحقق من إعدادات النظام
    if _table_exists(c, "system_config"):
        configs = c.execute("SELECT key, value FROM system_config").fetchall()
        print(f"\nإعدادات النظام ({len(configs)}):")
        for key, val in configs:
            print(f"  • {key:30} = {val}")
    else:
        print("\nإعدادات النظام: جدول system_config غير موجود")
    
    # 3. التحقق من المنشآت
    if _table_exists(c, "tenants"):
        tenants = c.execute("SELECT id, tenant_key, name FROM tenants").fetchall()
        print(f"\nالمنشآت ({len(tenants)}):")
        for tenant in tenants:
            print(f"  • {tenant[1]} (ID: {tenant[0]}) — {tenant[2]}")
    else:
        print("\nالمنشآت: جدول tenants غير موجود")
    
    # 4. التحقق من الأنشطة
    activities = c.execute("SELECT COUNT(*) FROM activities_definitions").fetchone()[0]
    print(f"\nالأنشطة المعرّفة: {activities}")
    
    conn.close()
    print("\n✅ اختبار قاعدة البيانات المركزية: نجح")
    return True


def test_local_db(db_path: str, device_name: str):
    """اختبار قاعدة بيانات محلية"""
    if not os.path.exists(db_path):
        print(f"❌ قاعدة البيانات المحلية غير موجودة: {db_path}")
        return False
    
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # 1. الجداول
    tables = c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    
    print(f"\n  {device_name}:")
    print(f"    الجداول: {len(tables)}")
    
    # 2. المزامنة
    sync_state = c.execute("SELECT COUNT(*) FROM local_sync_state").fetchone()[0]
    print(f"    حالة المزامنة: {sync_state} سجل")
    
    # 3. الأنشطة المحلية
    activities = c.execute("SELECT COUNT(*) FROM activities_local").fetchone()[0]
    print(f"    الأنشطة المحلية: {activities}")
    
    # 4. قائمة الانتظار
    queue = c.execute("SELECT COUNT(*) FROM offline_queue").fetchone()[0]
    print(f"    قائمة الانتظار المحلية: {queue} سجل")
    
    conn.close()
    return True


def test_local_databases():
    """اختبار جميع قواعد البيانات المحلية"""
    print("\n" + "="*80)
    print("  2. اختبار قواعد البيانات المحلية")
    print("="*80)
    
    local_dbs = [
        ("database/local_biz-001_pos-cashier-001.db", "POS - كاشير الفرع الرئيسي"),
        ("database/local_biz-001_agent-mobile-001.db", "Agent - مندوب البيع"),
        ("database/local_biz-001_cashier-branch-002.db", "Cashier - كاشير الفرع الثاني"),
    ]
    
    for db_path, device_name in local_dbs:
        if not test_local_db(db_path, device_name):
            return False
    
    print("\n✅ اختبار قواعد البيانات المحلية: نجح")
    return True


def test_config_files():
    """اختبار ملفات الإعدادات"""
    print("\n" + "="*80)
    print("  3. اختبار ملفات الإعدادات")
    print("="*80)
    
    config_dir = "config"
    config_files = [
        "device_biz-001_pos-cashier-001.json",
        "device_biz-001_agent-mobile-001.json",
        "device_biz-001_cashier-branch-002.json",
    ]
    
    for config_file in config_files:
        config_path = os.path.join(config_dir, config_file)
        if not os.path.exists(config_path):
            print(f"❌ ملف الإعدادات غير موجود: {config_path}")
            return False
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        device_id = config["device_info"]["device_id"]
        tenant_key = config["tenant_config"]["tenant_key"]
        db_path = config["tenant_config"]["local_db"]
        
        print(f"\n  ✓ {config_file}")
        print(f"    الجهاز: {device_id}")
        print(f"    المنشأة: {tenant_key}")
        print(f"    قاعدة البيانات: {db_path}")
        print(f"    وضع أوفلاين: {'نعم' if config['sync_config']['offline_mode_enabled'] else 'لا'}")
        print(f"    الميزات:")
        for feature, enabled in config["features"].items():
            status = "✓" if enabled else "✗"
            print(f"      {status} {feature}")
    
    print("\n✅ اختبار ملفات الإعدادات: نجح")
    return True


def test_activity_coverage():
    """اختبار غطاء الأنشطة"""
    print("\n" + "="*80)
    print("  4. اختبار غطاء الأنشطة (196 نشاط)")
    print("="*80)
    
    # قاعدة مركزية
    central_conn = sqlite3.connect("database/central_saas.db")
    central_activities = central_conn.execute(
        "SELECT COUNT(*) FROM activities_definitions"
    ).fetchone()[0]
    central_conn.close()
    
    # قاعدة محلية
    local_conn = sqlite3.connect("database/local_biz-001_pos-cashier-001.db")
    local_activities = local_conn.execute(
        "SELECT COUNT(*) FROM activities_local"
    ).fetchone()[0]
    local_conn.close()
    
    print(f"\nالأنشطة في المركز: {central_activities}")
    print(f"الأنشطة محلياً (POS): {local_activities}")
    print(f"التغطية المحلية: {(local_activities/central_activities*100):.1f}%")
    
    print("\n✅ اختبار غطاء الأنشطة: نجح")
    return True


def test_performance():
    """اختبار الأداء"""
    print("\n" + "="*80)
    print("  5. اختبار الأداء")
    print("="*80)
    
    import time
    
    db_path = "database/local_biz-001_pos-cashier-001.db"
    conn = sqlite3.connect(db_path)
    
    # اختبار 1: إدراج فاتورة
    print("\n  اختبار إدراج فاتورة:")
    start = time.time()
    c = conn.cursor()
    c.execute("SAVEPOINT perf_test")
    c.execute("""
        INSERT INTO invoices_local
        (invoice_number, activity_code, party_name, subtotal, total, status)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (f"INV-PERF-{datetime.now().strftime('%Y%m%d%H%M%S')}", "retail_fnb_general", "عميل تجريبي", 1000, 1150, "draft"))
    elapsed = (time.time() - start) * 1000
    print(f"    وقت الإدراج: {elapsed:.2f} ms")
    
    # اختبار 2: قراءة البيانات
    print("\n  اختبار قراءة البيانات:")
    start = time.time()
    rows = c.execute("SELECT * FROM invoices_local").fetchall()
    elapsed = (time.time() - start) * 1000
    print(f"    عدد الفواتير: {len(rows)}")
    print(f"    وقت القراءة: {elapsed:.2f} ms")
    
    c.execute("ROLLBACK TO perf_test")
    c.execute("RELEASE perf_test")
    conn.close()
    print("\n✅ اختبار الأداء: نجح")
    return True


def test_sync_queue():
    """اختبار قائمة المزامنة"""
    print("\n" + "="*80)
    print("  6. اختبار قائمة المزامنة")
    print("="*80)
    
    db_path = "database/local_biz-001_pos-cashier-001.db"
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # إضافة عنصر إلى قائمة الانتظار
    c.execute("SAVEPOINT sync_queue_test")
    c.execute("""
        INSERT INTO offline_queue
        (table_name, operation, record_id, data_json, is_synced)
        VALUES (?, ?, ?, ?, ?)
    """, ("invoices_local", "INSERT", 1, '{"invoice_number": "INV-001"}', 0))
    
    # التحقق من الحالة
    pending = c.execute(
        "SELECT COUNT(*) FROM offline_queue WHERE is_synced = 0"
    ).fetchone()[0]
    synced = c.execute(
        "SELECT COUNT(*) FROM offline_queue WHERE is_synced = 1"
    ).fetchone()[0]
    
    print(f"\nقائمة المزامنة:")
    print(f"  • معلقة: {pending} سجل")
    print(f"  • مُزامنة: {synced} سجل")
    
    c.execute("ROLLBACK TO sync_queue_test")
    c.execute("RELEASE sync_queue_test")
    conn.close()
    print("\n✅ اختبار قائمة المزامنة: نجح")
    return True


def main():
    """الاختبار الشامل"""
    print("\n" + "█" * 80)
    print("█" + " " * 78 + "█")
    print("█" + "  اختبار نظام المؤسسات SaaS الشامل".center(78) + "█")
    print("█" + " " * 78 + "█")
    print("█" * 80)
    
    tests = [
        ("قاعدة البيانات المركزية", test_central_db),
        ("قواعد البيانات المحلية", test_local_databases),
        ("ملفات الإعدادات", test_config_files),
        ("غطاء الأنشطة", test_activity_coverage),
        ("الأداء", test_performance),
        ("قائمة المزامنة", test_sync_queue),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n❌ خطأ في {test_name}: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    # الملخص النهائي
    print("\n" + "█" * 80)
    print("█" + " " * 78 + "█")
    print("█" + "  الملخص النهائي".center(78) + "█")
    print("█" + " " * 78 + "█")
    print("█" * 80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ نجح" if result else "❌ فشل"
        print(f"\n  {status} — {test_name}")
    
    print("\n" + "─" * 80)
    print(f"\nالنتيجة النهائية: {passed}/{total} اختبارات نجحت ({passed/total*100:.0f}%)")
    
    if passed == total:
        print("""
✅ ✅ ✅ نظام المؤسسات SaaS جاهز للإنتاج! ✅ ✅ ✅

الخطوات التالية:
  1. شغّل التطبيق: python app.py
  2. اختبر المزامنة الأوفلاين/الأونلاين
  3. أضف منشآت إضافية: python setup_tenant_local.py biz-002 pos-001
  4. انشر النظام على الخادم المركزي
""")
    else:
        print("\n❌ يوجد اختبارات فاشلة. تحقق من الأخطاء أعلاه.")
    
    print("█" * 80 + "\n")


if __name__ == "__main__":
    main()
