#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
_test_receivables_system_v2.py — اختبار نظام الذمم المتقدم

الاختبارات:
1. تشغيل الـ migration وإنشاء الجداول
2. إنشاء حركات ذمة
3. تسجيل الدفعات
4. تقرير التقادم
5. مقاييس الأداء
"""
import os
import sys
import sqlite3
from datetime import datetime, timedelta

# إضافة المسار
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.config import DB_PATH
from modules.advanced_receivables import (
    get_contact_balance, create_receivable_transaction, record_payment,
    generate_aging_report, calculate_performance_metrics, check_credit_alerts
)


def test_receivables_system():
    """اختبار نظام الذمم المتقدم"""
    print("=" * 80)
    print("اختبار نظام الذمم المتقدم (Advanced Receivables System)")
    print("=" * 80)
    
    # 1. الاتصال بقاعدة البيانات
    print("\n[1] الاتصال بقاعدة البيانات...")
    try:
        db = sqlite3.connect(DB_PATH)
        db.row_factory = sqlite3.Row
        print("✅ تم الاتصال بنجاح")
    except Exception as e:
        print(f"❌ خطأ: {e}")
        return False
    
    # 2. التحقق من الجداول
    print("\n[2] التحقق من الجداول الجديدة...")
    tables = [
        'receivables_payables_summary',
        'receivables_payables_transactions',
        'payment_allocations',
        'aging_snapshot',
        'credit_policies',
        'receivables_performance_metrics',
        'bad_debt_write_offs',
        'receivables_alerts',
    ]
    
    all_exist = True
    for table in tables:
        exists = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,)
        ).fetchone()
        status = "✅" if exists else "⚠️"
        if not exists:
            all_exist = False
        print(f"  {status} {table}")
    
    if not all_exist:
        print("\n⚠️ بعض الجداول غير موجودة - قد تحتاج لتشغيل migrations")
    
    # 3. إنشاء بيانات اختبار
    print("\n[3] إنشاء بيانات اختبار...")
    
    try:
        # منشأة
        db.execute(
            "INSERT OR IGNORE INTO businesses (id, name, tax_number, cr_number, country, industry_type) VALUES (?,?,?,?,?,?)",
            (1, "شركة الاختبار", "123456789", "9876543", "YE", "retail")
        )
        
        # عميل
        db.execute(
            "INSERT OR IGNORE INTO contacts (id, business_id, contact_type, name, phone, email) VALUES (?,?,?,?,?,?)",
            (1, 1, "customer", "أحمد محمد", "0501234567", "ahmed@example.com")
        )
        
        # حساب
        db.execute(
            "INSERT OR IGNORE INTO accounts (id, business_id, code, name, account_type, account_nature) VALUES (?,?,?,?,?,?)",
            (1, 1, "1104", "ذمم مدينة", "asset", "debit")
        )
        
        # مستخدم
        db.execute(
            "INSERT OR IGNORE INTO users (id, business_id, role_id, username, full_name, password_hash) VALUES (?,?,?,?,?,?)",
            (1, 1, 1, "admin", "المسؤول", "test")
        )
        
        db.commit()
        print("✅ تم إنشاء البيانات الاختبارية")
    except Exception as e:
        print(f"⚠️ خطأ: {e}")
    
    # 4. اختبار إنشاء حركة ذمة
    print("\n[4] اختبار إنشاء حركة ذمة...")
    try:
        trans_id = create_receivable_transaction(
            db, 1, 1, 'invoice', 1000, 'INV-001',
            due_date=(datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
            reference_id=1,
            notes="فاتورة اختبار"
        )
        print(f"✅ تم إنشاء حركة: ID={trans_id}")
    except Exception as e:
        print(f"❌ خطأ: {e}")
        return False
    
    # 5. اختبار الحصول على الرصيد
    print("\n[5] اختبار الحصول على الرصيد...")
    balance = get_contact_balance(db, 1, 1, 'receivable')
    print(f"✅ الرصيد المدين: {balance['current_balance']:.2f}")
    
    # 6. اختبار تسجيل دفعة
    print("\n[6] اختبار تسجيل دفعة...")
    try:
        payment_id, remaining = record_payment(
            db, 1, 1, 500, "CHQ-001", "شيك رقم 1"
        )
        print(f"✅ تم تسجيل دفعة: ID={payment_id}, المتبقي={remaining:.2f}")
    except Exception as e:
        print(f"❌ خطأ: {e}")
        return False
    
    # 7. اختبار تقرير التقادم
    print("\n[7] اختبار تقرير التقادم...")
    try:
        aging = generate_aging_report(db, 1, 'receivable')
        print(f"✅ تقرير التقادم:")
        for range_name, data in aging['aging'].items():
            print(f"   {range_name}: {data['count']} فاتورة / {data['amount']:.2f} ريال")
    except Exception as e:
        print(f"❌ خطأ: {e}")
        return False
    
    # 8. اختبار مقاييس الأداء
    print("\n[8] اختبار مقاييس الأداء...")
    try:
        period_end = datetime.now().strftime("%Y-%m-%d")
        period_start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        
        metrics = calculate_performance_metrics(db, 1, period_start, period_end)
        print(f"✅ مقاييس الأداء:")
        print(f"   DSO (Days Sales Outstanding): {metrics['dso']:.2f}")
        print(f"   Collection Rate: {metrics['collection_rate']:.2f}%")
        print(f"   Open Receivables: {metrics['open_receivables']:.2f}")
        print(f"   Bad Debt %: {metrics['bad_debt_percentage']:.2f}%")
    except Exception as e:
        print(f"❌ خطأ: {e}")
        return False
    
    # 9. اختبار التنبيهات
    print("\n[9] اختبار التنبيهات...")
    try:
        alerts = check_credit_alerts(db, 1)
        print(f"✅ عدد التنبيهات: {len(alerts)}")
        for alert in alerts[:3]:  # عرض أول 3 تنبيهات فقط
            print(f"   - {alert['type']}: {alert['message']}")
    except Exception as e:
        print(f"❌ خطأ: {e}")
        return False
    
    db.close()
    
    print("\n" + "=" * 80)
    print("✅ جميع الاختبارات نجحت!")
    print("=" * 80)
    return True


if __name__ == "__main__":
    success = test_receivables_system()
    sys.exit(0 if success else 1)
