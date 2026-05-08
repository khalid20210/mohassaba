import sqlite3, pathlib

db_path = 'database/accounting_dev.db'
sql_path = 'migrations/006_agents_pro.sql'

conn = sqlite3.connect(db_path)
sql = pathlib.Path(sql_path).read_text(encoding='utf-8')

lines = sql.split('\n')
main_sql = []
alter_lines = []
for line in lines:
    if line.strip().upper().startswith('ALTER TABLE'):
        alter_lines.append(line.strip())
    else:
        main_sql.append(line)

main_body = '\n'.join(main_sql)
try:
    conn.executescript(main_body)
    print('Tables + Indexes created OK')
except Exception as e:
    print(f'executescript error: {e}')

for stmt in alter_lines:
    stmt = stmt.rstrip(';')
    try:
        conn.execute(stmt)
        print(f'OK: {stmt[:70]}')
    except sqlite3.OperationalError as e:
        print(f'SKIP: {e}')

conn.commit()
conn.close()

conn2 = sqlite3.connect(db_path)
tables = conn2.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'agent_%' ORDER BY name"
).fetchall()
print()
print('agent_* tables now in DB:')
for t in tables:
    print(' ', t[0])
conn2.close()
