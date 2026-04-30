"""
modules/rls.py — Row-Level Security (عزل البيانات على مستوى التطبيق)

يضمن أن كل وصول لقاعدة البيانات مقيّد بـ business_id الحالي.
يعمل كـ wrapper فوق SQLite بدلاً من PostgreSQL RLS.
"""
import logging
from flask import session

from .extensions import get_db

_log = logging.getLogger(__name__)

# الجداول التي تحتوي على business_id وتخضع للـ RLS
_RLS_TABLES = frozenset({
    "accounts", "journal_entries", "journal_entry_lines",
    "tax_settings", "settings", "product_categories",
    "products", "warehouses", "stock", "stock_movements",
    "invoices", "invoice_lines", "contacts",
    "zatca_queue", "usage_logs",
})

# الجداول التي لا تحتوي business_id (مشتركة بين الجميع)
_SHARED_TABLES = frozenset({
    "businesses", "roles", "users",
})


class RLSViolation(PermissionError):
    """تُرفع عند محاولة الوصول لبيانات خارج نطاق business_id"""
    pass


class SafeDB:
    """
    Wrapper حول اتصال SQLite يُجبر كل query على تضمين business_id.

    الاستخدام العادي:
        db = get_safe_db()
        rows = db.select("invoices", "status=?", ("paid",))
        db.insert("contacts", {"name": "أحمد", "phone": "05x"})
        db.update("products", {"sale_price": 99}, "id=?", (5,))
        db.delete("contacts", "id=?", (3,))
        db.commit()

    للاستعلامات الخام (موروثة فقط):
        db.raw("SELECT * FROM invoices WHERE business_id=? AND id=?", (biz_id, inv_id))
    """

    __slots__ = ("_db", "_biz_id")

    def __init__(self, db, business_id: int):
        object.__setattr__(self, "_db",     db)
        object.__setattr__(self, "_biz_id", int(business_id))

    # ── SELECT ────────────────────────────────────────────────────────────────
    def select(self, table: str, conditions: str = "", params=(),
               columns: str = "*", extra: str = ""):
        """
        SELECT مع حقن business_id تلقائياً.
        extra: ORDER BY / LIMIT / OFFSET
        """
        self._assert_rls(table)
        if conditions:
            sql    = f"SELECT {columns} FROM {table} WHERE business_id=? AND ({conditions}) {extra}"
            args   = (self._biz_id,) + tuple(params)
        else:
            sql    = f"SELECT {columns} FROM {table} WHERE business_id=? {extra}"
            args   = (self._biz_id,)
        return self._db.execute(sql, args).fetchall()

    def select_one(self, table: str, conditions: str = "", params=(),
                   columns: str = "*"):
        self._assert_rls(table)
        if conditions:
            sql  = f"SELECT {columns} FROM {table} WHERE business_id=? AND ({conditions}) LIMIT 1"
            args = (self._biz_id,) + tuple(params)
        else:
            sql  = f"SELECT {columns} FROM {table} WHERE business_id=? LIMIT 1"
            args = (self._biz_id,)
        return self._db.execute(sql, args).fetchone()

    def count(self, table: str, conditions: str = "", params=()):
        self._assert_rls(table)
        if conditions:
            sql  = f"SELECT COUNT(*) FROM {table} WHERE business_id=? AND ({conditions})"
            args = (self._biz_id,) + tuple(params)
        else:
            sql  = f"SELECT COUNT(*) FROM {table} WHERE business_id=?"
            args = (self._biz_id,)
        return self._db.execute(sql, args).fetchone()[0]

    # ── INSERT ────────────────────────────────────────────────────────────────
    def insert(self, table: str, data: dict) -> int:
        """INSERT مع حقن business_id تلقائياً — يُعيد last_insert_rowid"""
        self._assert_rls(table)
        row           = dict(data)
        row["business_id"] = self._biz_id
        cols          = ", ".join(row.keys())
        placeholders  = ", ".join("?" * len(row))
        self._db.execute(
            f"INSERT INTO {table} ({cols}) VALUES ({placeholders})",
            list(row.values())
        )
        return self._db.execute("SELECT last_insert_rowid()").fetchone()[0]

    # ── UPDATE ────────────────────────────────────────────────────────────────
    def update(self, table: str, data: dict, conditions: str, params=()):
        """UPDATE محمي — لا يُعدّل سجلات خارج business_id الحالي"""
        self._assert_rls(table)
        if not conditions:
            raise RLSViolation("UPDATE يتطلب شرط WHERE صريح")
        set_clause = ", ".join(f"{k}=?" for k in data.keys())
        args       = list(data.values()) + [self._biz_id] + list(params)
        self._db.execute(
            f"UPDATE {table} SET {set_clause} WHERE business_id=? AND ({conditions})",
            args
        )

    # ── DELETE ────────────────────────────────────────────────────────────────
    def delete(self, table: str, conditions: str, params=()):
        """DELETE محمي — لا يحذف سجلات خارج business_id الحالي"""
        self._assert_rls(table)
        if not conditions:
            raise RLSViolation("DELETE يتطلب شرط WHERE صريح")
        args = (self._biz_id,) + tuple(params)
        self._db.execute(
            f"DELETE FROM {table} WHERE business_id=? AND ({conditions})",
            args
        )

    # ── مساعدات ───────────────────────────────────────────────────────────────
    def owns(self, table: str, record_id: int) -> bool:
        """تحقق أن سجلاً معيّناً ينتمي للـ business الحالي"""
        self._assert_rls(table)
        row = self._db.execute(
            f"SELECT id FROM {table} WHERE id=? AND business_id=?",
            (int(record_id), self._biz_id)
        ).fetchone()
        return row is not None

    def raw(self, sql: str, params=()):
        """
        استعلام خام — للحالات الموروثة فقط.
        تحذير: لا يُطبّق RLS تلقائياً.
        """
        _log.warning(f"RLS.raw() used — ensure business_id is included: {sql[:80]}")
        return self._db.execute(sql, params)

    def commit(self):
        self._db.commit()

    def rollback(self):
        self._db.rollback()

    @property
    def business_id(self) -> int:
        return self._biz_id

    # ── Internal ───────────────────────────────────────────────────────────────
    def _assert_rls(self, table: str):
        if table not in _RLS_TABLES:
            if table in _SHARED_TABLES:
                raise RLSViolation(
                    f"الجدول '{table}' مشترك — استخدم get_db() مباشرة"
                )
            raise RLSViolation(
                f"الجدول '{table}' غير مسجّل في RLS — أضفه إلى _RLS_TABLES"
            )


def get_safe_db() -> SafeDB:
    """
    الحصول على اتصال DB محمي بـ RLS.
    يُرفع خطأ إذا لم يكن هناك business_id في الجلسة.
    """
    biz_id = session.get("business_id")
    if not biz_id:
        raise RLSViolation("لا يوجد business_id في الجلسة — RLS يرفض الوصول")
    return SafeDB(get_db(), int(biz_id))


def verify_ownership(table: str, record_id: int) -> bool:
    """
    دالة مساعدة للتحقق السريع من ملكية سجل.
    تُستخدم في نهايات الـ API قبل أي عملية حساسة.
    """
    try:
        db = get_safe_db()
        return db.owns(table, record_id)
    except RLSViolation:
        return False
