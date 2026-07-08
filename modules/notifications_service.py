"""modules/notifications_service.py — user notifications for governance events."""
from __future__ import annotations

from typing import Any, Iterable

from modules.core_utils import table_exists as db_table_exists


def _table_exists(db, table_name: str) -> bool:
    return db_table_exists(db, table_name)


def create_notification(
    db,
    *,
    user_id: int,
    notif_type: str,
    title: str,
    message: str,
    auto_commit: bool = True,
) -> int:
    if not _table_exists(db, "notifications"):
        return 0

    db.execute(
        """
        INSERT INTO notifications (user_id, type, title, message, is_read)
        VALUES (?, ?, ?, ?, 0)
        """,
        (int(user_id), str(notif_type), str(title), str(message)),
    )
    row = db.execute("SELECT last_insert_rowid()").fetchone()
    if auto_commit:
        db.commit()
    return int(row[0] if not isinstance(row, dict) else row["last_insert_rowid()"])


def create_notifications_for_users(
    db,
    *,
    user_ids: Iterable[int],
    notif_type: str,
    title: str,
    message: str,
    auto_commit: bool = True,
) -> int:
    created = 0
    for user_id in dict.fromkeys(int(uid) for uid in user_ids if uid is not None):
        if create_notification(
            db,
            user_id=user_id,
            notif_type=notif_type,
            title=title,
            message=message,
            auto_commit=False,
        ):
            created += 1
    if auto_commit and created:
        db.commit()
    return created


def list_notifications(db, *, user_id: int, unread_only: bool = False, limit: int = 100, offset: int = 0):
    if not _table_exists(db, "notifications"):
        return []
    where = ["user_id=?"]
    params: list[Any] = [int(user_id)]
    if unread_only:
        where.append("is_read=0")
    rows = db.execute(
        f"""
        SELECT id, user_id, type, title, message, is_read, created_at
        FROM notifications
        WHERE {' AND '.join(where)}
        ORDER BY created_at DESC, id DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params + [max(1, int(limit)), max(0, int(offset))]),
    ).fetchall()
    return [dict(r) for r in rows]


def count_unread_notifications(db, *, user_id: int) -> int:
    if not _table_exists(db, "notifications"):
        return 0
    row = db.execute(
        "SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0",
        (int(user_id),),
    ).fetchone()
    return int(row[0] if row else 0)


def mark_notification_read(db, *, user_id: int, notification_id: int) -> bool:
    if not _table_exists(db, "notifications"):
        return False
    cur = db.execute(
        "UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?",
        (int(notification_id), int(user_id)),
    )
    db.commit()
    return cur.rowcount > 0


def mark_all_notifications_read(db, *, user_id: int) -> int:
    if not _table_exists(db, "notifications"):
        return 0
    cur = db.execute(
        "UPDATE notifications SET is_read=1 WHERE user_id=? AND is_read=0",
        (int(user_id),),
    )
    db.commit()
    return int(cur.rowcount or 0)
