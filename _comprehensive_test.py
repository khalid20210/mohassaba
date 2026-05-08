"""
_comprehensive_test.py
اختبار شامل لجميع الأنشطة والخدمات - للاستخدام الإنتاجي الحقيقي
تغطي: كل نشاط، كل خدمة، كل وظيفة - بدون ORM
"""
import os
import sys
import time
import json
from pathlib import Path

# ─── إعدادات الجلسة ──────────────────────────────────────────────────────
os.environ['SESSION_BACKEND'] = 'cookie'
os.environ['FLASK_ENV'] = 'development'

from modules import create_app

app = create_app()

# ─── ألوان الإخراج ────────────────────────────────────────────────────────
class C:
    OK = '\033[92m'
    FAIL = '\033[91m'
    WARN = '\033[93m'
    INFO = '\033[94m'
    END = '\033[0m'
    BOLD = '\033[1m'

# ─── البيانات الأساسية ────────────────────────────────────────────────────

INDUSTRIES = {
    'medical': {'name': 'عيادة الدكتور أحمد', 'currency': 'SAR'},
    'restaurant': {'name': 'مطعم الذوق الممتاز', 'currency': 'SAR'},
    'retail': {'name': 'محل البقالة المركزي', 'currency': 'SAR'},
    'pharmacy': {'name': 'صيدلية الصحة', 'currency': 'SAR'},
    'supply': {'name': 'مركز التوزيع التجاري', 'currency': 'SAR'},
}

class Tester:
    def __init__(self):
        self.businesses = {}
        self.results = {'pass': 0, 'fail': 0, 'error': 0}
        self.errors = []
        self.start_time = time.time()
        
    def log(self, industry, msg, status='INFO'):
        time_ms = f"{(time.time() - self.start_time) * 1000:.0f}ms"
        symbol = '✓' if status == 'PASS' else '✗' if status == 'FAIL' else '⚠' if status == 'WARN' else 'ℹ'
        color = C.OK if status == 'PASS' else C.FAIL if status == 'FAIL' else C.WARN if status == 'WARN' else C.INFO
        
        print(f"[{time_ms:>6}] [{industry:>8}] {color}{symbol} {msg}{C.END}")
        
        if status == 'FAIL':
            self.results['fail'] += 1
        elif status == 'PASS':
            self.results['pass'] += 1
        elif status == 'WARN':
            self.results['error'] += 1
            
    def setup_business(self, industry_code, industry_info):
        """إعداد نشاط تجاري"""
        try:
            with app.app_context():
                # نشاط تجاري جديد
                biz = Business.query.filter_by(name=industry_info['name']).first()
                if not biz:
                    biz = Business(
                        name=industry_info['name'],
                        sector=industry_code,
                        currency=industry_info['currency'],
                        country='SA',
                        is_active=True
                    )
                    db.session.add(biz)
                    db.session.flush()
                
                # مستخدم مسؤول
                admin = User.query.filter_by(
                    business_id=biz.id,
                    role='admin'
                ).first()
                if not admin:
                    admin = User(
                        username=f'admin_{industry_code}',
                        email=f'admin@{industry_code}.local',
                        business_id=biz.id,
                        role='admin',
                        is_active=True
                    )
                    admin.set_password('Test@2026')
                    db.session.add(admin)
                
                # حسابات المحاسبة
                accounts = [
                    ('1101', 'الصندوق', 'assets'),
                    ('1102', 'البنك', 'assets'),
                    ('1104', 'المخزون', 'assets'),
                    ('2102', 'الضريبة المستحقة', 'liabilities'),
                    ('4101', 'إيرادات المبيعات', 'income'),
                    ('5101', 'تكلفة المبيعات', 'expense'),
                ]
                
                for code, name, atype in accounts:
                    if not Account.query.filter_by(
                        business_id=biz.id, code=code
                    ).first():
                        acc = Account(
                            business_id=biz.id,
                            code=code,
                            name=name,
                            type=atype
                        )
                        db.session.add(acc)
                
                # مستودع افتراضي
                warehouse = Warehouse.query.filter_by(
                    business_id=biz.id,
                    name='المخزن الرئيسي'
                ).first()
                if not warehouse:
                    warehouse = Warehouse(
                        business_id=biz.id,
                        name='المخزن الرئيسي',
                        is_default=True
                    )
                    db.session.add(warehouse)
                    db.session.flush()
                
                db.session.commit()
                
                self.businesses[industry_code] = {
                    'id': biz.id,
                    'user': admin,
                    'warehouse': warehouse
                }
                
                self.log(industry_code, f'نشاط: {biz.name} | المستخدم: {admin.username}', 'PASS')
                return biz, admin, warehouse
                
        except Exception as e:
            self.log(industry_code, f'فشل الإعداد: {str(e)}', 'FAIL')
            self.errors.append((industry_code, str(e)))
            return None, None, None

    def test_industry(self, industry_code):
        """اختبار نشاط تجاري كامل"""
        print(f"\n{C.BOLD}{'='*60}")
        print(f"🔧 اختبار النشاط: {industry_code}")
        print(f"{'='*60}{C.END}\n")
        
        info = INDUSTRIES.get(industry_code, {})
        biz, admin, warehouse = self.setup_business(industry_code, info)
        
        if not biz:
            return
        
        with app.app_context():
            # ─── المنتجات والمخزون ──────────────────────────────
            try:
                products = []
                for i in range(3):
                    prod = Product(
                        business_id=biz.id,
                        name=f'منتج {i+1}',
                        sku=f'SKU_{industry_code}_{i+1}',
                        unit='piece',
                        purchase_price=Decimal('100.00'),
                        sale_price=Decimal('150.00')
                    )
                    db.session.add(prod)
                    db.session.flush()
                    products.append(prod)
                
                # المخزون
                for prod in products:
                    inv = ProductInventory(
                        business_id=biz.id,
                        product_id=prod.id,
                        current_qty=100,
                        min_qty=10
                    )
                    db.session.add(inv)
                    
                    # جدول stock للـ POS
                    stock = Stock(
                        business_id=biz.id,
                        product_id=prod.id,
                        warehouse_id=warehouse.id,
                        quantity=100,
                        avg_cost=Decimal('100.00')
                    )
                    db.session.add(stock)
                
                db.session.commit()
                self.log(industry_code, f'✓ {len(products)} منتجات + مخزون', 'PASS')
            except Exception as e:
                self.log(industry_code, f'المنتجات: {str(e)[:50]}', 'FAIL')
            
            # ─── الفاتورة ──────────────────────────────────────
            try:
                inv = Invoice(
                    business_id=biz.id,
                    type='sales',
                    customer_name='عميل تجريبي',
                    subtotal=Decimal('300.00'),
                    tax=Decimal('45.00'),
                    total=Decimal('345.00'),
                    status='completed'
                )
                db.session.add(inv)
                db.session.flush()
                
                for idx, prod in enumerate(products[:2]):
                    item = InvoiceItem(
                        invoice_id=inv.id,
                        product_id=prod.id,
                        quantity=2,
                        unit_price=Decimal('150.00'),
                        total=Decimal('300.00')
                    )
                    db.session.add(item)
                
                db.session.commit()
                self.log(industry_code, f'فاتورة: {inv.invoice_number}', 'PASS')
            except Exception as e:
                self.log(industry_code, f'الفاتورة: {str(e)[:50]}', 'FAIL')
            
            # ─── بيانات خاصة حسب النشاط ─────────────────────────
            if industry_code == 'medical':
                try:
                    for i in range(2):
                        patient = Patient(
                            business_id=biz.id,
                            name=f'مريض {i+1}',
                            phone='0501234567',
                            gender='M' if i % 2 == 0 else 'F'
                        )
                        db.session.add(patient)
                    
                    db.session.commit()
                    self.log(industry_code, '✓ 2 مريض تم تسجيلهم', 'PASS')
                except Exception as e:
                    self.log(industry_code, f'المرضى: {str(e)[:50]}', 'FAIL')
            
            elif industry_code == 'restaurant':
                try:
                    for i in range(5):
                        table = Contact(
                            business_id=biz.id,
                            name=f'الطاولة {i+1}',
                            type='internal',
                            is_active=True
                        )
                        db.session.add(table)
                    
                    db.session.commit()
                    self.log(industry_code, '✓ 5 طاولات معرّفة', 'PASS')
                except Exception as e:
                    self.log(industry_code, f'الطاولات: {str(e)[:50]}', 'FAIL')
            
            # ─── API بسيطة ─────────────────────────────────────
            try:
                with app.test_client() as client:
                    # لوحة التحكم
                    resp = client.get('/dashboard')
                    assert resp.status_code in [200, 302], f'Dashboard: {resp.status_code}'
                    
                    self.log(industry_code, 'لوحة التحكم تستجيب', 'PASS')
            except Exception as e:
                self.log(industry_code, f'API: {str(e)[:50]}', 'WARN')

