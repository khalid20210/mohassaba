import sqlite3
c = sqlite3.connect("database/accounting_prod.db")
tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
check = ["business_zatca_settings", "pos_shifts", "receivables", "payables", "debt_schedules", "preferred_language"]
for t in check:
    print(f"{t}: {'EXISTS' if t in tables else 'MISSING'}")
# users columns
cols = [r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()]
print(f"users.preferred_language: {'EXISTS' if 'preferred_language' in cols else 'MISSING'}")
c.close()
