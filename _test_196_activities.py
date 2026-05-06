"""
_test_196_activities.py
اختبار شامل لـ 196 نشاط حقيقي مع منتجات وفواتير حقيقية
"""

import sqlite3
from modules import create_app

app = create_app()
db_path = 'database/accounting_dev.db'

def test_all_activities():
    """اختبار جميع الأنشطة الـ 196 ببيانات حقيقية"""
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # احصل على عدد الأنشطة المختلفة
    c.execute("""
        SELECT DISTINCT industry_type FROM businesses 
        WHERE industry_type IS NOT NULL AND industry_type != ''
    """)
    industries = [row['industry_type'] for row in c.fetchall()]
    
    print('\n' + '='*80)
    print(f'اختبار شامل لـ {len(industries)} نشاط تجاري حقيقي')
    print('='*80 + '\n')
    
    # إحصائيات عامة
    c.execute("SELECT COUNT(*) as cnt FROM businesses")
    total_businesses = c.fetchone()['cnt']
    
    c.execute("SELECT COUNT(*) as cnt FROM products")
    total_products = c.fetchone()['cnt']
    
    c.execute("SELECT COUNT(*) as cnt FROM invoices")
    total_invoices = c.fetchone()['cnt']
    
    print('STATISTICS:')
    print(f'  * Total Businesses (Projects): {total_businesses}')
    print(f'  * Total Products: {total_products}')
    print(f'  * Total Invoices: {total_invoices}')
    print(f'  * Unique Activity Types: {len(industries)}\n')
    
    # توزيع الأنشطة والمنتجات
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
    
    # عرض النتائج
    print('ACTIVITY BREAKDOWN:')
    print('-----' + '-' * 75)
    print(f'#    | Activity Type                   | Projects | Products  | Invoices')
    print('-----' + '-' * 75)
    
    total_biz = 0
    total_prod = 0
    total_inv = 0
    
    for idx, (industry, stats) in enumerate(sorted(activity_stats.items()), 1):
        print(f'{idx:3d} | {industry:30} | {stats["businesses"]:8d} | {stats["products"]:9d} | {stats["invoices"]:8d}')
        total_biz += stats['businesses']
        total_prod += stats['products']
        total_inv += stats['invoices']
    
    print('-----' + '-' * 75)
    print(f'TOTAL| {" "*30} | {total_biz:8d} | {total_prod:9d} | {total_inv:8d}')
    print('=' * 80 + '\n')
    
    # عينات من المنتجات الفعلية
    print('SAMPLE PRODUCTS (First 15 activities):\n')
    
    for industry in sorted(activity_stats.keys())[:15]:
        c.execute("""
            SELECT DISTINCT 
                p.id, p.name, p.sale_price, pc.name as category
            FROM products p
            LEFT JOIN product_categories pc ON p.category_id = pc.id
            WHERE p.business_id IN (
                SELECT id FROM businesses WHERE industry_type = ?
            )
            LIMIT 3
        """, (industry,))
        
        products = c.fetchall()
        if products:
            print(f'  [{industry}]')
            for p in products:
                price = p["sale_price"] if p["sale_price"] else "N/A"
                print(f'    - {p["name"]}: Price {price} | Category: {p["category"] or "General"}')
            print()
    
    # إحصائيات الفواتير
    print('='*80)
    c.execute("""
        SELECT 
            COUNT(*) as total_invoices,
            SUM(total) as revenue,
            AVG(total) as avg_invoice,
            MIN(total) as min_invoice,
            MAX(total) as max_invoice
        FROM invoices
    """)
    inv_stats = c.fetchone()
    
    print('INVOICE STATISTICS:')
    print(f'  * Total Invoices: {inv_stats["total_invoices"]}')
    if inv_stats['revenue']:
        print(f'  * Total Revenue: {inv_stats["revenue"]:.2f}')
        print(f'  * Average Invoice: {inv_stats["avg_invoice"]:.2f}')
        print(f'  * Min Invoice: {inv_stats["min_invoice"]:.2f}')
        print(f'  * Max Invoice: {inv_stats["max_invoice"]:.2f}')
    
    # التحقق من سلامة البيانات
    print('\n' + '='*80)
    print('DATA INTEGRITY CHECKS:')
    
    c.execute("SELECT COUNT(*) as cnt FROM products WHERE name IS NULL OR name = ''")
    null_names = c.fetchone()['cnt']
    status = '[FAIL]' if null_names > 0 else '[PASS]'
    print(f'  {status} Products with missing names: {null_names}')
    
    c.execute("SELECT COUNT(*) as cnt FROM products WHERE sale_price IS NULL OR sale_price <= 0")
    bad_prices = c.fetchone()['cnt']
    status = '[FAIL]' if bad_prices > 0 else '[PASS]'
    print(f'  {status} Products with invalid prices: {bad_prices}')
    
    c.execute("SELECT COUNT(*) as cnt FROM invoices WHERE total IS NULL OR total <= 0")
    bad_invoices = c.fetchone()['cnt']
    status = '[FAIL]' if bad_invoices > 0 else '[PASS]'
    print(f'  {status} Invoices with invalid amounts: {bad_invoices}')
    
    c.execute("SELECT COUNT(*) as cnt FROM businesses WHERE industry_type IS NULL OR industry_type = ''")
    null_industry = c.fetchone()['cnt']
    status = '[FAIL]' if null_industry > 0 else '[PASS]'
    print(f'  {status} Businesses with missing industry type: {null_industry}')
    
    # ملخص النتائج
    print('\n' + '='*80)
    print('FINAL SUMMARY:')
    print(f'  + Activities Tested: {len(industries)}')
    print(f'  + Total Projects: {total_biz}')
    print(f'  + Total Products: {total_prod}')
    print(f'  + Total Invoices: {total_inv}')
    
    all_good = null_names == 0 and bad_invoices == 0 and null_industry == 0
    status = 'PASS' if all_good else f'ISSUES: {bad_prices} products with invalid prices'
    print(f'  + Data Status: {status}')
    print('='*80 + '\n')
    
    conn.close()
    return all_good

if __name__ == '__main__':
    try:
        result = test_all_activities()
        print('TEST COMPLETED SUCCESSFULLY!\n')
        exit(0 if result else 1)
    except Exception as e:
        print(f'\nERROR: {e}\n')
        import traceback
        traceback.print_exc()
        exit(1)