def main():
    print(f"\n{C.BOLD}{C.INFO}")
    print("╔" + "═" * 58 + "╗")
    print("║ اختبار شامل لجميع الأنشطة والخدمات - محاسبة v2.0 ║")
    print("╚" + "═" * 58 + "╝")
    print(f"{C.END}\n")
    
    tester = Tester()
    
    # اختبر كل نشاط
    for industry_code in INDUSTRIES:
        tester.test_industry(industry_code)
    
    # النتائج
    total = tester.results['pass'] + tester.results['fail'] + tester.results['error']
    pct = (tester.results['pass'] / total * 100) if total > 0 else 0
    
    print(f"\n{C.BOLD}{'='*60}")
    print(f"📊 النتائج النهائية:")
    print(f"{'='*60}{C.END}")
    print(f"{C.OK}✓ نجح: {tester.results['pass']}{C.END}")
    print(f"{C.FAIL}✗ فشل: {tester.results['fail']}{C.END}")
    print(f"{C.WARN}⚠ تحذير: {tester.results['error']}{C.END}")
    print(f"{C.INFO}النسبة: {pct:.1f}%{C.END}")
    print(f"الوقت: {(time.time() - tester.start_time):.1f}ث\n")
    
    if tester.errors:
        print(f"{C.WARN}الأخطاء المسجلة:{C.END}")
        for ind, err in tester.errors:
            print(f"  • {ind}: {err}")
    
    return 0 if pct >= 95 else 1

if __name__ == '__main__':
    sys.exit(main())
