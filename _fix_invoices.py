from modules import create_app
from modules.extensions import get_db

app = create_app()
with app.app_context():
    db = get_db()
    cols = [c['name'] for c in db.execute('PRAGMA table_info(invoices)').fetchall()]
    missing = []
    for col, defn in [
        ('payment_method', "TEXT DEFAULT 'cash'"),
    ]:
        if col not in cols:
            try:
                db.execute(f"ALTER TABLE invoices ADD COLUMN {col} {defn}")
                import sqlite3
                db.execute("COMMIT")
                missing.append(col)
                print(f"ADDED: {col}")
            except Exception as e:
                print(f"ERR {col}: {e}")
        else:
            print(f"EXISTS: {col}")
    if not missing:
        print("All columns already present")
