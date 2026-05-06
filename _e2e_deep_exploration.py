#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

"""
_e2e_deep_exploration.py — استكشاف عميق للبرنامج
سيناريو متقدم: العميل يستكشف المزيد من الميزات
"""
import sqlite3, random, string, time
import pathlib
import sys

ROOT = pathlib.Path(__file__).parent
sys.path.insert(0, str(ROOT))

from modules.industry_seeds import seed_industry_defaults
from modules.config import INDUSTRY_TYPES

DB_PATH = ROOT / "database" / "accounting_dev.db"

class DeepExploration:
    """استكشاف عميق للبرنامج"""
    
    def __init__(self, business_id, user_id, conn):
        self.business_id = business_id
        self.user_id = user_id
        self.conn = conn
        self.results = []
    
    def log(self, step: str, success: bool, details: str = ""):
        """تسجيل خطوة"""
        icon = "✓" if success else "✗"
        status = f"[{icon}]"
        msg = f"{status} {step}"
        if details:
            msg += f"\n      {details}"
        print(msg)
        self.results.append((step, success, details))
    
    # ════════════════════════════════════════════════════════════════════
    # استعراض التصنيفات والمنتجات
    # ════════════════════════════════════════════════════════════════════
    
    def explore_categories(self):
        """استعراض كل التصنيفات المتاحة"""
        print("\n📂 استعراض التصنيفات:")
        try:
            categories = self.conn.execute(
                """SELECT id, name, count FROM (
                   SELECT c.id, c.name, COUNT(p.id) as count
                   FROM product_categories c
                   LEFT JOIN products p ON p.category_id = c.id AND p.business_id = c.business_id
                   WHERE c.business_id = ?
                   GROUP BY c.id, c.name
                ) ORDER BY count DESC""",
                (self.business_id,)
            ).fetchall()
            
            if categories:
                category_list = [f"• {c['name']} ({c['count']} منتج)" for c in categories[:5]]
                cat_info = "\n      ".join(category_list)
                self.log("استعراض التصنيفات", True, cat_info)
            else:
                self.log("التصنيفات", False, "لا توجد تصنيفات")
                return False
        except Exception as e:
            self.log("التصنيفات", False, str(e)[:50])
            return False
        
        return True
    
    def explore_all_services(self):
        """استعراض جميع الخدمات المتاحة"""
        print("\n🔧 استعراض جميع الخدمات:")
        try:
            services = self.conn.execute(
                """SELECT name, sale_price, category_name FROM products 
                   WHERE business_id=? AND product_type='service'
                   ORDER BY sale_price DESC""",
                (self.business_id,)
            ).fetchall()
            
            if services:
                service_list = [f"• {s['name']}: {s['sale_price']} ر.س" for s in services]
                services_info = "\n      ".join(service_list[:8])
                total = len(services)
                self.log(f"جميع الخدمات ({total} خدمة)", True, services_info)
            else:
                self.log("الخدمات", False, "لا توجد خدمات")
                return False
        except Exception as e:
            self.log("الخدمات", False, str(e)[:50])
            return False
        
        return True
    
    # ════════════════════════════════════════════════════════════════════
    # عمليات متقدمة
    # ════════════════════════════════════════════════════════════════════
    
    def create_multiple_invoices(self, count: int = 3):
        """إنشاء عدة فواتير للاختبار"""
        print(f"\n💰 إنشاء {count} فواتير متعددة:")
        try:
            services = self.conn.execute(
                "SELECT id, name, sale_price FROM products WHERE business_id=? AND product_type='service' LIMIT ?",
                (self.business_id, count)
            ).fetchall()
            
            if not services:
                self.log("الفواتير المتعددة", False, "لا توجد خدمات")
                return False
            
            invoices_created = 0
            for idx, service in enumerate(services):
                invoice_number = f"INV-{self.business_id}-{int(time.time()) % 10000 + idx}"
                patient_names = ["أحمد علي", "فاطمة محمد", "علي حسن", "خديجة أحمد"]
                
                invoice_id = self.conn.execute(
                    """INSERT INTO invoices 
                       (business_id, invoice_number, invoice_type, invoice_date, party_name, subtotal, total, status, created_at)
                       VALUES (?,?,?,datetime('now'),?,?,?,'completed',datetime('now'))""",
                    (self.business_id, invoice_number, "sales", random.choice(patient_names),
                     service["sale_price"], service["sale_price"])
                ).lastrowid
                
                self.conn.execute(
                    "INSERT INTO invoice_lines (invoice_id, product_id, description, quantity, unit_price, total) VALUES (?,?,?,?,?,?)",
                    (invoice_id, service["id"], service["name"], 1, service["sale_price"], service["sale_price"])
                )
                
                invoices_created += 1
            
            self.conn.commit()
            self.log(f"إنشاء {count} فواتير", True, f"تم إنشاء {invoices_created} فاتورة بنجاح")
            
        except Exception as e:
            self.log("الفواتير المتعددة", False, str(e)[:50])
            return False
        
        return True
    
    def analyze_revenue(self):
        """تحليل الإيرادات"""
        print("\n📊 تحليل الإيرادات:")
        try:
            # إجمالي الإيرادات
            total_revenue = self.conn.execute(
                "SELECT COALESCE(SUM(total), 0) as total FROM invoices WHERE business_id=?",
                (self.business_id,)
            ).fetchone()["total"]
            
            # عدد الفواتير
            invoice_count = self.conn.execute(
                "SELECT COUNT(*) as c FROM invoices WHERE business_id=?",
                (self.business_id,)
            ).fetchone()["c"]
            
            # متوسط قيمة الفاتورة
            avg_invoice = total_revenue / invoice_count if invoice_count > 0 else 0
            
            revenue_info = f"الإجمالي: {total_revenue} ر.س | عدد الفواتير: {invoice_count} | المتوسط: {avg_invoice:.1f} ر.س"
            self.log("تحليل الإيرادات", True, revenue_info)
            
        except Exception as e:
            self.log("الإيرادات", False, str(e)[:50])
            return False
        
        return True
    
    def check_inventory_status(self):
        """فحص حالة المخزون"""
        print("\n📦 فحص حالة المخزون:")
        try:
            inventory = self.conn.execute(
                """SELECT p.name, pi.current_qty, pi.unit_cost, pi.unit_price
                   FROM product_inventory pi
                   JOIN products p ON pi.product_id = p.id
                   WHERE pi.business_id = ?
                   LIMIT 5""",
                (self.business_id,)
            ).fetchall()
            
            if inventory:
                inventory_list = [f"• {i['name']}: {i['current_qty']} وحدة (السعر: {i['unit_price']} ر.س)" for i in inventory]
                inv_info = "\n      ".join(inventory_list)
                self.log("حالة المخزون", True, inv_info)
            else:
                self.log("المخزون", False, "لا توجد منتجات بالمخزون")
                return False
        except Exception as e:
            self.log("المخزون", False, str(e)[:50])
            return False
        
        return True
    
    def view_business_settings(self):
        """عرض إعدادات المنشأة"""
        print("\n⚙️ إعدادات المنشأة:")
        try:
            # معلومات المنشأة
            business = self.conn.execute(
                "SELECT name, industry_type, country_code, city FROM businesses WHERE id=?",
                (self.business_id,)
            ).fetchone()
            
            # عدد الموظفين
            staff_count = self.conn.execute(
                "SELECT COUNT(*) as c FROM users WHERE business_id=?",
                (self.business_id,)
            ).fetchone()["c"]
            
            business_info = f"اسم المنشأة: {business['name']} | النوع: {business['industry_type']} | الموظفون: {staff_count}"
            self.log("معلومات المنشأة", True, business_info)
            
        except Exception as e:
            self.log("معلومات المنشأة", False, str(e)[:50])
            return False
        
        return True
    
    def summary(self):
        """ملخص الاستكشاف"""
        print("\n" + "="*70)
        print("  ملخص الاستكشاف العميق")
        print("="*70)
        
        passed = sum(1 for _, success, _ in self.results if success)
        total = len(self.results)
        
        print(f"\n✅ الخطوات المنجزة: {passed}/{total}")
        print(f"📈 نسبة النجاح: {100*passed//total if total > 0 else 0}%")
        
        print("\n📋 الاستكشافات التي تمت:")
        for step, success, _ in self.results:
            icon = "✓" if success else "✗"
            print(f"   {icon} {step}")
        
        print("\n" + "="*70)
        return passed == total


