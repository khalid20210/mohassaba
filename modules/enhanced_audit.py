"""
modules/enhanced_audit.py
═════════════════════════════════════════════════════════════════════════════════
نظام الرقابة المحسّن المجهري - المادة السادسة من الميثاق الدستوري
═════════════════════════════════════════════════════════════════════════════════

تسجيل كل نقرة، تغيير قيمة، وقت دخول، وجهاز مستخدم لضمان الرقابة الصارمة.
"""

import json
import logging
import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Any
from functools import wraps
from flask import request, session, g

logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════════════════════════
# Schema لجداول الرقابة المحسنة
# ════════════════════════════════════════════════════════════════════════════════

ENHANCED_AUDIT_SCHEMA = """
-- سجل الرقابة الشامل
CREATE TABLE IF NOT EXISTS enhanced_audit_logs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL,
    user_id             INTEGER NOT NULL,
    session_id          TEXT,
    
    -- معلومات الإجراء
    action              TEXT NOT NULL,          -- CREATE, READ, UPDATE, DELETE, LOGIN, LOGOUT, EXPORT
    resource_type       TEXT,                   -- Invoice, Product, Employee, Account
    resource_id         INTEGER,
    
    -- البيانات
    old_values          TEXT,                   -- JSON للقيم القديمة
    new_values          TEXT,                   -- JSON للقيم الجديدة
    changes_summary     TEXT,                   -- ملخص التغييرات
    
    -- معلومات الجهاز والشبكة
    ip_address          TEXT NOT NULL,
    device_id           TEXT,                   -- معرّف الجهاز الفريد
    device_name         TEXT,
    device_type         TEXT,                   -- Desktop, Tablet, Mobile
    os_name             TEXT,
    browser_name        TEXT,
    user_agent          TEXT,
    
    -- الأداء
    request_duration_ms INTEGER,
    status              TEXT DEFAULT 'success', -- success, failure, partial
    error_message       TEXT,
    
    -- الوقت
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    created_timestamp   INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
    
    FOREIGN KEY(business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_enhanced_audit_business_time 
    ON enhanced_audit_logs(business_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_enhanced_audit_user_action 
    ON enhanced_audit_logs(user_id, action);

CREATE INDEX IF NOT EXISTS idx_enhanced_audit_resource 
    ON enhanced_audit_logs(resource_type, resource_id);

CREATE INDEX IF NOT EXISTS idx_enhanced_audit_device 
    ON enhanced_audit_logs(device_id);

CREATE INDEX IF NOT EXISTS idx_enhanced_audit_ip 
    ON enhanced_audit_logs(ip_address);

-- جدول تتبع الجلسات المتزامنة
CREATE TABLE IF NOT EXISTS user_sessions_tracking (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL,
    user_id         INTEGER NOT NULL,
    session_id      TEXT NOT NULL UNIQUE,
    device_id       TEXT NOT NULL,
    ip_address      TEXT NOT NULL,
    
    login_at        TEXT NOT NULL DEFAULT (datetime('now')),
    last_activity   TEXT NOT NULL DEFAULT (datetime('now')),
    logout_at       TEXT,
    is_active       INTEGER DEFAULT 1,
    
    device_info     TEXT,                   -- JSON مع تفاصيل الجهاز
    
    FOREIGN KEY(business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_tracking_user 
    ON user_sessions_tracking(user_id, is_active);

-- جدول تنبيهات الأمان
CREATE TABLE IF NOT EXISTS security_alerts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL,
    alert_type          TEXT NOT NULL,      -- unusual_login, bulk_delete, high_value_transaction
    severity            TEXT NOT NULL,      -- low, medium, high, critical
    user_id             INTEGER,
    ip_address          TEXT,
    description         TEXT,
    details             TEXT,                -- JSON
    acknowledged_at     TEXT,
    acknowledged_by     INTEGER,
    
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    
    FOREIGN KEY(business_id) REFERENCES businesses(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_security_alerts_business 
    ON security_alerts(business_id, created_at DESC);

-- جدول الصلاحيات المتغيرة (عندما تتغير صلاحيات المستخدم)
CREATE TABLE IF NOT EXISTS permission_changes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id         INTEGER NOT NULL,
    user_id             INTEGER NOT NULL,
    changed_by_user_id  INTEGER NOT NULL,
    
    old_permissions     TEXT NOT NULL,      -- JSON
    new_permissions     TEXT NOT NULL,      -- JSON
    reason              TEXT,
    
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    
    FOREIGN KEY(business_id) REFERENCES businesses(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_permission_changes_user 
    ON permission_changes(user_id, created_at DESC);
"""


