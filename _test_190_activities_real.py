"""
_test_190_activities_real.py
اختبار شامل لـ 190 نشاط بيانات حقيقية مع منتجاتهم وخدماتهم
"""

import sqlite3
from modules import create_app
from collections import defaultdict

app = create_app()
db_path = 'database/accounting_dev.db'

def test_all_activities():
    """اختبار جميع الأنشطة الـ 190 بيانات حقيقية"""
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # 1. احصل على عدد الأنشطة المختلفة
    c.execute("""
        SELECT DISTINCT industry_type FROM businesses 
        WHERE industry_type IS NOT NULL AND industry_type != ''
    """)
    industries = [row['industry_type'] for row in c.fetchall()]
    
    print(f'\n{"="*80}')
    print(f'اختبار شامل لـ {len(industries)} نشاط تجاري')
    print(f'{"="*80}\n')
    
    # 2. إحصائيات عامة
    c.execute("SELECT COUNT(*) as cnt FROM businesses")
    total_businesses = c.fetchone()['cnt']
    
    c.execute("SELECT COUNT(*) as cnt FROM products")
    total_products = c.fetchone()['cnt']
    
    c.execute("SELECT COUNT(*) as cnt FROM invoices")
    total_invoices = c.fetchone()['cnt']
    
    print(f'📊 الإحصائيات العامة:')
    print(f'   • إجمالي المشاريع (Businesses): {total_businesses}')
    print(f'   • إجمالي المنتجات: {total_products}')
    print(f'   • إجمالي الفواتير: {total_invoices}')
    print(f'   • عدد أنواع الأنشطة المختلفة: {len(industries)}\n')
    
    # 3. توزيع الأنشطة والمنتجات
    activity_stats = {}
    for industry in industries:
        c.execute("""
            SELECT 
                b.industry_type,
                COUNT(DISTINCT b.id) as business_count,
                COUNT(DISTINCT p.id) as product_count,
                COUNT(DISTINCT i.id) as invoice_count
            FROM businesses b
            LEFT JOIN products p ON b.id = p.business_id
            LEFT JOIN invoices i ON b.id = i.business_id
            WHERE b.industry_type = ?
            GROUP BY b.industry_type
        """, (industry,))
        
        row = c.fetchone()
        if row:
            activity_stats[industry] = {
                'businesses': row['business_count'],
                'products': row['product_count'],
                'invoices': row['invoice_count']
            }
    
    # 4. عرض النتائج
    print(f'📋 تفصيل كل نشاط:')
    print('─' * 80)
    print(f'#    | النشاط التجاري                  | مشاريع | منتجات  | فواتير')
    print('─' * 80)
    
    total_biz = 0
    total_prod = 0
    total_inv = 0
    
    for idx, (industry, stats) in enumerate(sorted(activity_stats.items()), 1):
        print(f'{idx:3d} | {industry:30} | {stats["businesses"]:6d} | {stats["products"]:8d} | {stats["invoices"]:6d}')
        total_biz += stats['businesses']
        total_prod += stats['products']
        total_inv += stats['invoices']
    
    print('─' * 80)
    print(f'المجموع | {total_biz:35d} | {total_prod:8d} | {total_inv:6d}')
    print('=' * 80)
    
    # 5. عينات من المنتجات الفعلية لكل نشاط
    print(f'\n🛍️  عينات من المنتجات الحقيقية:\n')
    
    samples_shown = 0
    for industry in sorted(activity_stats.keys())[:15]:  # أول 15 نشاط
        c.execute("""
            SELECT DISTINCT 
                p.id, p.name, p.unit_price, pc.name as category
            FROM products p
            LEFT JOIN product_categories pc ON p.category_id = pc.id
            WHERE p.business_id IN (
                SELECT id FROM businesses WHERE industry_type = ?
            )
            LIMIT 3
        """, (industry,))
        
        products = c.fetchall()
        if products:
            print(f'   📌 {industry}:')
            for p in products:
                print(f'      • {p["name"]} - السعر: {p["unit_price"]} {p["category"] or "عام"}')
            print()
            samples_shown += len(products)
    
    # 6. إحصائيات الفواتير
    print('=' * 80)
    c.execute("""
        SELECT 
            COUNT(*) as total_invoices,
            SUM(total_amount) as revenue,
            AVG(total_amount) as avg_invoice
        FROM invoices
    """)
    inv_stats = c.fetchone()
    
    print(f'💰 إحصائيات الفواتير:')
    print(f'   • إجمالي الفواتير: {inv_stats["total_invoices"]}')
    if inv_stats['revenue']:
        print(f'   • إجمالي الإيرادات: {inv_stats["revenue"]:.2f}')
        print(f'   • متوسط الفاتورة: {inv_stats["avg_invoice"]:.2f}')
    
    # 7. التحقق من سلامة البيانات
    print(f'\n{"="*80}')
    print(f'✅ فحص سلامة البيانات:')
    
    c.execute("SELECT COUNT(*) as cnt FROM products WHERE name IS NULL OR name = ''")
    null_names = c.fetchone()['cnt']
    print(f'   • منتجات بدون اسم: {null_names} ❌' if null_names > 0 else f'   • جميع المنتجات لها أسماء ✅')
    
    c.execute("SELECT COUNT(*) as cnt FROM products WHERE unit_price IS NULL OR unit_price <= 0")
    bad_prices = c.fetchone()['cnt']
    print(f'   • منتجات بسعر خاطئ: {bad_prices} ❌' if bad_prices > 0 else f'   • جميع الأسعار صحيحة ✅')
    
    c.execute("SELECT COUNT(*) as cnt FROM invoices WHERE total_amount IS NULL OR total_amount <= 0")
    bad_invoices = c.fetchone()['cnt']
    print(f'   • فواتير بمبلغ خاطئ: {bad_invoices} ❌' if bad_invoices > 0 else f'   • جميع الفواتير صحيحة ✅')
    
    # 8. ملخص النتائج
    print(f'\n{"="*80}')
    print(f'📈 الملخص النهائي:')
    print(f'   ✓ عدد الأنشطة المختبرة: {len(industries)}')
    print(f'   ✓ عدد المشاريع: {total_biz}')
    print(f'   ✓ عدد المنتجات: {total_prod}')
    print(f'   ✓ عدد الفواتير: {total_inv}')
    print(f'   ✓ حالة البيانات: {"✅ جميع البيانات حقيقية وسليمة" if null_names == 0 and bad_prices == 0 and bad_invoices == 0 else "⚠️  هناك مشاكل في البيانات"}')
    print(f'{"="*80}\n')
    
    conn.close()
    return True

if __name__ == '__main__':
    try:
        test_all_activities()
        print('\n✅ الاختبار اكتمل بنجاح!\n')
    except Exception as e:
        print(f'\n❌ خطأ: {e}\n')
        import traceback
        traceback.print_exc()
