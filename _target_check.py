from modules import create_app
from modules.extensions import get_db

app = create_app()
paths = [
    "/owner/",
    "/inventory/",
    "/contacts/customers",
    "/invoices/",
    "/orders",
    "/recipes/",
    "/barcode/",
    "/medical/patients",
    "/rental/contracts",
    "/services/jobs",
    "/projects/",
    "/wholesale/orders",
    "/wholesale/pricing",
]

with app.app_context():
    db = get_db()
    u = db.execute("SELECT id, business_id FROM users ORDER BY id LIMIT 1").fetchone()
    uid = int(u["id"])
    bid = int(u["business_id"])

for p in paths:
    c = app.test_client()
    with c.session_transaction() as s:
        s["user_id"] = uid
        s["business_id"] = bid
    r = c.get(p, follow_redirects=False)
    print(p, "->", r.status_code, r.headers.get("Location") or "")
