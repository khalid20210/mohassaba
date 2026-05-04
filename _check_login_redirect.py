import re
import requests

s = requests.Session()
base = "http://127.0.0.1:5001"

resp = s.get(base + "/auth/login", timeout=10)
m = re.search(r'name="csrf_token" value="([^"]+)"', resp.text)
csrf = m.group(1) if m else ""

payload = {
    "csrf_token": csrf,
    "username": "testuser_check2",
    "password": "Test@123456",
}

r = s.post(base + "/auth/login", data=payload, allow_redirects=False, timeout=10)
print("login_status=", r.status_code)
print("location=", r.headers.get("Location"))
