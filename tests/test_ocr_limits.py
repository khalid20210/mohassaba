import sqlite3

import pytest
from flask import Flask, session

import modules.ocr_limits as ocr_limits


@pytest.fixture()
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE settings (business_id INTEGER, key TEXT, value TEXT)")
    conn.execute("CREATE TABLE businesses (id INTEGER PRIMARY KEY, plan TEXT)")
    ocr_limits.init_usage_logs(conn)
    try:
        yield conn
    finally:
        conn.close()


def test_get_plan_prefers_settings_then_businesses_then_default(db):
    db.execute("INSERT INTO businesses (id, plan) VALUES (?, ?)", (1, "pro"))
    db.execute(
        "INSERT INTO settings (business_id, key, value) VALUES (?, ?, ?)",
        (1, "subscription_plan", "starter"),
    )
    db.commit()
    assert ocr_limits.get_plan(db, 1) == "starter"

    db.execute("DELETE FROM settings WHERE business_id=1")
    db.commit()
    assert ocr_limits.get_plan(db, 1) == "pro"
    assert ocr_limits.get_plan(db, 99) == ocr_limits.DEFAULT_PLAN


def test_monthly_usage_and_log_usage(db):
    assert ocr_limits.get_monthly_usage(db, 1) == 0

    ocr_limits.log_ocr_usage(db, 1, feature="ocr_ai", units=3)
    assert ocr_limits.get_monthly_usage(db, 1) == 3


def test_check_ocr_limit_success_and_failure(db):
    db.execute(
        "INSERT INTO settings (business_id, key, value) VALUES (?, ?, ?)",
        (1, "subscription_plan", "free"),
    )
    db.commit()

    used, limit = ocr_limits.check_ocr_limit(db, 1, units=1)
    assert used == 0
    assert limit == ocr_limits.PLAN_LIMITS["free"]

    ocr_limits.log_ocr_usage(db, 1, feature="ocr_ai", units=10)
    with pytest.raises(ocr_limits.OCRLimitExceeded):
        ocr_limits.check_ocr_limit(db, 1, units=1)


def test_get_usage_summary_includes_percentages_and_features(db):
    db.execute(
        "INSERT INTO settings (business_id, key, value) VALUES (?, ?, ?)",
        (1, "subscription_plan", "starter"),
    )
    db.commit()
    ocr_limits.log_ocr_usage(db, 1, feature="ocr_ai", units=20)
    ocr_limits.log_ocr_usage(db, 1, feature="ocr_local", units=5)

    summary = ocr_limits.get_usage_summary(db, 1)
    assert summary["plan"] == "starter"
    assert summary["ocr_ai_used"] == 20
    assert summary["ocr_local_used"] == 5
    assert summary["ocr_ai_limit"] == ocr_limits.PLAN_LIMITS["starter"]
    assert summary["ocr_ai_pct"] == 20.0


def test_ocr_protected_returns_401_without_business_in_session(db, monkeypatch):
    app = Flask(__name__)
    app.secret_key = "test"
    monkeypatch.setattr("modules.extensions.get_db", lambda: db)

    @ocr_limits.ocr_protected
    def protected_handler():
        return "ok"

    with app.test_request_context("/"):
        response, status = protected_handler()
        assert status == 401
        assert response.get_json()["success"] is False


def test_ocr_protected_returns_429_on_limit_exceeded(db, monkeypatch):
    app = Flask(__name__)
    app.secret_key = "test"
    monkeypatch.setattr("modules.extensions.get_db", lambda: db)
    db.execute(
        "INSERT INTO settings (business_id, key, value) VALUES (?, ?, ?)",
        (1, "subscription_plan", "free"),
    )
    db.commit()
    ocr_limits.log_ocr_usage(db, 1, feature="ocr_ai", units=10)

    @ocr_limits.ocr_protected
    def protected_handler():
        return "ok"

    with app.test_request_context("/"):
        session["business_id"] = 1
        response, status = protected_handler()
        payload = response.get_json()
        assert status == 429
        assert payload["code"] == "OCR_LIMIT_EXCEEDED"
        assert payload["plan"] == "free"


def test_ocr_protected_runs_wrapped_function_and_logs_usage(db, monkeypatch):
    app = Flask(__name__)
    app.secret_key = "test"
    monkeypatch.setattr("modules.extensions.get_db", lambda: db)
    db.execute(
        "INSERT INTO settings (business_id, key, value) VALUES (?, ?, ?)",
        (1, "subscription_plan", "starter"),
    )
    db.commit()

    @ocr_limits.ocr_protected
    def protected_handler():
        return "done"

    with app.test_request_context("/"):
        session["business_id"] = 1
        assert protected_handler() == "done"

    assert ocr_limits.get_monthly_usage(db, 1) == 1
