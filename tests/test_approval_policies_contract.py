import sqlite3

from modules.policy_engine import ensure_default_policies, get_operation_policy, authorize_operation


def _db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute(
        """
        CREATE TABLE approval_policies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            entity_type TEXT NOT NULL,
            action_type TEXT NOT NULL,
            requires_approval INTEGER NOT NULL DEFAULT 0,
            conditions TEXT,
            role_based_rules TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(business_id, entity_type, action_type)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE operation_policies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            operation_key TEXT NOT NULL,
            permission_key TEXT,
            requires_approval INTEGER NOT NULL DEFAULT 0,
            min_approvals INTEGER NOT NULL DEFAULT 1,
            owner_only INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            updated_by INTEGER,
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(business_id, operation_key)
        )
        """
    )
    db.commit()
    return db


def test_default_seed_writes_approval_policies():
    db = _db()
    ensure_default_policies(db, 1)
    row = db.execute(
        "SELECT COUNT(*) AS c FROM approval_policies WHERE business_id=1"
    ).fetchone()
    assert row["c"] >= 4


def test_get_operation_policy_reads_new_contract():
    db = _db()
    db.execute(
        """
        INSERT INTO approval_policies (
            business_id, entity_type, action_type,
            requires_approval, conditions, role_based_rules, is_active
        ) VALUES (1, 'invoice', 'cancel.paid', 1, '{"min_approvals":2}', '{"permission_key":"invoice_cancel","owner_only":false}', 1)
        """
    )
    db.commit()

    p = get_operation_policy(db, 1, "invoice.cancel.paid", default_permission_key="invoice_cancel")
    assert p["requires_approval"] is True
    assert p["min_approvals"] == 2
    assert p["permission_key"] == "invoice_cancel"
    assert p["entity_type"] == "invoice"
    assert p["action_type"] == "cancel.paid"


def test_authorize_operation_uses_approval_policies_rules():
    db = _db()
    db.execute(
        """
        INSERT INTO approval_policies (
            business_id, entity_type, action_type,
            requires_approval, conditions, role_based_rules, is_active
        ) VALUES (1, 'invoice', 'cancel.paid', 1, '{"min_approvals":1}', '{"permission_key":"invoice_cancel","owner_only":false}', 1)
        """
    )
    db.commit()

    staff = {"id": 9, "permissions": '{"invoice_cancel": true}'}
    out = authorize_operation(
        db,
        business_id=1,
        user=staff,
        operation_key="invoice.cancel.paid",
        default_permission_key="invoice_cancel",
    )
    assert out["allowed"] is False
    assert out["approval_required"] is True
