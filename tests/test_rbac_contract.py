import sqlite3
import shutil
from pathlib import Path

from modules.migration_runner import run_migrations
from modules.rbac_service import (
    get_effective_permissions,
    sync_role_permissions_from_legacy_json,
    sync_user_role_assignment,
    user_has_perm,
)


def test_rbac_normalized_contract_and_sync(tmp_path: Path):
    db_path = tmp_path / "rbac.db"
    shutil.copy2(Path("database/accounting_dev.db"), db_path)

    run_migrations(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    assert conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='permissions'").fetchone()
    assert conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='role_permissions'").fetchone()
    assert conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_roles'").fetchone()

    biz_id = conn.execute("SELECT business_id FROM users WHERE id=1").fetchone()[0]
    conn.execute(
        "INSERT INTO roles (business_id, name, permissions, is_system) VALUES (?, ?, ?, 0)",
        (biz_id, "RBAC Test", '{"sales":true}'),
    )
    role_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO users (business_id, role_id, username, password_hash) VALUES (?, ?, ?, ?)",
        (biz_id, role_id, "rbac_test_user", "x"),
    )
    user_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()

    sync_role_permissions_from_legacy_json(conn, int(role_id), '{"sales":true}')
    sync_user_role_assignment(conn, int(user_id), int(role_id))
    conn.commit()

    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    perms = get_effective_permissions(conn, user)
    assert perms.get("sales") is True
    assert user_has_perm(conn, user, "sales") is True
    assert user_has_perm(conn, user, "inventory") is False

    role_perm_count = conn.execute("SELECT COUNT(*) FROM role_permissions WHERE role_id=?", (role_id,)).fetchone()[0]
    assert role_perm_count == 1
    user_role_count = conn.execute("SELECT COUNT(*) FROM user_roles WHERE user_id=?", (user_id,)).fetchone()[0]
    assert user_role_count == 1
