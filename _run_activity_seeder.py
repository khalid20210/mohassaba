"""تشغيل migration 017 وحقن الأنشطة في كلا قاعدتي البيانات"""
import sqlite3, sys, os
sys.path.insert(0, r"c:\Users\JEN21\OneDrive\سطح المكتب\محاسبه")
os.chdir(r"c:\Users\JEN21\OneDrive\سطح المكتب\محاسبه")

from modules.activity_seeder import seed_activities
from modules.config import INDUSTRY_TYPES

dbs = [
    r"c:\Users\JEN21\OneDrive\سطح المكتب\محاسبه\database\accounting_dev.db",
    r"c:\Users\JEN21\OneDrive\سطح المكتب\محاسبه\database\accounting_prod.db",
]

for db_path in dbs:
    name = os.path.basename(db_path)
    if not os.path.exists(db_path):
        print(f"[{name}] MISSING — skip")
        continue
    n = seed_activities(db_path)
    # تحقق من النتيجة
    c = sqlite3.connect(db_path)
    total = c.execute("SELECT COUNT(*) FROM industry_activities").fetchone()[0]
    cats  = c.execute("SELECT category, COUNT(*) FROM industry_activities GROUP BY category ORDER BY 2 DESC").fetchall()
    c.close()
    print(f"\n[{name}]")
    print(f"  inserted={n}  total_in_db={total} / {len(INDUSTRY_TYPES)} defined")
    print("  categories:")
    for cat, cnt in cats:
        print(f"    {cat or 'other':20} : {cnt}")

print("\n✅ الحقن اكتمل في كلا قاعدتي البيانات")
