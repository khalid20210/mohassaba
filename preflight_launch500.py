"""
preflight_launch500.py
فحص جاهزية قبل الإطلاق: يعتمد على create_app + endpoints.
"""
from pathlib import Path
import os


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding='utf-8').splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or '=' not in stripped:
            continue
        key, value = stripped.split('=', 1)
        os.environ[key.strip()] = value.strip()


def main() -> int:
    # استخدم إعدادات الإنتاج إن كان الملف موجوداً
    _load_env_file(Path('.env.production'))

    from modules import create_app

    app = create_app()
    c = app.test_client()

    checks = []

    health = c.get('/healthz')
    ready = c.get('/readyz')

    checks.append(("healthz", health.status_code == 200, health.status_code))
    checks.append(("readyz", ready.status_code == 200, ready.status_code))

    hjson = health.get_json(silent=True) or {}
    rjson = ready.get_json(silent=True) or {}

    redis_state = hjson.get('redis', 'unknown')
    queue_state = hjson.get('queue', 'unknown')

    checks.append(("redis", str(redis_state).startswith('ok'), redis_state))
    checks.append(("queue", str(queue_state).startswith('ok'), queue_state))

    req_id_ok = 'X-Request-ID' in health.headers
    checks.append(("request_id_header", req_id_ok, req_id_ok))

    print("=== Launch500 Preflight ===")
    failed = 0
    for name, ok, detail in checks:
        state = "PASS" if ok else "FAIL"
        print(f"{state:<5} | {name:<18} | {detail}")
        if not ok:
            failed += 1

    print("ready.checks:", rjson.get('checks'))

    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
