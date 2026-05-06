"""
modules/blueprints/admin/routes.py
═════════════════════════════════════════════════════════════════════════════════
لوحة تحكم الأدمن - God Mode
═════════════════════════════════════════════════════════════════════════════════

تفعيل صلاحيات الأدمن المطلقة حسب المادة الخامسة من الميثاق الدستوري
"""

import json
import logging
from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, g
from datetime import datetime, timedelta

from modules.extensions import get_db
from modules.middleware import admin_required
from modules.constitutional_framework import (
    AdminGodMode,
    ActivityMergingRules,
    get_constitutional_requirements
)
from modules.smart_recycle_bin import SmartRecycleBin
from modules.enhanced_audit import EnhancedAuditLogger

logger = logging.getLogger(__name__)

bp = Blueprint("admin", __name__, url_prefix="/admin")


# ════════════════════════════════════════════════════════════════════════════════
# الصفحة الرئيسية للأدمن
# ════════════════════════════════════════════════════════════════════════════════

@bp.route("/", methods=["GET"])
@admin_required
def admin_dashboard():
    """لوحة التحكم الرئيسية للأدمن"""
    db = get_db()
    
    # إحصائيات النظام
    businesses_count = db.execute("SELECT COUNT(*) as cnt FROM businesses").fetchone()
    users_count = db.execute("SELECT COUNT(*) as cnt FROM users").fetchone()
    invoices_total = db.execute("SELECT SUM(total) as sum FROM invoices").fetchone()
    
    # سجل الرقابة الأخير
    recent_audits = db.execute("""
        SELECT * FROM enhanced_audit_logs 
        ORDER BY created_at DESC LIMIT 20
    """).fetchall()
    
    # تنبيهات الأمان
    security_alerts = db.execute("""
        SELECT * FROM security_alerts 
        WHERE acknowledged_at IS NULL
        ORDER BY created_at DESC LIMIT 10
    """).fetchall()
    
    return render_template("admin/dashboard.html",
        businesses_count=businesses_count["cnt"],
        users_count=users_count["cnt"],
        invoices_total=invoices_total["sum"] or 0,
        recent_audits=recent_audits,
        security_alerts=security_alerts,
        constitutional_requirements=get_constitutional_requirements()
    )


# ════════════════════════════════════════════════════════════════════════════════
# المادة الخامسة: تجاوز قيود الدمج
# ════════════════════════════════════════════════════════════════════════════════

@bp.route("/bypass-merge", methods=["GET", "POST"])
@admin_required
def bypass_merge_restrictions():
    """تجاوز قيود الدمج والرسوم"""
    db = get_db()
    admin_id = session.get("user_id")
    
    if request.method == "POST":
        try:
            business_id = int(request.form.get("business_id"))
            from_activity_id = int(request.form.get("from_activity_id"))
            to_activity_id = int(request.form.get("to_activity_id"))
            reason = request.form.get("reason", "تجاوز من الأدمن")
            
            # تطبيق التجاوز
            success = AdminGodMode.bypass_merge_restrictions(
                db, admin_id, business_id, from_activity_id, to_activity_id, reason
            )
            
            if success:
                return jsonify({"success": True, "message": "تم التجاوز بنجاح"})
            else:
                return jsonify({"success": False, "message": "خطأ في التجاوز"})
        
        except Exception as e:
            logger.error(f"خطأ في تجاوز الدمج: {e}")
            return jsonify({"success": False, "message": str(e)}), 400
    
    # GET - عرض النموذج
    businesses = db.execute("SELECT id, name FROM businesses LIMIT 20").fetchall()
    activities = db.execute("SELECT id, name FROM activities_definitions ORDER BY name LIMIT 50").fetchall()
    
    return render_template("admin/bypass_merge.html",
        businesses=businesses,
        activities=activities
    )


# ════════════════════════════════════════════════════════════════════════════════
# تعديل البيانات التاريخية
# ════════════════════════════════════════════════════════════════════════════════

