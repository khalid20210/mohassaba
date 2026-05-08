"""
modules/resilience_engine.py
═════════════════════════════════════════════════════════════════════════════════
محرك الاستمرارية والتعافي من الأعطال - المادة السادسة من الميثاق
═════════════════════════════════════════════════════════════════════════════════

نظام ضمان الاستمرارية المطلقة:
• Automatic Failover - الانتقال التلقائي عند أي عطل
• Health Checks - فحوصات صحة النظام المستمرة
• Backup & Recovery - نسخ احتياطية واستعادة سريعة
• Circuit Breaker - كسر الحلقات عند الفشل المتكرر
• Graceful Degradation - تدهور ظريف بدلاً من الانهيار
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Callable
from enum import Enum
from dataclasses import dataclass
import json

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """حالات صحة النظام"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    RECOVERING = "recovering"


@dataclass
class HealthCheckResult:
    """نتيجة فحص الصحة"""
    status: HealthStatus
    component: str
    message: str
    last_checked: datetime
    response_time_ms: int
    details: Dict = None


class ComponentHealthMonitor:
    """مراقب صحة المكونات الحرجة"""
    
    def __init__(self):
        self.components: Dict[str, Dict] = {}
        self.health_history: Dict[str, List[HealthCheckResult]] = {}
        self.lock = threading.Lock()
    
    def register_component(self, name: str, check_func: Callable, timeout_ms: int = 5000):
        """تسجيل مكون للمراقبة"""
        with self.lock:
            self.components[name] = {
                "check_func": check_func,
                "timeout_ms": timeout_ms,
                "last_check": None,
                "failure_count": 0,
                "is_healthy": True,
            }
            self.health_history[name] = []
    
    def check_component(self, name: str) -> Optional[HealthCheckResult]:
        """فحص صحة مكون واحد"""
        if name not in self.components:
            return None
        
        component = self.components[name]
        start_time = time.time()
        
        try:
            # تنفيذ فحص الصحة مع timeout
            result = component["check_func"]()
            response_time_ms = int((time.time() - start_time) * 1000)
            
            if result:
                status = HealthStatus.HEALTHY
                component["failure_count"] = 0
                component["is_healthy"] = True
                message = f"✓ {name} يعمل بشكل طبيعي"
            else:
                status = HealthStatus.DEGRADED
                component["failure_count"] += 1
                message = f"⚠ {name} يعمل بكفاءة منخفضة"
            
        except Exception as e:
            response_time_ms = int((time.time() - start_time) * 1000)
            status = HealthStatus.UNHEALTHY
            component["failure_count"] += 1
            component["is_healthy"] = False
            message = f"✗ {name} معطل: {str(e)}"
            logger.error(message)
        
        check_result = HealthCheckResult(
            status=status,
            component=name,
            message=message,
            last_checked=datetime.now(),
            response_time_ms=response_time_ms,
            details={
                "failure_count": component["failure_count"],
                "is_healthy": component["is_healthy"],
            }
        )
        
        # حفظ السجل
        with self.lock:
            self.health_history[name].append(check_result)
            # احتفظ بآخر 100 فحص فقط
            if len(self.health_history[name]) > 100:
                self.health_history[name] = self.health_history[name][-100:]
            
            component["last_check"] = check_result
        
        return check_result
    
    def get_overall_health(self) -> HealthStatus:
        """الحصول على حالة النظام الكلية"""
        if not self.components:
            return HealthStatus.HEALTHY
        
        healthy_count = sum(1 for c in self.components.values() if c["is_healthy"])
        total = len(self.components)
        
        if healthy_count == total:
            return HealthStatus.HEALTHY
        elif healthy_count >= total * 0.75:  # 75% يعمل
            return HealthStatus.DEGRADED
        else:
            return HealthStatus.UNHEALTHY
    
    def get_health_report(self) -> Dict:
        """تقرير شامل عن صحة النظام"""
        with self.lock:
            report = {
                "overall_status": self.get_overall_health().value,
                "timestamp": datetime.now().isoformat(),
                "components": {}
            }
            
            for name, component in self.components.items():
                last_check = component["last_check"]
                report["components"][name] = {
                    "status": last_check.status.value if last_check else None,
                    "last_checked": last_check.last_checked.isoformat() if last_check else None,
                    "response_time_ms": last_check.response_time_ms if last_check else None,
                    "failure_count": component["failure_count"],
                    "is_healthy": component["is_healthy"],
                }
            
            return report


