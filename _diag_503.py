import sys, threading, json, collections
sys.path.insert(0, '.')
from app import app

with app.app_context():
    from modules.extensions import get_db
    db = get_db()
    u = db.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
    b = db.execute("SELECT id FROM businesses LIMIT 1").fetchone()[0]
    pr = db.execute("SELECT id, sale_price FROM products WHERE business_id=? LIMIT 1", (b,)).fetchone()
    p = (pr[0], float(pr[1] or 1))

results = []
lk = threading.Lock()

def go():
    c = app.test_client()
    try:
        with c.session_transaction() as s:
            s["user_id"] = u
            s["business_id"] = b
        r = c.post(
            "/api/pos/checkout",
            data=json.dumps({"items": [{"product_id": p[0], "quantity": 1, "unit_price": p[1]}], "payment_method": "cash"}),
            content_type="application/json",
        )
        code = r.status_code
        body = r.get_data(as_text=True) if code != 200 else ""
    except Exception as e:
        code = -1
        body = str(e)[:120]
    with lk:
        results.append((code, body[:300]))

threads = [threading.Thread(target=go) for _ in range(50)]
for t in threads:
    t.start()
for t in threads:
    t.join()

codes = collections.Counter(r[0] for r in results)
print("codes:", codes)
shown = 0
for c, b in results:
    if c != 200 and shown < 5:
        print(f"  [{c}] {b}")
        shown += 1