@bp.route("/modify-historical", methods=["GET", "POST"])
@admin_required
def modify_historical_transaction():
    """تعديل عملية تاريخية (فاتورة قديمة، إلخ)"""
    db = get_db()
    admin_id = session.get("user_id")
    
    if request.method == "POST":
        try:
            transaction_id = int(request.form.get("transaction_id"))
            old_data = json.loads(request.form.get("old_data", "{}"))
            new_data = json.loads(request.form.get("new_data", "{}"))
            reason = request.form.get("reason", "تعديل إداري")
            
            success = AdminGodMode.modify_historical_transaction(
                db, admin_id, transaction_id, old_data, new_data, reason
            )
            
            if success:
                return jsonify({"success": True, "message": "تم التعديل بنجاح"})
            else:
                return jsonify({"success": False, "message": "خطأ في التعديل"})
        
        except Exception as e:
            logger.error(f"خطأ في التعديل التاريخي: {e}")
            return jsonify({"success": False, "message": str(e)}), 400
    
    return render_template("admin/modify_historical.html")


# ════════════════════════════════════════════════════════════════════════════════
# تفعيل الميزات المميزة
# ════════════════════════════════════════════════════════════════════════════════

@bp.route("/enable-premium", methods=["GET", "POST"])
@admin_required
def enable_premium_feature():
    """تفعيل ميزات مميزة يدويًا"""
    db = get_db()
    admin_id = session.get("user_id")
    
    if request.method == "POST":
        try:
            business_id = int(request.form.get("business_id"))
            feature_name = request.form.get("feature_name")
            
            success = AdminGodMode.enable_premium_feature(
                db, admin_id, business_id, feature_name
            )
            
            if success:
                return jsonify({"success": True, "message": f"تم تفعيل {feature_name}"})
            else:
                return jsonify({"success": False, "message": "خطأ في التفعيل"})
        
        except Exception as e:
            logger.error(f"خطأ في تفعيل الميزة: {e}")
            return jsonify({"success": False, "message": str(e)}), 400
    
    businesses = db.execute("SELECT id, name FROM businesses LIMIT 20").fetchall()
    premium_features = [
        "ai_analytics",
        "delivery_app_integration",
        "advanced_reporting",
        "api_access",
        "white_label",
        "advanced_security",
    ]
    
    return render_template("admin/enable_premium.html",
        businesses=businesses,
        premium_features=premium_features
    )


# ════════════════════════════════════════════════════════════════════════════════
# إدارة سلة المهملات
# ════════════════════════════════════════════════════════════════════════════════