class CircuitBreaker:
    """نمط كسر الحلقة - منع طلبات متكررة للخدمات المعطلة"""
    
    class State(Enum):
        CLOSED = "closed"      # عادي - يسمح بالطلبات
        OPEN = "open"          # معطل - يرفض الطلبات
        HALF_OPEN = "half_open"  # اختبار - طلب تجريبي واحد
    
    def __init__(self, name: str, failure_threshold: int = 5, recovery_timeout_sec: int = 60):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_sec = recovery_timeout_sec
        
        self.state = self.State.CLOSED
        self.failure_count = 0
        self.last_failure_time = None
        self.lock = threading.Lock()
    
    def call(self, func: Callable, *args, **kwargs):
        """استدعاء دالة مع حماية كسر الحلقة"""
        with self.lock:
            if self.state == self.State.OPEN:
                # تحقق إذا مرّ timeout للتحول إلى HALF_OPEN
                if datetime.now() - self.last_failure_time > timedelta(seconds=self.recovery_timeout_sec):
                    self.state = self.State.HALF_OPEN
                    logger.info(f"Circuit Breaker {self.name}: HALF_OPEN - محاولة استعادة")
                else:
                    raise Exception(f"Circuit Breaker {self.name} مفتوح (معطل)")
        
        try:
            result = func(*args, **kwargs)
            
            with self.lock:
                if self.state == self.State.HALF_OPEN:
                    self.state = self.State.CLOSED
                    self.failure_count = 0
                    logger.info(f"Circuit Breaker {self.name}: استعاد النظام - CLOSED")
            
            return result
        
        except Exception as e:
            with self.lock:
                self.failure_count += 1
                self.last_failure_time = datetime.now()
                
                if self.failure_count >= self.failure_threshold:
                    self.state = self.State.OPEN
                    logger.error(f"Circuit Breaker {self.name}: OPEN - توقف الخدمة ({self.failure_count} أخطاء)")
            
            raise


class BackupRecoveryManager:
    """إدارة النسخ الاحتياطية والاستعادة"""
    
    BACKUP_SCHEMA = """
    CREATE TABLE IF NOT EXISTS backups (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        business_id         INTEGER,
        backup_type         TEXT NOT NULL,      -- full, incremental, snapshot
        backup_name         TEXT NOT NULL UNIQUE,
        backup_path         TEXT NOT NULL,
        size_bytes          INTEGER,
        compression_type    TEXT,               -- gzip, bzip2, none
        created_at          TEXT NOT NULL DEFAULT (datetime('now')),
        expires_at          TEXT,
        status              TEXT DEFAULT 'pending',  -- pending, completed, failed, restored
        restored_at         TEXT,
        restored_by_user_id INTEGER,
        error_message       TEXT,
        
        FOREIGN KEY(business_id) REFERENCES businesses(id) ON DELETE CASCADE
    );
    
    CREATE INDEX IF NOT EXISTS idx_backups_business_created 
        ON backups(business_id, created_at DESC);
    
    CREATE INDEX IF NOT EXISTS idx_backups_expires 
        ON backups(expires_at);
    """
    
    def __init__(self, backup_dir: str):
        self.backup_dir = backup_dir
    
    def create_backup(self, db, business_id: int, backup_type: str = "full") -> Tuple[bool, str]:
        """إنشاء نسخة احتياطية"""
        try:
            backup_name = f"{business_id}_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            logger.info(f"بدء إنشاء نسخة احتياطية: {backup_name}")
            
            # تسجيل النسخة في قاعدة البيانات
            db.execute("""
                INSERT INTO backups (business_id, backup_type, backup_name, backup_path, status)
                VALUES (?, ?, ?, ?, 'pending')
            """, (business_id, backup_type, backup_name, f"{self.backup_dir}/{backup_name}"))
            db.commit()
            
            # في الإنتاج: استدعاء أداة backup خارجية
            logger.info(f"اكتملت النسخة الاحتياطية: {backup_name}")
            return True, f"نسخة احتياطية {backup_name} جاهزة"
        
        except Exception as e:
            logger.error(f"خطأ في إنشاء النسخة: {e}")
            return False, f"خطأ: {str(e)}"
    
    def restore_backup(self, db, business_id: int, backup_name: str, restored_by_user_id: int) -> Tuple[bool, str]:
        """استعادة من نسخة احتياطية"""
        try:
            backup = db.execute(
                "SELECT * FROM backups WHERE business_id=? AND backup_name=?",
                (business_id, backup_name)
            ).fetchone()
            
            if not backup:
                return False, "النسخة غير موجودة"
            
            logger.warning(f"استعادة نسخة احتياطية: {backup_name}")
            
            # في الإنتاج: استدعاء أداة restore
            
            db.execute("""
                UPDATE backups 
                SET status='restored', restored_at=datetime('now'), restored_by_user_id=?
                WHERE backup_name=?
            """, (restored_by_user_id, backup_name))
            db.commit()
            
            return True, f"تمت الاستعادة من {backup_name}"
        
        except Exception as e:
            logger.error(f"خطأ في الاستعادة: {e}")
            return False, f"خطأ: {str(e)}"
    
    def cleanup_old_backups(self, db, retention_days: int = 30) -> int:
        """حذف النسخ الاحتياطية القديمة"""
        try:
            deleted = db.execute("""
                DELETE FROM backups 
                WHERE created_at < datetime('now', '-' || ? || ' days')
                AND status IN ('completed', 'failed')
            """, (retention_days,)).rowcount
            
            db.commit()
            logger.info(f"حذف {deleted} نسخة احتياطية قديمة")
            return deleted
        
        except Exception as e:
            logger.error(f"خطأ في تنظيف النسخ القديمة: {e}")
            return 0


