"""
_live_full_onboarding_preview.py
تشغيل حي شامل: تسجيل + دخول + onboarding لكل نشاط رئيسي/فرعي.
"""

import os
import re
import time
import random
import string
import requests
from collections import defaultdict

from modules.industry_seeds import _SEEDS, _GROUP_MAP, _detect_activity_family

BASE_URL = os.environ.get("LIVE_BASE_URL", "http://127.0.0.1:5003").strip() or "http://127.0.0.1:5003"
TIMEOUT = 20


def extract_csrf_token(html_text):
    if not html_text:
        return None
    m = re.search(r'name=["\']csrf_token["\']\s+value=["\']([^"\']+)["\']', html_text)
    if m:
        return m.group(1)
    m = re.search(r'value=["\']([^"\']+)["\']\s+name=["\']csrf_token["\']', html_text)
    if m:
        return m.group(1)
    return None


def get(session, path):
    return session.get(f"{BASE_URL}{path}", timeout=TIMEOUT, allow_redirects=True)


def post(session, path, data=None):
    return session.post(f"{BASE_URL}{path}", data=data or {}, timeout=TIMEOUT, allow_redirects=True)


def unique_id(n=6):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def run_one_activity(industry_type, idx, total):
    family = _detect_activity_family(industry_type)
    sid = unique_id(7)

    email = f"live_{industry_type[:24]}_{sid}@jinan.biz".replace(" ", "_")
    username = f"u_{sid}"
    fullname = f"Live User {sid}"
    password = "Test@12345"

    sess = requests.Session()

    # 1) فتح صفحة التسجيل + csrf
    r_reg_get = get(sess, "/auth/register")
    if r_reg_get.status_code != 200:
        return False, family, f"register GET failed: {r_reg_get.status_code}"

    csrf_reg = extract_csrf_token(r_reg_get.text) or ""

    # 2) تسجيل حساب جديد (مع نشاط)
    r_reg_post = post(sess, "/auth/register", {
        "csrf_token": csrf_reg,
        "full_name": fullname,
        "username": username,
        "country": "SA",
        "email": email,
        "password": password,
        "password_confirm": password,
        "industry_type": industry_type,
    })
    if r_reg_post.status_code not in (200, 302):
        return False, family, f"register POST failed: {r_reg_post.status_code}"

    # 3) دخول
    r_login_get = get(sess, "/auth/login")
    if r_login_get.status_code != 200:
        return False, family, f"login GET failed: {r_login_get.status_code}"

    csrf_login = extract_csrf_token(r_login_get.text) or ""
    r_login_post = post(sess, "/auth/login", {
        "csrf_token": csrf_login,
        "email": email,
        "password": password,
    })
    if r_login_post.status_code not in (200, 302):
        return False, family, f"login POST failed: {r_login_post.status_code}"

    # 4) onboarding (إن طُلب)
    r_ob_get = get(sess, "/onboarding")
    if r_ob_get.status_code == 200:
        csrf_ob = extract_csrf_token(r_ob_get.text) or ""
        r_ob_post = post(sess, "/onboarding", {
            "csrf_token": csrf_ob,
            "business_name": f"شركة مباشرة {industry_type[:20]} {sid}",
            "industry_type": industry_type,
            "city": "الرياض",
            "tax_number": "300000000000003",
            "phone": "0501234567",
        })
        if r_ob_post.status_code not in (200, 302):
            return False, family, f"onboarding POST failed: {r_ob_post.status_code}"

    # 5) التحقق من الوصول الفعلي بعد الدخول
    r_dash = get(sess, "/dashboard")
    if r_dash.status_code != 200:
        return False, family, f"dashboard failed: {r_dash.status_code}"

    return True, family, f"OK | email={email}"


def main():
    t0 = time.time()

    all_types = sorted(set(list(_SEEDS.keys()) + list(_GROUP_MAP.keys())))
    total = len(all_types)

    print("\n" + "=" * 80)
    print("LIVE PREVIEW: Register + Login + Onboarding for ALL activities")
    print(f"BASE URL: {BASE_URL}")
    print(f"Total activities: {total}")
    print("=" * 80)

    pass_count = 0
    fail_count = 0
    by_family = defaultdict(lambda: {"pass": 0, "fail": 0})
    failures = []

    for i, itype in enumerate(all_types, 1):
        ok, family, detail = run_one_activity(itype, i, total)
        if ok:
            pass_count += 1
            by_family[family]["pass"] += 1
            print(f"✓ [{i:3d}/{total}] {itype:<45} ({family}) -> {detail}")
        else:
            fail_count += 1
            by_family[family]["fail"] += 1
            failures.append((itype, detail))
            print(f"✗ [{i:3d}/{total}] {itype:<45} ({family}) -> {detail}")

    elapsed = time.time() - t0

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Passed: {pass_count}")
    print(f"Failed: {fail_count}")
    print(f"Elapsed: {elapsed:.2f}s")

    print("\nBy family:")
    for fam in sorted(by_family.keys()):
        s = by_family[fam]
        print(f"  - {fam:<30} pass={s['pass']:3d} fail={s['fail']:3d}")

    if failures:
        print("\nFailures:")
        for itype, detail in failures:
            print(f"  - {itype}: {detail}")

    raise SystemExit(0 if fail_count == 0 else 1)


if __name__ == "__main__":
    main()
