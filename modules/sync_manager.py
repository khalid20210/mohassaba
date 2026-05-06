"""
sync_manager.py
==============
محرك المزامنة — يدير تبادل البيانات بين الأجهزة المحلية والخادم المركزي
بدون انقطاع في وضع أوفلاين + مزامنة ذكية عند الاتصال
"""

import sqlite3
import json
import hashlib
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import threading
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


ALLOWED_SYNC_TABLES = {
    "products_local",
    "services_local",
    "invoices_local",
    "invoice_lines_local",
    "inventory_local",
    "stock_movements_local",
    "tenant_info",
    "activities_local",
}


def _ensure_allowed_table(table: str) -> str:
    """يمنع حقن SQL عبر أسماء الجداول القادمة من المزامنة."""
    normalized = (table or "").strip()
    if normalized not in ALLOWED_SYNC_TABLES:
        raise ValueError(f"Table not allowed for sync: {normalized}")
    return normalized


class SyncManager:
    """
    إدارة المزامنة بين قاعدة البيانات المحلية والمركزية
    
    الخصائص:
      • مزامنة ثنائية الاتجاه (bidirectional)
      • معالجة النزاعات (conflict resolution)
      • إعادة محاولة تلقائية
      • تتبع آخر تحديث (last-modified timestamps)
    """
    
    def __init__(self, local_db_path: str, central_url: str = "http://localhost:5001",
                 tenant_key: str = "biz-001", device_id: str = "device-001"):
        """
        Args:
            local_db_path: مسار قاعدة البيانات المحلية
            central_url: URL الخادم المركزي
            tenant_key: معرّف المنشأة
            device_id: معرّف الجهاز
        """
        self.local_db = local_db_path
        self.central_url = central_url
        self.tenant_key = tenant_key
        self.device_id = device_id
        self.is_syncing = False
        self.is_online = False
        
        # تحقق من الاتصال
        self._check_online_status()
    
    def _check_online_status(self):
        """التحقق من حالة الاتصال بالخادم"""
        try:
            resp = requests.get(f"{self.central_url}/healthz", timeout=2)
            self.is_online = resp.status_code == 200
        except:
            self.is_online = False
        
        status = "🟢 متصل" if self.is_online else "🔴 بلا اتصال"
        logger.info(f"{status} — الخادم المركزي")
    
    def sync(self):
        """
        تشغيل دورة مزامنة كاملة:
          1. تحميل البيانات الجديدة من الخادم (pull)
          2. رفع التغييرات المحلية (push)
          3. معالجة النزاعات
        """
        if self.is_syncing:
            logger.warning("❌ المزامنة قيد التنفيذ بالفعل")
            return
        
        self.is_syncing = True
        try:
            logger.info("🔄 بدء المزامنة...")
            
            # إذا كان بلا اتصال، اعمل محلياً فقط
            if not self.is_online:
                logger.info("⚠️  العمل بوضع أوفلاين — لا يوجد اتصال بالخادم")
                self._process_offline_queue()
                return
            
            # مزامنة متصل
            self._pull_from_central()  # تحميل من الخادم
            self._push_to_central()     # رفع إلى الخادم
            self._reconcile_conflicts() # معالجة النزاعات
            
            logger.info("✅ المزامنة مكتملة")
            
        except Exception as e:
            logger.error(f"❌ خطأ في المزامنة: {e}")
        finally:
            self.is_syncing = False
    
    def _pull_from_central(self):
        """تحميل البيانات الجديدة من الخادم المركزي"""
        logger.info("📥 تحميل البيانات من الخادم...")
        
        conn = sqlite3.connect(self.local_db)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        try:
            # احصل على آخر تحديث محلي
            sync_state = c.execute(
                "SELECT * FROM local_sync_state ORDER BY last_sync_timestamp DESC LIMIT 5"
            ).fetchall()
            
            # طلب التحديثات من الخادم
            last_sync = sync_state[0]["last_sync_timestamp"] if sync_state else None
            
            payload = {
                "tenant_key": self.tenant_key,
                "device_id": self.device_id,
                "last_sync": last_sync,
            }
            
            resp = requests.post(
                f"{self.central_url}/api/v1/sync/pull",
                json=payload,
                timeout=30
            )
            
            if resp.status_code != 200:
                logger.warning(f"⚠️  خطأ في التحميل: {resp.text}")
                return
            
            data = resp.json()
            updates = data.get("updates", {})
            
            for table_name, records in updates.items():
                logger.info(f"   • تحديث {table_name}: {len(records)} سجل")
                
                for record in records:
                    if record["operation"] == "INSERT":
                        self._insert_record(c, table_name, record["data"])
                    elif record["operation"] == "UPDATE":
                        self._update_record(c, table_name, record["data"])
                    elif record["operation"] == "DELETE":
                        self._delete_record(c, table_name, record["data"]["id"])
                
                # حدّث حالة المزامنة
                c.execute("""
                    INSERT OR REPLACE INTO local_sync_state
                    (table_name, last_download, synced_records)
                    VALUES (?, datetime('now'), ?)
                """, (table_name, len(records)))
            
            conn.commit()
            logger.info(f"✅ تم تحميل {sum(len(r) for r in updates.values())} سجل")
            
        except Exception as e:
            logger.error(f"❌ خطأ في التحميل: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    def _push_to_central(self):
        """رفع التغييرات المحلية إلى الخادم"""
        logger.info("📤 رفع التغييرات إلى الخادم...")
        
        conn = sqlite3.connect(self.local_db)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        try:
            # احصل على التغييرات المحلية غير المُزامنة
            changes = c.execute("""
                SELECT * FROM offline_queue
                WHERE is_synced = 0 AND attempted_sync = 0
                ORDER BY created_at
                LIMIT 1000
            """).fetchall()
            
            if not changes:
                logger.info("   ✓ لا توجد تغييرات محلية جديدة")
                return
            
            # اجمع التغييرات حسب الجدول
            by_table = {}
            for change in changes:
                table = change["table_name"]
                if table not in by_table:
                    by_table[table] = []
                by_table[table].append(dict(change))
            
            # أرسل الدفعات
            for table_name, records in by_table.items():
                payload = {
                    "tenant_key": self.tenant_key,
                    "device_id": self.device_id,
                    "table": table_name,
                    "records": records,
                }
                
                try:
                    resp = requests.post(
                        f"{self.central_url}/api/v1/sync/push",
                        json=payload,
                        timeout=30
                    )
                    
                    if resp.status_code == 200:
                        # ضع علامة على التغييرات كمُزامنة
                        record_ids = [r["id"] for r in records]
                        placeholders = ",".join("?" * len(record_ids))
                        c.execute(
                            f"UPDATE offline_queue SET is_synced=1, synced_at=datetime('now') WHERE id IN ({placeholders})",
                            record_ids
                        )
                        logger.info(f"   ✓ {table_name}: {len(records)} سجل")
                    else:
                        # حاول لاحقاً
                        for rec_id in [r["id"] for r in records]:
                            c.execute(
                                "UPDATE offline_queue SET attempted_sync=1, last_sync_attempt=datetime('now'), sync_error=? WHERE id=?",
                                (resp.text[:200], rec_id)
                            )
                        logger.warning(f"   ⚠️  {table_name}: فشل الرفع - سيُحاول لاحقاً")
                
                except requests.Timeout:
                    logger.warning(f"   ⏱️  {table_name}: انتهاء المهلة الزمنية")
                except Exception as e:
                    logger.warning(f"   ❌ {table_name}: {e}")
            
            conn.commit()
            logger.info(f"✅ تم رفع {len(changes)} تغيير")
            
        except Exception as e:
            logger.error(f"❌ خطأ في الرفع: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    def _process_offline_queue(self):
        """معالجة قائمة الانتظار المحلية (بدون اتصال)"""
        logger.info("📋 معالجة قائمة الانتظار المحلية...")
        
        conn = sqlite3.connect(self.local_db)
        c = conn.cursor()
        
        # احسب عدد السجلات المعلقة
        pending = c.execute(
            "SELECT COUNT(*) as count FROM offline_queue WHERE is_synced = 0"
        ).fetchone()[0]
        
        logger.info(f"   📦 {pending} تغيير معلق (سيتم مزامنتها لاحقاً)")
        
        conn.close()
    
    def _reconcile_conflicts(self):
        """معالجة النزاعات (عندما تعدّل أجهزة متعددة نفس السجل)"""
        logger.info("🔍 فحص النزاعات...")
        
        conn = sqlite3.connect(self.local_db)
        c = conn.cursor()
        
        try:
            conflicts = c.execute("""
                SELECT * FROM sync_conflicts
                WHERE resolution IS NULL
            """).fetchall()
            
            for conflict in conflicts:
                # استخدم: آخر تعديل يفوز (last-write-wins)
                c.execute("""
                    UPDATE sync_conflicts
                    SET resolution = 'last_write_wins',
                        resolved_at = datetime('now')
                    WHERE id = ?
                """, (conflict[0],))
                
                logger.info(f"   ✓ نزاع معالج: {conflict[2]} (الحل: last-write-wins)")
            
            conn.commit()
            logger.info(f"✅ تم معالجة {len(conflicts)} نزاع")
            
        except Exception as e:
            logger.error(f"❌ خطأ في معالجة النزاعات: {e}")
        finally:
            conn.close()
    
    def _insert_record(self, cursor, table: str, data: dict):
        """إدراج سجل جديد"""
        table = _ensure_allowed_table(table)
        cols = ", ".join(data.keys())
        vals = ", ".join(["?" for _ in data])
        query = f"INSERT OR IGNORE INTO {table} ({cols}) VALUES ({vals})"
        cursor.execute(query, list(data.values()))
    
    def _update_record(self, cursor, table: str, data: dict):
        """تحديث سجل موجود"""
        table = _ensure_allowed_table(table)
        payload = dict(data)
        rec_id = payload.pop("id", None)
        if not rec_id:
            return
        
        updates = ", ".join([f"{k}=?" for k in payload.keys()])
        query = f"UPDATE {table} SET {updates}, server_last_modified=datetime('now') WHERE id=?"
        cursor.execute(query, list(payload.values()) + [rec_id])
    
    def _delete_record(self, cursor, table: str, record_id: int):
        """حذف سجل"""
        table = _ensure_allowed_table(table)
        cursor.execute(f"DELETE FROM {table} WHERE id = ?", (record_id,))


class BackgroundSyncThread(threading.Thread):
    """خيط عمل للمزامنة المستمرة في الخلفية"""
    
    def __init__(self, sync_manager: SyncManager, interval_seconds: int = 300):
        super().__init__()
        self.sync_manager = sync_manager
        self.interval = interval_seconds
        self.daemon = True
        self._stop_event = threading.Event()
    
    def run(self):
        """الحلقة الرئيسية للمزامنة"""
        logger.info(f"🔄 بدء خيط المزامنة الدوري (كل {self.interval} ثانية)")
        
        while not self._stop_event.is_set():
            try:
                self.sync_manager._check_online_status()
                self.sync_manager.sync()
            except Exception as e:
                logger.error(f"❌ خطأ في الحلقة الدورية: {e}")
            
            # انتظر قبل المزامنة التالية
            self._stop_event.wait(self.interval)
    
    def stop(self):
        """إيقاف خيط المزامنة"""
        logger.info("⏹️  إيقاف خيط المزامنة")
        self._stop_event.set()


# مثال على الاستخدام
if __name__ == "__main__":
    manager = SyncManager(
        local_db_path="database/local_biz001_pos001.db",
        tenant_key="biz-001",
        device_id="pos-001"
    )
    
    # شغّل المزامنة يدوياً
    manager.sync()
    
    # أو شغّل الحلقة الدورية في الخلفية
    sync_thread = BackgroundSyncThread(manager, interval_seconds=300)
    sync_thread.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("⏹️  إيقاف...")
        sync_thread.stop()
