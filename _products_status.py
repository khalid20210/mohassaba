"""
_products_status.py — يعرض عدد المنتجات لكل منشأة مع نوع النشاط
"""
import sqlite3

DB = r"c:\Users\JEN21\OneDrive\سطح المكتب\محاسبه\database\accounting_dev.db"

db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

rows = db.execute("""
    SELECT b.id, b.name, b.industry_type,
           COUNT(p.id) as prod_cnt
    FROM businesses b
    LEFT JOIN products p ON p.business_id = b.id
    GROUP BY b.id
    ORDER BY prod_cnt DESC
""").fetchall()

print(f"{'ID':>3}  {'المنشأة':30}  {'النشاط':35}  {'منتجات':>7}")
print("-" * 80)
total = 0
for r in rows:
    print(f"{r['id']:>3}  {r['name'][:30]:30}  {(r['industry_type'] or '—')[:35]:35}  {r['prod_cnt']:>7}")
    total += r['prod_cnt']
print("-" * 80)
print(f"{'إجمالي':>74}  {total:>7}")

# ملخص حسب نوع النشاط
print("\n--- ملخص حسب نوع النشاط ---")
summary = db.execute("""
    SELECT b.industry_type, COUNT(DISTINCT b.id) as biz_cnt, COUNT(p.id) as prod_cnt
    FROM businesses b
    LEFT JOIN products p ON p.business_id = b.id
    GROUP BY b.industry_type
    ORDER BY prod_cnt DESC
""").fetchall()
for r in summary:
    print(f"  {(r['industry_type'] or 'بدون نشاط')[:40]:40}  منشآت:{r['biz_cnt']:>3}  منتجات:{r['prod_cnt']:>6}")

db.close()
