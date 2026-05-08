import sqlite3
db = sqlite3.connect("database/accounting_dev.db")
try:
    db.execute("ALTER TABLE users ADD COLUMN preferred_language TEXT DEFAULT 'ar'")
    db.commit()
    print("OK: preferred_language column added")
except sqlite3.OperationalError as e:
    if "duplicate column" in str(e):
        print("OK: column already exists")
    else:
        raise
