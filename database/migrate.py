"""
migrate.py — مشغّل ملفات الترحيل لقاعدة البيانات
=====================================================
يطبّق ملفات SQL من مجلد migrations/ بالترتيب الأبجدي،
ويتتبع ما تم تطبيقه في جدول _migrations داخل قاعدة البيانات.

الاستخدام:
    python migrate.py           # تطبيق جميع الترحيلات غير المُطبَّقة
    python migrate.py --status  # عرض حالة الترحيلات فقط
"""

import sqlite3
import sys
from pathlib import Path

DB_PATH        = Path(__file__).parent / "accounting.db"
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


# ─── مساعد: فحص وجود عمود ────────────────────────────────────────────────────
def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


# ─── مساعد: تنفيذ عبارة واحدة مع تجاهل الأخطاء المتوقعة ─────────────────────
def exec_stmt(conn: sqlite3.Connection, stmt: str) -> None:
    """
    ينفّذ عبارة SQL واحدة.
    يتجاهل:
      - duplicate column name  (العمود موجود بالفعل)
      - already exists         (الجدول/الفهرس/الـ View موجود)
    """
    stmt = stmt.strip()
    if not stmt or stmt.startswith("--"):
        return
    try:
        conn.execute(stmt)
    except sqlite3.OperationalError as e:
        err = str(e).lower()
        # أخطاء مقبولة (idempotent)
        ignorable = (
            "duplicate column name",
            "already exists",
            "no such table: sqlite_sequence",
        )
        if any(ig in err for ig in ignorable):
            return  # تجاهل
        raise


# ─── تهيئة جدول تتبع الترحيلات ───────────────────────────────────────────────
def init_tracking(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            filename    TEXT    NOT NULL UNIQUE,
            applied_at  TEXT    DEFAULT (datetime('now'))
        )
    """)
    conn.commit()


# ─── تطبيق ملف ترحيل واحد ────────────────────────────────────────────────────
def apply_migration(conn: sqlite3.Connection, filepath: Path) -> None:
    sql = filepath.read_text(encoding="utf-8")

    # تقسيم العبارات على أساس ";" مع الحفاظ على التعليقات
    statements = []
    current = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue          # تخطي التعليقات
        current.append(line)
        if stripped.endswith(";"):
            stmt = "\n".join(current).strip().rstrip(";")
            if stmt:
                statements.append(stmt)
            current = []

    conn.execute("PRAGMA foreign_keys = OFF")
    for stmt in statements:
        exec_stmt(conn, stmt)
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute(
        "INSERT OR IGNORE INTO _migrations (filename) VALUES (?)",
        (filepath.name,)
    )
    conn.commit()


# ─── البرنامج الرئيسي ─────────────────────────────────────────────────────────
def run_migrations(status_only: bool = False) -> None:
    if not DB_PATH.exists():
        print(f"✗ لم يتم العثور على قاعدة البيانات: {DB_PATH}")
        print("  شغّل import_products.py أولاً لإنشاء قاعدة البيانات.")
        return

    conn = sqlite3.connect(DB_PATH)
    init_tracking(conn)

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))

    if not migration_files:
        print("لا توجد ملفات ترحيل في مجلد migrations/")
        conn.close()
        return

    print("=" * 54)
    print("  حالة ملفات الترحيل")
    print("=" * 54)

    applied = {
        row[0] for row in
        conn.execute("SELECT filename FROM _migrations").fetchall()
    }

    pending = []
    for mf in migration_files:
        is_applied = mf.name in applied
        status = "✓ مُطبَّق" if is_applied else "○ معلّق"
        print(f"  {status}  {mf.name}")
        if not is_applied:
            pending.append(mf)

    print()

    if status_only:
        conn.close()
        return

    if not pending:
        print("✓ جميع الترحيلات مُطبَّقة. لا يوجد شيء جديد.")
        conn.close()
        return

    print(f"سيتم تطبيق {len(pending)} ترحيل(ات):")
    for mf in pending:
        print(f"  → {mf.name}")
    print()

    for mf in pending:
        try:
            apply_migration(conn, mf)
            print(f"  ✓ {mf.name} — تم بنجاح")
        except Exception as e:
            print(f"  ✗ {mf.name} — خطأ: {e}")
            conn.close()
            return

    conn.close()
    print()
    print("✓ اكتملت جميع الترحيلات.")


# ─── عرض ملخص ما بعد الترحيل ─────────────────────────────────────────────────
def show_summary() -> None:
    conn = sqlite3.connect(DB_PATH)
    print()
    print("=" * 54)
    print("  ملخص قاعدة البيانات")
    print("=" * 54)

    # المنشآت
    cur = conn.execute("SELECT id, name, industry_type FROM businesses")
    print("المنشآت (Tenants):")
    for r in cur.fetchall():
        print(f"  [{r[0]}] {r[1]}  |  النشاط: {r[2] or 'غير محدد'}")

    # الجداول وأعدادها
    tables = [
        ("products",        "المنتجات"),
        ("accounts",        "الحسابات"),
        ("product_categories", "التصنيفات"),
        ("warehouses",      "المستودعات"),
        ("users",           "المستخدمون"),
        ("roles",           "الأدوار"),
        ("journal_entries", "قيود اليومية"),
        ("contacts",        "جهات الاتصال"),
    ]
    print()
    print("الجداول:")
    for tbl, label in tables:
        try:
            cnt = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            print(f"  {label:20} : {cnt}")
        except sqlite3.OperationalError:
            print(f"  {label:20} : (غير موجود)")

    # التحقق من tenant_id view
    view_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='view' AND name='tenants'"
    ).fetchone()
    print()
    print("Views:")
    print(f"  tenants  : {'✓ موجود' if view_exists else '✗ غير موجود'}")

    conn.close()


if __name__ == "__main__":
    status_only = "--status" in sys.argv
    run_migrations(status_only)
    if not status_only and DB_PATH.exists():
        show_summary()
