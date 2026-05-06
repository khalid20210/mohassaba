import sqlite3

c = sqlite3.connect(r"c:\Users\JEN21\OneDrive\سطح المكتب\محاسبه\database\accounting_dev.db")
tables = sorted(r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'"))
act_tables = [t for t in tables if any(x in t for x in ("activ", "industry", "sector", "seed", "categor"))]
print("Activity-related tables:", act_tables)
for t in act_tables:
    n = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    cols = [r[1] for r in c.execute(f"PRAGMA table_info({t})")]
    print(f"  {t}: {n} rows  cols={cols}")
    if n > 0:
        for r in c.execute(f"SELECT * FROM {t} LIMIT 3").fetchall():
            print(f"    {r}")
c.close()

# check CSV columns
import csv, os, glob
patterns = [
    r"c:\Users\JEN21\OneDrive\سطح المكتب\محاسبه\منتجات\منتجات\*.csv",
    r"c:\Users\JEN21\OneDrive\سطح المكتب\محاسبه\منتجات\*.csv",
]
for pat in patterns:
    for f in glob.glob(pat):
        if os.path.getsize(f) < 1000:
            continue
        print(f"\nCSV: {os.path.basename(f)}")
        with open(f, encoding="utf-8-sig", errors="replace") as fh:
            reader = csv.DictReader(fh)
            print("  cols:", reader.fieldnames)
            for i, row in enumerate(reader):
                if i >= 3:
                    break
                print(f"  row: {dict(row)}")
        break
