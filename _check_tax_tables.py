import sqlite3
db = sqlite3.connect('database/accounting_dev.db')
c = db.cursor()

# Check tax tables
c.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%tax%' OR name LIKE '%setting%' OR name LIKE '%vat%')")
tax_tables = [r[0] for r in c.fetchall()]
print("Tax-related tables:", tax_tables)

for t in tax_tables:
    c.execute(f"PRAGMA table_info({t})")
    cols = [r[1] for r in c.fetchall()]
    print(f"  {t}: {cols}")

db.close()
