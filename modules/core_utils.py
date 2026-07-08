"""Common low-level helpers used across service modules.

This module is intentionally small and side-effect free to keep services
decoupled and avoid duplicated utility code.
"""

from __future__ import annotations

import json
from typing import Any, Optional


def table_exists(db, table_name: str) -> bool:
    row = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def json_safe_nullable(value: Any) -> Optional[str]:
    """Serialize value while preserving None and plain strings as-is."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def json_safe_text(value: Any) -> str:
    """Serialize value into a JSON text with a robust fallback shape."""
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return json.dumps({"raw": str(value)}, ensure_ascii=False)
