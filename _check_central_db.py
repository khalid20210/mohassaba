import sqlite3

# التحقق من central_saas.db
conn = sqlite3.connect('database/central_saas.db')
c = conn.cursor()

tables = c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()

print(f"Central SAAS DB - {len(tables)} tables:\n")

for table in tables:
    name = table[0]
    count = c.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
    print(f"  {name:30} - {count:10,d} records")

conn.close()
