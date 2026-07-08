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


def test_owner_robot_settings_api_exposes_last_event_and_dispatch_shape():
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

    resp = client.get("/owner/api/robots/settings")
    assert resp.status_code == 200

    data = resp.get_json()
    assert isinstance(data, dict)
    assert data.get("status") == "success"
    assert isinstance(data.get("summary"), dict)
    assert "alerts_24h" in data["summary"]
    assert "robots_with_alerts_24h" in data["summary"]
    assert "robots_with_failed_dispatch_24h" in data["summary"]
    assert "channels_24h" in data["summary"]
    assert isinstance(data["summary"]["channels_24h"], dict)
    assert isinstance(data.get("robots"), list)

    for robot in data["robots"]:
        assert "last_event_at" in robot
        assert "last_event_type" in robot
        assert "last_event_payload" in robot
        assert "last_dispatch_by_channel" in robot
        assert "has_alert_24h" in robot
        assert "has_failed_dispatch_24h" in robot
        assert isinstance(robot["last_dispatch_by_channel"], dict)
