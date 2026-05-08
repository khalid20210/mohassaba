import sqlite3
db = sqlite3.connect('database/accounting_dev.db')
rows = db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
for r in rows:
    print(r[0])

print("\n--- agents columns ---")
try:
    cols = db.execute("PRAGMA table_info(agents)").fetchall()
    for c in cols:
        print(c[1], c[2])
except:
    print("table agents not found")
