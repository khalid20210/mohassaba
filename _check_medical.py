import sqlite3
c = sqlite3.connect('database/accounting_dev.db')

# patients
try:
    cols = c.execute('PRAGMA table_info(patients)').fetchall()
    print('=== patients columns ===')
    for col in cols: print(f'  {col[1]} ({col[2]})')
except Exception as e:
    print('patients ERROR:', e)

# all tables
q = "SELECT name FROM sqlite_master WHERE type='table'"
all_tables = [r[0] for r in c.execute(q).fetchall()]
keywords = ['patient','appoint','prescri','medical','insur','visit','doctor','pharmacy','clinic']
medical = [t for t in all_tables if any(k in t.lower() for k in keywords)]
print('\n=== medical-related tables ===')
for t in medical:
    cnt = c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
    print(f'  {t} ({cnt} rows)')

c.close()
