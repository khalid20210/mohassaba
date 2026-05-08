import sqlite3, os, sys

base = r"c:\Users\JEN21\OneDrive\سطح المكتب\محاسبه"
dev_db  = os.path.join(base, "database", "accounting_dev.db")
prod_db = os.path.join(base, "database", "accounting_prod.db")

print("=" * 65)
print("  تقرير حالة الأنشطة والمنتجات في قاعدة البيانات")
print("=" * 65)

for label, path in [("DEV", dev_db), ("PROD", prod_db)]:
    if not os.path.exists(path):
        print(f"\n[{label}] MISSING: {path}")
        continue
    c = sqlite3.connect(path)
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    print(f"\n[{label}] {os.path.basename(path)}")

    # ── الأنشطة ──────────────────────────────────────────────────
    for t in ("activities", "activity_types", "industry_types", "activities_definitions"):
        if t in tables:
            n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t}: {n} rows")
            if n > 0:
                sample = c.execute(f"SELECT * FROM {t} LIMIT 3").fetchall()
                cols = [d[0] for d in c.execute(f"SELECT * FROM {t} LIMIT 1").description]
                print(f"  cols: {cols}")
                for r in sample:
                    print(f"    {r}")

    # ── المنتجات ─────────────────────────────────────────────────
    for t in ("products", "products_bulk"):
        if t in tables:
            n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t}: {n:,} rows")
            if n > 0:
                cols = [d[1] for d in c.execute(f"PRAGMA table_info({t})")]
                print(f"    cols: {cols}")
                biz = c.execute(f"SELECT COUNT(DISTINCT business_id) FROM {t}").fetchone()[0] if "business_id" in cols else "N/A"
                print(f"    distinct business_id: {biz}")
                # عينة
                q = f"SELECT {','.join(cols[:5])} FROM {t} LIMIT 3"
                for r in c.execute(q).fetchall():
                    print(f"    {r}")
        else:
            print(f"  {t}: TABLE_MISSING")

    c.close()

print("\n" + "=" * 65)
print("  ملفات CSV للمنتجات في المشروع")
print("=" * 65)
import glob
patterns = [
    os.path.join(base, "منتجات", "**", "*.csv"),
    os.path.join(base, "منتجات", "*.csv"),
    os.path.join(base, "uploads", "excel", "*.csv"),
    os.path.join(base, "uploads", "excel", "*.xlsx"),
]
found = set()
for p in patterns:
    found.update(glob.glob(p, recursive=True))

if found:
    for f in sorted(found):
        sz = os.path.getsize(f) // 1024
        try:
            with open(f, encoding="utf-8-sig", errors="replace") as fh:
                rows = sum(1 for _ in fh) - 1
        except:
            rows = "?"
        print(f"  {os.path.basename(f):45} {sz:>5} KB  {rows:>7} rows")
else:
    print("  لا توجد ملفات CSV")

print()
