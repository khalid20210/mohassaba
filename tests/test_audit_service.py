import json
import sqlite3

from flask import Flask, g, session

from modules.audit_service import record_audit_event


def _make_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    return app


def _make_db_with_basic_audit_schema():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute(
        """
        CREATE TABLE audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER,
            user_id INTEGER,
            action TEXT,
            action_type TEXT,
            entity_type TEXT,
            entity_id INTEGER,
            old_value TEXT,
            new_value TEXT,
            before_data TEXT,
            after_data TEXT,
            status TEXT,
            ip_address TEXT,
            user_agent TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    return db


def _make_db_with_enhanced_schema():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute(
        """
        CREATE TABLE audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER,
            user_id INTEGER,
            action TEXT,
            new_value TEXT
        )
        """
    )
    db.execute(
        """
        CREATE TABLE enhanced_audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER,
            user_id INTEGER,
            session_id TEXT,
            action TEXT,
            resource_type TEXT,
            resource_id INTEGER,
            old_values TEXT,
            new_values TEXT,
            ip_address TEXT,
            user_agent TEXT,
            status TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    return db


def test_record_audit_event_writes_basic_table():
    app = _make_app()
    db = _make_db_with_basic_audit_schema()

    with app.test_request_context("/x", environ_base={"REMOTE_ADDR": "10.0.0.1"}):
        session["user_id"] = 55
        g.user = {"full_name": "Owner", "username": "owner", "role_name": "owner"}

        ok = record_audit_event(
            db,
            business_id=7,
            action="update_invoice",
            entity_type="invoice",
            entity_id=12,
            old_value={"total": 100},
            new_value={"total": 110},
        )

    assert ok is True
    row = db.execute("SELECT * FROM audit_logs").fetchone()
    assert row is not None
    assert row["business_id"] == 7
    assert row["user_id"] == 55
    assert row["action"] == "update_invoice"
    assert row["action_type"] == "update_invoice"
    assert row["before_data"] is not None
    assert row["after_data"] is not None
    assert row["status"] == "success"


def test_record_audit_event_embeds_reason_in_new_value():
    app = _make_app()
    db = _make_db_with_basic_audit_schema()

    with app.test_request_context("/x"):
        session["user_id"] = 9
        g.user = {"full_name": "A", "username": "a", "role_name": "owner"}

        ok = record_audit_event(
            db,
            business_id=2,
            action="price_change",
            entity_type="product",
            entity_id=4,
            old_value={"price": 50},
            new_value={"price": 75},
            reason="seasonal_update",
        )

    assert ok is True
    row = db.execute("SELECT new_value FROM audit_logs LIMIT 1").fetchone()
    payload = json.loads(row["new_value"])
    assert payload["reason"] == "seasonal_update"
    assert payload["value"]["price"] == 75


def test_record_audit_event_writes_enhanced_when_available():
    app = _make_app()
    db = _make_db_with_enhanced_schema()

    with app.test_request_context("/x"):
        session["user_id"] = 1
        session["session_id"] = "sess-123"
        g.user = {"full_name": "Owner", "username": "owner", "role_name": "owner"}

        ok = record_audit_event(
            db,
            business_id=11,
            action="delete_contact",
            entity_type="contact",
            entity_id=99,
            old_value={"is_active": 1},
            new_value={"is_active": 0},
            reason="duplicate_record",
        )

    assert ok is True
    legacy_count = db.execute("SELECT COUNT(*) AS c FROM audit_logs").fetchone()["c"]
    enhanced_count = db.execute("SELECT COUNT(*) AS c FROM enhanced_audit_logs").fetchone()["c"]
    assert legacy_count == 1
    assert enhanced_count == 1


def test_record_audit_event_accepts_failed_status():
    app = _make_app()
    db = _make_db_with_basic_audit_schema()

    with app.test_request_context("/x"):
        session["user_id"] = 7
        g.user = {"full_name": "Owner", "username": "owner", "role_name": "owner"}
        ok = record_audit_event(
            db,
            business_id=1,
            action="update_failed",
            entity_type="invoice",
            entity_id=1,
            old_value={"status": "draft"},
            new_value={"status": "pending"},
            status="failed",
        )

    assert ok is True
    row = db.execute("SELECT status, action_type FROM audit_logs ORDER BY id DESC LIMIT 1").fetchone()
    assert row["status"] == "failed"
    assert row["action_type"] == "update_failed"
