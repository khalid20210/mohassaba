"""
ترحيل أكواد النشاط القديمة (العامة) إلى أكواد تفصيلية.

الاستخدام:
  - معاينة فقط (افتراضي):
      .venv\Scripts\python.exe _migrate_legacy_industry_types.py

  - تطبيق فعلي:
      .venv\Scripts\python.exe _migrate_legacy_industry_types.py --apply
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime

from modules.config import DB_PATH, INDUSTRY_TYPES


LEGACY_TO_DETAILED: dict[str, str] = {
    # أكواد legacy عامة
    "retail": "retail_fnb_supermarket",
    "wholesale": "wholesale_fnb_general",
    "restaurant": "food_restaurant",
    "cafe": "food_cafe",
    "coffeeshop": "food_coffeeshop",
    "services": "services_consulting",
    "medical": "medical_complex",

    # أكواد قديمة غير قياسية ظهرت في بعض البيانات
    "retail_electronics": "retail_electronics_mobile",
    "retail_beauty_cosmetics": "retail_health_cosmetics",
    "wholesale_beauty_cosmetics": "wholesale_health_cosmetics",
    "wholesale_fashion_accessories": "wholesale_fashion_bags",
}


def _ensure_audit_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS industry_type_migration_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            business_name TEXT,
            old_industry_type TEXT NOT NULL,
            new_industry_type TEXT NOT NULL,
            migrated_at TEXT NOT NULL,
            migrated_by TEXT NOT NULL
        )
        """
    )


def _fetch_candidates(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    keys = tuple(LEGACY_TO_DETAILED.keys())
    placeholders = ",".join(["?"] * len(keys))
    sql = f"""
        SELECT id, name, industry_type
        FROM businesses
        WHERE industry_type IN ({placeholders})
        ORDER BY id
    """
    return conn.execute(sql, keys).fetchall()


def _validate_mapping() -> None:
    known = {k for k, _ in INDUSTRY_TYPES}
    unknown_targets = [v for v in LEGACY_TO_DETAILED.values() if v not in known]
    if unknown_targets:
        raise RuntimeError(
            "أكواد هدف غير موجودة في INDUSTRY_TYPES: " + ", ".join(sorted(set(unknown_targets)))
        )


def run(apply_changes: bool = False) -> int:
    _validate_mapping()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        _ensure_audit_table(conn)
        rows = _fetch_candidates(conn)

        if not rows:
            print("✅ لا توجد أكواد قديمة تحتاج ترحيل.")
            return 0

        print(f"📌 عدد المنشآت المرشحة للترحيل: {len(rows)}")
        for row in rows:
            old_code = (row["industry_type"] or "").strip()
            new_code = LEGACY_TO_DETAILED.get(old_code)
            print(f"- ID={row['id']} | {row['name']} | {old_code} -> {new_code}")

        if not apply_changes:
            print("\nℹ️ وضع المعاينة فقط. لإجراء الترحيل فعلياً استخدم --apply")
            return 0

        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        actor = "_migrate_legacy_industry_types.py"

        migrated_count = 0
        for row in rows:
            business_id = int(row["id"])
            business_name = row["name"]
            old_code = (row["industry_type"] or "").strip()
            new_code = LEGACY_TO_DETAILED[old_code]

            if old_code == new_code:
                continue

            conn.execute(
                "UPDATE businesses SET industry_type=?, updated_at=datetime('now') WHERE id=?",
                (new_code, business_id),
            )
            conn.execute(
                """
                INSERT INTO industry_type_migration_audit
                (business_id, business_name, old_industry_type, new_industry_type, migrated_at, migrated_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (business_id, business_name, old_code, new_code, now, actor),
            )
            migrated_count += 1

        conn.commit()
        print(f"\n✅ تم ترحيل {migrated_count} منشأة بنجاح.")
        return 0

    except Exception as exc:
        conn.rollback()
        print(f"❌ فشل الترحيل: {exc}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    apply_flag = "--apply" in sys.argv
    raise SystemExit(run(apply_changes=apply_flag))
