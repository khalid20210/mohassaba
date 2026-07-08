"""
modules/audit_service.py
خدمة تدقيق موحدة: تجمع بين audit_logs التقليدي و enhanced_audit_logs
مع توافق خلفي ودعم before/after + reason.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from flask import g, request, session


def _json_dumps_safe(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _table_columns(db, table_name: str) -> set[str]:
    try:
        rows = db.execute(f"PRAGMA table_info({table_name})").fetchall()
        cols: set[str] = set()
        for row in rows:
            # sqlite row: (cid, name, type, notnull, dflt_value, pk)
            if isinstance(row, dict):
                name = row.get("name")
            else:
                name = row[1] if len(row) > 1 else None
            if name:
                cols.add(str(name))
        return cols
    except Exception:
        return set()


def _insert_dynamic(db, table_name: str, payload: Dict[str, Any], columns: set[str]) -> bool:
    used = {k: v for k, v in payload.items() if k in columns}
    if not used:
        return False

    ordered_keys = sorted(used.keys())
    placeholders = ", ".join(["?"] * len(ordered_keys))
    col_sql = ", ".join(ordered_keys)
    values = [used[k] for k in ordered_keys]

    db.execute(
        f"INSERT INTO {table_name} ({col_sql}) VALUES ({placeholders})",
        tuple(values),
    )
    return True


def record_audit_event(
    db,
    *,
    business_id: int,
    action: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    old_value: Any = None,
    new_value: Any = None,
    reason: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    status: str = "success",
) -> bool:
    """
    يسجل حدث تدقيق بشكل موحد.
    - يكتب إلى audit_logs إن وجد
    - ويحاول الكتابة إلى enhanced_audit_logs إن وجد
    - لا يرمي exception حتى لا يعطل تدفق العمل
    """
    try:
        user_id = session.get("user_id")
        actor_name = ""
        actor_role = ""
        if getattr(g, "user", None):
            actor_name = g.user.get("full_name") or g.user.get("username", "")
            actor_role = g.user.get("role_name", "")

        ip_address = request.remote_addr or ""
        user_agent = (request.user_agent.string or "")[:255]

        status_norm = str(status or "success").strip().lower()
        if status_norm not in {"success", "failed"}:
            status_norm = "failed"

        old_value_json = _json_dumps_safe(old_value)
        new_payload = new_value
        if reason:
            wrapped: Dict[str, Any] = {"value": new_value, "reason": reason}
            if metadata:
                wrapped["metadata"] = metadata
            new_payload = wrapped
        elif metadata:
            new_payload = {"value": new_value, "metadata": metadata}
        new_value_json = _json_dumps_safe(new_payload)

        # 1) جدول audit_logs التقليدي
        audit_cols = _table_columns(db, "audit_logs")
        if audit_cols:
            payload = {
                "business_id": business_id,
                "user_id": user_id,
                "actor_name": actor_name,
                "actor_role": actor_role,
                "action": action,
                "action_type": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "old_value": old_value_json,
                "new_value": new_value_json,
                "before_data": old_value_json,
                "after_data": new_value_json,
                "status": status_norm,
                "ip_address": ip_address,
                "user_agent": user_agent,
            }
            _insert_dynamic(db, "audit_logs", payload, audit_cols)

        # 2) جدول enhanced_audit_logs (إن وجد)
        enhanced_cols = _table_columns(db, "enhanced_audit_logs")
        if enhanced_cols:
            enhanced_payload = {
                "business_id": business_id,
                "user_id": user_id or 0,
                "session_id": session.get("session_id") if session else "",
                "action": action,
                "resource_type": entity_type,
                "resource_id": entity_id,
                "old_values": old_value_json,
                "new_values": new_value_json,
                "ip_address": ip_address or "0.0.0.0",
                "user_agent": user_agent,
                "status": "success",
            }
            _insert_dynamic(db, "enhanced_audit_logs", enhanced_payload, enhanced_cols)

        db.commit()
        return True
    except Exception:
        return False
