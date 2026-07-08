"""Runtime bridge between owner robot settings and real business events."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from modules.notifications_service import create_notifications_for_users


def _as_dict(row):
    return dict(row) if row is not None and not isinstance(row, dict) else row


def _ensure_runtime_tables(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS business_robot_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            robot_code TEXT NOT NULL,
            owner_enabled INTEGER NOT NULL DEFAULT 0,
            preset_mode TEXT NOT NULL DEFAULT 'balanced',
            operation_mode TEXT NOT NULL DEFAULT 'assistive',
            alert_invoice_threshold INTEGER NOT NULL DEFAULT 6,
            warning_level TEXT NOT NULL DEFAULT 'medium',
            check_frequency TEXT NOT NULL DEFAULT 'daily',
            notify_channel TEXT NOT NULL DEFAULT 'in_app',
            activation_state TEXT NOT NULL DEFAULT 'sandbox',
            updated_by INTEGER,
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(business_id, robot_code)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_robot_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            robot_code TEXT NOT NULL UNIQUE,
            robot_name TEXT NOT NULL,
            scope_type TEXT NOT NULL DEFAULT 'shared',
            activity_sector TEXT,
            risk_level TEXT NOT NULL DEFAULT 'medium',
            strict_mode INTEGER NOT NULL DEFAULT 1,
            requires_confirm INTEGER NOT NULL DEFAULT 1,
            rollout_state TEXT NOT NULL DEFAULT 'off',
            is_active INTEGER NOT NULL DEFAULT 0,
            description TEXT,
            created_by INTEGER,
            updated_by INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS robot_runtime_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            robot_code TEXT NOT NULL,
            event_type TEXT NOT NULL,
            event_bucket TEXT,
            payload_json TEXT,
            created_by INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(business_id, robot_code, event_type, event_bucket)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS robot_runtime_dispatches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            robot_code TEXT NOT NULL,
            event_type TEXT NOT NULL,
            notify_channel TEXT NOT NULL DEFAULT 'in_app',
            attempted_count INTEGER NOT NULL DEFAULT 0,
            delivered_count INTEGER NOT NULL DEFAULT 0,
            delivery_status TEXT NOT NULL DEFAULT 'queued',
            details_json TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    try:
        cols = db.execute("PRAGMA table_info(business_robot_settings)").fetchall()
        names = {str(c[1] if not isinstance(c, dict) else c.get('name') or '') for c in cols or []}
        if "activation_state" not in names:
            db.execute("ALTER TABLE business_robot_settings ADD COLUMN activation_state TEXT NOT NULL DEFAULT 'sandbox'")
    except Exception:
        pass


def _normalize_notify_channel(raw: str) -> str:
    channel = (raw or "in_app").strip().lower()
    if channel not in {"in_app", "email", "sms", "whatsapp"}:
        return "in_app"
    return channel


def _dispatch_robot_notification(
    db,
    *,
    business_id: int,
    robot_code: str,
    event_type: str,
    notify_channel: str,
    recipients: list[int],
    title: str,
    message: str,
    auto_commit: bool,
) -> int:
    channel = _normalize_notify_channel(notify_channel)
    attempted = len(recipients or [])
    delivered = 0
    status = "skipped"

    if attempted > 0:
        notif_type = "robot_threshold_alert"
        body = message

        # Channels other than in_app are prepared with graceful fallback
        # until outbound providers are configured.
        if channel != "in_app":
            label = channel.upper()
            body = f"[{label}] {message}"
            status = "fallback_in_app"
        else:
            status = "delivered_in_app"

        delivered = create_notifications_for_users(
            db,
            user_ids=recipients,
            notif_type=notif_type,
            title=title,
            message=body,
            auto_commit=auto_commit,
        )

    db.execute(
        """
        INSERT INTO robot_runtime_dispatches
            (business_id, robot_code, event_type, notify_channel,
             attempted_count, delivered_count, delivery_status, details_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (
            int(business_id),
            str(robot_code or ""),
            str(event_type or ""),
            channel,
            attempted,
            int(delivered or 0),
            status,
            json.dumps(
                {
                    "channel": channel,
                    "fallback_to_in_app": channel != "in_app",
                    "attempted": attempted,
                    "delivered": int(delivered or 0),
                },
                ensure_ascii=False,
            ),
        ),
    )
    return int(delivered or 0)


def _is_invoice_relevant_robot(robot_code: str) -> bool:
    code = (robot_code or "").strip().lower()
    if not code:
        return False
    keys = (
        "invoice", "sales", "cash", "collection", "receivable", "ar", "vat", "zatca",
        "billing", "revenue", "pos",
    )
    return any(k in code for k in keys)


def _window_start(now: datetime, frequency: str) -> datetime:
    f = (frequency or "daily").strip().lower()
    if f == "realtime":
        return now - timedelta(hours=1)
    if f == "weekly":
        return now - timedelta(days=7)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _bucket_key(now: datetime, frequency: str) -> str:
    f = (frequency or "daily").strip().lower()
    if f == "realtime":
        return now.strftime("%Y-%m-%d %H")
    if f == "weekly":
        y, w, _ = now.isocalendar()
        return f"{y}-W{w:02d}"
    return now.strftime("%Y-%m-%d")


