import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from modules import create_app; from modules.extensions import get_db
app = create_app(); app.app_context().push(); db = get_db()

print("=== أخطاء Worker ===")
rows = db.execute(
    "SELECT error_msg, COUNT(*) AS cnt FROM offline_sync_queue GROUP BY error_msg ORDER BY cnt DESC LIMIT 10"
).fetchall()
for r in rows:
    print(f"  [{r['cnt']}x] {r['error_msg']}")

print()
print("=== inventory_movements columns ===")
cols = [c["name"] for c in db.execute("PRAGMA table_info(inventory_movements)").fetchall()]
print(cols)

print()
print("=== users per business ===")
bizs = db.execute("SELECT u.id AS uid, u.business_id FROM users u LIMIT 20").fetchall()
for b in bizs:
    print(f"  user={b['uid']} biz={b['business_id']}")
