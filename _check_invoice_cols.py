import sqlite3
db = sqlite3.connect('database/accounting_dev.db')
c = db.cursor()
c.execute("PRAGMA table_info(invoices)")
print("Invoices table columns:")
for row in c.fetchall():
    print(f"  {row[1]:25} | {row[2]}")
db.close()