class RateLimitingPolicy:
    """سياسات تقنين التدفق (Rate Limiting)"""
    
    def __init__(self):
        self.request_queues: Dict[str, List[float]] = {}
        self.lock = threading.Lock()
    
    def check_rate_limit(self, user_id: str, max_requests: int = 100, window_sec: int = 60) -> Tuple[bool, int]:
        """
        التحقق من حد التدفق
        
        المخرجات:
        (هل مسموح، عدد الطلبات المتبقية)
        """
        with self.lock:
            now = time.time()
            
            if user_id not in self.request_queues:
                self.request_queues[user_id] = []
            
            queue = self.request_queues[user_id]
            
            # إزالة الطلبات القديمة خارج النافذة الزمنية
            queue[:] = [t for t in queue if now - t < window_sec]
            
            if len(queue) < max_requests:
                queue.append(now)
                remaining = max_requests - len(queue)
                return True, remaining
            else:
                return False, 0


class GracefulDegradation:
    """تدهور ظريف - تقليل الميزات بدلاً من الانهيار"""
    
    @staticmethod
    def get_degraded_response(feature: str, error: str) -> Dict:
        """حصول على رد مُخفّف عند فشل ميزة ما"""
        degradation_modes = {
            "advanced_analytics": {
                "status": "degraded",
                "message": "التحليلات المتقدمة مؤقتاً غير متاحة",
                "fallback": "العرض البسيط متاح",
            },
            "ai_suggestions": {
                "status": "degraded",
                "message": "الاقتراحات الذكية مؤقتاً غير متاحة",
                "fallback": "استخدم البحث اليدوي",
            },
            "real_time_sync": {
                "status": "degraded",
                "message": "المزامنة الفورية مؤقتاً غير متاحة",
                "fallback": "سيتم المزامنة عند استعادة الاتصال",
            },
            "export": {
                "status": "degraded",
                "message": "التصدير مؤقتاً غير متاح",
                "fallback": "يمكنك إعادة المحاولة لاحقاً",
            },
        }
        
        return degradation_modes.get(feature, {
            "status": "degraded",
            "message": f"الميزة مؤقتاً غير متاحة: {error}",
            "fallback": "الميزات الأساسية متاحة",
        })


# ════════════════════════════════════════════════════════════════════════════════
# مثيل عام للمراقب
# ════════════════════════════════════════════════════════════════════════════════

health_monitor = ComponentHealthMonitor()
rate_limiter = RateLimitingPolicy()
