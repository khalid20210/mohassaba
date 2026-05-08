import sqlite3
c = sqlite3.connect('database/accounting_dev.db')
c.execute("INSERT OR IGNORE INTO _schema_migrations (filename) VALUES ('005_complete_services.sql')")
c.commit()
rows = c.execute('SELECT filename FROM _schema_migrations ORDER BY id').fetchall()
print('Migrations tracked:')
for r in rows:
    print(' -', r[0])
c.close()
print('Done!')
