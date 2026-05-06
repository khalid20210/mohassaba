import sqlite3
db = sqlite3.connect('database/accounting_dev.db')
c = db.cursor()
c.execute("PRAGMA table_info(warehouses)")
print("Warehouses columns:")
for row in c.fetchall():
    print(f"  {row[1]:20} | {row[2]}")
c.execute("SELECT * FROM warehouses LIMIT 3")
print("Sample warehouses:", c.fetchall())
db.close()
