"""
modules/db_adapter.py
طبقة abstraction لقاعدة البيانات: تسمح بالانتقال من SQLite → PostgreSQL بدون تغيير كود Business Logic
"""
import sqlite3
from typing import Optional

from flask import g

from modules.config import (
    DB_PATH,
    SQLITE_BUSY_TIMEOUT_MS,
    SQLITE_CACHE_SIZE,
    SQLITE_MMAP_SIZE,
    SQLITE_WAL_AUTOCHECKPOINT,
)


class DatabaseConnection:
    """واجهة موحدة للاتصال بقاعدة البيانات (SQLite الآن، PostgreSQL لاحقاً)."""
    
    def __init__(self, connection):
        self.conn = connection
        self._backend = self._detect_backend()
    
    def _detect_backend(self) -> str:
        """اكتشف نوع DB من connection object."""
        if isinstance(self.conn, sqlite3.Connection):
            return "sqlite"
        # في المستقبل: psycopg2.connection → "postgresql"
        return "sqlite"
    
    def execute(self, query: str, params: tuple = ()):
        """تنفيذ استعلام مع تسجيل الأداء."""
        from modules.observability import perf_tracker
        import time
        
        start = time.time()
        try:
            cursor = self.conn.execute(query, params)
            duration_ms = (time.time() - start) * 1000
            
            # تسجيل الأداء
            result_count = len(cursor.fetchall()) if hasattr(cursor, 'fetchall') else 0
            perf_tracker.track_db_query(query, duration_ms, params, result_count)
            
            return cursor
        except Exception as e:
            duration_ms = (time.time() - start) * 1000
            from modules.observability import perf_tracker as pt
            pt.track_error("DB_ERROR", str(e), {
                "query_first_80": query[:80],
                "duration_ms": duration_ms,
            })
            raise
    
    def fetchone(self, cursor):
        """جلب صف واحد (موحد بين الـ backends)."""
        return cursor.fetchone()
    
    def fetchall(self, cursor):
        """جلب جميع الصفوف (موحد بين الـ backends)."""
        return cursor.fetchall()
    
    def commit(self):
        """حفظ التغييرات."""
        self.conn.commit()
    
    def rollback(self):
        """إلغاء التغييرات."""
        self.conn.rollback()
    
    def close(self):
        """إغلاق الاتصال."""
        self.conn.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()


def get_db_adapter() -> DatabaseConnection:
    """الحصول على اتصال قاعدة البيانات الموحد."""
    if "db_adapter" not in g:
        conn = sqlite3.connect(
            str(DB_PATH),
            timeout=max(1, SQLITE_BUSY_TIMEOUT_MS / 1000),
            check_same_thread=False,   # ضروري لـ Waitress multi-thread
        )
        conn.row_factory = sqlite3.Row

        # إعدادات تزيد throughput في بيئة الضغط العالي
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute(f"PRAGMA cache_size = {SQLITE_CACHE_SIZE}")
        conn.execute(f"PRAGMA mmap_size = {SQLITE_MMAP_SIZE}")
        conn.execute("PRAGMA temp_store = MEMORY")
        conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
        conn.execute(f"PRAGMA wal_autocheckpoint = {SQLITE_WAL_AUTOCHECKPOINT}")
        conn.execute("PRAGMA page_size = 4096")

        g.db_adapter = DatabaseConnection(conn)

    return g.db_adapter


def close_db_adapter(exc=None):
    """إغلاق اتصال قاعدة البيانات."""
    db = g.pop("db_adapter", None)
    if db is not None:
        db.close()


# للتوافق الخلفي — الدالة get_db تُرجع sqlite3.Connection مباشرة
def get_db() -> sqlite3.Connection:
    """الدالة القديمة للتوافق مع الكود الموجود."""
    adapter = get_db_adapter()
    return adapter.conn
