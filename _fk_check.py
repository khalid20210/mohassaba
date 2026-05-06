import sqlite3
from collections import Counter

c = sqlite3.connect("database/accounting_dev.db")

# FK violations details
fk_violations = c.execute("PRAGMA foreign_key_check").fetchall()
print(f"Total FK violations: {len(fk_violations)}")

# Group by table
by_table = Counter(row[0] for row in fk_violations)
print("\nViolations by table:")
for table, count in by_table.most_common():
    print(f"  {table}: {count}")

# Show some sample violations
print("\nSample violations (first 10):")
for row in fk_violations[:10]:
    print(f"  table={row[0]}, rowid={row[1]}, refers_to={row[2]}, fk_id={row[3]}")

# Check migrations table
tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
for possible in ["schema_migrations", "migrations", "_migrations", "db_migrations", "applied_migrations"]:
    if possible in tables:
        count = c.execute(f"SELECT COUNT(*) FROM {possible}").fetchone()[0]
        print(f"\nMigrations table: {possible}, count={count}")
        rows = c.execute(f"SELECT * FROM {possible} ORDER BY applied_at DESC LIMIT 5").fetchall()
        for r in rows:
            print(f"  {r}")

c.close()
