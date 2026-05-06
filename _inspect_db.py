import sqlite3

db = sqlite3.connect('database/accounting_dev.db')
c = db.cursor()

print("=== AGENTS ===")
c.execute("PRAGMA table_info(agents)")
cols = [r[1] for r in c.fetchall()]
print("Columns:", cols)
c.execute("SELECT * FROM agents LIMIT 3")
for row in c.fetchall():
    print(row)

print("\n=== BUSINESSES (sample) ===")
c.execute("PRAGMA table_info(businesses)")
cols = [r[1] for r in c.fetchall()]
print("Columns:", cols)
c.execute("SELECT * FROM businesses LIMIT 2")
for row in c.fetchall():
    print(row)

print("\n=== USERS (sample) ===")
c.execute("PRAGMA table_info(users)")
cols = [r[1] for r in c.fetchall()]
print("Columns:", cols)
c.execute("SELECT * FROM users LIMIT 2")
for row in c.fetchall():
    print(row)

db.close()
