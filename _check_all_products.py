import sqlite3, os, csv, glob

base = r"c:\Users\JEN21\OneDrive\سطح المكتب\محاسبه"
print("=" * 65)
print("  فحص المنتجات في قواعد البيانات")
print("=" * 65)

dbs = {
    "accounting_dev.db":  base + r"\database\accounting_dev.db",
    "accounting_prod.db": base + r"\database\accounting_prod.db",
    "accounting.db":      base + r"\database\accounting.db",
    "central_saas.db":    base + r"\database\central_saas.db",
}
for name, path in dbs.items():
    if not os.path.exists(path):
        print(f"\n{name}: MISSING")
        continue
    sz = os.path.getsize(path) // 1024
    c = sqlite3.connect(path)
    tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    print(f"\n[{name}] ({sz} KB)")
    for t in ("products", "products_bulk", "inventory", "stock"):
        if t in tables:
            n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            print(f"  {t}: {n:,} rows")
            if n > 0 and t == "products":
                sample = c.execute(f"SELECT id, name, barcode, price FROM products LIMIT 3").fetchall()
                for row in sample:
                    print(f"    sample: {row}")
        else:
            print(f"  {t}: TABLE_MISSING")
    c.close()

print("\n" + "=" * 65)
print("  ملفات CSV/Excel للمنتجات الموجودة في المشروع")
print("=" * 65)
patterns = [
    base + r"\منتجات\**\*.csv",
    base + r"\منتجات\*.csv",
    base + r"\uploads\excel\*.csv",
    base + r"\uploads\excel\*.xlsx",
    base + r"\*.csv",
]
found = set()
for pat in patterns:
    for f in glob.glob(pat, recursive=True):
        found.add(f)

for f in sorted(found):
    sz = os.path.getsize(f)
    # count rows
    try:
        with open(f, encoding="utf-8", errors="replace") as fh:
            rows = sum(1 for _ in fh) - 1
    except:
        rows = "?"
    print(f"  {os.path.basename(f):40} {sz//1024:>5} KB  {rows:>6} rows")
