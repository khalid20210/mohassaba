"""
modules/execution_service.py
Execution Layer للمرحلة 4: ربط approval_requests بصف تنفيذ محكوم.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from modules.core_utils import json_safe_text, table_exists
from modules.notifications_service import create_notification


def enqueue_execution(db, approval_request_id: int) -> int:
    if not table_exists(db, "execution_queue"):
        return 0

    db.execute(
        """
        INSERT INTO execution_queue (approval_request_id, status)
        VALUES (?, 'pending')
        ON CONFLICT(approval_request_id) DO NOTHING
        """,
        (int(approval_request_id),),
    )
    row = db.execute(
        "SELECT id FROM execution_queue WHERE approval_request_id=? LIMIT 1",
        (int(approval_request_id),),
    ).fetchone()
    db.commit()
    return int((row[0] if not isinstance(row, dict) else row["id"])) if row else 0


def list_execution_queue(db, status: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    where = []
    params: List[Any] = []
    if status in {"pending", "executed", "failed"}:
        where.append("eq.status=?")
        params.append(status)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = db.execute(
        f"""
        SELECT eq.id, eq.approval_request_id, eq.status, eq.executed_at, eq.result, eq.created_at,
               ar.status AS approval_status,
               COALESCE(ar.action_type, ar.operation_key) AS action_type,
               ar.entity_type,
               ar.entity_id,
               COALESCE(ar.payload, ar.payload_json) AS payload
        FROM execution_queue eq
        LEFT JOIN approval_requests ar ON ar.id = eq.approval_request_id
        {where_sql}
        ORDER BY eq.id DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params + [max(1, int(limit)), max(0, int(offset))]),
    ).fetchall()
    return [dict(r) for r in rows]


def process_pending_queue(db, limit: int = 100) -> Dict[str, int]:
    """
    تنفيذ عناصر الصف.
    النسخة الحالية تنفذ تنفيذًا آمنًا عامًا: توثيق نجاح التنفيذ عند اعتماد الطلب.
    """
    rows = db.execute(
        """
        SELECT eq.id, eq.approval_request_id,
               ar.status AS approval_status,
               COALESCE(ar.action_type, ar.operation_key) AS action_type,
               ar.entity_type,
               ar.entity_id,
               COALESCE(ar.payload, ar.payload_json) AS payload
        FROM execution_queue eq
        LEFT JOIN approval_requests ar ON ar.id = eq.approval_request_id
        WHERE eq.status='pending'
        ORDER BY eq.id ASC
        LIMIT ?
        """,
        (max(1, int(limit)),),
    ).fetchall()

    processed = 0
    executed = 0
    failed = 0

    for row in rows:
        processed += 1
        r = dict(row)
        if r.get("approval_status") != "approved":
            db.execute(
                "UPDATE execution_queue SET status='failed', executed_at=datetime('now'), result=? WHERE id=?",
                (json_safe_text({"error": "approval_not_approved"}), int(r["id"])),
            )
            if r.get("approval_request_id"):
                req = db.execute(
                    "SELECT requested_by, operation_key FROM approval_requests WHERE id=? LIMIT 1",
                    (int(r["approval_request_id"]),),
                ).fetchone()
                if req and int(req[0] or 0):
                    create_notification(
                        db,
                        user_id=int(req[0]),
                        notif_type="execution_failed",
                        title="فشل تنفيذ الطلب",
                        message=f"{req[1]} لم يدخل مرحلة التنفيذ لأن الموافقة لم تكتمل.",
                    )
            failed += 1
            continue

        result = {
            "ok": True,
            "message": "execution_applied",
            "action_type": r.get("action_type"),
            "entity_type": r.get("entity_type"),
            "entity_id": r.get("entity_id"),
            "payload": r.get("payload"),
        }
        db.execute(
            "UPDATE execution_queue SET status='executed', executed_at=datetime('now'), result=? WHERE id=?",
            (json_safe_text(result), int(r["id"])),
        )
        if r.get("approval_request_id"):
            req = db.execute(
                "SELECT requested_by, operation_key FROM approval_requests WHERE id=? LIMIT 1",
                (int(r["approval_request_id"]),),
            ).fetchone()
            if req and int(req[0] or 0):
                create_notification(
                    db,
                    user_id=int(req[0]),
                    notif_type="execution_executed",
                    title="تم تنفيذ الطلب",
                    message=f"{req[1]} تم تنفيذه بنجاح.",
                )
        executed += 1

    db.commit()
    return {
        "processed": processed,
        "executed": executed,
        "failed": failed,
    }
