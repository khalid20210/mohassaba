"""Architecture guard for blueprint import boundaries.

This script enforces that blueprints import domain operations from engines,
not directly from low-level services.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys


BANNED_IMPORTS = (
    "from modules.approval_service",
    "from modules.execution_service",
    "from modules.rbac_service",
)

BLUEPRINTS_ROOT = Path("modules") / "blueprints"


def _iter_python_files(root: Path):
    for path in root.rglob("*.py"):
        if path.is_file():
            yield path


def main() -> int:
    if not BLUEPRINTS_ROOT.exists():
        print("[architecture-guard] blueprints root not found, skipping")
        return 0

    violations: list[str] = []
    for py_file in _iter_python_files(BLUEPRINTS_ROOT):
        text = py_file.read_text(encoding="utf-8", errors="replace")
        for pattern in BANNED_IMPORTS:
            if re.search(rf"^\s*{re.escape(pattern)}", text, re.MULTILINE):
                violations.append(f"{py_file.as_posix()}: banned import '{pattern}'")

    if violations:
        print("[architecture-guard] Found architecture violations:")
        for item in violations:
            print(f" - {item}")
        print("Use modules.engines.* as boundary imports from blueprints.")
        return 1

    print("[architecture-guard] OK: no banned direct service imports in blueprints.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
