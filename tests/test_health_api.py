import json
import sqlite3

import pytest


def _find_owner_user():
    from modules.config import DB_PATH

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT u.id AS user_id, u.business_id AS business_id, r.permissions AS permissions
        FROM users u
        LEFT JOIN roles r ON r.id = u.role_id
        """
    ).fetchall()
    conn.close()

    for row in rows:
        try:
            perms = json.loads(row["permissions"] or "{}")
        except Exception:
            perms = {}
        if perms.get("all"):
            return int(row["user_id"]), int(row["business_id"])
    return None


def _ensure_onboarding_complete(business_id: int):
    from modules.config import DB_PATH

    conn = sqlite3.connect(str(DB_PATH))
    # upsert: نضمن القيمة حتى لو كان السجل موجود مسبقاً
    conn.execute(
        """
        INSERT INTO settings (business_id, key, value)
        VALUES (?, 'onboarding_complete', '1')
        ON CONFLICT(business_id, key) DO UPDATE SET value='1'
        """,
        (business_id,),
    )
    conn.commit()
    conn.close()


def test_healthz_returns_ok_json():
    from app import app

    client = app.test_client()
    resp = client.get("/healthz")

    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, dict)
    assert data.get("status") == "ok"
    for key in ("platform", "region", "env", "queue", "time"):
        assert key in data


def test_readyz_returns_readiness_payload():
    from app import app

    client = app.test_client()
    resp = client.get("/readyz")

    assert resp.status_code in (200, 503)
    data = resp.get_json()
    assert isinstance(data, dict)
    assert data.get("status") in ("ready", "degraded")
    assert isinstance(data.get("checks"), dict)

    for key in ("db", "tables", "migrations", "redis", "queue"):
        assert key in data["checks"]


def test_diagnostics_owner_access_returns_json():
    from app import app

    owner = _find_owner_user()
    if owner is None:
        pytest.skip("No owner user with permissions.all found in database")

    user_id, business_id = owner
    _ensure_onboarding_complete(business_id)
    client = app.test_client()

    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["business_id"] = business_id

    resp = client.get("/diagnostics")
    assert resp.status_code in (200, 500)

    data = resp.get_json()
    assert isinstance(data, dict)
    # المهم هنا: وصول المالك يُعيد JSON تشخيصي (وليس redirect/html)
    assert ("platform" in data) or ("error" in data)