class DeviceFingerprint:
    """إنشاء بصمة فريدة للجهاز"""
    
    @staticmethod
    def generate(user_agent: str, accept_language: str = "", accept_encoding: str = "") -> str:
        """
        إنشاء معرّف جهاز فريد بناءً على خصائص الطلب
        """
        fingerprint_data = f"{user_agent}|{accept_language}|{accept_encoding}"
        return hashlib.sha256(fingerprint_data.encode()).hexdigest()[:16]
    
    @staticmethod
    def extract_device_info(user_agent: str) -> Dict[str, str]:
        """استخراج معلومات الجهاز والمتصفح من user agent"""
        import re
        
        device_info = {
            "device_type": "Unknown",
            "os_name": "Unknown",
            "browser_name": "Unknown",
        }
        
        # كشف نوع الجهاز
        if "Mobile" in user_agent or "Android" in user_agent:
            device_info["device_type"] = "Mobile"
        elif "Tablet" in user_agent or "iPad" in user_agent:
            device_info["device_type"] = "Tablet"
        else:
            device_info["device_type"] = "Desktop"
        
        # كشف نظام التشغيل
        if "Windows" in user_agent:
            device_info["os_name"] = "Windows"
        elif "Macintosh" in user_agent:
            device_info["os_name"] = "macOS"
        elif "Linux" in user_agent:
            device_info["os_name"] = "Linux"
        elif "Android" in user_agent:
            device_info["os_name"] = "Android"
        elif "iPhone" in user_agent or "iPad" in user_agent:
            device_info["os_name"] = "iOS"
        
        # كشف المتصفح
        if "Chrome" in user_agent:
            device_info["browser_name"] = "Chrome"
        elif "Firefox" in user_agent:
            device_info["browser_name"] = "Firefox"
        elif "Safari" in user_agent:
            device_info["browser_name"] = "Safari"
        elif "Edge" in user_agent:
            device_info["browser_name"] = "Edge"
        
        return device_info


