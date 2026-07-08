import sqlite3

from flask import Flask, g, session

from modules.approval_service import ensure_operation_or_create_request, approve_request
from modules.execution_service import list_execution_queue, process_pending_queue
from modules.policy_engine import ensure_default_policies


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
        CREATE TABLE execution_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            approval_request_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            executed_at TEXT,
            result TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(approval_request_id)
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


def test_approve_enqueue_then_process_execution_queue():
    app = _app()
    db = _db()
    ensure_default_policies(db, 1)

    staff = {"id": 12, "permissions": '{"invoice_cancel": true}', "username": "staff"}
    owner = {"id": 1, "permissions": '{"all": true}', "username": "owner"}

    with app.test_request_context("/x", environ_base={"REMOTE_ADDR": "127.0.0.1"}):
        session["user_id"] = 12
        g.user = staff

        gate = ensure_operation_or_create_request(
            db,
            business_id=1,
            user=staff,
            operation_key="invoice.cancel.paid",
            default_permission_key="invoice_cancel",
            entity_type="invoice",
            entity_id=101,
            reason="needs owner approval",
            payload={"invoice_number": "INV-101"},
        )
        assert gate["approval_required"] is True

        session["user_id"] = 1
        g.user = owner

        out = approve_request(
            db,
            business_id=1,
            request_id=int(gate["request_id"]),
            approver_user=owner,
            comment="ok",
        )
        assert out["ok"] is True
        assert out["status"] == "approved"

    queued = list_execution_queue(db, status="pending", limit=10, offset=0)
    assert len(queued) == 1
    assert queued[0]["approval_request_id"] == int(gate["request_id"])

    processed = process_pending_queue(db, limit=10)
    assert processed["processed"] == 1
    assert processed["executed"] == 1

    rows = list_execution_queue(db, status="executed", limit=10, offset=0)
    assert len(rows) == 1
    assert rows[0]["status"] == "executed"
    assert rows[0]["result"] is not None