def _owner_user_ids(db, business_id: int) -> list[int]:
    rows = db.execute(
        "SELECT id, permissions FROM users WHERE business_id=? AND is_active=1",
        (int(business_id),),
    ).fetchall()
    recipients: list[int] = []
    for row in rows or []:
        item = _as_dict(row) or {}
        uid = int(item.get("id") or 0)
        if uid <= 0:
            continue
        raw = item.get("permissions")
        try:
            perms = json.loads(raw or "{}") if raw else {}
        except Exception:
            perms = {}
        if bool(perms.get("all")):
            recipients.append(uid)
    return recipients


def process_invoice_robots(
    db,
    *,
    business_id: int,
    invoice_id: int,
    invoice_total: float,
    actor_user_id: int | None = None,
    source_channel: str = "invoices",
    auto_commit: bool = True,
) -> dict:
    """Evaluate enabled owner robots after invoice creation and emit alerts."""
    _ensure_runtime_tables(db)

    now = datetime.now()
    robots = db.execute(
        """
         SELECT s.robot_code, s.owner_enabled, s.operation_mode, s.alert_invoice_threshold,
                         s.warning_level, s.check_frequency, s.notify_channel, s.activation_state,
               c.robot_name, c.rollout_state, c.is_active
        FROM business_robot_settings s
        JOIN platform_robot_catalog c ON c.robot_code = s.robot_code
        WHERE s.business_id=? AND s.owner_enabled=1
              AND c.is_active=1
              AND LOWER(COALESCE(c.rollout_state, 'off')) IN ('pilot', 'on')
        """,
        (int(business_id),),
    ).fetchall()

    processed = 0
    triggered = 0
    notified = 0

    recipients = _owner_user_ids(db, int(business_id))
    if actor_user_id and int(actor_user_id) > 0 and int(actor_user_id) not in recipients:
        recipients.append(int(actor_user_id))

    for row in robots or []:
        robot = _as_dict(row) or {}
        code = str(robot.get("robot_code") or "").strip()
        if not _is_invoice_relevant_robot(code):
            continue

        activation_state = str(robot.get("activation_state") or "sandbox").strip().lower()
        if activation_state == "off":
            continue

        processed += 1
        freq = str(robot.get("check_frequency") or "daily").strip().lower()
        threshold = int(robot.get("alert_invoice_threshold") or 6)
        threshold = max(1, threshold)

        since = _window_start(now, freq).strftime("%Y-%m-%d %H:%M:%S")
        cnt_row = db.execute(
            """
            SELECT COUNT(*) AS c
            FROM invoices
            WHERE business_id=?
              AND invoice_type='sale'
                            AND status IN ('pending', 'paid', 'partial', 'unpaid')
              AND datetime(COALESCE(created_at, invoice_date)) >= datetime(?)
            """,
            (int(business_id), since),
        ).fetchone()
        invoices_count = int((_as_dict(cnt_row) or {}).get("c") or (cnt_row[0] if cnt_row else 0) or 0)
        if invoices_count < threshold:
            continue

        bucket = _bucket_key(now, freq)
        event_type = f"invoice_threshold_{freq}"
        payload = {
            "invoice_id": int(invoice_id),
            "invoice_total": float(invoice_total or 0),
            "source_channel": source_channel,
            "invoices_count": invoices_count,
            "threshold": threshold,
            "frequency": freq,
            "operation_mode": str(robot.get("operation_mode") or "assistive"),
            "warning_level": str(robot.get("warning_level") or "medium"),
            "notify_channel": _normalize_notify_channel(str(robot.get("notify_channel") or "in_app")),
            "activation_state": activation_state,
        }

        inserted = False
        try:
            db.execute(
                """
                INSERT INTO robot_runtime_events
                    (business_id, robot_code, event_type, event_bucket, payload_json, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    int(business_id),
                    code,
                    event_type,
                    bucket,
                    json.dumps(payload, ensure_ascii=False),
                    int(actor_user_id or 0) or None,
                ),
            )
            inserted = True
        except Exception:
            inserted = False

        if not inserted:
            continue

        triggered += 1
        if activation_state == "sandbox":
            db.execute(
                """
                INSERT INTO robot_runtime_dispatches
                    (business_id, robot_code, event_type, notify_channel,
                     attempted_count, delivered_count, delivery_status, details_json, created_at)
                VALUES (?, ?, ?, ?, 0, 0, 'sandbox_readonly', ?, datetime('now'))
                """,
                (
                    int(business_id),
                    code,
                    event_type,
                    str(robot.get("notify_channel") or "in_app"),
                    json.dumps({"activation_state": activation_state, "note": "read_only_observation"}, ensure_ascii=False),
                ),
            )
            continue

        title = f"تنبيه روبوت: {robot.get('robot_name') or code}"
        message = (
            f"وصلت فواتير البيع إلى {invoices_count} خلال ({freq}) "
            f"وتجاوزت عتبة {threshold}. "
            f"آخر فاتورة رقم #{invoice_id} بقيمة {float(invoice_total or 0):.2f}."
        )
        notified += _dispatch_robot_notification(
            db,
            business_id=int(business_id),
            robot_code=code,
            event_type=event_type,
            notify_channel=str(robot.get("notify_channel") or "in_app"),
            recipients=recipients,
            title=title,
            message=message,
            auto_commit=auto_commit,
        )

    if auto_commit:
        db.commit()
    return {
        "processed": processed,
        "triggered": triggered,
        "notified": notified,
    }
