from __future__ import annotations

import json
from typing import Any

from modules.core_utils import table_exists as db_table_exists


DEFAULT_OWNER_POLICIES: dict[str, Any] = {
    "pos_cancel_daily_threshold": 3,
    "inventory_damage_requires_owner": 1,
    "payroll_manual_edit_requires_owner": 1,
    "journal_posted_requires_owner": 1,
    "robot_default_activation_state": "sandbox",
    "robot_urgent_channel": "whatsapp",
}


def _table_exists(db, table_name: str) -> bool:
    return db_table_exists(db, table_name)


def _column_exists(db, table_name: str, column_name: str) -> bool:
    try:
        rows = db.execute(f"PRAGMA table_info({table_name})").fetchall()
    except Exception:
        return False

    for row in rows or []:
        if isinstance(row, dict):
            if str(row.get("name") or "") == column_name:
                return True
        elif len(row) > 1 and str(row[1] or "") == column_name:
            return True
    return False


def ensure_sovereign_tables(db) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS owner_security_policies (
            business_id INTEGER NOT NULL,
            policy_key TEXT NOT NULL,
            policy_value TEXT,
            updated_by INTEGER,
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (business_id, policy_key)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS owner_action_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            request_type TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id INTEGER,
            requested_by INTEGER,
            status TEXT NOT NULL DEFAULT 'pending',
            reason TEXT NOT NULL,
            payload_json TEXT,
            owner_note TEXT,
            reviewed_by INTEGER,
            reviewed_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_owner_action_requests_lookup ON owner_action_requests(business_id, request_type, status, created_at DESC)"
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS owner_impact_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            action_key TEXT NOT NULL,
            entity_type TEXT,
            entity_id INTEGER,
            actor_user_id INTEGER,
            summary TEXT NOT NULL,
            reason TEXT,
            protected_amount REAL NOT NULL DEFAULT 0,
            payload_json TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_owner_impact_logs_biz ON owner_impact_logs(business_id, created_at DESC)"
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS pos_cashier_locks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            lock_reason TEXT NOT NULL,
            trigger_count INTEGER NOT NULL DEFAULT 0,
            source_entity_type TEXT,
            source_entity_id INTEGER,
            status TEXT NOT NULL DEFAULT 'active',
            locked_at TEXT NOT NULL DEFAULT (datetime('now')),
            released_at TEXT,
            released_by INTEGER,
            release_note TEXT
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_pos_cashier_locks_active ON pos_cashier_locks(business_id, user_id, status, locked_at DESC)"
    )

    if _table_exists(db, "business_robot_settings") and not _column_exists(db, "business_robot_settings", "activation_state"):
        db.execute("ALTER TABLE business_robot_settings ADD COLUMN activation_state TEXT NOT NULL DEFAULT 'sandbox'")


def ensure_default_owner_policies(db, business_id: int) -> None:
    for key, value in DEFAULT_OWNER_POLICIES.items():
        db.execute(
            """
            INSERT INTO owner_security_policies (business_id, policy_key, policy_value, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(business_id, policy_key) DO NOTHING
            """,
            (int(business_id), str(key), json.dumps(value, ensure_ascii=False)),
        )


def get_owner_policy_map(db, business_id: int) -> dict[str, Any]:
    ensure_sovereign_tables(db)
    ensure_default_owner_policies(db, business_id)
    rows = db.execute(
        "SELECT policy_key, policy_value FROM owner_security_policies WHERE business_id=?",
        (int(business_id),),
    ).fetchall()
    out: dict[str, Any] = {}
    for row in rows or []:
        item = dict(row) if not isinstance(row, dict) else row
        key = str(item.get("policy_key") or "")
        raw = item.get("policy_value")
        try:
            out[key] = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            out[key] = raw
    for key, value in DEFAULT_OWNER_POLICIES.items():
        out.setdefault(key, value)
    return out


def get_owner_policy_int(db, business_id: int, policy_key: str, default: int) -> int:
    value = get_owner_policy_map(db, business_id).get(policy_key, default)
    try:
        return int(float(value))
    except Exception:
        return default


