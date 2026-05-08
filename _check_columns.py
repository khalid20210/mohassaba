import sqlite3
db = sqlite3.connect('database/accounting_dev.db')
c = db.cursor()
c.execute("PRAGMA table_info(products)")
print("Products table columns:")
for row in c.fetchall():
    print(f"  {row[1]:30} | Type: {row[2]}")
db.close()
