import shutil
from pathlib import Path

import sqlite3

from modules.migration_runner import run_migrations
from modules.notifications_service import (
    count_unread_notifications,
    create_notification,
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
)
from modules.approval_service import create_approval_request, approve_request
from modules.execution_service import process_pending_queue


def test_notifications_contract_and_governance_hooks(tmp_path: Path):
    db_path = tmp_path / "notifications.db"
    shutil.copy2(Path("database/accounting_dev.db"), db_path)
    run_migrations(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    user = conn.execute(
        """
        SELECT u.id, u.business_id, u.role_id, u.username, u.full_name,
               COALESCE(r.permissions, '{}') AS permissions
        FROM users u
        LEFT JOIN roles r ON r.id = u.role_id
        WHERE COALESCE(r.permissions, '') LIKE '%"all":true%'
        ORDER BY u.id
        LIMIT 1
        """
    ).fetchone()
    if user is None:
        user = conn.execute(
            """
            SELECT u.id, u.business_id, u.role_id, u.username, u.full_name,
                   COALESCE(r.permissions, '{}') AS permissions
            FROM users u
            LEFT JOIN roles r ON r.id = u.role_id
            ORDER BY u.id
            LIMIT 1
            """
        ).fetchone()
    assert user is not None

    base_unread = count_unread_notifications(conn, user_id=int(user["id"]))

    nid = create_notification(
        conn,
        user_id=int(user["id"]),
        notif_type="info",
        title="Test Notification",
        message="hello",
    )
    assert nid > 0
    items = list_notifications(conn, user_id=int(user["id"]), unread_only=False)
    assert items and items[0]["title"] == "Test Notification"
    assert count_unread_notifications(conn, user_id=int(user["id"])) == base_unread + 1
    assert mark_notification_read(conn, user_id=int(user["id"]), notification_id=nid) is True
    assert count_unread_notifications(conn, user_id=int(user["id"])) == base_unread

    request_id = create_approval_request(
        conn,
        business_id=int(user["business_id"]),
        requested_by=int(user["id"]),
        operation_key="settings.update_branding",
        entity_type="settings",
        entity_id=1,
        reason="update branding",
        payload={"foo": "bar"},
        required_approvals=1,
    )
    assert request_id > 0
    approvals = list_notifications(conn, user_id=int(user["id"]), unread_only=True)
    assert any(n["type"] == "approval_requested" for n in approvals)

    approve_result = approve_request(
        conn,
        business_id=int(user["business_id"]),
        request_id=request_id,
        approver_user=dict(user),
        comment="ok",
    )
    assert approve_result["ok"] is True
    approvals_after = list_notifications(conn, user_id=int(user["id"]), unread_only=True)
    assert any(n["type"] == "approval_approved" for n in approvals_after)

    processed = process_pending_queue(conn, limit=10)
    assert processed["processed"] >= 0

    assert mark_all_notifications_read(conn, user_id=int(user["id"])) >= 0