def main():
    try:
        # الاتصال بقاعدة البيانات
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        
        # استخدام آخر عيادة تم إنشاؤها
        business = conn.execute(
            "SELECT id FROM businesses ORDER BY id DESC LIMIT 1"
        ).fetchone()
        
        if not business:
            print("❌ لا توجد عيادات في النظام")
            return False
        
        business_id = business["id"]
        
        # الحصول على مالك العيادة
        user = conn.execute(
            "SELECT id FROM users WHERE business_id=? LIMIT 1",
            (business_id,)
        ).fetchone()
        
        user_id = user["id"] if user else None
        
        print("\n╔════════════════════════════════════════════════════════════════════╗")
        print(f"║  الاستكشاف العميق للبرنامج — معرّف العيادة: {business_id}                         ║")
        print("║  مراحل متقدمة: تحليل الإيرادات، المخزون، الإعدادات                 ║")
        print("╚════════════════════════════════════════════════════════════════════╝")
        
        explorer = DeepExploration(business_id, user_id, conn)
        
        t0 = time.time()
        
        # تنفيذ الاستكشافات
        explorer.explore_categories()
        explorer.explore_all_services()
        explorer.create_multiple_invoices(3)
        explorer.analyze_revenue()
        explorer.check_inventory_status()
        explorer.view_business_settings()
        
        elapsed = time.time() - t0
        success = explorer.summary()
        
        print(f"\n⏱️  الزمن الإجمالي: {elapsed:.2f}s\n")
        
        conn.close()
        
        return success
        
    except Exception as e:
        print(f"❌ خطأ: {e}")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
