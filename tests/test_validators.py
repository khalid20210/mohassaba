from datetime import datetime, timedelta

import pytest

from modules.validators import (
    V,
    _ValidationAbort,
    validate,
    validate_or_abort,
)


def test_required_and_optional_rules():
    assert V.required(" value ", "name") == " value "
    assert V.optional(None, "name") is None

    with pytest.raises(Exception):
        V.required(None, "name")

    with pytest.raises(Exception):
        V.required("   ", "name")


def test_string_rules_and_sanitization():
    assert V.str_strip("  hi  ", "field") == "hi"
    assert V.str_max(5)("  abc  ", "field") == "abc"
    assert V.str_min(3)("  abc  ", "field") == "abc"
    assert V.safe_text("hello", "field") == "hello"
    assert V.no_html("safe", "field") == "safe"

    with pytest.raises(Exception):
        V.str_max(3)("abcd", "field")

    with pytest.raises(Exception):
        V.str_min(4)("abc", "field")

    with pytest.raises(Exception):
        V.no_html("<b>x</b>", "field")

    with pytest.raises(Exception):
        V.safe_text("DROP TABLE users", "field")


def test_numeric_date_and_format_rules():
    assert V.positive_number("2.5", "price") == 2.5
    assert V.positive_int("4", "qty") == 4
    assert V.num_range(1, 5)("3", "score") == 3
    assert V.date_str("2026-01-01", "date") == "2026-01-01"
    assert V.email("USER@EXAMPLE.COM", "email") == "user@example.com"
    assert V.saudi_phone("05 1234-5678", "phone") == "0512345678"
    assert V.vat_number("312345678901234", "vat") == "312345678901234"
    assert V.cr_number("1234567890", "cr") == "1234567890"
    assert V.payment_method("Credit", "method") == "credit"
    assert V.one_of("a", "b")("a", "kind") == "a"
    assert V.non_empty_list([1], "items") == [1]
    assert V.list_max(2)([1, 2], "items") == [1, 2]
    assert V.not_future(datetime.now().strftime("%Y-%m-%d"), "date")

    with pytest.raises(Exception):
        V.positive_number("abc", "price")
    with pytest.raises(Exception):
        V.positive_int("0", "qty")
    with pytest.raises(Exception):
        V.num_range(1, 5)("9", "score")
    with pytest.raises(Exception):
        V.date_str("2026/01/01", "date")
    with pytest.raises(Exception):
        V.not_future((datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"), "date")
    with pytest.raises(Exception):
        V.email("bad-email", "email")
    with pytest.raises(Exception):
        V.saudi_phone("12345", "phone")
    with pytest.raises(Exception):
        V.vat_number("123", "vat")
    with pytest.raises(Exception):
        V.cr_number("123", "cr")
    with pytest.raises(Exception):
        V.payment_method("cash2", "method")
    with pytest.raises(Exception):
        V.one_of("a", "b")("c", "kind")
    with pytest.raises(Exception):
        V.non_empty_list([], "items")
    with pytest.raises(Exception):
        V.list_max(1)([1, 2], "items")


def test_validate_handles_optional_and_collects_errors():
    schema = {
        "name": [V.required, V.str_max(10)],
        "email": [V.optional, V.email],
        "qty": [V.required, V.positive_int],
    }
    cleaned, errors = validate(
        {"name": "  Alice  ", "email": "", "qty": "0"},
        schema,
    )

    assert cleaned["name"] == "Alice"
    assert cleaned["email"] == ""
    assert "qty" in errors


def test_validate_or_abort_raises_on_invalid_payload():
    schema = {"name": [V.required]}

    with pytest.raises(_ValidationAbort) as exc:
        validate_or_abort({"name": ""}, schema)

    assert "name" in exc.value.errors