def get_owner_policy_bool(db, business_id: int, policy_key: str, default: bool) -> bool:
    value = get_owner_policy_map(db, business_id).get(policy_key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    raw = str(value or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def set_owner_policy(db, business_id: int, policy_key: str, value: Any, updated_by: int | None = None) -> None:
    ensure_sovereign_tables(db)
    db.execute(
        """
        INSERT INTO owner_security_policies (business_id, policy_key, policy_value, updated_by, updated_at)
        VALUES (?, ?, ?, ?, datetime('now'))
        ON CONFLICT(business_id, policy_key) DO UPDATE SET
            policy_value=excluded.policy_value,
            updated_by=excluded.updated_by,
            updated_at=datetime('now')
        """,
        (int(business_id), str(policy_key), json.dumps(value, ensure_ascii=False), updated_by),
    )


def log_owner_impact(
    db,
    *,
    business_id: int,
    category: str,
    action_key: str,
    summary: str,
    reason: str = "",
    entity_type: str | None = None,
    entity_id: int | None = None,
    actor_user_id: int | None = None,
    protected_amount: float = 0.0,
    payload: dict[str, Any] | None = None,
) -> None:
    ensure_sovereign_tables(db)
    db.execute(
        """
        INSERT INTO owner_impact_logs
            (business_id, category, action_key, entity_type, entity_id,
             actor_user_id, summary, reason, protected_amount, payload_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(business_id),
            str(category or "general"),
            str(action_key or "unknown"),
            entity_type,
            entity_id,
            actor_user_id,
            str(summary or ""),
            str(reason or ""),
            float(protected_amount or 0),
            json.dumps(payload or {}, ensure_ascii=False),
        ),
    )


def create_owner_action_request(
    db,
    *,
    business_id: int,
    request_type: str,
    entity_type: str,
    entity_id: int | None,
    requested_by: int | None,
    reason: str,
    payload: dict[str, Any] | None = None,
) -> int:
    ensure_sovereign_tables(db)
    row = db.execute(
        """
        INSERT INTO owner_action_requests
            (business_id, request_type, entity_type, entity_id, requested_by, reason, payload_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(business_id),
            str(request_type or "manual_review"),
            str(entity_type or "unknown"),
            entity_id,
            requested_by,
            str(reason or "").strip()[:800],
            json.dumps(payload or {}, ensure_ascii=False),
        ),
    )
    return int(row.lastrowid or 0)


def get_active_cashier_lock(db, business_id: int, user_id: int) -> dict[str, Any] | None:
    ensure_sovereign_tables(db)
    row = db.execute(
        """
        SELECT * FROM pos_cashier_locks
        WHERE business_id=? AND user_id=? AND status='active'
        ORDER BY id DESC LIMIT 1
        """,
        (int(business_id), int(user_id)),
    ).fetchone()
    return dict(row) if row and not isinstance(row, dict) else row


def release_cashier_lock(
    db,
    *,
    business_id: int,
    lock_id: int,
    released_by: int | None,
    release_note: str = "",
) -> bool:
    ensure_sovereign_tables(db)
    row = db.execute(
        "SELECT id FROM pos_cashier_locks WHERE id=? AND business_id=? AND status='active' LIMIT 1",
        (int(lock_id), int(business_id)),
    ).fetchone()
    if not row:
        return False
    db.execute(
        """
        UPDATE pos_cashier_locks
        SET status='released', released_at=datetime('now'), released_by=?, release_note=?
        WHERE id=? AND business_id=?
        """,
        (released_by, str(release_note or "")[:500], int(lock_id), int(business_id)),
    )
    return True


def enforce_cashier_cancel_lock(
    db,
    *,
    business_id: int,
    user_id: int | None,
    invoice_id: int,
    invoice_number: str,
    invoice_total: float,
    reason: str,
) -> dict[str, Any]:
    if not user_id or int(user_id) <= 0:
        return {"locked": False, "cancel_count": 0, "threshold": 0}

    ensure_sovereign_tables(db)
    threshold = max(1, get_owner_policy_int(db, int(business_id), "pos_cancel_daily_threshold", 3))

    requests_row = db.execute(
        """
        SELECT COUNT(*) AS c
        FROM invoice_cancel_requests
        WHERE business_id=? AND requested_by=?
          AND datetime(created_at) >= datetime('now', '-1 day')
        """,
        (int(business_id), int(user_id)),
    ).fetchone()
    cancelled_row = db.execute(
        """
        SELECT COUNT(*) AS c
        FROM invoices
        WHERE business_id=? AND cancelled_by=?
          AND datetime(COALESCE(cancelled_at, created_at)) >= datetime('now', '-1 day')
        """,
        (int(business_id), int(user_id)),
    ).fetchone()

    requests_count = int((requests_row[0] if requests_row and not isinstance(requests_row, dict) else (requests_row or {}).get("c") or 0) or 0)
    cancelled_count = int((cancelled_row[0] if cancelled_row and not isinstance(cancelled_row, dict) else (cancelled_row or {}).get("c") or 0) or 0)
    cancel_count = requests_count + cancelled_count

    active_lock = get_active_cashier_lock(db, int(business_id), int(user_id))
    if active_lock:
        return {
            "locked": True,
            "cancel_count": cancel_count,
            "threshold": threshold,
            "lock_id": int(active_lock.get("id") or 0),
        }

    if cancel_count < threshold:
        return {"locked": False, "cancel_count": cancel_count, "threshold": threshold}

    lock_reason = f"تجاوز حد إلغاء الفواتير اليومي ({cancel_count}/{threshold})"
    row = db.execute(
        """
        INSERT INTO pos_cashier_locks
            (business_id, user_id, lock_reason, trigger_count, source_entity_type, source_entity_id, status)
        VALUES (?, ?, ?, ?, 'invoice', ?, 'active')
        """,
        (int(business_id), int(user_id), lock_reason, cancel_count, int(invoice_id)),
    )
    lock_id = int(row.lastrowid or 0)

    log_owner_impact(
        db,
        business_id=int(business_id),
        category="anti_fraud",
        action_key="pos.cashier_locked_after_cancels",
        summary=f"تم تجميد الكاشير بعد تجاوز حد الإلغاء اليومي عند الفاتورة {invoice_number}",
        reason=reason,
        entity_type="invoice",
        entity_id=int(invoice_id),
        actor_user_id=int(user_id),
        protected_amount=float(invoice_total or 0),
        payload={
            "cancel_count_24h": cancel_count,
            "threshold": threshold,
            "invoice_number": invoice_number,
            "lock_id": lock_id,
        },
    )

    return {"locked": True, "cancel_count": cancel_count, "threshold": threshold, "lock_id": lock_id}