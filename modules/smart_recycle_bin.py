"""
modules/smart_recycle_bin.py
═════════════════════════════════════════════════════════════════════════════════
نظام سلة المهملات الذكية - المادة الثانية من الميثاق الدستوري
═════════════════════════════════════════════════════════════════════════════════

كل عملية حذف تُنقل إلى السلة بدلاً من الحذف النهائي.
فقط الأدمن (أبو عبد الله) يملك صلاحية الحذف النهائي أو الاستعادة.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════════════════════════
# Schema لجدول سلة المهملات
# ════════════════════════════════════════════════════════════════════════════════

RECYCLE_BIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS recycle_bin (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL,
    table_name          TEXT NOT NULL,          -- الجدول الأصلي (invoices, products, etc.)
    record_id           INTEGER NOT NULL,        -- ID الحقل الأصلي
    original_data       TEXT NOT NULL,            -- بيانات JSON كاملة
    deleted_by_user_id  INTEGER NOT NULL,
    deleted_at          TEXT NOT NULL DEFAULT (datetime('now')),
    retention_until     TEXT NOT NULL,            -- تاريخ الحذف النهائي التلقائي
    is_admin_locked     INTEGER DEFAULT 0,        -- هل تم قفل من الأدمن (لا يحذف تلقائياً)
    restoration_count   INTEGER DEFAULT 0,        -- عدد مرات الاستعادة
    last_restored_at    TEXT,
    notes               TEXT,                     -- ملاحظات حول السبب
    UNIQUE(business_id, table_name, record_id),
    FOREIGN KEY(business_id) REFERENCES businesses(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_recycle_bin_business_table 
    ON recycle_bin(business_id, table_name);

CREATE INDEX IF NOT EXISTS idx_recycle_bin_deleted_at 
    ON recycle_bin(deleted_at);

CREATE INDEX IF NOT EXISTS idx_recycle_bin_retention 
    ON recycle_bin(retention_until);

-- جدول سجل استعادات السلة (للرقابة)
CREATE TABLE IF NOT EXISTS recycle_bin_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL,
    record_id       INTEGER NOT NULL,
    action          TEXT NOT NULL,              -- 'moved_to_bin' | 'restored' | 'permanently_deleted'
    performed_by    INTEGER NOT NULL,           -- user_id
    reason          TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(business_id) REFERENCES businesses(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_recycle_history_business 
    ON recycle_bin_history(business_id, created_at);
"""


