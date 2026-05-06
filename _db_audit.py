import sqlite3, os, sys
db = "instance/jenan.db"
if not os.path.exists(db):
    print("DB_NOT_FOUND"); sys.exit(1)
c = sqlite3.connect(db)
t = c.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
b = c.execute("SELECT COUNT(*) FROM businesses").fetchone()[0]
u = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
m = c.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
i = c.execute("PRAGMA integrity_check").fetchone()[0]
fk = c.execute("PRAGMA foreign_key_check").fetchall()
print(f"TABLES={t} BIZ={b} USERS={u} MIGS={m} INTEGRITY={i} FK_VIOLATIONS={len(fk)}")
c.close()
