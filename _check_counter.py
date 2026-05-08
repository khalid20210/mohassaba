import sqlite3
conn = sqlite3.connect('database/accounting_dev.db')
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
if 'medical_file_counter' not in tables:
    conn.execute('CREATE TABLE medical_file_counter (business_id INTEGER PRIMARY KEY, last_number INTEGER DEFAULT 0)')
    conn.commit()
    print('CREATED medical_file_counter')
else:
    print('EXISTS - OK')
conn.close()
