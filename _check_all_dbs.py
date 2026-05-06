import sqlite3
import os

dbs = ['accounting_dev.db', 'accounting.db', 'database.db']
result = []

for db_name in dbs:
    if os.path.exists(db_name):
        try:
            conn = sqlite3.connect(db_name)
            c = conn.cursor()
            tables = c.execute('SELECT name FROM sqlite_master WHERE type="table"').fetchall()
            size_kb = os.path.getsize(db_name) / 1024
            result.append(f'{db_name}: {len(tables)} tables ({size_kb:.1f} KB)')
            if len(tables) > 0:
                result.append(f'  Sample tables: {", ".join([t[0] for t in tables[:3]])}')
            conn.close()
        except Exception as e:
            result.append(f'{db_name}: Error - {e}')

for line in result:
    print(line)
