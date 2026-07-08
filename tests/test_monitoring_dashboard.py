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


def test_monitoring_summary_owner_access_returns_payload():
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

    resp = client.get("/api/v1/monitoring/summary")
    assert resp.status_code == 200
    data = resp.get_json()
    assert isinstance(data, dict)
    assert data.get("status") == "ok"
    assert "summary" in data
    assert "recent" in data
    assert "metrics" in data
    for key in ("pending_approvals", "execution_pending", "unread_notifications", "audit_24h"):
        assert key in data["summary"]


def test_monitoring_dashboard_page_renders_for_owner():
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

    resp = client.get("/monitoring")
    assert resp.status_code == 200
    assert b"\xd9\x84\xd9\x88\xd8\xad\xd8\xa9 \xd8\xa7\xd9\x84\xd9\x85\xd8\xb1\xd8\xa7\xd9\x82\xd8\xa8\xd8\xa9" in resp.data
