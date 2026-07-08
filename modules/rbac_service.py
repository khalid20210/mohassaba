"""modules/rbac_service.py — RBAC normalized helpers with legacy fallback."""
from __future__ import annotations

import json
from typing import Any

from modules.core_utils import table_exists


DEFAULT_PERMISSION_KEYS = (
    "all",
    "sales",
    "purchases",
    "warehouse",
    "contacts",
    "pos",
    "accounting",
    "reports",
    "analytics",
    "settings",
    "invoice_edit",
    "invoice_cancel",
    "invoice_delete",
    "invoice_reason_optional",
    "business_profile_edit",
    "business_profile_reason_optional",
    "inventory",
)


def _json_loads_dict(value: Any) -> dict[str, bool]:
    if value in (None, ""):
        return {}
    if isinstance(value, dict):
        return {str(k): bool(v) for k, v in value.items()}
    try:
        raw = json.loads(value)
    except Exception:
        return {}
    if isinstance(raw, dict):
        return {str(k): bool(v) for k, v in raw.items()}
    return {}


def list_known_permission_keys(db) -> list[str]:
    if table_exists(db, "permissions"):
        rows = db.execute("SELECT name FROM permissions ORDER BY name").fetchall()
        if rows:
            return [r[0] for r in rows]
    return list(DEFAULT_PERMISSION_KEYS)


def sync_user_role_assignment(db, user_id: int, role_id: int | None) -> None:
    if not table_exists(db, "user_roles"):
        return
    db.execute("DELETE FROM user_roles WHERE user_id=?", (user_id,))
    if role_id:
        db.execute(
            "INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)",
            (user_id, role_id),
        )


def sync_role_permissions_from_legacy_json(db, role_id: int, permissions_json: Any) -> None:
    if not table_exists(db, "role_permissions") or not table_exists(db, "permissions"):
        return
    perms = _json_loads_dict(permissions_json)
    db.execute("DELETE FROM role_permissions WHERE role_id=?", (role_id,))
    if not perms:
        return
    for key, enabled in perms.items():
        if not enabled:
            continue
        perm_row = db.execute("SELECT id FROM permissions WHERE name=?", (key,)).fetchone()
        if perm_row:
            db.execute(
                "INSERT OR IGNORE INTO role_permissions (role_id, permission_id) VALUES (?, ?)",
                (role_id, int(perm_row[0])),
            )


def get_effective_permissions(db, user_row) -> dict[str, bool]:
    if not user_row:
        return {}

    user_id = int(user_row["id"])
    role_id = user_row["role_id"] if "role_id" in user_row.keys() else None

    if table_exists(db, "user_roles") and table_exists(db, "role_permissions") and table_exists(db, "permissions"):
        rows = db.execute(
            """
            SELECT p.name
            FROM user_roles ur
            JOIN role_permissions rp ON rp.role_id = ur.role_id
            JOIN permissions p ON p.id = rp.permission_id
            WHERE ur.user_id=?
            """,
            (user_id,),
        ).fetchall()
        perms = {str(r[0]): True for r in rows}
        if perms:
            return perms

    legacy = _json_loads_dict(user_row["permissions"] if "permissions" in user_row.keys() else None)
    if legacy:
        return legacy

    if role_id and table_exists(db, "roles"):
        role_row = db.execute("SELECT permissions FROM roles WHERE id=?", (role_id,)).fetchone()
        if role_row:
            return _json_loads_dict(role_row[0])

    return {}


def user_has_perm(db, user_row, perm_key: str) -> bool:
    if not user_row:
        return False
    perms = get_effective_permissions(db, user_row)
    return bool(perms.get("all") or perms.get(perm_key))


def ensure_role_permission_sync(db) -> None:
    if not (table_exists(db, "role_permissions") and table_exists(db, "permissions") and table_exists(db, "roles")):
        return

    roles = db.execute("SELECT id, permissions FROM roles").fetchall()
    for role in roles:
        sync_role_permissions_from_legacy_json(db, int(role["id"]), role["permissions"])

    if table_exists(db, "user_roles") and table_exists(db, "users"):
        users = db.execute("SELECT id, role_id FROM users WHERE role_id IS NOT NULL").fetchall()
        for user in users:
            sync_user_role_assignment(db, int(user["id"]), int(user["role_id"]))
