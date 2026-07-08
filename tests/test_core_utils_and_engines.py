import sqlite3

from modules import approval_service, audit_service, execution_service, rbac_service
from modules.core_utils import json_safe_nullable, json_safe_text, table_exists
from modules.engines import (
    accounting_engine,
    audit_approval_engine,
    execution_engine,
    user_permissions_engine,
)


def test_core_utils_table_exists_and_json_helpers():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")

    assert table_exists(db, "sample") is True
    assert table_exists(db, "missing") is False

    assert json_safe_nullable(None) is None
    assert json_safe_nullable("raw") == "raw"
    assert json_safe_nullable({"x": 1}) == '{"x": 1}'

    class BadRepr:
        def __str__(self):
            return "bad"

    # Should never raise and always return JSON text.
    result = json_safe_text(BadRepr())
    assert isinstance(result, str)
    assert "raw" in result


def test_accounting_engine_helpers_are_backward_compatible():
    page, per_page, offset = accounting_engine.compute_pagination(-2, 20)
    assert page == 1
    assert per_page == 20
    assert offset == 0

    d_from, d_to = accounting_engine.parse_iso_date_range("2026-06-01", "2026-06-19")
    assert d_from == "2026-06-01"
    assert d_to == "2026-06-19"

    invalid_from, invalid_to = accounting_engine.parse_iso_date_range("bad", "date")
    assert len(invalid_from) == 10
    assert len(invalid_to) == 10


def test_engine_facades_export_existing_contracts():
    assert user_permissions_engine.user_has_perm is rbac_service.user_has_perm
    assert execution_engine.process_pending_queue is execution_service.process_pending_queue
    assert audit_approval_engine.approve_request is approval_service.approve_request
    assert audit_approval_engine.list_requests is approval_service.list_requests
    assert audit_approval_engine.get_request_by_id is approval_service.get_request_by_id
    assert audit_approval_engine.record_audit_event is audit_service.record_audit_event
