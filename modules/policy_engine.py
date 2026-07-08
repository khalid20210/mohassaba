"""
modules/policy_engine.py
Policy Engine موحّد لتقييم الصلاحيات وسياسات العمليات الحساسة.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from modules.core_utils import table_exists as db_table_exists


def _table_exists(db, table_name: str) -> bool:
    return db_table_exists(db, table_name)


def _parse_operation_key(operation_key: str) -> tuple[str, str]:
    raw = str(operation_key or "").strip()
    if "." in raw:
        entity, action = raw.split(".", 1)
        return (entity or "unknown"), (action or "default")
    return raw or "unknown", "default"


def _json_loads_dict(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            out = json.loads(raw or "{}")
            return out if isinstance(out, dict) else {}
        except Exception:
            return {}
    return {}


def parse_permissions(raw_permissions: Any) -> Dict[str, bool]:
    if isinstance(raw_permissions, dict):
        return {str(k): bool(v) for k, v in raw_permissions.items()}
    if isinstance(raw_permissions, str):
        try:
            payload = json.loads(raw_permissions or "{}")
            if isinstance(payload, dict):
                return {str(k): bool(v) for k, v in payload.items()}
        except Exception:
            return {}
    return {}


def is_owner(user: Optional[dict]) -> bool:
    if not user:
        return False
    perms = parse_permissions(user.get("permissions"))
    return bool(perms.get("all"))


def can_access_permission(user: Optional[dict], permission_key: str) -> bool:
    if not user:
        return False
    perms = parse_permissions(user.get("permissions"))
    if perms.get("all"):
        return True
    return bool(perms.get(permission_key))


def get_operation_policy(db, business_id: int, operation_key: str, default_permission_key: Optional[str] = None) -> Dict[str, Any]:
    entity_type, action_type = _parse_operation_key(operation_key)

    # 1) العقد الجديد: approval_policies
    if _table_exists(db, "approval_policies"):
        row = db.execute(
            """
            SELECT entity_type, action_type, requires_approval, conditions, role_based_rules, is_active
            FROM approval_policies
            WHERE business_id=? AND entity_type=? AND action_type=?
            LIMIT 1
            """,
            (business_id, entity_type, action_type),
        ).fetchone()

        if row:
            row_d = dict(row) if isinstance(row, dict) else {
                "entity_type": row[0],
                "action_type": row[1],
                "requires_approval": row[2],
                "conditions": row[3],
                "role_based_rules": row[4],
                "is_active": row[5],
            }

            conditions = _json_loads_dict(row_d.get("conditions"))
            rules = _json_loads_dict(row_d.get("role_based_rules"))
            permission_key = rules.get("permission_key") or default_permission_key
            owner_only = bool(rules.get("owner_only", False))
            min_approvals = int(conditions.get("min_approvals", 1) or 1)

            return {
                "operation_key": operation_key,
                "permission_key": permission_key,
                "requires_approval": bool(row_d.get("requires_approval")),
                "min_approvals": max(1, min_approvals),
                "owner_only": owner_only,
                "is_active": bool(row_d.get("is_active", True)),
                "entity_type": entity_type,
                "action_type": action_type,
                "conditions": conditions,
                "role_based_rules": rules,
            }

    # 2) fallback للعقد القديم: operation_policies
    row = db.execute(
        """
        SELECT operation_key, permission_key, requires_approval, min_approvals, owner_only, is_active
        FROM operation_policies
        WHERE business_id=? AND operation_key=?
        LIMIT 1
        """,
        (business_id, operation_key),
    ).fetchone()

    if not row:
        return {
            "operation_key": operation_key,
            "permission_key": default_permission_key,
            "requires_approval": False,
            "min_approvals": 1,
            "owner_only": False,
            "is_active": True,
            "entity_type": entity_type,
            "action_type": action_type,
            "conditions": {"min_approvals": 1},
            "role_based_rules": ({"permission_key": default_permission_key} if default_permission_key else {}),
        }

    if isinstance(row, dict):
        permission_key = row.get("permission_key")
        requires_approval = bool(row.get("requires_approval"))
        min_approvals = int(row.get("min_approvals") or 1)
        owner_only = bool(row.get("owner_only"))
        is_active = bool(row.get("is_active"))
    else:
        permission_key = row[1]
        requires_approval = bool(row[2])
        min_approvals = int(row[3] or 1)
        owner_only = bool(row[4])
        is_active = bool(row[5])

    if not permission_key:
        permission_key = default_permission_key

    return {
        "operation_key": operation_key,
        "permission_key": permission_key,
        "requires_approval": requires_approval,
        "min_approvals": max(1, min_approvals),
        "owner_only": owner_only,
        "is_active": is_active,
        "entity_type": entity_type,
        "action_type": action_type,
        "conditions": {"min_approvals": max(1, min_approvals)},
        "role_based_rules": {
            **({"permission_key": permission_key} if permission_key else {}),
            "owner_only": owner_only,
        },
    }


def authorize_operation(
    db,
    *,
    business_id: int,
    user: Optional[dict],
    operation_key: str,
    default_permission_key: Optional[str] = None,
) -> Dict[str, Any]:
    if not user:
        return {"allowed": False, "reason": "unauthenticated", "approval_required": False}

    policy = get_operation_policy(db, business_id, operation_key, default_permission_key)
    if not policy.get("is_active", True):
        return {"allowed": False, "reason": "operation_disabled", "approval_required": False, "policy": policy}

    owner = is_owner(user)

    if policy.get("owner_only") and not owner:
        return {"allowed": False, "reason": "owner_only", "approval_required": False, "policy": policy}

    perm_key = policy.get("permission_key")
    if perm_key and not can_access_permission(user, perm_key):
        return {"allowed": False, "reason": f"missing_permission:{perm_key}", "approval_required": False, "policy": policy}

    if policy.get("requires_approval") and not owner:
        return {
            "allowed": False,
            "reason": "approval_required",
            "approval_required": True,
            "policy": policy,
        }

    return {"allowed": True, "reason": "ok", "approval_required": False, "policy": policy}


def ensure_default_policies(db, business_id: int) -> None:
    """حقن سياسات افتراضية آمنة للعمليات الحساسة (idempotent)."""
    defaults = [
        # تعديل صلاحيات المستخدمين: يتطلب مالك بشكل افتراضي.
        ("permissions.update_user_permissions", "settings", 0, 1, 1, 1),
        # حذف نهائي: يجب أن يمر عبر طلب موافقة إن لم يكن مالكاً.
        ("recycle_bin.permanent_delete", "settings", 1, 1, 0, 1),
        # إلغاء فاتورة مدفوعة: دوماً عبر workflow لغير المالك.
        ("invoice.cancel.paid", "invoice_cancel", 1, 1, 0, 1),
        # اعتماد طلبات حساسة: مالك فقط.
        ("approval.resolve", "settings", 0, 1, 1, 1),
    ]

    # العقد الجديد approval_policies
    if _table_exists(db, "approval_policies"):
        for operation_key, permission_key, requires_approval, min_approvals, owner_only, is_active in defaults:
            entity_type, action_type = _parse_operation_key(operation_key)
            db.execute(
                """
                INSERT INTO approval_policies (
                    business_id, entity_type, action_type,
                    requires_approval, conditions, role_based_rules, is_active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(business_id, entity_type, action_type) DO NOTHING
                """,
                (
                    business_id,
                    entity_type,
                    action_type,
                    int(requires_approval),
                    json.dumps({"min_approvals": int(min_approvals)}),
                    json.dumps({
                        **({"permission_key": permission_key} if permission_key else {}),
                        "owner_only": bool(owner_only),
                    }),
                    int(is_active),
                ),
            )

    # fallback/توافق للعقد القديم operation_policies
    if not _table_exists(db, "operation_policies"):
        db.commit()
        return

    for operation_key, permission_key, requires_approval, min_approvals, owner_only, is_active in defaults:
        db.execute(
            """
            INSERT INTO operation_policies (
                business_id, operation_key, permission_key,
                requires_approval, min_approvals, owner_only, is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(business_id, operation_key) DO NOTHING
            """,
            (
                business_id,
                operation_key,
                permission_key,
                int(requires_approval),
                int(min_approvals),
                int(owner_only),
                int(is_active),
            ),
        )
    db.commit()
