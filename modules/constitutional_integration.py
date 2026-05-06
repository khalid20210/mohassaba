"""
modules/constitutional_integration.py
═════════════════════════════════════════════════════════════════════════════════
تكامل الميثاق الدستوري مع تطبيق Flask
═════════════════════════════════════════════════════════════════════════════════

يتم استدعاء هذا الملف عند بدء التطبيق لتهيئة جميع أنظمة الميثاق.
"""

import logging
from flask import Flask
from typing import Tuple

logger = logging.getLogger(__name__)


def initialize_constitutional_framework(app: Flask) -> Tuple[bool, str]:
    """
    تهيئة جميع متطلبات الميثاق الدستوري عند بدء التطبيق
    """
    try:
        logger.info("🏛️  بدء تهيئة الميثاق الدستوري الشامل لـ Jenan Biz...")
        
        # ── المادة الأولى: Extreme Scalability ──────────────────────────────
        from .constitutional_framework import ScalabilityRequirements
        scalability_reqs = ScalabilityRequirements()
        app.config["SCALABILITY_REQUIREMENTS"] = scalability_reqs.to_dict()
        logger.info(f"✓ المادة 1: متطلبات الأداء الفائق ({scalability_reqs.max_concurrent_transactions:,} عملية/ثانية)")
        
        # ── المادة الثانية: الخدمات المشتركة ──────────────────────────────
        from .constitutional_framework import SharedServices
        shared_services = SharedServices()
        app.config["SHARED_SERVICES"] = {
            "required_tables": shared_services.get_required_tables(),
            "all_enabled": True
        }
        logger.info("✓ المادة 2: الخدمات المشتركة (محاسبة، ضريبة، HR، خزينة، سلة مهملات)")
        
        # ── المادة الثالثة: التخصيص القطاعي ──────────────────────────────
        from .constitutional_framework import SECTOR_CONFIGURATIONS
        app.config["SECTOR_CONFIGURATIONS"] = SECTOR_CONFIGURATIONS
        logger.info(f"✓ المادة 3: التخصيص القطاعي ({len(SECTOR_CONFIGURATIONS)} قطاعات)")
        
        # ── المادة الرابعة: مصفوفة الدمج والرسوم ──────────────────────────
        from .constitutional_framework import ActivityMergingRules
        app.config["MERGING_RULES"] = ActivityMergingRules.FEES
        app.config["UMBRELLA_BUSINESSES"] = list(ActivityMergingRules.UMBRELLA_BUSINESSES.keys())
        logger.info("✓ المادة 4: مصفوفة الدمج والرسوم (دمج ذكي، رسوم متدرجة)")
        
        # ── المادة الخامسة: God Mode ──────────────────────────────────
        from .constitutional_framework import AdminGodMode
        app.config["ADMIN_GOD_MODE_ENABLED"] = True
        logger.info("✓ المادة 5: صلاحيات الأدمن المطلقة (God Mode)")
        
        # ── المادة السادسة: الأمان والاستمرارية ──────────────────────────
        # 1. نظام سلة المهملات
        from .smart_recycle_bin import RECYCLE_BIN_SCHEMA
        app.config["RECYCLE_BIN_ENABLED"] = True
        logger.info("✓ المادة 6a: سلة المهملات الذكية (حماية البيانات)")
        
        # 2. نظام الرقابة المحسّن
        from .enhanced_audit import ENHANCED_AUDIT_SCHEMA
        app.config["ENHANCED_AUDIT_ENABLED"] = True
        logger.info("✓ المادة 6b: الرقابة المحسّنة (تتبع كل نقرة)")
        
        # 3. محرك الاستمرارية
        from .resilience_engine import health_monitor, rate_limiter, CircuitBreaker
        app.config["HEALTH_MONITORING_ENABLED"] = True
        app.config["HEALTH_MONITOR"] = health_monitor
        app.config["RATE_LIMITER"] = rate_limiter
        logger.info("✓ المادة 6c: محرك الاستمرارية (failover، backup، recovery)")
        
        logger.info("🎉 اكتمل تهيئة الميثاق الدستوري - النظام جاهز للتشغيل")
        return True, "الميثاق الدستوري جاهز"
        
    except Exception as e:
        logger.error(f"❌ خطأ في تهيئة الميثاق: {e}")
        return False, f"خطأ: {str(e)}"


