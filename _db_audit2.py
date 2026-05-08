import sqlite3

for db_path in ["database/accounting_dev.db", "database/accounting.db", "database/accounting_prod.db"]:
    try:
        c = sqlite3.connect(db_path)
        t = c.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        try:
            b = c.execute("SELECT COUNT(*) FROM businesses").fetchone()[0]
        except Exception:
            b = "N/A"
        try:
            u = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        except Exception:
            u = "N/A"
        try:
            m = c.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        except Exception:
            m = "N/A"
        i = c.execute("PRAGMA integrity_check").fetchone()[0]
        fk = c.execute("PRAGMA foreign_key_check").fetchall()
        print(f"[{db_path}] TABLES={t} BIZ={b} USERS={u} MIGS={m} INTEGRITY={i} FK_VIOLATIONS={len(fk)}")
        c.close()
    except Exception as e:
        print(f"[{db_path}] ERROR={e}")
