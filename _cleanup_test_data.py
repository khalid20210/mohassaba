import sqlite3, sys
sys.path.insert(0, '.')
from modules.config import DB_PATH

conn = sqlite3.connect(str(DB_PATH))
conn.execute("PRAGMA foreign_keys = OFF")

# احذف البيانات التجريبية المتراكمة من جلسات الاختبار
conn.execute("DELETE FROM invoices WHERE id > 5")
conn.execute("DELETE FROM journal_entries WHERE id > 20")
conn.execute("DELETE FROM invoice_lines WHERE id > 20")
conn.execute("DELETE FROM zatca_queue WHERE id > 5")
conn.execute("DELETE FROM audit_logs WHERE id > 10")

# أعد ضبط عدادات الفواتير
conn.execute("""
UPDATE biz_counters SET seq = COALESCE(
    (SELECT MAX(CAST(SUBSTR(invoice_number, 5) AS INTEGER))
     FROM invoices WHERE business_id = biz_counters.business_id
     AND invoice_number LIKE 'INV-%'), 0)
WHERE counter_key LIKE 'invoice_sale_%'
""")
conn.execute("""
UPDATE biz_counters SET seq = COALESCE(
    (SELECT MAX(CAST(SUBSTR(entry_number, 4) AS INTEGER))
     FROM journal_entries WHERE business_id = biz_counters.business_id
     AND entry_number LIKE 'JE-%'), 0)
WHERE counter_key = 'journal_entry'
""")

conn.commit()
conn.execute("VACUUM")
conn.commit()

for t in ["invoices", "journal_entries", "invoice_lines", "zatca_queue", "audit_logs"]:
    try:
        n = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"{t}: {n}")
    except Exception as e:
        print(f"{t}: error {e}")

for r in conn.execute("SELECT counter_key, seq FROM biz_counters WHERE business_id=1").fetchall():
    print("counter", r[0], "=", r[1])

conn.close()
print("cleanup done")