class EnhancedAuditLogger:
    """نظام السجل المحسّن"""
    
    @staticmethod
    def log_action(
        db,
        business_id: int,
        user_id: int,
        action: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[int] = None,
        old_values: Optional[Dict] = None,
        new_values: Optional[Dict] = None,
        request_duration_ms: Optional[int] = None,
        status: str = "success",
        error_message: Optional[str] = None,
    ) -> bool:
        """تسجيل إجراء بشامل"""
        try:
            # استخراج معلومات الطلب
            user_agent = request.user_agent.string if request else ""
            ip_address = request.remote_addr if request else "0.0.0.0"
            session_id = session.get("session_id") if session else ""
            
            # إنشاء بصمة الجهاز
            device_id = DeviceFingerprint.generate(user_agent)
            device_info = DeviceFingerprint.extract_device_info(user_agent)
            
            # حساب ملخص التغييرات
            changes_summary = ""
            if old_values and new_values:
                changed_fields = []
                for key in new_values:
                    if key not in old_values or old_values[key] != new_values[key]:
                        changed_fields.append(key)
                changes_summary = ", ".join(changed_fields)
            
            db.execute("""
                INSERT INTO enhanced_audit_logs (
                    business_id,
                    user_id,
                    session_id,
                    action,
                    resource_type,
                    resource_id,
                    old_values,
                    new_values,
                    changes_summary,
                    ip_address,
                    device_id,
                    device_name,
                    device_type,
                    os_name,
                    browser_name,
                    user_agent,
                    request_duration_ms,
                    status,
                    error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                business_id,
                user_id,
                session_id,
                action,
                resource_type,
                resource_id,
                json.dumps(old_values) if old_values else None,
                json.dumps(new_values) if new_values else None,
                changes_summary,
                ip_address,
                device_id,
                device_info.get("device_type"),
                device_info.get("device_type"),
                device_info.get("os_name"),
                device_info.get("browser_name"),
                user_agent,
                request_duration_ms,
                status,
                error_message,
            ))
            
            db.commit()
            return True
        except Exception as e:
            logger.error(f"خطأ في تسجيل الإجراء: {e}")
            return False
    
    @staticmethod
    def log_login(db, business_id: int, user_id: int, session_id: str) -> bool:
        """تسجيل دخول المستخدم"""
        try:
            user_agent = request.user_agent.string if request else ""
            ip_address = request.remote_addr if request else "0.0.0.0"
            device_id = DeviceFingerprint.generate(user_agent)
            device_info = DeviceFingerprint.extract_device_info(user_agent)
            
            db.execute("""
                INSERT INTO user_sessions_tracking (
                    business_id,
                    user_id,
                    session_id,
                    device_id,
                    ip_address,
                    device_info
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                business_id,
                user_id,
                session_id,
                device_id,
                ip_address,
                json.dumps(device_info)
            ))
            
            # تسجيل في السجل الشامل
            EnhancedAuditLogger.log_action(
                db, business_id, user_id, "LOGIN",
                request_duration_ms=0, status="success"
            )
            
            db.commit()
            return True
        except Exception as e:
            logger.error(f"خطأ في تسجيل الدخول: {e}")
            return False
    
    @staticmethod
    def log_logout(db, business_id: int, user_id: int, session_id: str) -> bool:
        """تسجيل خروج المستخدم"""
        try:
            db.execute("""
                UPDATE user_sessions_tracking 
                SET logout_at = datetime('now'), is_active = 0
                WHERE session_id = ? AND user_id = ?
            """, (session_id, user_id))
            
            EnhancedAuditLogger.log_action(
                db, business_id, user_id, "LOGOUT",
                request_duration_ms=0, status="success"
            )
            
            db.commit()
            return True
        except Exception as e:
            logger.error(f"خطأ في تسجيل الخروج: {e}")
            return False
    
    @staticmethod
    def check_suspicious_activity(db, business_id: int, user_id: int) -> List[str]:
        """التحقق من الأنشطة المريبة"""
        alerts = []
        
        try:
            # تحقق من محاولات دخول متعددة من عناوين IP مختلفة
            recent_ips = db.execute("""
                SELECT COUNT(DISTINCT ip_address) as ip_count
                FROM enhanced_audit_logs
                WHERE business_id=? AND user_id=? AND action='LOGIN'
                AND created_at > datetime('now', '-1 hour')
            """, (business_id, user_id)).fetchone()
            
            if recent_ips and recent_ips["ip_count"] > 3:
                alerts.append("multiple_ip_login")
            
            # تحقق من حذف كمي
            bulk_deletes = db.execute("""
                SELECT COUNT(*) as delete_count
                FROM enhanced_audit_logs
                WHERE business_id=? AND user_id=? AND action='DELETE'
                AND created_at > datetime('now', '-10 minutes')
            """, (business_id, user_id)).fetchone()
            
            if bulk_deletes and bulk_deletes["delete_count"] > 50:
                alerts.append("bulk_delete_detected")
            
            # تحقق من تصدير كمي
            bulk_exports = db.execute("""
                SELECT COUNT(*) as export_count
                FROM enhanced_audit_logs
                WHERE business_id=? AND user_id=? AND action='EXPORT'
                AND created_at > datetime('now', '-10 minutes')
            """, (business_id, user_id)).fetchone()
            
            if bulk_exports and bulk_exports["export_count"] > 10:
                alerts.append("bulk_export_detected")
            
            # إنشاء تنبيهات أمان إذا لزم الحال
            for alert_type in alerts:
                db.execute("""
                    INSERT INTO security_alerts (business_id, alert_type, severity, user_id, description)
                    VALUES (?, ?, 'high', ?, ?)
                """, (business_id, alert_type, user_id, f"نشاط مريب: {alert_type}"))
            
            db.commit()
            
        except Exception as e:
            logger.error(f"خطأ في التحقق من الأنشطة المريبة: {e}")
        
        return alerts
    
    @staticmethod
    def get_audit_logs(db, business_id: int, filters: Optional[Dict] = None, limit: int = 100, offset: int = 0) -> List[Dict]:
        """جلب سجلات الرقابة مع التصفية"""
        try:
            query = """
                SELECT * FROM enhanced_audit_logs 
                WHERE business_id = ?
            """
            params = [business_id]
            
            if filters:
                if "user_id" in filters:
                    query += " AND user_id = ?"
                    params.append(filters["user_id"])
                if "action" in filters:
                    query += " AND action = ?"
                    params.append(filters["action"])
                if "resource_type" in filters:
                    query += " AND resource_type = ?"
                    params.append(filters["resource_type"])
                if "date_from" in filters:
                    query += " AND created_at >= ?"
                    params.append(filters["date_from"])
                if "date_to" in filters:
                    query += " AND created_at <= ?"
                    params.append(filters["date_to"])
            
            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            records = db.execute(query, params).fetchall()
            return [dict(r) for r in records]
        except Exception as e:
            logger.error(f"خطأ في جلب سجلات الرقابة: {e}")
            return []


def audit_log_action(action: str, resource_type: str = None):
    """ديكوراتور لتسجيل الإجراءات تلقائياً"""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            start_time = datetime.now()
            try:
                result = f(*args, **kwargs)
                duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                
                # تسجيل الإجراء الناجح
                if hasattr(g, 'db') and hasattr(g, 'user_id') and hasattr(g, 'business_id'):
                    EnhancedAuditLogger.log_action(
                        g.db,
                        g.business_id,
                        g.user_id,
                        action,
                        resource_type=resource_type,
                        request_duration_ms=duration_ms,
                        status="success"
                    )
                
                return result
            except Exception as e:
                duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                
                # تسجيل الخطأ
                if hasattr(g, 'db') and hasattr(g, 'user_id') and hasattr(g, 'business_id'):
                    EnhancedAuditLogger.log_action(
                        g.db,
                        g.business_id,
                        g.user_id,
                        action,
                        resource_type=resource_type,
                        request_duration_ms=duration_ms,
                        status="failure",
                        error_message=str(e)
                    )
                
                raise
        return wrapped
    return decorator