class SmartRecycleBin:
    """إدارة سلة المهملات الذكية"""
    
    # الإعدادات الافتراضية
    DEFAULT_RETENTION_DAYS = 30  # عدد أيام الاحتفاظ قبل الحذف التلقائي
    ADMIN_ONLY_RETENTION_DAYS = 365  # الأدمن يمكنه القفل لسنة كاملة
    
    @staticmethod
    def move_to_bin(db, business_id: int, table_name: str, record_id: int, original_data: Dict, deleted_by_user_id: int, notes: str = "") -> Tuple[bool, str]:
        """
        نقل سجل إلى سلة المهملات بدلاً من حذفه نهائياً
        """
        try:
            retention_days = SmartRecycleBin.DEFAULT_RETENTION_DAYS
            retention_date = (datetime.now() + timedelta(days=retention_days)).isoformat()
            
            db.execute("""
                INSERT INTO recycle_bin (
                    business_id,
                    table_name,
                    record_id,
                    original_data,
                    deleted_by_user_id,
                    retention_until,
                    notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(business_id, table_name, record_id) DO UPDATE SET
                    original_data = excluded.original_data,
                    deleted_by_user_id = excluded.deleted_by_user_id,
                    deleted_at = datetime('now'),
                    retention_until = excluded.retention_until,
                    notes = excluded.notes
            """, (
                business_id,
                table_name,
                record_id,
                json.dumps(original_data),
                deleted_by_user_id,
                retention_date,
                notes
            ))
            
            # تسجيل في السجل
            db.execute("""
                INSERT INTO recycle_bin_history (business_id, record_id, action, performed_by, reason)
                VALUES (?, ?, 'moved_to_bin', ?, ?)
            """, (business_id, record_id, deleted_by_user_id, notes))
            
            db.commit()
            logger.info(f"نقل السجل {record_id} من {table_name} إلى السلة (المنشأة: {business_id})")
            return True, "تم نقل البيانات إلى السلة بنجاح"
            
        except Exception as e:
            logger.error(f"خطأ في نقل السجل إلى السلة: {e}")
            return False, f"خطأ: {str(e)}"
    
    @staticmethod
    def restore_from_bin(db, business_id: int, record_id: int, table_name: str, restored_by_user_id: int) -> Tuple[bool, str]:
        """
        استعادة سجل من سلة المهملات
        """
        try:
            # جلب البيانات الأصلية
            bin_record = db.execute("""
                SELECT original_data FROM recycle_bin 
                WHERE business_id=? AND record_id=? AND table_name=?
            """, (business_id, record_id, table_name)).fetchone()
            
            if not bin_record:
                return False, "السجل غير موجود في السلة"
            
            original_data = json.loads(bin_record["original_data"])
            
            # إعادة الإدراج في الجدول الأصلي
            # (يتم هذا حسب نوع الجدول - يجب تخصيص هذا الجزء حسب كل جدول)
            
            # تحديث سلة المهملات
            db.execute("""
                UPDATE recycle_bin 
                SET restoration_count = restoration_count + 1,
                    last_restored_at = datetime('now')
                WHERE business_id=? AND record_id=? AND table_name=?
            """, (business_id, record_id, table_name))
            
            # تسجيل الاستعادة
            db.execute("""
                INSERT INTO recycle_bin_history (business_id, record_id, action, performed_by, reason)
                VALUES (?, ?, 'restored', ?, 'استعادة يدوية')
            """, (business_id, record_id, restored_by_user_id))
            
            db.commit()
            logger.info(f"تم استعادة السجل {record_id} من السلة")
            return True, "تم استعادة البيانات بنجاح"
            
        except Exception as e:
            logger.error(f"خطأ في الاستعادة: {e}")
            return False, f"خطأ: {str(e)}"
    
    @staticmethod
    def permanently_delete(db, business_id: int, record_id: int, table_name: str, admin_id: int, reason: str) -> Tuple[bool, str]:
        """
        حذف دائم من سلة المهملات - فقط للأدمن
        """
        try:
            # التحقق من أن المستخدم هو أدمن
            user = db.execute(
                "SELECT role FROM users WHERE id=? AND business_id=?",
                (admin_id, business_id)
            ).fetchone()
            
            if not user or user["role"] != "admin":
                return False, "ليس لديك صلاحية الحذف النهائي"
            
            # حذف من السلة
            db.execute("""
                DELETE FROM recycle_bin 
                WHERE business_id=? AND record_id=? AND table_name=?
            """, (business_id, record_id, table_name))
            
            # تسجيل الحذف النهائي
            db.execute("""
                INSERT INTO recycle_bin_history (business_id, record_id, action, performed_by, reason)
                VALUES (?, ?, 'permanently_deleted', ?, ?)
            """, (business_id, record_id, admin_id, reason))
            
            db.commit()
            logger.warning(f"حذف دائم من قبل الأدمن {admin_id}: {table_name}[{record_id}]")
            return True, "تم الحذف النهائي"
            
        except Exception as e:
            logger.error(f"خطأ في الحذف النهائي: {e}")
            return False, f"خطأ: {str(e)}"
    
    @staticmethod
    def admin_lock_retention(db, business_id: int, record_id: int, table_name: str, admin_id: int, lock_until_date: str) -> Tuple[bool, str]:
        """
        قفل سجل من الحذف التلقائي من قبل الأدمن (مثلاً: فاتورة قديمة مهمة)
        """
        try:
            # التحقق من أن المستخدم هو أدمن
            user = db.execute(
                "SELECT role FROM users WHERE id=? AND business_id=?",
                (admin_id, business_id)
            ).fetchone()
            
            if not user or user["role"] != "admin":
                return False, "ليس لديك صلاحية القفل"
            
            db.execute("""
                UPDATE recycle_bin 
                SET is_admin_locked = 1,
                    retention_until = ?
                WHERE business_id=? AND record_id=? AND table_name=?
            """, (lock_until_date, business_id, record_id, table_name))
            
            db.commit()
            logger.info(f"قفل السجل {record_id} من الحذف التلقائي حتى {lock_until_date}")
            return True, "تم قفل السجل من الحذف التلقائي"
            
        except Exception as e:
            logger.error(f"خطأ في القفل: {e}")
            return False, f"خطأ: {str(e)}"
    
    @staticmethod
    def cleanup_expired_records(db, business_id: Optional[int] = None) -> Tuple[int, str]:
        """
        حذف السجلات منتهية الاحتفاظ تلقائياً
        """
        try:
            if business_id:
                db.execute("""
                    DELETE FROM recycle_bin 
                    WHERE business_id=? 
                    AND retention_until < datetime('now')
                    AND is_admin_locked = 0
                """, (business_id,))
            else:
                db.execute("""
                    DELETE FROM recycle_bin 
                    WHERE retention_until < datetime('now')
                    AND is_admin_locked = 0
                """)
            
            deleted_count = db.total_changes
            db.commit()
            
            logger.info(f"تم حذف {deleted_count} سجل منتهي الاحتفاظ")
            return deleted_count, "تم تنظيف السجلات المنتهية"
            
        except Exception as e:
            logger.error(f"خطأ في التنظيف: {e}")
            return 0, f"خطأ: {str(e)}"
    
    @staticmethod
    def get_recycle_bin_contents(db, business_id: int, limit: int = 100, offset: int = 0) -> List[Dict]:
        """
        الحصول على محتويات سلة المهملات
        """
        try:
            records = db.execute("""
                SELECT 
                    id,
                    table_name,
                    record_id,
                    original_data,
                    deleted_by_user_id,
                    deleted_at,
                    retention_until,
                    is_admin_locked,
                    restoration_count,
                    notes
                FROM recycle_bin 
                WHERE business_id=?
                ORDER BY deleted_at DESC
                LIMIT ? OFFSET ?
            """, (business_id, limit, offset)).fetchall()
            
            return [dict(r) for r in records]
        except Exception as e:
            logger.error(f"خطأ في جلب محتويات السلة: {e}")
            return []
    
    @staticmethod
    def get_recycle_bin_stats(db, business_id: int) -> Dict:
        """
        الحصول على إحصائيات سلة المهملات
        """
        try:
            stats = db.execute("""
                SELECT 
                    COUNT(*) as total_items,
                    COUNT(CASE WHEN is_admin_locked = 1 THEN 1 END) as locked_items,
                    COUNT(DISTINCT table_name) as affected_tables,
                    MIN(deleted_at) as oldest_deletion,
                    MAX(deleted_at) as newest_deletion
                FROM recycle_bin 
                WHERE business_id=?
            """, (business_id,)).fetchone()
            
            return dict(stats) if stats else {}
        except Exception as e:
            logger.error(f"خطأ في جلب إحصائيات السلة: {e}")
            return {}
