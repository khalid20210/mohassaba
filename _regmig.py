import sqlite3
conn = sqlite3.connect('database/accounting_dev.db')
# check columns
cur = conn.execute("PRAGMA table_info(_schema_migrations)")
cols = [row[1] for row in cur.fetchall()]
print("Columns:", cols)
if cols:
    conn.execute("INSERT OR IGNORE INTO _schema_migrations (filename) VALUES ('006_agents_pro.sql')")
    conn.commit()
    print("Registered 006_agents_pro.sql")
else:
    print("Table not found or empty")
conn.close()
