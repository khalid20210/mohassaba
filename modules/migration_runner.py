"""
modules/migration_runner.py
════════════════════════════════════════════════════════════════════
نظام تهجير قاعدة البيانات — بديل Flask-Migrate لـ raw SQLite

الفكرة:
  - كل ملف .sql في مجلد migrations/ يمثّل تغييراً على الـ Schema
  - يتم تشغيل كل ملف مرة واحدة فقط، ويُسجَّل في جدول _schema_migrations
  - عند إضافة ميزة جديدة (مثل المناديب والعمولات)، أنشئ ملف SQL جديداً فقط
  - البيانات القديمة تبقى سليمة — لا DROP، لا TRUNCATE

الاستخدام:
  from modules.migration_runner import run_migrations
  run_migrations(db_path)
════════════════════════════════════════════════════════════════════
"""
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


def run_migrations(db_path: Path) -> None:
    """تشغيل جميع ملفات SQL التي لم تُطبَّق بعد، بالترتيب الرقمي."""
    MIGRATIONS_DIR.mkdir(exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")

        # ── أنشئ جدول تتبع الـ migrations إذا لم يكن موجوداً ──
        conn.execute("""
            CREATE TABLE IF NOT EXISTS _schema_migrations (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                filename   TEXT    NOT NULL UNIQUE,
                applied_at TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.commit()

        # ── جمع الملفات المطبّقة مسبقاً ──
        applied = {
            row[0]
            for row in conn.execute("SELECT filename FROM _schema_migrations")
        }

        # ── ترتيب الملفات رقمياً: 001_*.sql < 002_*.sql < ... ──
        sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))

        pending = [f for f in sql_files if f.name not in applied]
        if not pending:
            logger.debug("✅ قاعدة البيانات محدّثة — لا توجد migrations معلقة")
            return

        for sql_file in pending:
            logger.info(f"⚙️  تطبيق migration: {sql_file.name}")
            sql = sql_file.read_text(encoding="utf-8")

            try:
                # نفّذ كل جملة SQL منفصلة (تجاهل الفارغة والتعليقات)
                skipped = 0
                for stmt in _split_statements(sql):
                    if not stmt:
                        continue
                    try:
                        conn.execute(stmt)
                    except Exception as stmt_err:
                        err_msg = str(stmt_err).lower()
                        normalized_stmt = stmt.strip().lower()
                        # تجاهل أخطاء التكرار الشائعة في ALTER TABLE/CREATE
                        if any(k in err_msg for k in (
                            "duplicate column", "already exists", "table already exists"
                        )):
                            skipped += 1
                            continue

                        # في قواعد قديمة قد لا توجد أعمدة لبعض الفهارس الجديدة
                        # نتجاوز فقط أخطاء no such column الخاصة بإنشاء الفهارس.
                        if "no such column" in err_msg and normalized_stmt.startswith("create index"):
                            skipped += 1
                            continue

                        # تجاهل أخطاء no such column في UPDATE لتوافق schema (عمود قديم غير موجود)
                        if "no such column" in err_msg and normalized_stmt.startswith("update "):
                            skipped += 1
                            continue

                        # تجاهل فهارس على جداول غير موجودة بعد (تُنشأ ديناميكياً)
                        if "no such table" in err_msg and normalized_stmt.startswith("create index"):
                            skipped += 1
                            continue

                        raise

                conn.execute(
                    "INSERT INTO _schema_migrations (filename) VALUES (?)",
                    (sql_file.name,),
                )
                conn.commit()
                if skipped:
                    logger.info(f"✅  تم: {sql_file.name} ({skipped} جملة متخطاة — مكررة)")
                else:
                    logger.info(f"✅  تم: {sql_file.name}")

            except Exception as e:
                conn.rollback()
                logger.error(f"❌  فشل migration {sql_file.name}: {e}")
                raise RuntimeError(
                    f"فشل في تطبيق migration '{sql_file.name}': {e}"
                ) from e

    finally:
        conn.close()


def _split_statements(sql: str) -> list[str]:
    """تقسيم نص SQL إلى جُمَل مستقلة، مع تجاهل التعليقات والفراغات."""
    stmts = []
    current: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or not stripped:
            continue
        current.append(line)
        if stripped.endswith(";"):
            stmts.append("\n".join(current).strip())
            current = []
    if current:
        joined = "\n".join(current).strip()
        if joined:
            stmts.append(joined)
    return stmts
