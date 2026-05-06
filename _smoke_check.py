import re
import sys
from modules import create_app
from modules.extensions import get_db


def fill_rule(rule):
    s = rule
    s = re.sub(r"<int:[^>]+>", "1", s)
    s = re.sub(r"<float:[^>]+>", "1.0", s)
    s = re.sub(r"<path:[^>]+>", "x", s)
    s = re.sub(r"<string:[^>]+>", "x", s)
    s = re.sub(r"<[^>]+>", "x", s)
    return s


app = create_app()
with app.app_context():
    db = get_db()
    user = db.execute("SELECT id, business_id FROM users ORDER BY id LIMIT 1").fetchone()
    if not user:
        print("NO_USERS")
        raise SystemExit(0)
    user_id = int(user["id"])
    biz_id = int(user["business_id"])

client = app.test_client()
with client.session_transaction() as sess:
    sess["user_id"] = user_id
    sess["business_id"] = biz_id

failures = []
checked = 0
for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
    if "GET" not in rule.methods:
        continue
    if rule.rule.startswith("/static"):
        continue

    path = fill_rule(rule.rule)
    if any(x in path for x in ["/api/", "/healthz", "/readyz", "/sw.js"]):
        continue
    if "logout" in path:
        continue

    checked += 1
    try:
        resp = client.get(path, follow_redirects=False)
        if resp.status_code >= 500:
            failures.append((path, resp.status_code))
    except Exception as exc:
        failures.append((path, f"EXC:{type(exc).__name__}: {exc}"))

print(f"CHECKED={checked}")
print(f"FAILURES={len(failures)}")
for p, c in failures:
    print(f"{c} {p}")

sys.exit(1 if failures else 0)