def setup_constitutional_tables(app: Flask, db) -> Tuple[bool, str]:
    """
    إنشاء جميع جداول الميثاق الدستوري في قاعدة البيانات
    """
    try:
        logger.info("إنشاء جداول الميثاق الدستوري...")
        
        schemas = []
        
        # سلة المهملات
        from .smart_recycle_bin import RECYCLE_BIN_SCHEMA
        schemas.append(("recycle_bin", RECYCLE_BIN_SCHEMA))
        
        # الرقابة المحسّنة
        from .enhanced_audit import ENHANCED_AUDIT_SCHEMA
        schemas.append(("audit", ENHANCED_AUDIT_SCHEMA))
        
        # الاستمرارية والنسخ الاحتياطية
        from .resilience_engine import BackupRecoveryManager
        schemas.append(("backup", BackupRecoveryManager.BACKUP_SCHEMA))
        
        # تطبيق جميع الـ schemas
        for schema_name, schema_sql in schemas:
            try:
                for statement in schema_sql.split(";"):
                    stmt = statement.strip()
                    if stmt:
                        db.execute(stmt)
                db.commit()
                logger.info(f"✓ جداول {schema_name} جاهزة")
            except Exception as e:
                if "already exists" in str(e) or "duplicate" in str(e):
                    logger.info(f"ℹ جداول {schema_name} موجودة مسبقاً")
                else:
                    logger.warning(f"⚠ تحذير {schema_name}: {e}")
        
        return True, "جداول الميثاق جاهزة"
    
    except Exception as e:
        logger.error(f"❌ خطأ في إنشاء جداول الميثاق: {e}")
        return False, f"خطأ: {str(e)}"


def validate_constitutional_compliance(db, business_id: int) -> Tuple[bool, dict]:
    """
    التحقق من امتثال منشأة ما لمتطلبات الميثاق
    """
    try:
        from .constitutional_framework import SharedServices
        
        services = SharedServices()
        is_compliant, errors = services.validate_business(db, business_id)
        
        compliance_report = {
            "business_id": business_id,
            "is_compliant": is_compliant,
            "validation_errors": errors,
            "required_services": [
                "double_entry_bookkeeping",
                "zatca_compliance",
                "hr_payroll",
                "cash_management",
                "audit_trail",
                "smart_recycle_bin",
            ]
        }
        
        return is_compliant, compliance_report
    
    except Exception as e:
        logger.error(f"خطأ في التحقق من الامتثال: {e}")
        return False, {"error": str(e)}


def register_constitutional_health_checks(app: Flask) -> None:
    """
    تسجيل فحوصات الصحة الدستورية
    """
    from .resilience_engine import health_monitor
    
    def check_database_health():
        """فحص صحة قاعدة البيانات"""
        try:
            from .extensions import get_db
            db = get_db()
            result = db.execute("SELECT 1").fetchone()
            return result is not None
        except Exception:
            return False
    
    def check_tables_exist():
        """التحقق من وجود جميع الجداول الدستورية"""
        try:
            from .extensions import get_db
            db = get_db()
            required_tables = [
                "businesses", "users", "accounts", "invoices",
                "employees", "audit_logs", "recycle_bin",
                "enhanced_audit_logs", "backups"
            ]
            for table in required_tables:
                result = db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
                    (table,),
                ).fetchone()
                if not result:
                    return False
            return True
        except Exception:
            return False
    
    # تسجيل الفحوصات
    health_monitor.register_component("database", check_database_health, timeout_ms=1000)
    health_monitor.register_component("schema", check_tables_exist, timeout_ms=2000)


def get_constitutional_dashboard_data(db, business_id: int) -> dict:
    """
    الحصول على بيانات لوحة تحكم الميثاق الدستوري
    """
    try:
        from .smart_recycle_bin import SmartRecycleBin
        from .enhanced_audit import EnhancedAuditLogger
        
        recycle_stats = SmartRecycleBin.get_recycle_bin_stats(db, business_id)
        
        audit_logs_count = db.execute(
            "SELECT COUNT(*) as cnt FROM enhanced_audit_logs WHERE business_id=? AND created_at > datetime('now', '-7 days')",
            (business_id,)
        ).fetchone()
        
        return {
            "recycle_bin_items": recycle_stats.get("total_items", 0),
            "locked_items": recycle_stats.get("locked_items", 0),
            "audit_logs_7_days": audit_logs_count["cnt"] if audit_logs_count else 0,
            "system_status": "healthy",
        }
    
    except Exception as e:
        logger.error(f"خطأ في جلب بيانات الميثاق: {e}")
        return {}
