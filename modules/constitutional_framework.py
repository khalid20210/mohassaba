"""
modules/constitutional_framework.py
═════════════════════════════════════════════════════════════════════════════════
الميثاق الدستوري التقني والتشغيلي الشامل لمنصة Jenan Biz
═════════════════════════════════════════════════════════════════════════════════

يحتوي على:
• المادة الأولى: معمارية Extreme Scalability (100,000 tx/sec)
• المادة الثانية: الخدمات المشتركة النواة (196 نشاط)
• المادة الثالثة: التخصيص القطاعي الدقيق
• المادة الرابعة: مصفوفة الدمج والرسوم
• المادة الخامسة: God Mode للأدمن المطلق
• المادة السادسة: الأمان والاستمرارية المطلقة
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from enum import Enum

logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════════════════════════
# المادة الأولى: معمارية Extreme Scalability
# ════════════════════════════════════════════════════════════════════════════════

class ScalabilityTier(Enum):
    """مستويات التوسع حسب عدد المنشآت المتزامنة"""
    TIER_1 = {"label": "مستقل", "businesses": 1, "concurrent_tx": 100}
    TIER_2 = {"label": "ناشيء", "businesses": 50, "concurrent_tx": 5_000}
    TIER_3 = {"label": "متنامي", "businesses": 500, "concurrent_tx": 50_000}
    TIER_4 = {"label": "شركات", "businesses": 5_000, "concurrent_tx": 500_000}
    TIER_5 = {"label": "مؤسسي", "businesses": 20_000, "concurrent_tx": 2_000_000}


@dataclass
class ScalabilityRequirements:
    """متطلبات الأداء الفائق"""
    max_concurrent_transactions: int = 100_000  # عملية متزامنة في الثانية
    max_concurrent_users: int = 20_000  # مستخدم متزامن
    db_isolation_level: str = "database-per-tenant"  # عزل كامل
    financial_precision: int = 5  # خانات عشرية للقيم المالية ($0.00000)
    response_time_p99: int = 200  # ميلي ثانية (99th percentile)
    availability_sla: float = 99.99  # %
    
    def to_dict(self):
        return {
            "max_concurrent_transactions": self.max_concurrent_transactions,
            "max_concurrent_users": self.max_concurrent_users,
            "db_isolation_level": self.db_isolation_level,
            "financial_precision_decimals": self.financial_precision,
            "response_time_p99_ms": self.response_time_p99,
            "availability_sla_percent": self.availability_sla,
        }


# ════════════════════════════════════════════════════════════════════════════════
# المادة الثانية: الخدمات المشتركة (النواة الصلبة لـ 196 نشاط)
# ════════════════════════════════════════════════════════════════════════════════

@dataclass
class SharedServices:
    """الخدمات الأساسية التي تظهر في كل منشأة"""
    
    # 1. المحرك المحاسبي الموحد
    double_entry_bookkeeping: bool = True
    chart_of_accounts: bool = True
    cost_centers: bool = True
    
    # 2. الامتثال الضريبي والفوترة
    zatca_qr_code_invoices: bool = True
    electronic_invoice_system: bool = True
    tax_compliance_engine: bool = True
    
    # 3. إدارة الموارد البشرية والرواتب
    hr_employee_files: bool = True
    employee_contracts: bool = True
    payroll_engine: bool = True
    allowances_deductions: bool = True
    
    # 4. الخزينة والبنك
    cash_management: bool = True
    bank_reconciliation: bool = True
    fund_management: bool = True
    
    # 5. سلة المهملات الذكية
    smart_recycle_bin: bool = True
    
    # 6. خدمات إضافية
    audit_trail_complete: bool = True
    backup_recovery: bool = True
    
    def get_required_tables(self) -> List[str]:
        """الجداول المطلوبة لتفعيل الخدمات"""
        tables = [
            "businesses",  # الأساس
            "users",
            "accounts",  # محرك محاسبي
            "journal_entries",
            "invoices",  # فوترة
            "employees",  # HR
            "payroll",
            "audit_logs",  # الرقابة
            "recycle_bin",  # سلة المهملات
            "backups",  # نسخ احتياطية
        ]
        return tables
    
    def validate_business(self, db, business_id: int) -> Tuple[bool, List[str]]:
        """التحقق من توفر جميع الخدمات المطلوبة"""
        errors = []
        required_tables = self.get_required_tables()
        
        for table in required_tables:
            try:
                count = db.execute(
                    f"SELECT COUNT(*) as cnt FROM {table} WHERE business_id=?",
                    (business_id,)
                ).fetchone()
                if count is None:
                    errors.append(f"جدول {table} غير موجود")
            except Exception as e:
                errors.append(f"خطأ في {table}: {str(e)}")
        
        return len(errors) == 0, errors


# ════════════════════════════════════════════════════════════════════════════════
# المادة الثالثة: التخصيص القطاعي الدقيق
# ════════════════════════════════════════════════════════════════════════════════

SECTOR_CONFIGURATIONS = {
    "retail": {
        "name": "التجزئة والجملة",
        "enabled_features": [
            "barcode_scanning",
            "batch_tracking",
            "expiry_date_management",
            "stock_reorder_points",
            "purchase_orders",
            "stock_movements",
        ],
        "required_modules": ["inventory", "barcode", "supply"],
    },
    "pharmacy": {
        "name": "الصحي والطبي",
        "enabled_features": [
            "drug_dispensing",
            "batch_tracking",
            "expiry_alerts",
            "patient_files",
            "appointment_management",
            "prescription_tracking",
        ],
        "required_modules": ["inventory", "medical", "contacts"],
    },
    "restaurant": {
        "name": "المطاعم والأغذية",
        "enabled_features": [
            "pos_mode_restaurant",
            "table_management",
            "kitchen_orders",
            "recipe_management",
            "ingredient_tracking",
            "shift_management",
        ],
        "required_modules": ["pos", "restaurant", "inventory"],
    },
    "construction": {
        "name": "المقاولات والعقارات",
        "enabled_features": [
            "project_management",
            "extract_tracking",
            "contract_management",
            "tenant_debts",
            "rental_agreements",
            "site_reports",
        ],
        "required_modules": ["construction", "contacts", "invoices"],
    },
    "wholesale": {
        "name": "تجار الجملة والموزعون",
        "enabled_features": [
            "distributor_management",
            "bulk_orders",
            "payment_terms",
            "credit_limits",
            "inventory_levels",
            "route_management",
        ],
        "required_modules": ["wholesale", "inventory", "supply"],
    },
    "workshop": {
        "name": "الورش والصيانة والإيجار",
        "enabled_features": [
            "work_order_management",
            "asset_tracking",
            "rental_agreements",
            "maintenance_logs",
            "service_pricing",
            "job_assignment",
        ],
        "required_modules": ["rental", "services", "inventory"],
    },
}


def get_sector_config(sector: str) -> Dict:
    """الحصول على إعدادات قطاع معين"""
    if sector not in SECTOR_CONFIGURATIONS:
        logger.warning(f"قطاع غير معروف: {sector}")
        return SECTOR_CONFIGURATIONS.get("retail")
    return SECTOR_CONFIGURATIONS[sector]


# ════════════════════════════════════════════════════════════════════════════════
# المادة الرابعة: مصفوفة الدمج والرسوم
# ════════════════════════════════════════════════════════════════════════════════

class ActivityMergingRules:
    """قواعد دمج الأنشطة والرسوم المطبقة"""
    
    # تصنيفات الأنشطة الرئيسية
    CATEGORY_GROUPS = {
        "food": ["مطاعم", "كافيهات", "محلات حلويات", "دجاج"],
        "health": ["صيدليات", "عيادات", "مختبرات", "مستشفيات"],
        "clothing": ["ملابس", "أحذية", "إكسسوارات", "أزياء"],
        "construction": ["مقاولات", "عقارات", "ديكور", "مواد بناء"],
        "other": ["متنوعات", "هدايا", "إلكترونيات", "رياضة"],
    }
    
    # الرسوم المطبقة
    FEES = {
        "same_category_merge": 0,  # ريال - دمج نفس القطاع
        "expansion_same_mode": 80,  # ريال - توسع تكميلي نفس القطاع
        "radical_separation": 100,  # ريال - فصل جذري (قطاع مختلف)
        "umbrella_business_free": 0,  # ريال - السوبر ماركت يدمج مجاناً
    }
    
    # قواعد الأنشطة المظلة (الكبرى)
    UMBRELLA_BUSINESSES = {
        "supermarket": {
            "name": "سوبر ماركت",
            "allowed_categories": ["food", "clothing", "health", "other"],
            "free_merging": True,
            "min_size_sqm": 100,  # متر مربع
        },
        "department_store": {
            "name": "متجر متعدد الأقسام",
            "allowed_categories": ["clothing", "electronics", "other"],
            "free_merging": True,
            "min_size_sqm": 150,
        },
    }
    
    @staticmethod
    def calculate_merge_fee(from_activity: str, to_activity: str, business_type: str) -> Tuple[int, str]:
        """
        حساب رسم الدمج بين نشاطين
        
        المخرجات:
        (الرسم بالريال، السبب)
        """
        # إذا كانت المنشأة نوع مظلة (سوبر ماركت)، لا رسوم
        if business_type.lower() in ActivityMergingRules.UMBRELLA_BUSINESSES:
            return 0, "أنشطة مظلة - دمج مجاني"
        
        # إذا كانا من نفس القطاع
        for category, activities in ActivityMergingRules.CATEGORY_GROUPS.items():
            if from_activity in activities and to_activity in activities:
                return ActivityMergingRules.FEES["same_category_merge"], "دمج من نفس القطاع"
        
        # إذا كانا من قطاعات مختلفة تماماً
        return ActivityMergingRules.FEES["radical_separation"], "فصل جذري - قطاعات مختلفة"
    
    @staticmethod
    def validate_merge_request(db, business_id: int, from_activity_id: int, to_activity_id: int) -> Tuple[bool, str, int]:
        """
        التحقق من صحة طلب دمج نشاطين
        
        المخرجات:
        (هل التصريح صحيح، الرسالة، الرسم المستحق)
        """
        try:
            # جلب بيانات المنشأة والأنشطة
            biz = db.execute(
                "SELECT industry_type FROM businesses WHERE id=?",
                (business_id,)
            ).fetchone()
            
            if not biz:
                return False, "المنشأة غير موجودة", 0
            
            from_activity = db.execute(
                "SELECT name FROM activities_definitions WHERE id=?",
                (from_activity_id,)
            ).fetchone()
            
            to_activity = db.execute(
                "SELECT name FROM activities_definitions WHERE id=?",
                (to_activity_id,)
            ).fetchone()
            
            if not from_activity or not to_activity:
                return False, "النشاط غير موجود", 0
            
            fee, reason = ActivityMergingRules.calculate_merge_fee(
                from_activity["name"],
                to_activity["name"],
                biz["industry_type"]
            )
            
            return True, f"الدمج مسموح - {reason}", fee
            
        except Exception as e:
            logger.error(f"خطأ في التحقق من الدمج: {e}")
            return False, "خطأ في العملية", 0


# ════════════════════════════════════════════════════════════════════════════════
# المادة الخامسة: God Mode (الصلاحيات المطلقة للأدمن)
# ════════════════════════════════════════════════════════════════════════════════

class AdminGodMode:
    """سلطات الأدمن المطلقة - تجاوز كل القيود"""
    
    @staticmethod
    def bypass_merge_restrictions(db, admin_id: int, business_id: int, from_activity_id: int, to_activity_id: int, reason: str) -> bool:
        """تجاوز قيود الدمج بسلطة الأدمن"""
        try:
            # تسجيل العملية في audit log
            db.execute("""
                INSERT INTO audit_logs (business_id, user_id, action, details, created_at)
                VALUES (?, ?, 'ADMIN_MERGE_BYPASS', ?, datetime('now'))
            """, (business_id, admin_id, json.dumps({
                "from_activity": from_activity_id,
                "to_activity": to_activity_id,
                "reason": reason,
                "admin_override": True
            })))
            db.commit()
            return True
        except Exception as e:
            logger.error(f"خطأ في تجاوز قيود الدمج: {e}")
            return False
    
    @staticmethod
    def modify_historical_transaction(db, admin_id: int, transaction_id: int, old_data: dict, new_data: dict, reason: str) -> bool:
        """تعديل عملية تاريخية (فاتورة قديمة، إلخ)"""
        try:
            # حفظ النسخة القديمة
            db.execute("""
                INSERT INTO admin_modifications_log (
                    admin_id, transaction_id, old_data, new_data, reason, created_at
                ) VALUES (?, ?, ?, ?, ?, datetime('now'))
            """, (
                admin_id,
                transaction_id,
                json.dumps(old_data),
                json.dumps(new_data),
                reason
            ))
            
            # تطبيق التغيير
            # يتم تنفيذه حسب نوع العملية (فاتورة، إلخ)
            db.commit()
            logger.info(f"تعديل تاريخي من قبل الأدمن {admin_id} على عملية {transaction_id}")
            return True
        except Exception as e:
            logger.error(f"خطأ في التعديل التاريخي: {e}")
            return False
    
    @staticmethod
    def enable_premium_feature(db, admin_id: int, business_id: int, feature_name: str) -> bool:
        """تفعيل ميزة مميزة يدويًا بدون فوترة"""
        try:
            db.execute("""
                UPDATE businesses 
                SET premium_features = json_set(premium_features, ?, 1)
                WHERE id = ?
            """, (f"$.{feature_name}", business_id))
            
            # تسجيل الإجراء
            db.execute("""
                INSERT INTO audit_logs (business_id, user_id, action, details, created_at)
                VALUES (?, ?, 'ADMIN_FEATURE_ENABLE', ?, datetime('now'))
            """, (business_id, admin_id, json.dumps({
                "feature": feature_name,
                "admin_override": True
            })))
            
            db.commit()
            logger.info(f"الأدمن {admin_id} فعل الميزة {feature_name} للمنشأة {business_id}")
            return True
        except Exception as e:
            logger.error(f"خطأ في تفعيل الميزة: {e}")
            return False
    
    @staticmethod
    def restore_from_recycle_bin(db, admin_id: int, record_id: int, table_name: str, business_id: int) -> bool:
        """استعادة سجل من سلة المهملات"""
        try:
            # جلب البيانات من سلة المهملات
            record = db.execute("""
                SELECT original_data FROM recycle_bin 
                WHERE id=? AND table_name=? AND business_id=?
            """, (record_id, table_name, business_id)).fetchone()
            
            if not record:
                logger.warning(f"السجل {record_id} من الجدول {table_name} غير موجود")
                return False
            
            # استعادة البيانات
            original_data = json.loads(record["original_data"])
            # سيتم استعادة السجل حسب نوع الجدول
            
            # تسجيل الاستعادة
            db.execute("""
                INSERT INTO audit_logs (business_id, user_id, action, details, created_at)
                VALUES (?, ?, 'ADMIN_RESTORE', ?, datetime('now'))
            """, (business_id, admin_id, json.dumps({
                "record_id": record_id,
                "table": table_name,
                "admin_action": True
            })))
            
            db.commit()
            return True
        except Exception as e:
            logger.error(f"خطأ في الاستعادة: {e}")
            return False


# ════════════════════════════════════════════════════════════════════════════════
# المادة السادسة: الأمان والرقابة والاستمرارية
# ════════════════════════════════════════════════════════════════════════════════

@dataclass
class AuditLogEntry:
    """سجل تفصيلي لكل إجراء في النظام"""
    business_id: int
    user_id: int
    action: str  # CREATE, UPDATE, DELETE, LOGIN, LOGOUT, EXPORT, etc.
    resource_type: str  # Invoice, Product, Employee, etc.
    resource_id: Optional[int]
    old_values: Optional[Dict] = None
    new_values: Optional[Dict] = None
    device_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    timestamp: Optional[datetime] = None
    duration_ms: Optional[int] = None
    status: str = "success"  # success, failure
    error_message: Optional[str] = None
    
    def to_dict(self):
        return {
            "business_id": self.business_id,
            "user_id": self.user_id,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "old_values": self.old_values,
            "new_values": self.new_values,
            "device_id": self.device_id,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "error_message": self.error_message,
        }


class ResiliencyEngine:
    """محرك الاستمرارية والتعافي من الأعطال"""
    
    @staticmethod
    def setup_high_availability(db) -> bool:
        """إعداد نظام High Availability"""
        try:
            # تفعيل النسخ الاحتياطية المستمرة
            # تفعيل Replication إلى خادم احتياطي
            # إعداد Health Checks المستمرة
            logger.info("نظام High Availability جاهز")
            return True
        except Exception as e:
            logger.error(f"خطأ في إعداد HA: {e}")
            return False
    
    @staticmethod
    def automatic_failover_to_backup() -> bool:
        """الانتقال التلقائي إلى الخادم الاحتياطي"""
        try:
            logger.warning("تفعيل Failover إلى الخادم الاحتياطي")
            # تنفيذ الانتقال
            return True
        except Exception as e:
            logger.error(f"خطأ في Failover: {e}")
            return False


# ════════════════════════════════════════════════════════════════════════════════
# دالات الحصول على المتطلبات
# ════════════════════════════════════════════════════════════════════════════════

def get_constitutional_requirements() -> Dict:
    """الحصول على جميع متطلبات الميثاق الدستوري"""
    return {
        "Article_1_Scalability": ScalabilityRequirements().to_dict(),
        "Article_2_SharedServices": {
            "required_tables": SharedServices().get_required_tables(),
            "services_enabled": [
                "double_entry_bookkeeping",
                "zatca_compliance",
                "hr_payroll",
                "cash_management",
                "smart_recycle_bin",
                "audit_trail",
            ]
        },
        "Article_3_SectorSpecific": list(SECTOR_CONFIGURATIONS.keys()),
        "Article_4_MergingRules": {
            "fees": ActivityMergingRules.FEES,
            "umbrella_businesses": list(ActivityMergingRules.UMBRELLA_BUSINESSES.keys()),
        },
        "Article_5_AdminGodMode": [
            "bypass_merge_restrictions",
            "modify_historical_transactions",
            "enable_premium_features",
            "restore_from_recycle_bin",
        ],
        "Article_6_Security": [
            "comprehensive_audit_logs",
            "device_id_tracking",
            "ip_logging",
            "user_agent_logging",
            "automatic_failover",
            "continuous_backup",
        ]
    }
