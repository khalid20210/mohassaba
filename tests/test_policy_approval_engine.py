import sqlite3

from flask import Flask, g, session

from modules.approval_service import (
    ensure_operation_or_create_request,
    approve_request,
    reject_request,
    list_requests,
    get_request_by_id,
)
from modules.policy_engine import ensure_default_policies, authorize_operation


def _app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    return app


def _db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
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
    db.execute(
        """
        CREATE TABLE approval_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            operation_key TEXT NOT NULL,
            action_type TEXT,
            entity_type TEXT,
            entity_id INTEGER,
            requested_by INTEGER,
            status TEXT NOT NULL DEFAULT 'pending',
            reason TEXT,
            payload_json TEXT,
            payload TEXT,
            required_approvals INTEGER NOT NULL DEFAULT 1,
            current_approvals INTEGER NOT NULL DEFAULT 0,
            requested_at TEXT DEFAULT (datetime('now')),
            resolved_at TEXT,
            resolved_by INTEGER,
            approved_by INTEGER,
            approved_at TEXT
        )
        """
    )
    db.execute(
        """
        CREATE TABLE approval_request_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            business_id INTEGER NOT NULL,
            approver_user_id INTEGER NOT NULL,
            decision TEXT NOT NULL,
            comment TEXT,
            decided_at TEXT DEFAULT (datetime('now')),
            UNIQUE(request_id, approver_user_id)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER,
            user_id INTEGER,
            action TEXT,
            entity_type TEXT,
            entity_id INTEGER,
            old_value TEXT,
            new_value TEXT,
            ip_address TEXT,
            user_agent TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    db.commit()
    return db


def test_default_policies_seeded_once():
    db = _db()
    ensure_default_policies(db, 1)
    ensure_default_policies(db, 1)
    count = db.execute("SELECT COUNT(*) AS c FROM operation_policies WHERE business_id=1").fetchone()["c"]
    assert count >= 4


def test_authorize_operation_requires_approval_for_non_owner():
    db = _db()
    ensure_default_policies(db, 1)

    user = {"id": 10, "permissions": '{"invoice_cancel": true}'}
    out = authorize_operation(
        db,
        business_id=1,
        user=user,
        operation_key="invoice.cancel.paid",
        default_permission_key="invoice_cancel",
    )
    assert out["allowed"] is False
    assert out["approval_required"] is True


def test_approval_request_flow_create_then_approve():
    app = _app()
    db = _db()
    ensure_default_policies(db, 1)

    non_owner = {"id": 77, "permissions": '{"invoice_cancel": true}', "username": "staff"}
    owner = {"id": 1, "permissions": '{"all": true}', "username": "owner"}

    with app.test_request_context("/approve", environ_base={"REMOTE_ADDR": "127.0.0.1"}):
        session["user_id"] = 77
        g.user = non_owner

        gate = ensure_operation_or_create_request(
            db,
            business_id=1,
            user=non_owner,
            operation_key="invoice.cancel.paid",
            default_permission_key="invoice_cancel",
            entity_type="invoice",
            entity_id=123,
            reason="test reason",
            payload={"invoice_number": "INV-1"},
        )

        assert gate["approval_required"] is True
        assert gate["request_id"] is not None

        session["user_id"] = 1
        g.user = owner
        approved = approve_request(
            db,
            business_id=1,
            request_id=int(gate["request_id"]),
            approver_user=owner,
            comment="approved by owner",
        )
        assert approved["ok"] is True
        assert approved["status"] == "approved"

    row = db.execute("SELECT status FROM approval_requests WHERE id=?", (int(gate["request_id"]),)).fetchone()
    assert row["status"] == "approved"

    row2 = db.execute("SELECT action_type, payload, approved_by, approved_at FROM approval_requests WHERE id=?", (int(gate["request_id"]),)).fetchone()
    assert row2["action_type"] == "invoice.cancel.paid"
    assert row2["payload"] is not None
    assert row2["approved_by"] == 1
    assert row2["approved_at"] is not None


def test_reject_request_sets_required_contract_fields():
    app = _app()
    db = _db()
    ensure_default_policies(db, 1)

    non_owner = {"id": 50, "permissions": '{"invoice_cancel": true}', "username": "staff"}
    owner = {"id": 1, "permissions": '{"all": true}', "username": "owner"}

    with app.test_request_context("/approve", environ_base={"REMOTE_ADDR": "127.0.0.1"}):
        session["user_id"] = 50
        g.user = non_owner
        gate = ensure_operation_or_create_request(
            db,
            business_id=1,
            user=non_owner,
            operation_key="invoice.cancel.paid",
            default_permission_key="invoice_cancel",
            entity_type="invoice",
            entity_id=321,
            reason="cancel",
            payload={"invoice_number": "INV-2"},
        )

        session["user_id"] = 1
        g.user = owner
        rejected = reject_request(
            db,
            business_id=1,
            request_id=int(gate["request_id"]),
            approver_user=owner,
            comment="rejected by owner",
        )
        assert rejected["ok"] is True
        assert rejected["status"] == "rejected"

    row = db.execute("SELECT status, approved_by, approved_at FROM approval_requests WHERE id=?", (int(gate["request_id"]),)).fetchone()
    assert row["status"] == "rejected"
    assert row["approved_by"] == 1
    assert row["approved_at"] is not None


def test_list_and_get_requests_return_stage1_contract_fields():
    app = _app()
    db = _db()
    ensure_default_policies(db, 1)
    non_owner = {"id": 99, "permissions": '{"invoice_cancel": true}', "username": "staff"}

    with app.test_request_context("/approve", environ_base={"REMOTE_ADDR": "127.0.0.1"}):
        session["user_id"] = 99
        g.user = non_owner
        gate = ensure_operation_or_create_request(
            db,
            business_id=1,
            user=non_owner,
            operation_key="invoice.cancel.paid",
            default_permission_key="invoice_cancel",
            entity_type="invoice",
            entity_id=777,
            reason="need approval",
            payload={"x": 1},
        )

    rid = int(gate["request_id"])
    items = list_requests(db, 1, status="pending", limit=10, offset=0)
    assert len(items) >= 1
    first = items[0]
    for key in ("id", "action_type", "entity_type", "entity_id", "requested_by", "status", "approved_by", "approved_at", "payload"):
        assert key in first

    item = get_request_by_id(db, 1, rid)
    assert item is not None
    assert item["id"] == rid
    assert item["action_type"] == "invoice.cancel.paid"
