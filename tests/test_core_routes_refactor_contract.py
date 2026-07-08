import sqlite3

from flask import Flask

from modules.blueprints.core.routes import (
    _extract_comment_value,
    _parse_limit_offset_args,
    _table_exists,
)


def test_core_table_exists_helper_contract():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")

    assert _table_exists(db, "sample") is True
    assert _table_exists(db, "missing") is False


def test_parse_limit_offset_args_contract():
    app = Flask(__name__)
    with app.test_request_context("/x?limit=30&offset=12"):
        limit, offset = _parse_limit_offset_args(limit_default=100, limit_max=500)
        assert limit == 30
        assert offset == 12

    with app.test_request_context("/x?limit=9999&offset=-5"):
        limit, offset = _parse_limit_offset_args(limit_default=100, limit_max=500)
        assert limit == 500
        assert offset == 0


def test_extract_comment_value_prefers_form_then_json():
    app = Flask(__name__)

    with app.test_request_context("/x", method="POST", data={"comment": "from-form"}):
        assert _extract_comment_value() == "from-form"

    with app.test_request_context("/x", method="POST", json={"comment": "from-json"}):
        assert _extract_comment_value() == "from-json"
