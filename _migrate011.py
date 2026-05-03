"""
_migrate011.py — تطبيق migration 011 (v2.0 Engine)
يُشغَّل مرة واحدة بعد نشر التحديث

استخدام:
  python _migrate011.py
"""
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).parent
DB_PATH  = BASE_DIR / "database.db"
SQL_FILE = BASE_DIR / "migrations" / "011_v2_engine.sql"


def apply_migration():
    if not DB_PATH.exists():
        print(f"❌ قاعدة البيانات غير موجودة: {DB_PATH}")
        return

    sql = SQL_FILE.read_text(encoding="utf-8")

    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.executescript(sql)
        conn.commit()
        print("  ✓ تم تطبيق جميع الجداول والفهارس بنجاح")
    except sqlite3.OperationalError as e:
        err = str(e)
        if "already exists" in err or "duplicate column" in err:
            print(f"  ↩ (موجود مسبقاً): {e}")
        else:
            print(f"  ✕ خطأ: {e}")
    finally:
        conn.close()
    print(f"\n✅ اكتمل migration 011")


if __name__ == "__main__":
    print("🚀 تطبيق Migration 011 — جنان بيز v2.0 Engine\n")
    apply_migration()
