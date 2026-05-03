from modules import create_app; from modules.extensions import get_db
app = create_app(); app.app_context().push(); db = get_db()
tables = [t['name'] for t in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
print(tables)
# أعمدة invoice_lines
cols = [c['name'] for c in db.execute("PRAGMA table_info(invoice_lines)").fetchall()]
print("invoice_lines:", cols)
cols2 = [c['name'] for c in db.execute("PRAGMA table_info(journal_entry_lines)").fetchall()]
print("journal_entry_lines:", cols2)
cols3 = [c['name'] for c in db.execute("PRAGMA table_info(stock_movements)").fetchall()]
print("stock_movements:", cols3)
cols4 = [c['name'] for c in db.execute("PRAGMA table_info(journal_entries)").fetchall()]
print("journal_entries:", cols4)
