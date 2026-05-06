"""اختبار INSERT للفاتورة مباشرة"""
import sqlite3
from datetime import datetime

db = sqlite3.connect('database/accounting_dev.db')
db.row_factory = sqlite3.Row

biz_id = 31
now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# محاكاة next_invoice_number
try:
    db.execute("""CREATE TABLE IF NOT EXISTS biz_counters (
        business_id INTEGER NOT NULL,
        counter_key TEXT NOT NULL,
        seq INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (business_id, counter_key))""")
    db.execute("INSERT OR IGNORE INTO biz_counters (business_id, counter_key, seq) VALUES (?,?,0)", (biz_id, "invoice_sale_INV"))
    db.execute("UPDATE biz_counters SET seq=seq+1 WHERE business_id=? AND counter_key=?", (biz_id, "invoice_sale_INV"))
    row = db.execute("SELECT seq FROM biz_counters WHERE business_id=? AND counter_key=?", (biz_id, "invoice_sale_INV")).fetchone()
    inv_number = f"INV-{row['seq']:05d}"
    print("inv_number:", inv_number)
except Exception as e:
    print("inv_number ERROR:", e)

# محاكاة INSERT الفاتورة
try:
    inv_id = db.execute(
        """INSERT INTO invoices
           (business_id, invoice_number, invoice_type, invoice_date, due_date,
            party_name, subtotal, tax_amount, total, paid_amount,
            payment_method, status, notes, created_by, created_at)
           VALUES (?, ?, 'sale', DATE('now'), ?,
                   ?, ?, ?, ?, 0,
                   ?, ?, ?, ?, ?)""",
        (
            biz_id, "INV-TEST-001", None,
            "شركة النور", 6750.0, 1012.5, 7762.5,
            "credit", "pending",
            "اختبار",
            1, now,
        )
    ).lastrowid
    print("invoice INSERT OK, id:", inv_id)
    db.rollback()  # تراجع عن الاختبار
except Exception as e:
    print("invoice INSERT ERROR:", e)

# تحقق من أعمدة invoice_lines
try:
    cols = db.execute("PRAGMA table_info(invoice_lines)").fetchall()
    print("invoice_lines columns:", [c['name'] for c in cols])
except Exception as e:
    print("PRAGMA invoice_lines ERROR:", e)

# تحقق من أعمدة invoices
try:
    cols = db.execute("PRAGMA table_info(invoices)").fetchall()
    print("invoices columns:", [c['name'] for c in cols])
except Exception as e:
    print("PRAGMA invoices ERROR:", e)
