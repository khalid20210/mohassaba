import sqlite3

c = sqlite3.connect("database/accounting_prod.db")
t = c.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
print(f"PROD: TABLES={t}")
print("Tables:", ", ".join(tables[:20]))
if "businesses" in tables:
    b = c.execute("SELECT COUNT(*) FROM businesses").fetchone()[0]
    print(f"PROD businesses={b}")
if "users" in tables:
    u = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    print(f"PROD users={u}")
i = c.execute("PRAGMA integrity_check").fetchone()[0]
fk = c.execute("PRAGMA foreign_key_check").fetchall()
print(f"PROD INTEGRITY={i} FK_VIOLATIONS={len(fk)}")

# check migration table
for mig_table in ["schema_migrations", "_migrations", "migrations", "applied_migrations"]:
    if mig_table in tables:
        m = c.execute(f"SELECT COUNT(*) FROM {mig_table}").fetchone()[0]
        print(f"PROD {mig_table}={m}")
        rows = c.execute(f"SELECT * FROM {mig_table}").fetchall()
        for r in rows:
            print(f"  {r}")
c.close()
