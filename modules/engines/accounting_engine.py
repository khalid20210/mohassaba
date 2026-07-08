"""Accounting Engine facade and pure helpers.

No behavior changes: helpers only centralize parsing logic already used
in accounting routes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Tuple


def parse_iso_date_range(date_from: str, date_to: str) -> Tuple[str, str]:
    """Validate date range in %Y-%m-%d format with current defaults fallback."""
    default_from = datetime.now().strftime("%Y-%m-01")
    default_to = datetime.now().strftime("%Y-%m-%d")
    try:
        datetime.strptime(date_from, "%Y-%m-%d")
        datetime.strptime(date_to, "%Y-%m-%d")
    except ValueError:
        return default_from, default_to
    return date_from, date_to


def compute_pagination(page: int, per_page: int) -> Tuple[int, int, int]:
    """Return normalized page, per_page and offset values."""
    normalized_page = max(1, int(page or 1))
    normalized_per_page = max(1, int(per_page or 1))
    offset = (normalized_page - 1) * normalized_per_page
    return normalized_page, normalized_per_page, offset
