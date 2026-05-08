import sqlite3
conn = sqlite3.connect("database/accounting_dev.db")
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type=? ORDER BY name", ("table",))
tables = [r[0] for r in cur.fetchall()]
for t in tables:
    if t.startswith("_"): continue
    cur.execute("PRAGMA table_info(" + t + ")")
    cols = [r[1] for r in cur.fetchall()]
    print(t + "=" + ",".join(cols))
conn.close()
