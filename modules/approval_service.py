"""
modules/approval_service.py
Approval Workflow Service وربط مباشر مع Policy Engine و Audit.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from modules.core_utils import json_safe_nullable, table_exists
from modules.audit_service import record_audit_event
from modules.execution_service import enqueue_execution
from modules.notifications_service import create_notification
from modules.policy_engine import authorize_operation, get_operation_policy, is_owner


def create_approval_request(
    db,
    *,
    business_id: int,
    requested_by: int,
    operation_key: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    reason: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    required_approvals: int = 1,
) -> int:
    db.execute(
        """
        INSERT INTO approval_requests (
            business_id, operation_key, action_type, entity_type, entity_id,
            requested_by, status, reason, payload_json, payload, required_approvals
        )
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
        """,
        (
            business_id,
            operation_key,
            operation_key,
            entity_type,
            entity_id,
            requested_by,
            reason or "",
            json_safe_nullable(payload),
            json_safe_nullable(payload),
            max(1, int(required_approvals or 1)),
        ),
    )
    req_id = int(db.execute("SELECT last_insert_rowid()").fetchone()[0])

    record_audit_event(
        db,
        business_id=business_id,
        action="approval_requested",
        entity_type=entity_type or operation_key,
        entity_id=entity_id,
        new_value={"request_id": req_id, "operation_key": operation_key, "reason": reason},
    )

    create_notification(
        db,
        user_id=int(requested_by),
        notif_type="approval_requested",
        title="تم إنشاء طلب موافقة",
        message=f"{operation_key} بانتظار الاعتماد.",
    )

    db.commit()
    return req_id


def ensure_operation_or_create_request(
    db,
    *,
    business_id: int,
    user: Optional[dict],
    operation_key: str,
    default_permission_key: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    reason: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    auth = authorize_operation(
        db,
        business_id=business_id,
        user=user,
        operation_key=operation_key,
        default_permission_key=default_permission_key,
    )
    if auth.get("allowed"):
        return {"allowed": True, "approval_required": False, "request_id": None, "policy": auth.get("policy")}

    if not auth.get("approval_required"):
        return {
            "allowed": False,
            "approval_required": False,
            "reason": auth.get("reason"),
            "request_id": None,
            "policy": auth.get("policy"),
        }

    if not user or not user.get("id"):
        return {
            "allowed": False,
            "approval_required": True,
            "reason": "cannot_create_request_without_user",
            "request_id": None,
            "policy": auth.get("policy"),
        }

    policy = auth.get("policy") or get_operation_policy(db, business_id, operation_key, default_permission_key)
    request_id = create_approval_request(
        db,
        business_id=business_id,
        requested_by=int(user["id"]),
        operation_key=operation_key,
        entity_type=entity_type,
        entity_id=entity_id,
        reason=reason,
        payload=payload,
        required_approvals=int(policy.get("min_approvals") or 1),
    )
    return {
        "allowed": False,
        "approval_required": True,
        "reason": "pending_approval",
        "request_id": request_id,
        "policy": policy,
    }


def approve_request(
    db,
    *,
    business_id: int,
    request_id: int,
    approver_user: dict,
    comment: Optional[str] = None,
) -> Dict[str, Any]:
    row = db.execute(
        """
        SELECT * FROM approval_requests
        WHERE id=? AND business_id=?
        LIMIT 1
        """,
        (request_id, business_id),
    ).fetchone()
    if not row:
        return {"ok": False, "error": "request_not_found"}

    row_d = dict(row)
    if row_d.get("status") != "pending":
        return {"ok": False, "error": "request_not_pending", "status": row_d.get("status")}

    if not is_owner(approver_user):
        # في النسخة الحالية: اعتماد العمليات الحساسة للمالك فقط
        return {"ok": False, "error": "owner_only_approval"}

    db.execute(
        """
        INSERT INTO approval_request_votes (request_id, business_id, approver_user_id, decision, comment)
        VALUES (?, ?, ?, 'approved', ?)
        ON CONFLICT(request_id, approver_user_id) DO UPDATE SET
            decision='approved',
            comment=excluded.comment,
            decided_at=datetime('now')
        """,
        (request_id, business_id, int(approver_user["id"]), comment or ""),
    )

    approvals = int(
        db.execute(
            "SELECT COUNT(*) FROM approval_request_votes WHERE request_id=? AND decision='approved'",
            (request_id,),
        ).fetchone()[0]
    )
    required = int(row_d.get("required_approvals") or 1)

    if approvals >= required:
        db.execute(
            """
            UPDATE approval_requests
            SET status='approved', current_approvals=?, resolved_at=datetime('now'), resolved_by=?,
                approved_at=datetime('now'), approved_by=?
            WHERE id=?
            """,
            (approvals, int(approver_user["id"]), int(approver_user["id"]), request_id),
        )
        final_status = "approved"
        enqueue_execution(db, int(request_id))
    else:
        db.execute(
            "UPDATE approval_requests SET current_approvals=? WHERE id=?",
            (approvals, request_id),
        )
        final_status = "pending"

    record_audit_event(
        db,
        business_id=business_id,
        action="approval_decision",
        entity_type="approval_request",
        entity_id=request_id,
        new_value={"decision": "approved", "status": final_status, "comment": comment},
    )

    if int(row_d.get("requested_by") or 0):
        create_notification(
            db,
            user_id=int(row_d["requested_by"]),
            notif_type="approval_approved",
            title="تمت الموافقة على الطلب",
            message=f"{row_d.get('operation_key')} تمت الموافقة عليه.",
        )

    db.commit()
    return {"ok": True, "status": final_status, "approvals": approvals, "required": required}


def reject_request(
    db,
    *,
    business_id: int,
    request_id: int,
    approver_user: dict,
    comment: Optional[str] = None,
) -> Dict[str, Any]:
    row = db.execute(
        "SELECT * FROM approval_requests WHERE id=? AND business_id=? LIMIT 1",
        (request_id, business_id),
    ).fetchone()
    if not row:
        return {"ok": False, "error": "request_not_found"}

    if not is_owner(approver_user):
        return {"ok": False, "error": "owner_only_approval"}

    db.execute(
        """
        INSERT INTO approval_request_votes (request_id, business_id, approver_user_id, decision, comment)
        VALUES (?, ?, ?, 'rejected', ?)
        ON CONFLICT(request_id, approver_user_id) DO UPDATE SET
            decision='rejected',
            comment=excluded.comment,
            decided_at=datetime('now')
        """,
        (request_id, business_id, int(approver_user["id"]), comment or ""),
    )

    db.execute(
        """
        UPDATE approval_requests
        SET status='rejected', resolved_at=datetime('now'), resolved_by=?,
            approved_at=datetime('now'), approved_by=?
        WHERE id=?
        """,
        (int(approver_user["id"]), int(approver_user["id"]), request_id),
    )

    record_audit_event(
        db,
        business_id=business_id,
        action="approval_decision",
        entity_type="approval_request",
        entity_id=request_id,
        new_value={"decision": "rejected", "comment": comment},
    )

    requested_by = int(row["requested_by"] or 0) if "requested_by" in row.keys() else 0
    if requested_by:
        create_notification(
            db,
            user_id=requested_by,
            notif_type="approval_rejected",
            title="تم رفض طلب الموافقة",
            message=f"{row['operation_key']} تم رفضه.",
        )

    db.commit()
    return {"ok": True, "status": "rejected"}


def list_pending_requests(db, business_id: int, limit: int = 50, offset: int = 0):
    rows = db.execute(
        """
        SELECT ar.*, COALESCE(ar.action_type, ar.operation_key) AS action_type,
               COALESCE(ar.payload, ar.payload_json) AS payload,
               u.full_name AS requested_by_name
        FROM approval_requests ar
        LEFT JOIN users u ON u.id = ar.requested_by
        WHERE ar.business_id=? AND ar.status='pending'
        ORDER BY ar.requested_at DESC
        LIMIT ? OFFSET ?
        """,
        (business_id, max(1, int(limit)), max(0, int(offset))),
    ).fetchall()
    return [dict(r) for r in rows]


def list_requests(db, business_id: int, status: Optional[str] = None, limit: int = 100, offset: int = 0):
    """إرجاع طلبات الموافقة مع فلترة اختيارية بالحالة."""
    where = ["ar.business_id=?"]
    params = [business_id]

    if status in {"pending", "approved", "rejected"}:
        where.append("ar.status=?")
        params.append(status)

    users_exists = table_exists(db, "users")
    if users_exists:
        sql = f"""
            SELECT ar.id,
                   COALESCE(ar.action_type, ar.operation_key) AS action_type,
                   ar.entity_type,
                   ar.entity_id,
                   ar.requested_by,
                   ar.status,
                   ar.approved_by,
                   ar.approved_at,
                   COALESCE(ar.payload, ar.payload_json) AS payload,
                   ar.requested_at,
                   ru.full_name AS requested_by_name,
                   au.full_name AS approved_by_name
            FROM approval_requests ar
            LEFT JOIN users ru ON ru.id = ar.requested_by
            LEFT JOIN users au ON au.id = ar.approved_by
            WHERE {' AND '.join(where)}
            ORDER BY ar.requested_at DESC
            LIMIT ? OFFSET ?
        """
    else:
        sql = f"""
            SELECT ar.id,
                   COALESCE(ar.action_type, ar.operation_key) AS action_type,
                   ar.entity_type,
                   ar.entity_id,
                   ar.requested_by,
                   ar.status,
                   ar.approved_by,
                   ar.approved_at,
                   COALESCE(ar.payload, ar.payload_json) AS payload,
                   ar.requested_at,
                   NULL AS requested_by_name,
                   NULL AS approved_by_name
            FROM approval_requests ar
            WHERE {' AND '.join(where)}
            ORDER BY ar.requested_at DESC
            LIMIT ? OFFSET ?
        """

    rows = db.execute(
        sql,
        tuple(params + [max(1, int(limit)), max(0, int(offset))]),
    ).fetchall()
    return [dict(r) for r in rows]


def get_request_by_id(db, business_id: int, request_id: int):
    users_exists = table_exists(db, "users")
    if users_exists:
        sql = """
            SELECT ar.id,
                   COALESCE(ar.action_type, ar.operation_key) AS action_type,
                   ar.entity_type,
                   ar.entity_id,
                   ar.requested_by,
                   ar.status,
                   ar.approved_by,
                   ar.approved_at,
                   COALESCE(ar.payload, ar.payload_json) AS payload,
                   ar.requested_at,
                   ru.full_name AS requested_by_name,
                   au.full_name AS approved_by_name
            FROM approval_requests ar
            LEFT JOIN users ru ON ru.id = ar.requested_by
            LEFT JOIN users au ON au.id = ar.approved_by
            WHERE ar.business_id=? AND ar.id=?
            LIMIT 1
        """
    else:
        sql = """
            SELECT ar.id,
                   COALESCE(ar.action_type, ar.operation_key) AS action_type,
                   ar.entity_type,
                   ar.entity_id,
                   ar.requested_by,
                   ar.status,
                   ar.approved_by,
                   ar.approved_at,
                   COALESCE(ar.payload, ar.payload_json) AS payload,
                   ar.requested_at,
                   NULL AS requested_by_name,
                   NULL AS approved_by_name
            FROM approval_requests ar
            WHERE ar.business_id=? AND ar.id=?
            LIMIT 1
        """

    row = db.execute(
        sql,
        (business_id, request_id),
    ).fetchone()
    return dict(row) if row else None
