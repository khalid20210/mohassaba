#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

"""
_e2e_patient_flow.py — اختبار End-to-End شامل
سيناريو: عميل جديد (منشأة طبية) يستكشف ويجرب البرنامج

الخطوات:
1. تسجيل منشأة جديدة (عيادة طبية)
2. إنشاء حساب مالك
3. تسجيل الدخول
4. استعراض الخدمات المتاحة
5. تجربة إنشاء فاتورة بيع
6. إدارة المخزون
7. عرض التقارير والإحصائيات
8. اختبار الإعدادات
"""
import sqlite3, hashlib, json, random, string, time
from datetime import datetime
import pathlib
import sys

ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

from modules.industry_seeds import seed_industry_defaults
from modules.config import INDUSTRY_TYPES

DB_PATH = ROOT / "database" / "accounting_dev.db"

class PatientFlowSimulator:
    """محاكاة رحلة عميل جديد من البداية إلى النهاية"""
    
    def __init__(self):
        self.conn = None
        self.user_id = None
        self.business_id = None
        self.session_token = None
        self.results = []
        self.errors = []
    
    def log(self, step: str, success: bool, details: str = ""):
        """تسجيل خطوة"""
        icon = "✓" if success else "✗"
        status = f"[{icon}]"
        msg = f"{status} {step}"
        if details:
            msg += f"\n      {details}"
        print(msg)
        self.results.append((step, success, details))
    
    def connect(self):
        """الاتصال بقاعدة البيانات"""
        self.conn = sqlite3.connect(str(DB_PATH))
        self.conn.row_factory = sqlite3.Row
        self.log("الاتصال بقاعدة البيانات", True)
    
    # ════════════════════════════════════════════════════════════════════
    # المرحلة 1: التسجيل والتوثيق
    # ════════════════════════════════════════════════════════════════════
    
    def step_1_register_clinic(self):
        """الخطوة 1: تسجيل عيادة طبية جديدة"""
        print("\n" + "="*70)
        print("  المرحلة 1: التسجيل والإنشاء")
        print("="*70)
        
        try:
            # إنشاء اسم فريد للعيادة
            uid = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
            clinic_name_ar = f"عيادة الحياة الطبية {uid}"
            clinic_name_en = f"Al-Hayah Clinic {uid}"
            
            # إدراج العيادة
            self.business_id = self.conn.execute(
                """INSERT INTO businesses 
                   (name, name_en, industry_type, country_code, city, currency, country, is_active)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (clinic_name_ar, clinic_name_en, "medical", "SA", "الرياض", "SAR", "SA", 1)
            ).lastrowid
            self.conn.commit()
            
            clinic_info = f"اسم العيادة: {clinic_name_ar} | النوع: عيادة طبية | المدينة: الرياض"
            self.log("تسجيل عيادة طبية جديدة", True, clinic_info)
            
        except Exception as e:
            self.errors.append(str(e))
            self.log("تسجيل العيادة", False, str(e)[:50])
            return False
        
        return True
    
    def step_2_create_owner_account(self):
        """الخطوة 2: إنشاء حساب مالك العيادة"""
        try:
            # بيانات المالك
            owner_name = "د. أحمد محمد"
            owner_email = f"admin{random.randint(1000,9999)}@clinic.com"
            owner_phone = "0501234567"
            password_plain = "SecurePass123!"
            password_hash = hashlib.sha256(password_plain.encode()).hexdigest()
            
            # إنشاء حساب المستخدم
            self.user_id = self.conn.execute(
                """INSERT INTO users 
                   (business_id, role_id, username, full_name, email, phone, password_hash, is_active, created_at)
                   VALUES (?,?,?,?,?,?,?,?,datetime('now'))""",
                (self.business_id, 1, owner_email.split("@")[0], owner_name, owner_email, owner_phone, password_hash, 1)
            ).lastrowid
            self.conn.commit()
            
            account_info = f"المالك: {owner_name} | البريد: {owner_email} | الرقم: {owner_phone}"
            self.log("إنشاء حساب المالك", True, account_info)
            
            # حفظ بيانات تسجيل الدخول للخطوات التالية
            self.owner_email = owner_email
            self.owner_password = password_plain
            
        except Exception as e:
            self.errors.append(str(e))
            # تهيئة المتغيرات لتجنب الأخطاء اللاحقة
            self.owner_email = "unknown@clinic.com"
            self.owner_password = "unknown"
            self.log("إنشاء الحساب", False, str(e)[:50])
            return False
        
        return True
    
    def step_3_initialize_clinic_defaults(self):
        """الخطوة 3: تهيئة البذور والبيانات الافتراضية للعيادة"""
        try:
            # تهيئة بيانات العيادة (تصنيفات، منتجات، خدمات، إعدادات)
            summary = seed_industry_defaults(self.conn, self.business_id, "medical")
            
            # التحقق من ما تم إنشاؤه
            categories = self.conn.execute(
                "SELECT COUNT(*) as c FROM product_categories WHERE business_id=?",
                (self.business_id,)
            ).fetchone()["c"]
            
            products = self.conn.execute(
                "SELECT COUNT(*) as c FROM products WHERE business_id=?",
                (self.business_id,)
            ).fetchone()["c"]
            
            services = self.conn.execute(
                "SELECT COUNT(*) as c FROM products WHERE business_id=? AND product_type='service'",
                (self.business_id,)
            ).fetchone()["c"]
            
            init_info = f"التصنيفات: {categories} | الخدمات الطبية: {services} | المنتجات: {products}"
            self.log("تهيئة بيانات العيادة", True, init_info)
            
        except Exception as e:
            self.errors.append(str(e))
            self.log("تهيئة البيانات", False, str(e)[:50])
            return False
        
        return True
    
    # ════════════════════════════════════════════════════════════════════
    # المرحلة 2: استعراض الخدمات
    # ════════════════════════════════════════════════════════════════════
    
    def step_4_explore_services(self):
        """الخطوة 4: استعراض جميع الخدمات المتاحة"""
        print("\n" + "="*70)
        print("  المرحلة 2: استعراض الخدمات والمنتجات")
        print("="*70)
        
        try:
            # الخدمات الطبية المتاحة
            services = self.conn.execute(
                """SELECT name, sale_price, category_name FROM products 
                   WHERE business_id=? AND product_type='service'
                   ORDER BY category_name, name""",
                (self.business_id,)
            ).fetchall()
            
            if services:
                services_list = [f"• {s['name']} ({s['sale_price']} ر.س)" for s in services[:5]]
                services_info = " | ".join(services_list)
                self.log("استعراض الخدمات الطبية", True, services_info)
            else:
                self.log("استعراض الخدمات", False, "لا توجد خدمات")
                return False
            
        except Exception as e:
            self.errors.append(str(e))
            self.log("استعراض الخدمات", False, str(e)[:50])
            return False
        
        return True
    
    def step_5_explore_products(self):
        """الخطوة 5: استعراض المنتجات والأدوات الطبية"""
        try:
            products = self.conn.execute(
                """SELECT name, sale_price, category_name FROM products 
                   WHERE business_id=? AND product_type='product'
                   ORDER BY category_name, name LIMIT 8""",
                (self.business_id,)
            ).fetchall()
            
            if products:
                products_list = [f"• {p['name']} ({p['sale_price']} ر.س)" for p in products[:4]]
                products_info = "\n      ".join(products_list)
                self.log("استعراض المنتجات والأدوات", True, products_info)
            else:
                self.log("استعراض المنتجات", False, "لا توجد منتجات")
                return False
            
        except Exception as e:
            self.errors.append(str(e))
            self.log("استعراض المنتجات", False, str(e)[:50])
            return False
        
        return True
    
    # ════════════════════════════════════════════════════════════════════
    # المرحلة 3: تجربة العمليات الأساسية
    # ════════════════════════════════════════════════════════════════════
    
    def step_6_create_patient_invoice(self):
        """الخطوة 6: إنشاء فاتورة خدمة لمريض"""
        print("\n" + "="*70)
        print("  المرحلة 3: تجربة العمليات الأساسية")
        print("="*70)
        
        try:
            # الحصول على خدمة طبية
            service = self.conn.execute(
                """SELECT id, name, sale_price FROM products 
                   WHERE business_id=? AND product_type='service' LIMIT 1""",
                (self.business_id,)
            ).fetchone()
            
            if not service:
                self.log("إنشاء فاتورة خدمة", False, "لا توجد خدمات متاحة")
                return False
            
            # إنشاء رقم فاتورة فريد
            invoice_number = f"INV-{self.business_id}-{int(time.time()) % 10000}"
            
            # إنشاء فاتورة
            invoice_id = self.conn.execute(
                """INSERT INTO invoices 
                   (business_id, invoice_number, invoice_type, invoice_date, party_name, subtotal, total, status, notes, created_at)
                   VALUES (?,?,?,datetime('now'),?,?,?,'completed',?,datetime('now'))""",
                (self.business_id, invoice_number, "sales", "أحمد علي", service["sale_price"], 
                 service["sale_price"], "خدمة طبية - الكشفية الأولية", )
            ).lastrowid
            
            # إضافة بند للفاتورة
            self.conn.execute(
                """INSERT INTO invoice_lines 
                   (invoice_id, product_id, description, quantity, unit_price, total)
                   VALUES (?,?,?,?,?,?)""",
                (invoice_id, service["id"], service["name"], 1, service["sale_price"], service["sale_price"])
            )
            self.conn.commit()
            
            invoice_info = f"الفاتورة #{invoice_number} | الخدمة: {service['name']} | المبلغ: {service['sale_price']} ر.س"
            self.log("إنشاء فاتورة خدمة طبية", True, invoice_info)
            
            self.invoice_id = invoice_id
            
        except Exception as e:
            self.errors.append(str(e))
            self.log("إنشاء الفاتورة", False, str(e)[:50])
            return False
        
        return True
    
    def step_7_manage_inventory(self):
        """الخطوة 7: إدارة المخزون"""
        try:
            # الحصول على منتج
            product = self.conn.execute(
                """SELECT id, name FROM products 
                   WHERE business_id=? AND product_type='product' LIMIT 1""",
                (self.business_id,)
            ).fetchone()
            
            if not product:
                self.log("إدارة المخزون", False, "لا توجد منتجات")
                return False
            
            # إضافة كمية للمخزون
            initial_qty = 50
            # التحقق إذا كان المنتج موجود بالفعل
            existing = self.conn.execute(
                "SELECT id FROM product_inventory WHERE business_id=? AND product_id=?",
                (self.business_id, product["id"])
            ).fetchone()
            
            if existing:
                self.conn.execute(
                    "UPDATE product_inventory SET current_qty = current_qty + ?, updated_at = datetime('now') WHERE business_id=? AND product_id=?",
                    (initial_qty, self.business_id, product["id"])
                )
            else:
                self.conn.execute(
                    """INSERT INTO product_inventory 
                       (business_id, product_id, current_qty, updated_at)
                       VALUES (?,?,?,datetime('now'))""",
                    (self.business_id, product["id"], initial_qty)
                )
            self.conn.commit()
            
            inventory_info = f"المنتج: {product['name']} | الكمية: {initial_qty}"
            self.log("إضافة كمية للمخزون", True, inventory_info)
            
        except Exception as e:
            self.errors.append(str(e))
            self.log("إدارة المخزون", False, str(e)[:50])
            return False
        
        return True
    
    # ════════════════════════════════════════════════════════════════════
    # المرحلة 4: استعراض الإحصائيات والتقارير
    # ════════════════════════════════════════════════════════════════════
    
    def step_8_view_statistics(self):
        """الخطوة 8: عرض الإحصائيات والتقارير"""
        print("\n" + "="*70)
        print("  المرحلة 4: الإحصائيات والتقارير")
        print("="*70)
        
        try:
            # إجمالي الفواتير
            total_invoices = self.conn.execute(
                "SELECT COUNT(*) as c FROM invoices WHERE business_id=?",
                (self.business_id,)
            ).fetchone()["c"]
            
            # إجمالي المبيعات
            total_sales = self.conn.execute(
                "SELECT COALESCE(SUM(total), 0) as total FROM invoices WHERE business_id=?",
                (self.business_id,)
            ).fetchone()["total"]
            
            # عدد المرضى الفريدين
            unique_patients = self.conn.execute(
                """SELECT COUNT(DISTINCT party_name) as c FROM invoices 
                   WHERE business_id=? AND party_name IS NOT NULL""",
                (self.business_id,)
            ).fetchone()["c"]
            
            stats_info = f"الفواتير: {total_invoices} | المبيعات: {total_sales} ر.س | المرضى: {unique_patients}"
            self.log("عرض الإحصائيات", True, stats_info)
            
        except Exception as e:
            self.errors.append(str(e))
            self.log("عرض الإحصائيات", False, str(e)[:50])
            return False
        
        return True
    
    def step_9_check_settings(self):
        """الخطوة 9: التحقق من الإعدادات"""
        try:
            settings = self.conn.execute(
                "SELECT key, value FROM settings WHERE business_id=? LIMIT 10",
                (self.business_id,)
            ).fetchall()
            
            if settings:
                settings_keys = [s["key"] for s in settings[:5]]
                settings_info = " | ".join(settings_keys)
                self.log("التحقق من الإعدادات", True, settings_info)
            else:
                self.log("الإعدادات", False, "لا توجد إعدادات")
                return False
            
        except Exception as e:
            self.errors.append(str(e))
            self.log("الإعدادات", False, str(e)[:50])
            return False
        
        return True
    
    # ════════════════════════════════════════════════════════════════════
    # المرحلة 5: الملخص والنتائج
    # ════════════════════════════════════════════════════════════════════
    
    def step_10_final_summary(self):
        """الخطوة 10: ملخص التجربة الشاملة"""
        print("\n" + "="*70)
        print("  المرحلة 5: الملخص النهائي")
        print("="*70)
        
        passed = sum(1 for _, success, _ in self.results if success)
        total = len(self.results)
        
        print(f"\n  عدد الخطوات المنجزة: {passed}/{total}")
        print(f"  نسبة النجاح: {100*passed//total}%")
        
        if self.errors:
            print(f"\n  الأخطاء المسجلة: {len(self.errors)}")
            for err in self.errors[:3]:
                print(f"    - {err[:60]}")
        
        print(f"\n  معلومات العيادة:")
        print(f"    - معرّف العيادة: {self.business_id}")
        print(f"    - معرّف المالك: {self.user_id}")
        print(f"    - بريد المالك: {self.owner_email}")
        print(f"    - كلمة المرور: {self.owner_password}")
        
        print("\n" + "="*70)
        self.log("الملخص النهائي", passed == total, f"{passed}/{total} خطوات نجحت")
    
    def run_full_flow(self):
        """تشغيل كامل رحلة العميل"""
        print("\n╔════════════════════════════════════════════════════════════════════╗")
        print("║  اختبار E2E شامل — عميل جديد (عيادة طبية)                           ║")
        print("║  رحلة كاملة: التسجيل → الخدمات → العمليات → الإحصائيات             ║")
        print("╚════════════════════════════════════════════════════════════════════╝")
        
        t0 = time.time()
        
        steps = [
            ("تسجيل العيادة", self.step_1_register_clinic),
            ("إنشاء الحساب", self.step_2_create_owner_account),
            ("تهيئة البيانات", self.step_3_initialize_clinic_defaults),
            ("استعراض الخدمات", self.step_4_explore_services),
            ("استعراض المنتجات", self.step_5_explore_products),
            ("إنشاء فاتورة", self.step_6_create_patient_invoice),
            ("إدارة المخزون", self.step_7_manage_inventory),
            ("الإحصائيات", self.step_8_view_statistics),
            ("الإعدادات", self.step_9_check_settings),
        ]
        
        for step_name, step_func in steps:
            try:
                if not step_func():
                    break
            except Exception as e:
                self.errors.append(str(e))
                self.log(step_name, False, str(e)[:50])
        
        elapsed = time.time() - t0
        
        self.step_10_final_summary()
        print(f"\n  الزمن الإجمالي: {elapsed:.2f}s\n")
        
        return len([r for r in self.results if r[1]]) == len(self.results)


def main():
    try:
        simulator = PatientFlowSimulator()
        simulator.connect()
        success = simulator.run_full_flow()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"خطأ: {e}")
        sys.exit(1)
    finally:
        if simulator and simulator.conn:
            # تنظيف البيانات (اختياري - للاختبار فقط)
            # simulator.conn.execute("DELETE FROM businesses WHERE id=?", (simulator.business_id,))
            # simulator.conn.commit()
            simulator.conn.close()


if __name__ == "__main__":
    main()
