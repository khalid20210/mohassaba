"""علّم migration 018 كمطبّق في جدول _schema_migrations"""
import sqlite3

for db_path in ['database/accounting_dev.db', 'database/accounting_prod.db']:
    try:
        c = sqlite3.connect(db_path)
        c.execute("INSERT OR IGNORE INTO _schema_migrations (filename) VALUES (?)",
                  ('018_medical_sector_complete.sql',))
        c.commit()
        c.close()
        print(f'OK: {db_path}')
    except Exception as e:
        print(f'SKIP {db_path}: {e}')
