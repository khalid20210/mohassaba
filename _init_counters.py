from modules import create_app
from modules.extensions import get_db

app = create_app()
with app.app_context():
    db = get_db()
    db.execute("""CREATE TABLE IF NOT EXISTS biz_counters (
        business_id INTEGER NOT NULL,
        counter_key TEXT NOT NULL,
        seq INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (business_id, counter_key)
    )""")
    bizs = db.execute("SELECT DISTINCT id FROM businesses").fetchall()
    for b in bizs:
        bid = b["id"]
        row = db.execute(
            "SELECT COALESCE(MAX(CAST(REPLACE(invoice_number,'INV-','') AS INTEGER)),0) AS seq"
            " FROM invoices WHERE business_id=? AND invoice_type='sale' AND invoice_number LIKE 'INV-%'",
            (bid,)
        ).fetchone()
        db.execute("INSERT OR REPLACE INTO biz_counters VALUES (?,?,?)", (bid, "invoice_sale_INV", row["seq"] or 0))
        row2 = db.execute("SELECT COUNT(*) as cnt FROM journal_entries WHERE business_id=?", (bid,)).fetchone()
        db.execute("INSERT OR REPLACE INTO biz_counters VALUES (?,?,?)", (bid, "journal_entry", row2["cnt"] or 0))
    db.commit()
    print("biz_counters initialized OK")
    for r in db.execute("SELECT * FROM biz_counters").fetchall():
        print(dict(r))