@bp.route("/recycle-bin", methods=["GET"])
@admin_required
def recycle_bin_admin():
    """عرض سلة المهملات للإدارة"""
    db = get_db()
    
    page = int(request.args.get("page", 1))
    per_page = 50
    offset = (page - 1) * per_page
    
    # الحصول على السجلات
    records = db.execute("""
        SELECT * FROM recycle_bin 
        ORDER BY deleted_at DESC 
        LIMIT ? OFFSET ?
    """, (per_page, offset)).fetchall()
    
    # إجمالي العدد
    total = db.execute("SELECT COUNT(*) as cnt FROM recycle_bin").fetchone()
    
    return render_template("admin/recycle_bin.html",
        records=records,
        total=total["cnt"],
        page=page,
        per_page=per_page,
        pages=((total["cnt"] + per_page - 1) // per_page)
    )


@bp.route("/recycle-bin/restore/<int:record_id>", methods=["POST"])
@admin_required
def restore_recycle_record(record_id):
    """استعادة سجل من السلة"""
    db = get_db()
    admin_id = session.get("user_id")
    
    try:
        record = db.execute(
            "SELECT business_id, table_name FROM recycle_bin WHERE id=?",
            (record_id,)
        ).fetchone()
        
        if not record:
            return jsonify({"success": False, "message": "السجل غير موجود"}), 404
        
        success, message = SmartRecycleBin.restore_from_bin(
            db, record["business_id"], record_id, record["table_name"], admin_id
        )
        
        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "message": message}), 400
    
    except Exception as e:
        logger.error(f"خطأ في الاستعادة: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@bp.route("/recycle-bin/delete/<int:record_id>", methods=["POST"])
@admin_required
def permanently_delete_record(record_id):
    """حذف دائم من السلة"""
    db = get_db()
    admin_id = session.get("user_id")
    
    try:
        record = db.execute(
            "SELECT business_id, table_name FROM recycle_bin WHERE id=?",
            (record_id,)
        ).fetchone()
        
        if not record:
            return jsonify({"success": False, "message": "السجل غير موجود"}), 404
        
        reason = request.form.get("reason", "حذف إداري")
        success, message = SmartRecycleBin.permanently_delete(
            db, record["business_id"], record_id, record["table_name"], admin_id, reason
        )
        
        if success:
            return jsonify({"success": True, "message": message})
        else:
            return jsonify({"success": False, "message": message}), 400
    
    except Exception as e:
        logger.error(f"خطأ في الحذف الدائم: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


# ════════════════════════════════════════════════════════════════════════════════
# سجل الرقابة الشامل
# ════════════════════════════════════════════════════════════════════════════════

@bp.route("/audit-logs", methods=["GET"])
@admin_required
def view_audit_logs():
    """عرض جميع سجلات الرقابة"""
    db = get_db()
    
    page = int(request.args.get("page", 1))
    per_page = 100
    offset = (page - 1) * per_page
    
    filters = {}
    if request.args.get("user_id"):
        filters["user_id"] = int(request.args.get("user_id"))
    if request.args.get("action"):
        filters["action"] = request.args.get("action")
    
    logs = EnhancedAuditLogger.get_audit_logs(
        db, 0,  # 0 = جميع المنشآت
        filters=filters,
        limit=per_page,
        offset=offset
    )
    
    total = db.execute("SELECT COUNT(*) as cnt FROM enhanced_audit_logs").fetchone()
    
    return render_template("admin/audit_logs.html",
        logs=logs,
        total=total["cnt"],
        page=page,
        per_page=per_page,
        pages=((total["cnt"] + per_page - 1) // per_page)
    )


# ════════════════════════════════════════════════════════════════════════════════
# تنبيهات الأمان
# ════════════════════════════════════════════════════════════════════════════════

@bp.route("/security-alerts", methods=["GET"])
@admin_required
def security_alerts():
    """عرض تنبيهات الأمان"""
    db = get_db()
    
    alerts = db.execute("""
        SELECT * FROM security_alerts 
        ORDER BY created_at DESC LIMIT 100
    """).fetchall()
    
    return render_template("admin/security_alerts.html", alerts=alerts)


@bp.route("/security-alerts/<int:alert_id>/acknowledge", methods=["POST"])
@admin_required
def acknowledge_alert(alert_id):
    """تأكيد الاطلاع على تنبيه أمان"""
    db = get_db()
    admin_id = session.get("user_id")
    
    try:
        db.execute(
            "UPDATE security_alerts SET acknowledged_at=datetime('now'), acknowledged_by=? WHERE id=?",
            (admin_id, alert_id)
        )
        db.commit()
        return jsonify({"success": True, "message": "تم تأكيد الاطلاع"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


# ════════════════════════════════════════════════════════════════════════════════
# صحة النظام والاستمرارية
# ════════════════════════════════════════════════════════════════════════════════

@bp.route("/system-health", methods=["GET"])
@admin_required
def system_health():
    """تقرير صحة النظام"""
    from modules.resilience_engine import health_monitor
    
    # فحص جميع المكونات
    for component_name in health_monitor.components.keys():
        health_monitor.check_component(component_name)
    
    health_report = health_monitor.get_health_report()
    
    return render_template("admin/system_health.html", report=health_report)


# ════════════════════════════════════════════════════════════════════════════════
# النسخ الاحتياطية
# ════════════════════════════════════════════════════════════════════════════════

@bp.route("/backups", methods=["GET", "POST"])
@admin_required
def manage_backups():
    """إدارة النسخ الاحتياطية"""
    db = get_db()
    admin_id = session.get("user_id")
    
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "create":
            business_id = int(request.form.get("business_id") or 0)
            backup_type = request.form.get("backup_type", "full")
            
            from modules.resilience_engine import BackupRecoveryManager
            manager = BackupRecoveryManager("backups/")
            success, message = manager.create_backup(db, business_id, backup_type)
            
            return jsonify({"success": success, "message": message})
    
    backups = db.execute("""
        SELECT * FROM backups 
        ORDER BY created_at DESC LIMIT 50
    """).fetchall()
    
    businesses = db.execute("SELECT id, name FROM businesses LIMIT 20").fetchall()
    
    return render_template("admin/backups.html",
        backups=backups,
        businesses=businesses
    )
