"""تطبيق migrations المعلقة على accounting_prod.db"""
import sys
sys.path.insert(0, ".")
from modules.migration_runner import run_migrations
from pathlib import Path

db = Path("database/accounting_prod.db")
print(f"Applying pending migrations to: {db}")
run_migrations(db)
print("Done!")

# Verify
import sqlite3
c = sqlite3.connect(str(db))
m = c.execute("SELECT COUNT(*) FROM _schema_migrations").fetchone()[0]
rows = c.execute("SELECT filename FROM _schema_migrations ORDER BY id").fetchall()
print(f"\nTotal migrations applied: {m}")
for r in rows:
    print(f"  ✓ {r[0]}")

# Check new tables
tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
check = ["business_zatca_settings", "pos_shifts"]
for t in check:
    print(f"{t}: {'✓ EXISTS' if t in tables else '✗ MISSING'}")
cols = [r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()]
print(f"users.preferred_language: {'✓ EXISTS' if 'preferred_language' in cols else '✗ MISSING'}")
c.close()
