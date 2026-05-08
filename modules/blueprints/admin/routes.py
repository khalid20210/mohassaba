"""
modules/blueprints/admin/routes.py
لوحة تحكم مالك البرنامج (Platform Super Admin)
"""

import csv
import io
import json
import logging
from datetime import datetime

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from modules.constitutional_framework import AdminGodMode, get_constitutional_requirements
from modules.enhanced_audit import EnhancedAuditLogger
from modules.extensions import csrf_protect, get_db
from modules.middleware import admin_required
from modules.smart_recycle_bin import SmartRecycleBin

logger = logging.getLogger(__name__)

bp = Blueprint("admin", __name__, url_prefix="/admin")


def _table_exists(db, table_name: str) -> bool:
    row = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _column_exists(db, table_name: str, column_name: str) -> bool:
    try:
        cols = db.execute(f"PRAGMA table_info({table_name})").fetchall()
        return any((c[1] if not isinstance(c, dict) else c.get("name")) == column_name for c in cols)
    except Exception:
        return False


def _safe_scalar(db, query: str, params=(), default=0):
    try:
        row = db.execute(query, params).fetchone()
        if not row:
            return default
        if isinstance(row, dict):
            return list(row.values())[0] if row else default
        return row[0]
    except Exception:
        return default


def _safe_fetchone(db, query: str, params=()):
    try:
        return db.execute(query, params).fetchone()
    except Exception:
        return None


def _safe_fetchall(db, query: str, params=()):
    try:
        return db.execute(query, params).fetchall()
    except Exception:
        return []


def _rows_to_dicts(rows):
    out = []
    for row in rows or []:
        try:
            out.append(dict(row))
        except Exception:
            out.append(row)
    return out


def _ensure_admin_tables(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_features (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER,
            feature_name TEXT NOT NULL,
            is_enabled INTEGER NOT NULL DEFAULT 1,
            updated_by INTEGER,
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(business_id, feature_name)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_releases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version TEXT NOT NULL,
            title TEXT NOT NULL,
            notes TEXT,
            is_mandatory INTEGER NOT NULL DEFAULT 0,
            created_by INTEGER,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT,
            updated_by INTEGER,
            updated_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_sector_overrides (
            sector_key  TEXT PRIMARY KEY,
            is_enabled  INTEGER NOT NULL DEFAULT 1,
            custom_name TEXT
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_sidebar_overrides (
            sector_key TEXT NOT NULL,
            item_key   TEXT NOT NULL,
            is_enabled INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (sector_key, item_key)
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS marketing_badges (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            badge_text  TEXT NOT NULL,
            badge_color TEXT NOT NULL DEFAULT '#ffffff',
            badge_bg    TEXT NOT NULL DEFAULT '#dc2626',
            badge_icon  TEXT DEFAULT '🔥',
            badge_type  TEXT DEFAULT 'offer',
            sector_key  TEXT,
            show_on_login    INTEGER NOT NULL DEFAULT 1,
            show_on_register INTEGER NOT NULL DEFAULT 1,
            is_active   INTEGER NOT NULL DEFAULT 1,
            sort_order  INTEGER NOT NULL DEFAULT 0,
            expires_at  TEXT,
            created_by  INTEGER,
            created_at  TEXT DEFAULT (datetime('now'))
        )
        """
    )
    if _table_exists(db, "businesses") and not _column_exists(db, "businesses", "account_status"):
        try:
            db.execute("ALTER TABLE businesses ADD COLUMN account_status TEXT DEFAULT 'approved'")
        except Exception:
            pass
    db.commit()


def _read_uploaded_product_rows(file_storage):
    filename = (file_storage.filename or "").lower()
    payload = file_storage.read()

    if filename.endswith(".csv") or filename.endswith(".txt"):
        text = payload.decode("utf-8-sig", errors="replace")
        first_line = text.splitlines()[0] if text.splitlines() else ""
        delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        return [dict(r or {}) for r in reader]

    if filename.endswith(".xlsx"):
        try:
            import openpyxl
        except Exception as exc:
            raise ValueError("رفع XLSX يحتاج تثبيت openpyxl") from exc

        wb = openpyxl.load_workbook(io.BytesIO(payload), data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []

        headers = [str(h or "").strip() for h in rows[0]]
        out = []
        for values in rows[1:]:
            item = {}
            for i, h in enumerate(headers):
                item[h] = "" if i >= len(values) or values[i] is None else str(values[i]).strip()
            out.append(item)
        return out

    raise ValueError("صيغة ملف غير مدعومة. استخدم CSV أو XLSX")


def _normalize_col_name(value: str) -> str:
    return (value or "").strip().lower().replace("_", "").replace("-", "").replace(" ", "")


def _extract_first(row: dict, aliases: list[str]) -> str:
    normalized = {_normalize_col_name(k): (v or "") for k, v in row.items()}
    for alias in aliases:
        val = normalized.get(_normalize_col_name(alias), "")
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _to_float(val) -> float:
    raw = str(val or "").strip().replace(",", "")
    if not raw:
        return 0.0
    try:
        return float(raw)
    except Exception:
        return 0.0


def _normalize_uploaded_product(row: dict):
    name = _extract_first(row, ["الاسم", "اسم المنتج", "name", "product name"])
    if not name:
        return None

    barcode = _extract_first(row, ["الباركود", "barcode", "ean", "sku"]) or ""
    barcode = barcode.replace(" ", "").replace('"', "")

    price = _to_float(_extract_first(row, ["السعر", "سعر البيع", "sale_price", "price"]))
    description = _extract_first(row, ["الوصف", "description", "desc"]) or ""
    category_name = _extract_first(row, ["صنف المنتج", "التصنيف", "category", "category_name"]) or "منتجات عامة"

    return {
        "name": name,
        "barcode": barcode,
        "price": price,
        "description": description,
        "category_name": category_name,
    }


@bp.route("/", methods=["GET"])
@admin_required
def admin_dashboard():
    """لوحة التحكم الرئيسية لمالك البرنامج"""
    db = get_db()
    _ensure_admin_tables(db)

    businesses_count = int(_safe_scalar(db, "SELECT COUNT(*) FROM businesses", default=0) or 0)
    users_count      = int(_safe_scalar(db, "SELECT COUNT(*) FROM users", default=0) or 0)
    invoices_count   = int(_safe_scalar(db, "SELECT COUNT(*) FROM invoices", default=0) or 0)
    invoices_total   = float(_safe_scalar(db, "SELECT COALESCE(SUM(total),0) FROM invoices", default=0) or 0)
    products_count   = int(_safe_scalar(db, "SELECT COUNT(*) FROM products", default=0) or 0)
    contacts_count   = int(_safe_scalar(db, "SELECT COUNT(*) FROM contacts", default=0) or 0)

    # منشآت نشطة آخر 24 ساعة
    active_today = int(_safe_scalar(
        db, "SELECT COUNT(DISTINCT business_id) FROM invoices WHERE created_at >= datetime('now','-1 day')", default=0
    ) or 0)

    # إجمالي العمليات اليوم
    ops_today = int(_safe_scalar(
        db, "SELECT COUNT(*) FROM invoices WHERE date(created_at) = date('now')", default=0
    ) or 0)

    pending_registrations = 0
    if _table_exists(db, "businesses") and _column_exists(db, "businesses", "account_status"):
        pending_registrations = int(
            _safe_scalar(db, "SELECT COUNT(*) FROM businesses WHERE account_status='pending'", default=0) or 0
        )

    # آخر 5 منشآت مسجلة
    recent_businesses = _rows_to_dicts(_safe_fetchall(
        db,
        "SELECT id, name, industry_type, created_at FROM businesses ORDER BY created_at DESC LIMIT 5"
    ))

    # توزيع القطاعات
    sector_dist = _rows_to_dicts(_safe_fetchall(
        db,
        "SELECT industry_type, COUNT(*) as cnt FROM businesses GROUP BY industry_type ORDER BY cnt DESC LIMIT 10"
    ))

    recent_audits = []
    if _table_exists(db, "enhanced_audit_logs"):
        recent_audits = _safe_fetchall(
            db, "SELECT action, actor_name, created_at, business_id FROM enhanced_audit_logs ORDER BY created_at DESC LIMIT 15"
        )
    elif _table_exists(db, "audit_logs"):
        recent_audits = _safe_fetchall(
            db, "SELECT action, actor_name, created_at, business_id FROM audit_logs ORDER BY created_at DESC LIMIT 15"
        )

    security_alerts = []
    if _table_exists(db, "security_alerts"):
        security_alerts = _safe_fetchall(
            db, "SELECT * FROM security_alerts WHERE acknowledged_at IS NULL ORDER BY created_at DESC LIMIT 10"
        )

    latest_releases = _safe_fetchall(
        db, "SELECT version, title, is_mandatory, created_at FROM platform_releases ORDER BY created_at DESC LIMIT 5"
    )

    return render_template(
        "admin/dashboard.html",
        businesses_count=businesses_count,
        users_count=users_count,
        invoices_count=invoices_count,
        invoices_total=invoices_total,
        products_count=products_count,
        contacts_count=contacts_count,
        active_today=active_today,
        ops_today=ops_today,
        pending_registrations=pending_registrations,
        recent_businesses=recent_businesses,
        sector_dist=sector_dist,
        recent_audits=_rows_to_dicts(recent_audits),
        security_alerts=_rows_to_dicts(security_alerts),
        latest_releases=_rows_to_dicts(latest_releases),
        constitutional_requirements=get_constitutional_requirements(),
    )



@bp.route("/registrations", methods=["GET"])
@admin_required
def registrations_page():
    """طلبات التسجيل على مستوى المنصة"""
    db = get_db()
    _ensure_admin_tables(db)

    pending = _safe_fetchall(
        db,
        """
        SELECT b.id AS biz_id, b.name AS biz_name, b.created_at, b.country_code,
               u.username, u.full_name, u.email
        FROM businesses b
        JOIN users u ON u.business_id = b.id
        WHERE b.account_status = 'pending'
        ORDER BY b.created_at DESC
        """,
    )

    history = _safe_fetchall(
        db,
        """
        SELECT b.id AS biz_id, b.name AS biz_name, b.created_at, b.country_code,
               b.account_status,
               u.username, u.full_name, u.email
        FROM businesses b
        JOIN users u ON u.business_id = b.id
        WHERE b.account_status IN ('approved','rejected')
        ORDER BY b.created_at DESC
        LIMIT 100
        """,
    )

    return render_template(
        "admin/registrations.html",
        pending=_rows_to_dicts(pending),
        history=_rows_to_dicts(history),
    )


@bp.route("/registrations/approve", methods=["POST"])
@admin_required
def approve_registration():
    guard = csrf_protect()
    if guard:
        return guard

    db = get_db()
    _ensure_admin_tables(db)
    biz_id = request.form.get("biz_id", "").strip()
    if not biz_id.isdigit():
        flash("طلب غير صالح", "error")
        return redirect(url_for("admin.registrations_page"))

    biz_id = int(biz_id)
    db.execute("UPDATE businesses SET account_status='approved', is_active=1 WHERE id=?", (biz_id,))
    db.execute("UPDATE users SET is_active=1 WHERE business_id=?", (biz_id,))
    db.commit()

    flash("تمت الموافقة على طلب التسجيل وتفعيل الحساب.", "success")
    return redirect(url_for("admin.registrations_page"))


@bp.route("/registrations/reject", methods=["POST"])
@admin_required
def reject_registration():
    guard = csrf_protect()
    if guard:
        return guard

    db = get_db()
    _ensure_admin_tables(db)
    biz_id = request.form.get("biz_id", "").strip()
    if not biz_id.isdigit():
        flash("طلب غير صالح", "error")
        return redirect(url_for("admin.registrations_page"))

    biz_id = int(biz_id)
    db.execute("UPDATE businesses SET account_status='rejected' WHERE id=?", (biz_id,))
    db.commit()

    flash("تم رفض طلب التسجيل.", "info")
    return redirect(url_for("admin.registrations_page"))


@bp.route("/bypass-merge", methods=["GET", "POST"])
@admin_required
def bypass_merge_restrictions():
    """تجاوز قيود الدمج والرسوم"""
    db = get_db()
    admin_id = session.get("user_id")

    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard
        try:
            business_id = int(request.form.get("business_id"))
            from_activity_id = int(request.form.get("from_activity_id"))
            to_activity_id = int(request.form.get("to_activity_id"))
            reason = request.form.get("reason", "تجاوز من الأدمن")

            success = AdminGodMode.bypass_merge_restrictions(
                db, admin_id, business_id, from_activity_id, to_activity_id, reason
            )
            if success:
                return jsonify({"success": True, "message": "تم التجاوز بنجاح"})
            return jsonify({"success": False, "message": "خطأ في التجاوز"})
        except Exception as exc:
            logger.error("خطأ في تجاوز الدمج: %s", exc)
            return jsonify({"success": False, "message": str(exc)}), 400

    businesses = _safe_fetchall(db, "SELECT id, name FROM businesses ORDER BY id DESC LIMIT 50")
    activities = _safe_fetchall(db, "SELECT id, name FROM activities_definitions ORDER BY name LIMIT 100")
    return render_template(
        "admin/bypass_merge.html",
        businesses=_rows_to_dicts(businesses),
        activities=_rows_to_dicts(activities),
    )


@bp.route("/modify-historical", methods=["GET", "POST"])
@admin_required
def modify_historical_transaction():
    """تعديل عملية تاريخية"""
    db = get_db()
    admin_id = session.get("user_id")

    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard
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
            return jsonify({"success": False, "message": "خطأ في التعديل"})
        except Exception as exc:
            logger.error("خطأ في التعديل التاريخي: %s", exc)
            return jsonify({"success": False, "message": str(exc)}), 400

    return render_template("admin/modify_historical.html")


@bp.route("/enable-premium", methods=["GET", "POST"])
@admin_required
def enable_premium_feature():
    """تفعيل ميزات مميزة يدويًا"""
    db = get_db()
    _ensure_admin_tables(db)
    admin_id = session.get("user_id")

    premium_features = [
        "ai_analytics",
        "delivery_app_integration",
        "advanced_reporting",
        "api_access",
        "white_label",
        "advanced_security",
    ]

    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard
        try:
            business_id = int(request.form.get("business_id"))
            feature_name = request.form.get("feature_name", "").strip()
            if feature_name not in premium_features:
                return jsonify({"success": False, "message": "ميزة غير معروفة"}), 400

            success = AdminGodMode.enable_premium_feature(db, admin_id, business_id, feature_name)

            db.execute(
                """
                INSERT INTO platform_features (business_id, feature_name, is_enabled, updated_by, updated_at)
                VALUES (?, ?, 1, ?, datetime('now'))
                ON CONFLICT(business_id, feature_name) DO UPDATE
                SET is_enabled=1, updated_by=excluded.updated_by, updated_at=excluded.updated_at
                """,
                (business_id, feature_name, admin_id),
            )
            db.commit()

            if success:
                return jsonify({"success": True, "message": f"تم تفعيل {feature_name}"})
            return jsonify({"success": True, "message": f"تم حفظ تفعيل {feature_name} على المنصة"})
        except Exception as exc:
            logger.error("خطأ في تفعيل الميزة: %s", exc)
            return jsonify({"success": False, "message": str(exc)}), 400

    businesses = _safe_fetchall(db, "SELECT id, name FROM businesses ORDER BY id DESC LIMIT 100")
    return render_template(
        "admin/enable_premium.html",
        businesses=_rows_to_dicts(businesses),
        premium_features=premium_features,
    )


@bp.route("/feature-flags", methods=["GET", "POST"])
@admin_required
def feature_flags():
    """إدارة flags للمزايا على مستوى المنصة/المنشآت"""
    db = get_db()
    _ensure_admin_tables(db)
    admin_id = session.get("user_id")

    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard

        feature_name = request.form.get("feature_name", "").strip()
        enabled = 1 if request.form.get("is_enabled") else 0
        business_id_raw = request.form.get("business_id", "").strip()
        business_id = int(business_id_raw) if business_id_raw.isdigit() else 0

        if not feature_name:
            flash("اسم الميزة مطلوب", "error")
            return redirect(url_for("admin.feature_flags"))

        db.execute(
            """
            INSERT INTO platform_features (business_id, feature_name, is_enabled, updated_by, updated_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(business_id, feature_name) DO UPDATE
            SET is_enabled=excluded.is_enabled, updated_by=excluded.updated_by, updated_at=excluded.updated_at
            """,
            (business_id, feature_name, enabled, admin_id),
        )
        db.commit()
        flash("تم تحديث إعداد الميزة بنجاح", "success")
        return redirect(url_for("admin.feature_flags"))

    businesses = _safe_fetchall(db, "SELECT id, name FROM businesses ORDER BY id DESC LIMIT 200")
    flags = _safe_fetchall(
        db,
        """
        SELECT pf.*, b.name AS business_name
        FROM platform_features pf
        LEFT JOIN businesses b ON b.id = pf.business_id
        ORDER BY pf.updated_at DESC LIMIT 200
        """,
    )

    return render_template(
        "admin/feature_flags.html",
        businesses=_rows_to_dicts(businesses),
        flags=_rows_to_dicts(flags),
    )


@bp.route("/products-import", methods=["GET", "POST"])
@admin_required
def platform_products_import():
    """استيراد منتجات على مستوى أي منشأة مع دمج فوري"""
    db = get_db()
    businesses = _safe_fetchall(db, "SELECT id, name FROM businesses ORDER BY id DESC LIMIT 300")

    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard

        business_id_raw = request.form.get("business_id", "").strip()
        if not business_id_raw.isdigit():
            flash("يجب اختيار منشأة صحيحة", "error")
            return redirect(url_for("admin.platform_products_import"))

        business_id = int(business_id_raw)
        uploaded = request.files.get("products_file")
        if not uploaded or not (uploaded.filename or "").strip():
            flash("اختر ملف المنتجات أولاً", "error")
            return redirect(url_for("admin.platform_products_import"))

        try:
            raw_rows = _read_uploaded_product_rows(uploaded)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("admin.platform_products_import"))
        except Exception:
            flash("فشل قراءة الملف، تأكد من صحة التنسيق", "error")
            return redirect(url_for("admin.platform_products_import"))

        inserted = 0
        updated = 0
        skipped = 0
        seen_keys = set()

        for raw in raw_rows:
            item = _normalize_uploaded_product(raw or {})
            if not item:
                skipped += 1
                continue

            key = f"bc:{item['barcode']}" if item["barcode"] else f"nm:{item['name'].strip().lower()}"
            if key in seen_keys:
                skipped += 1
                continue
            seen_keys.add(key)

            if item["barcode"]:
                existing = db.execute(
                    "SELECT id FROM products WHERE business_id=? AND barcode=?",
                    (business_id, item["barcode"]),
                ).fetchone()
            else:
                existing = db.execute(
                    """
                    SELECT id FROM products
                    WHERE business_id=?
                      AND LOWER(TRIM(name))=LOWER(TRIM(?))
                      AND (barcode IS NULL OR barcode='')
                    LIMIT 1
                    """,
                    (business_id, item["name"]),
                ).fetchone()

            if existing:
                db.execute(
                    """
                    UPDATE products
                    SET name=?, description=?, category_name=?, sale_price=?,
                        can_sell=1, is_pos=1, updated_at=datetime('now')
                    WHERE id=?
                    """,
                    (
                        item["name"],
                        item["description"],
                        item["category_name"],
                        item["price"],
                        existing["id"],
                    ),
                )
                updated += 1
            else:
                db.execute(
                    """
                    INSERT INTO products (
                        business_id, barcode, name, description, category_name,
                        sale_price, purchase_price, can_sell, can_purchase,
                        track_stock, is_pos, product_type, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, 1, 1, 1, 1, 'product', 1)
                    """,
                    (
                        business_id,
                        item["barcode"] or None,
                        item["name"],
                        item["description"],
                        item["category_name"],
                        item["price"],
                    ),
                )
                inserted += 1

        db.commit()
        flash(
            f"تم الدمج الفوري للملف: إضافة {inserted} | تحديث {updated} | تخطي {skipped}",
            "success",
        )
        return redirect(url_for("admin.platform_products_import"))

    return render_template("admin/products_import.html", businesses=_rows_to_dicts(businesses))


@bp.route("/audit-logs", methods=["GET"])
@admin_required
def view_audit_logs():
    """عرض جميع سجلات الرقابة"""
    db = get_db()

    page = max(1, int(request.args.get("page", 1)))
    per_page = 100
    offset = (page - 1) * per_page

    filters = {}
    if request.args.get("user_id"):
        filters["user_id"] = int(request.args.get("user_id"))
    if request.args.get("action"):
        filters["action"] = request.args.get("action")

    logs = []
    total = 0
    if _table_exists(db, "enhanced_audit_logs"):
        try:
            logs = EnhancedAuditLogger.get_audit_logs(
                db,
                0,
                filters=filters,
                limit=per_page,
                offset=offset,
            )
        except Exception:
            logs = _safe_fetchall(
                db,
                "SELECT * FROM enhanced_audit_logs ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (per_page, offset),
            )
        total = int(_safe_scalar(db, "SELECT COUNT(*) FROM enhanced_audit_logs", default=0) or 0)
    elif _table_exists(db, "audit_logs"):
        logs = _safe_fetchall(
            db,
            "SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (per_page, offset),
        )
        total = int(_safe_scalar(db, "SELECT COUNT(*) FROM audit_logs", default=0) or 0)

    return render_template(
        "admin/audit_logs.html",
        logs=_rows_to_dicts(logs),
        total=total,
        page=page,
        per_page=per_page,
        pages=((total + per_page - 1) // per_page) if total else 1,
    )


@bp.route("/security-alerts", methods=["GET"])
@admin_required
def security_alerts():
    """عرض تنبيهات الأمان"""
    db = get_db()
    alerts = []
    if _table_exists(db, "security_alerts"):
        alerts = _safe_fetchall(
            db,
            "SELECT * FROM security_alerts ORDER BY created_at DESC LIMIT 200",
        )
    return render_template("admin/security_alerts.html", alerts=_rows_to_dicts(alerts))


@bp.route("/security-alerts/<int:alert_id>/acknowledge", methods=["POST"])
@admin_required
def acknowledge_alert(alert_id):
    """تأكيد الاطلاع على تنبيه أمان"""
    guard = csrf_protect()
    if guard:
        return guard

    db = get_db()
    admin_id = session.get("user_id")

    try:
        db.execute(
            "UPDATE security_alerts SET acknowledged_at=datetime('now'), acknowledged_by=? WHERE id=?",
            (admin_id, alert_id),
        )
        db.commit()
        return jsonify({"success": True, "message": "تم تأكيد الاطلاع"})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)}), 500


@bp.route("/system-health", methods=["GET"])
@admin_required
def system_health():
    """تقرير صحة النظام"""
    from modules.resilience_engine import health_monitor

    for component_name in health_monitor.components.keys():
        health_monitor.check_component(component_name)

    health_report = health_monitor.get_health_report()
    return render_template("admin/system_health.html", report=health_report)


@bp.route("/release-center", methods=["GET", "POST"])
@admin_required
def release_center():
    """مركز تحديثات البرنامج وإدارة نسخ المنصة"""
    db = get_db()
    _ensure_admin_tables(db)
    admin_id = session.get("user_id")

    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard

        action = request.form.get("action", "").strip()
        if action == "create_release":
            version = request.form.get("version", "").strip()
            title = request.form.get("title", "").strip()
            notes = request.form.get("notes", "").strip()
            is_mandatory = 1 if request.form.get("is_mandatory") else 0

            if not version or not title:
                flash("الإصدار والعنوان مطلوبان", "error")
                return redirect(url_for("admin.release_center"))

            db.execute(
                """
                INSERT INTO platform_releases (version, title, notes, is_mandatory, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                """,
                (version, title, notes, is_mandatory, admin_id),
            )
            db.commit()
            flash("تم نشر إصدار جديد في مركز التحديثات.", "success")
            return redirect(url_for("admin.release_center"))

        if action == "update_controls":
            controls = {
                "maintenance_mode": "1" if request.form.get("maintenance_mode") else "0",
                "public_registration_open": "1" if request.form.get("public_registration_open") else "0",
                "min_supported_version": request.form.get("min_supported_version", "").strip(),
            }
            for key, value in controls.items():
                db.execute(
                    """
                    INSERT INTO platform_settings (setting_key, setting_value, updated_by, updated_at)
                    VALUES (?, ?, ?, datetime('now'))
                    ON CONFLICT(setting_key) DO UPDATE
                    SET setting_value=excluded.setting_value,
                        updated_by=excluded.updated_by,
                        updated_at=excluded.updated_at
                    """,
                    (key, value, admin_id),
                )
            db.commit()
            flash("تم تحديث إعدادات التحكم المركزية.", "success")
            return redirect(url_for("admin.release_center"))

    releases = _safe_fetchall(
        db,
        "SELECT * FROM platform_releases ORDER BY created_at DESC LIMIT 100",
    )
    settings_rows = _safe_fetchall(db, "SELECT setting_key, setting_value FROM platform_settings")
    settings = {row["setting_key"]: row["setting_value"] for row in settings_rows}

    return render_template(
        "admin/release_center.html",
        releases=_rows_to_dicts(releases),
        settings=settings,
    )


@bp.route("/backups", methods=["GET", "POST"])
@admin_required
def manage_backups():
    """إدارة النسخ الاحتياطية"""
    db = get_db()

    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard

        action = request.form.get("action")
        if action == "create":
            business_id = int(request.form.get("business_id") or 0)
            backup_type = request.form.get("backup_type", "full")

            from modules.resilience_engine import BackupRecoveryManager

            manager = BackupRecoveryManager("backups/")
            success, message = manager.create_backup(db, business_id, backup_type)
            return jsonify({"success": success, "message": message})

    backups = _safe_fetchall(db, "SELECT * FROM backups ORDER BY created_at DESC LIMIT 100")
    businesses = _safe_fetchall(db, "SELECT id, name FROM businesses ORDER BY id DESC LIMIT 100")

    return render_template(
        "admin/backups.html",
        backups=_rows_to_dicts(backups),
        businesses=_rows_to_dicts(businesses),
    )


@bp.route("/recycle-bin", methods=["GET"])
@admin_required
def recycle_bin_admin():
    """عرض سلة المهملات للإدارة"""
    db = get_db()

    page = max(1, int(request.args.get("page", 1)))
    per_page = 50
    offset = (page - 1) * per_page

    records = _safe_fetchall(
        db,
        "SELECT * FROM recycle_bin ORDER BY deleted_at DESC LIMIT ? OFFSET ?",
        (per_page, offset),
    )
    total = int(_safe_scalar(db, "SELECT COUNT(*) FROM recycle_bin", default=0) or 0)

    return render_template(
        "admin/recycle_bin.html",
        records=_rows_to_dicts(records),
        total=total,
        page=page,
        per_page=per_page,
        pages=((total + per_page - 1) // per_page) if total else 1,
    )


@bp.route("/recycle-bin/restore/<int:record_id>", methods=["POST"])
@admin_required
def restore_recycle_record(record_id):
    """استعادة سجل من السلة"""
    guard = csrf_protect()
    if guard:
        return guard

    db = get_db()
    admin_id = session.get("user_id")

    try:
        record = db.execute(
            "SELECT business_id, table_name FROM recycle_bin WHERE id=?",
            (record_id,),
        ).fetchone()

        if not record:
            return jsonify({"success": False, "message": "السجل غير موجود"}), 404

        success, message = SmartRecycleBin.restore_from_bin(
            db,
            record["business_id"],
            record_id,
            record["table_name"],
            admin_id,
        )
        if success:
            return jsonify({"success": True, "message": message})
        return jsonify({"success": False, "message": message}), 400

    except Exception as exc:
        logger.error("خطأ في الاستعادة: %s", exc)
        return jsonify({"success": False, "message": str(exc)}), 500


@bp.route("/recycle-bin/delete/<int:record_id>", methods=["POST"])
@admin_required
def permanently_delete_record(record_id):
    """حذف دائم من السلة"""
    guard = csrf_protect()
    if guard:
        return guard

    db = get_db()
    admin_id = session.get("user_id")

    try:
        record = db.execute(
            "SELECT business_id, table_name FROM recycle_bin WHERE id=?",
            (record_id,),
        ).fetchone()

        if not record:
            return jsonify({"success": False, "message": "السجل غير موجود"}), 404

        reason = request.form.get("reason", "حذف إداري")
        success, message = SmartRecycleBin.permanently_delete(
            db,
            record["business_id"],
            record_id,
            record["table_name"],
            admin_id,
            reason,
        )
        if success:
            return jsonify({"success": True, "message": message})
        return jsonify({"success": False, "message": message}), 400

    except Exception as exc:
        logger.error("خطأ في الحذف الدائم: %s", exc)
        return jsonify({"success": False, "message": str(exc)}), 500


# ─── محرر الثيم والألوان ──────────────────────────────────────────────────────

THEME_DEFAULTS = {
    "theme_primary":       "#2563eb",
    "theme_primary_dark":  "#1d4ed8",
    "theme_primary_light": "#dbeafe",
    "theme_accent":        "#0ea5e9",
    "theme_sidebar_bg":    "#1e293b",
    "theme_sidebar_text":  "#e2e8f0",
    "theme_sidebar_active":"#3b82f6",
}

@bp.route("/theme.css")
def admin_theme_css():
    """يُرجع CSS variables مخصصة من إعدادات قاعدة البيانات"""
    db = get_db()
    _ensure_admin_tables(db)
    rows = _safe_fetchall(db, "SELECT setting_key, setting_value FROM platform_settings WHERE setting_key LIKE 'theme_%'")
    settings = {r["setting_key"]: r["setting_value"] for r in rows}
    # دمج القيم الافتراضية مع القيم المحفوظة
    vals = {**THEME_DEFAULTS, **{k: v for k, v in settings.items() if v}}

    css = f""":root {{
  --primary:         {vals['theme_primary']};
  --primary-dark:    {vals['theme_primary_dark']};
  --primary-light:   {vals['theme_primary_light']};
  --accent:          {vals['theme_accent']};
  --sidebar-bg:      {vals['theme_sidebar_bg']};
  --sidebar-text:    {vals['theme_sidebar_text']};
  --sidebar-active:  {vals['theme_sidebar_active']};
}}
.sidebar {{ background: var(--sidebar-bg) !important; }}
.sidebar a {{ color: var(--sidebar-text) !important; }}
.sidebar a.active {{ background: var(--sidebar-active) !important; }}
.btn-primary {{ background: var(--primary) !important; }}
.btn-primary:hover {{ background: var(--primary-dark) !important; }}
"""
    from flask import Response
    return Response(css, mimetype="text/css", headers={"Cache-Control": "no-store"})


@bp.route("/theme", methods=["GET", "POST"])
@admin_required
def admin_theme():
    """محرر الثيم والألوان"""
    db = get_db()
    _ensure_admin_tables(db)
    admin_id = session.get("user_id")

    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard
        for key in THEME_DEFAULTS:
            val = request.form.get(key, "").strip()
            if val:
                db.execute(
                    """INSERT INTO platform_settings (setting_key, setting_value, updated_by, updated_at)
                       VALUES (?, ?, ?, datetime('now'))
                       ON CONFLICT(setting_key) DO UPDATE
                       SET setting_value=excluded.setting_value,
                           updated_by=excluded.updated_by,
                           updated_at=excluded.updated_at""",
                    (key, val, admin_id),
                )
        db.commit()
        flash("تم حفظ الثيم بنجاح — سيظهر التغيير فوراً على جميع صفحات البرنامج.", "success")
        return redirect(url_for("admin.admin_theme"))

    rows = _safe_fetchall(db, "SELECT setting_key, setting_value FROM platform_settings WHERE setting_key LIKE 'theme_%'")
    saved = {r["setting_key"]: r["setting_value"] for r in rows}
    current = {**THEME_DEFAULTS, **{k: v for k, v in saved.items() if v}}
    return render_template("admin/theme_editor.html", current=current, defaults=THEME_DEFAULTS)


# ─── محرر القطاعات ────────────────────────────────────────────────────────────

@bp.route("/sectors", methods=["GET", "POST"])
@admin_required
def admin_sectors():
    """تفعيل/تعطيل القطاعات المتاحة للتسجيل"""
    from modules.config import INDUSTRY_TYPES
    db = get_db()
    _ensure_admin_tables(db)
    admin_id = session.get("user_id")

    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard
        enabled_keys = set(request.form.getlist("enabled_sectors"))
        for code, _ in INDUSTRY_TYPES:
            is_enabled = 1 if code in enabled_keys else 0
            db.execute(
                """INSERT INTO platform_sector_overrides (sector_key, is_enabled)
                   VALUES (?, ?)
                   ON CONFLICT(sector_key) DO UPDATE SET is_enabled=excluded.is_enabled""",
                (code, is_enabled),
            )
        db.commit()
        flash("تم حفظ إعدادات القطاعات بنجاح.", "success")
        return redirect(url_for("admin.admin_sectors"))

    # قراءة الحالة الحالية
    rows = _safe_fetchall(db, "SELECT sector_key, is_enabled FROM platform_sector_overrides")
    overrides = {r["sector_key"]: r["is_enabled"] for r in rows}
    sectors = []
    for code, name in INDUSTRY_TYPES:
        sectors.append({
            "code": code,
            "name": name,
            "is_enabled": overrides.get(code, 1),  # افتراضي: مفعّل
        })
    return render_template("admin/sector_editor.html", sectors=sectors)


# ─── محرر القائمة الجانبية ────────────────────────────────────────────────────

@bp.route("/sidebar", methods=["GET", "POST"])
@admin_required
def admin_sidebar():
    """تفعيل/تعطيل بنود القائمة الجانبية لكل قطاع"""
    from modules.config import SIDEBAR_CONFIG
    db = get_db()
    _ensure_admin_tables(db)
    admin_id = session.get("user_id")

    # القطاعات الرئيسية فقط (بدون الأسماء المستعارة مثل cafe)
    main_sectors = [k for k in SIDEBAR_CONFIG if not k.startswith("_")]

    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard
        sector = request.form.get("sector", "").strip()
        if sector not in main_sectors:
            flash("قطاع غير صالح", "error")
            return redirect(url_for("admin.admin_sidebar"))
        enabled_items = set(request.form.getlist("enabled_items"))
        all_items = SIDEBAR_CONFIG.get("_common", []) + SIDEBAR_CONFIG.get(sector, [])
        for item in all_items:
            key = item["key"]
            is_enabled = 1 if key in enabled_items else 0
            db.execute(
                """INSERT INTO platform_sidebar_overrides (sector_key, item_key, is_enabled)
                   VALUES (?, ?, ?)
                   ON CONFLICT(sector_key, item_key) DO UPDATE SET is_enabled=excluded.is_enabled""",
                (sector, key, is_enabled),
            )
        db.commit()
        flash(f"تم حفظ قائمة قطاع «{sector}» بنجاح.", "success")
        return redirect(url_for("admin.admin_sidebar") + f"?sector={sector}")

    # قراءة الحالة الحالية
    selected_sector = request.args.get("sector", main_sectors[0] if main_sectors else "retail")
    if selected_sector not in main_sectors:
        selected_sector = main_sectors[0]

    rows = _safe_fetchall(
        db, "SELECT item_key, is_enabled FROM platform_sidebar_overrides WHERE sector_key=?",
        (selected_sector,)
    )
    overrides = {r["item_key"]: r["is_enabled"] for r in rows}

    common_items = [
        {**item, "is_enabled": overrides.get(item["key"], 1)}
        for item in SIDEBAR_CONFIG.get("_common", [])
    ]
    sector_items = [
        {**item, "is_enabled": overrides.get(item["key"], 1)}
        for item in SIDEBAR_CONFIG.get(selected_sector, [])
    ]

    # قراءة الترتيب المحفوظ (إن وُجد) وتطبيقه على القوائم
    def _apply_order(items, sector, group):
        import json as _json
        key_ps = f"sidebar_order_{sector}_{group}"
        row = _safe_fetchone(db, "SELECT val FROM platform_settings WHERE key=?", (key_ps,))
        if row:
            try:
                order = _json.loads(row["val"])
                order_map = {k: i for i, k in enumerate(order)}
                items = sorted(items, key=lambda it: order_map.get(it["key"], 999))
            except Exception:
                pass
        return items

    common_items = _apply_order(common_items, selected_sector, "common")
    sector_items = _apply_order(sector_items, selected_sector, "sector")

    return render_template(
        "admin/sidebar_editor.html",
        main_sectors=main_sectors,
        selected_sector=selected_sector,
        common_items=common_items,
        sector_items=sector_items,
    )


@bp.route("/sidebar/reorder", methods=["POST"])
@admin_required
def admin_sidebar_reorder():
    """حفظ الترتيب الجديد لبنود القائمة الجانبية (drag-and-drop)"""
    import json as _json
    data = request.get_json(silent=True) or {}
    sector = data.get("sector", "").strip()
    group = data.get("group", "").strip()   # common | sector
    order = data.get("order", [])           # list of item keys

    if not sector or group not in ("common", "sector") or not isinstance(order, list):
        return jsonify(success=False, error="بيانات غير صالحة"), 400

    db = get_db()
    _ensure_admin_tables(db)
    key_ps = f"sidebar_order_{sector}_{group}"
    val = _json.dumps(order, ensure_ascii=False)
    db.execute(
        """INSERT INTO platform_settings(key,val) VALUES(?,?)
           ON CONFLICT(key) DO UPDATE SET val=excluded.val""",
        (key_ps, val),
    )
    db.commit()
    return jsonify(success=True)


# ─── الشارات التسويقية ──────────────────────────────────────────────────────

def get_active_badges(db, *, on_login=False, on_register=False):
    """جلب الشارات النشطة غير المنتهية — مساعدة عامة للوحات Login/Register"""
    try:
        _ensure_admin_tables(db)
        cond = "is_active = 1 AND (expires_at IS NULL OR expires_at > datetime('now'))"
        if on_login:
            cond += " AND show_on_login = 1"
        if on_register:
            cond += " AND show_on_register = 1"
        rows = db.execute(
            f"SELECT * FROM marketing_badges WHERE {cond} ORDER BY sort_order ASC, id DESC LIMIT 8"
        ).fetchall()
        return _rows_to_dicts(rows)
    except Exception:
        return []


@bp.route("/badges", methods=["GET", "POST"])
@admin_required
def admin_badges():
    """إدارة الشارات التسويقية"""
    db = get_db()
    _ensure_admin_tables(db)
    admin_id = session.get("user_id")

    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard

        action = request.form.get("action", "").strip()

        if action == "create":
            badge_text  = request.form.get("badge_text", "").strip()
            badge_color = request.form.get("badge_color", "#ffffff").strip()
            badge_bg    = request.form.get("badge_bg", "#dc2626").strip()
            badge_icon  = request.form.get("badge_icon", "🔥").strip()
            badge_type  = request.form.get("badge_type", "offer").strip()
            sector_key  = request.form.get("sector_key", "").strip() or None
            show_login  = 1 if request.form.get("show_on_login") else 0
            show_reg    = 1 if request.form.get("show_on_register") else 0
            expires_at  = request.form.get("expires_at", "").strip() or None
            sort_order  = int(request.form.get("sort_order", 0) or 0)

            if not badge_text:
                flash("نص الشارة مطلوب", "error")
                return redirect(url_for("admin.admin_badges"))

            db.execute(
                """INSERT INTO marketing_badges
                   (badge_text, badge_color, badge_bg, badge_icon, badge_type,
                    sector_key, show_on_login, show_on_register, is_active,
                    sort_order, expires_at, created_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                (badge_text, badge_color, badge_bg, badge_icon, badge_type,
                 sector_key, show_login, show_reg, sort_order, expires_at, admin_id),
            )
            db.commit()
            flash(f"تم إنشاء الشارة «{badge_text}» بنجاح.", "success")
            return redirect(url_for("admin.admin_badges"))

        if action == "toggle":
            badge_id = int(request.form.get("badge_id", 0) or 0)
            row = db.execute("SELECT is_active FROM marketing_badges WHERE id=?", (badge_id,)).fetchone()
            if row:
                new_state = 0 if (row[0] if not isinstance(row, dict) else row["is_active"]) else 1
                db.execute("UPDATE marketing_badges SET is_active=? WHERE id=?", (new_state, badge_id))
                db.commit()
                flash("تم تغيير حالة الشارة.", "success")
            return redirect(url_for("admin.admin_badges"))

        if action == "delete":
            badge_id = int(request.form.get("badge_id", 0) or 0)
            db.execute("DELETE FROM marketing_badges WHERE id=?", (badge_id,))
            db.commit()
            flash("تم حذف الشارة.", "success")
            return redirect(url_for("admin.admin_badges"))

        if action == "edit":
            badge_id    = int(request.form.get("badge_id", 0) or 0)
            badge_text  = request.form.get("badge_text", "").strip()
            badge_color = request.form.get("badge_color", "#ffffff").strip()
            badge_bg    = request.form.get("badge_bg", "#dc2626").strip()
            badge_icon  = request.form.get("badge_icon", "🔥").strip()
            show_login  = 1 if request.form.get("show_on_login") else 0
            show_reg    = 1 if request.form.get("show_on_register") else 0
            expires_at  = request.form.get("expires_at", "").strip() or None
            sort_order  = int(request.form.get("sort_order", 0) or 0)

            db.execute(
                """UPDATE marketing_badges
                   SET badge_text=?, badge_color=?, badge_bg=?, badge_icon=?,
                       show_on_login=?, show_on_register=?, expires_at=?, sort_order=?
                   WHERE id=?""",
                (badge_text, badge_color, badge_bg, badge_icon,
                 show_login, show_reg, expires_at, sort_order, badge_id),
            )
            db.commit()
            flash("تم تحديث الشارة.", "success")
            return redirect(url_for("admin.admin_badges"))

    badges = _rows_to_dicts(_safe_fetchall(
        db, "SELECT * FROM marketing_badges ORDER BY sort_order ASC, id DESC"
    ))
    from modules.config import INDUSTRY_TYPES
    return render_template("admin/badges.html", badges=badges, industry_types=INDUSTRY_TYPES)


# ─── إدارة المستخدمين والصلاحيات ─────────────────────────────────────────────

@bp.route("/users", methods=["GET", "POST"])
@admin_required
def admin_users():
    """إدارة كل مستخدمي المنصة — حظر، تفعيل، تغيير صلاحيات"""
    db = get_db()
    _ensure_admin_tables(db)
    admin_id = session.get("user_id")

    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard

        action  = request.form.get("action", "").strip()
        user_id = int(request.form.get("user_id", 0) or 0)

        if action == "toggle_active":
            row = db.execute("SELECT is_active FROM users WHERE id=?", (user_id,)).fetchone()
            if row:
                new_state = 0 if (row[0] if not isinstance(row, dict) else row["is_active"]) else 1
                db.execute("UPDATE users SET is_active=? WHERE id=?", (new_state, user_id))
                db.commit()
                state_label = "تم تفعيل" if new_state else "تم إيقاف"
                flash(f"{state_label} المستخدم #{user_id}", "success")

        elif action == "reset_password":
            import secrets as _sec
            new_pwd = _sec.token_urlsafe(10)
            from modules.extensions import hash_password
            db.execute("UPDATE users SET password_hash=? WHERE id=?",
                       (hash_password(new_pwd), user_id))
            db.commit()
            flash(f"كلمة المرور الجديدة للمستخدم #{user_id}: {new_pwd}", "info")

        elif action == "change_role":
            new_role_id = int(request.form.get("role_id", 0) or 0)
            if new_role_id:
                db.execute("UPDATE users SET role_id=? WHERE id=?", (new_role_id, user_id))
                db.commit()
                flash(f"تم تغيير دور المستخدم #{user_id}", "success")

        elif action == "delete_user":
            db.execute("DELETE FROM users WHERE id=? AND id != ?", (user_id, admin_id))
            db.commit()
            flash(f"تم حذف المستخدم #{user_id}", "success")

        return redirect(url_for("admin.admin_users"))

    search = request.args.get("q", "").strip()
    biz_filter = request.args.get("biz", "").strip()

    where_parts = ["1=1"]
    params = []
    if search:
        where_parts.append("(u.username LIKE ? OR u.full_name LIKE ? OR u.email LIKE ?)")
        params += [f"%{search}%", f"%{search}%", f"%{search}%"]
    if biz_filter and biz_filter.isdigit():
        where_parts.append("u.business_id=?")
        params.append(int(biz_filter))

    users = _rows_to_dicts(_safe_fetchall(db, f"""
        SELECT u.id, u.username, u.full_name, u.email, u.is_active, u.created_at,
               b.name AS biz_name, b.industry_type, r.name AS role_name,
               u.business_id, u.role_id,
               (SELECT COUNT(*) FROM audit_logs al WHERE al.user_id=u.id) AS activity_count
        FROM users u
        LEFT JOIN businesses b ON b.id = u.business_id
        LEFT JOIN roles r ON r.id = u.role_id
        WHERE {' AND '.join(where_parts)}
        ORDER BY u.id DESC LIMIT 300
    """, params))

    roles = _rows_to_dicts(_safe_fetchall(db, "SELECT id, name FROM roles ORDER BY name"))
    businesses = _rows_to_dicts(_safe_fetchall(db, "SELECT id, name FROM businesses ORDER BY name LIMIT 200"))

    total = _safe_scalar(db, "SELECT COUNT(*) FROM users")
    active = _safe_scalar(db, "SELECT COUNT(*) FROM users WHERE is_active=1")

    return render_template("admin/users.html",
        users=users, roles=roles, businesses=businesses,
        search=search, biz_filter=biz_filter,
        total=total, active=active)


@bp.route("/users/activity/<int:uid>")
@admin_required
def user_activity(uid: int):
    """تقرير نشاط مستخدم محدد"""
    db = get_db()
    user = db.execute("""
        SELECT u.*, b.name AS biz_name, r.name AS role_name
        FROM users u
        LEFT JOIN businesses b ON b.id=u.business_id
        LEFT JOIN roles r ON r.id=u.role_id
        WHERE u.id=?
    """, (uid,)).fetchone()
    if not user:
        flash("المستخدم غير موجود", "error")
        return redirect(url_for("admin.admin_users"))
    user = dict(user)

    logs = _rows_to_dicts(_safe_fetchall(db, """
        SELECT action, entity_type, entity_id, created_at, ip_address
        FROM audit_logs WHERE user_id=? ORDER BY created_at DESC LIMIT 200
    """, (uid,)))

    stats = {
        "total_actions": len(logs),
        "last_action": logs[0]["created_at"] if logs else None,
        "unique_actions": len({l["action"] for l in logs}),
    }

    return render_template("admin/user_activity.html", user=user, logs=logs, stats=stats)


# ─── محرر محتوى المنصة ────────────────────────────────────────────────────────

PLATFORM_CONTENT_FIELDS = [
    ("platform_name",        "اسم المنصة",             "text",     "Jinan Biz"),
    ("platform_tagline",     "الشعار / الوصف",          "text",     "نظام إدارة الأعمال الذكي"),
    ("platform_logo_url",    "رابط الشعار (URL)",       "url",      ""),
    ("platform_support_email","البريد الإلكتروني للدعم","email",    "support@example.com"),
    ("platform_support_phone","رقم الدعم الفني",        "text",     "+966"),
    ("platform_twitter",     "رابط تويتر / X",          "url",      ""),
    ("platform_whatsapp",    "رقم واتساب الدعم",        "text",     ""),
    ("platform_footer_text", "نص الفوتر",               "text",     "جميع الحقوق محفوظة"),
    ("platform_terms_url",   "رابط الشروط والأحكام",    "url",      ""),
    ("platform_privacy_url", "رابط سياسة الخصوصية",     "url",      ""),
    ("platform_onboarding_video","رابط فيديو الترحيب",  "url",      ""),
    ("platform_announcement","إعلان بارز (للواجهة)",    "textarea", ""),
    ("platform_maintenance_msg","رسالة الصيانة",         "textarea", "البرنامج في صيانة مؤقتة، نعود قريباً."),
    ("platform_reg_welcome", "رسالة الترحيب (التسجيل)", "textarea", "مرحباً بك في منصتنا!"),
]

@bp.route("/content", methods=["GET", "POST"])
@admin_required
def platform_content():
    """محرر محتوى المنصة — الاسم، الشعار، النصوص، روابط التواصل"""
    db = get_db()
    _ensure_admin_tables(db)
    admin_id = session.get("user_id")

    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard
        for key, *_ in PLATFORM_CONTENT_FIELDS:
            val = request.form.get(key, "").strip()
            db.execute(
                """INSERT INTO platform_settings (setting_key, setting_value, updated_by, updated_at)
                   VALUES (?, ?, ?, datetime('now'))
                   ON CONFLICT(setting_key) DO UPDATE
                   SET setting_value=excluded.setting_value,
                       updated_by=excluded.updated_by, updated_at=excluded.updated_at""",
                (key, val, admin_id),
            )
        db.commit()
        flash("تم حفظ محتوى المنصة بنجاح.", "success")
        return redirect(url_for("admin.platform_content"))

    rows = _safe_fetchall(db, "SELECT setting_key, setting_value FROM platform_settings")
    saved = {r["setting_key"]: r["setting_value"] for r in rows}
    fields_with_values = [
        (key, label, ftype, saved.get(key, default))
        for key, label, ftype, default in PLATFORM_CONTENT_FIELDS
    ]
    return render_template("admin/content_editor.html", fields=fields_with_values)


# ─── API عام لإعدادات المنصة (للقوالب) ──────────────────────────────────────

def get_platform_setting(db, key: str, default: str = "") -> str:
    """قراءة إعداد واحد من platform_settings"""
    try:
        row = db.execute("SELECT setting_value FROM platform_settings WHERE setting_key=?", (key,)).fetchone()
        if row:
            val = row[0] if not isinstance(row, dict) else row["setting_value"]
            return val or default
    except Exception:
        pass
    return default


# ─── ترتيب بنود القائمة الجانبية (drag & drop) ───────────────────────────────

@bp.route("/sidebar/reorder", methods=["POST"])
@admin_required
def sidebar_reorder():
    """حفظ الترتيب الجديد لبنود القائمة الجانبية عبر JSON"""
    guard = csrf_protect()
    if guard:
        return guard
    db = get_db()
    _ensure_admin_tables(db)

    # التأكد من وجود عمود sort_order
    try:
        db.execute("ALTER TABLE platform_sidebar_overrides ADD COLUMN sort_order INTEGER DEFAULT 0")
        db.commit()
    except Exception:
        pass

    data = request.get_json(silent=True) or {}
    sector = data.get("sector", "").strip()
    order  = data.get("order", [])   # قائمة item_keys بالترتيب الجديد

    if not sector or not isinstance(order, list):
        return jsonify({"success": False, "message": "بيانات غير صالحة"}), 400

    for i, item_key in enumerate(order):
        db.execute(
            """INSERT INTO platform_sidebar_overrides (sector_key, item_key, is_enabled, sort_order)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(sector_key, item_key) DO UPDATE SET sort_order=excluded.sort_order""",
            (sector, str(item_key), i),
        )
    db.commit()
    return jsonify({"success": True, "message": f"تم حفظ ترتيب {len(order)} بند"})


# ═══════════════════════════════════════════════════════════════════════════════
# قسم 1 — إدارة المنتجات والخدمات (Platform-wide CRUD)
# ═══════════════════════════════════════════════════════════════════════════════

def _ensure_platform_catalog(db):
    """جدول المنتجات/الخدمات المنصة الموحّد (غير مرتبط بمنشأة)"""
    db.execute("""
        CREATE TABLE IF NOT EXISTS platform_catalog (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            description TEXT    DEFAULT '',
            price       REAL    NOT NULL DEFAULT 0,
            category    TEXT    DEFAULT 'عام',
            image_url   TEXT    DEFAULT '',
            file_url    TEXT    DEFAULT '',
            file_type   TEXT    DEFAULT '',
            is_active   INTEGER NOT NULL DEFAULT 1,
            is_featured INTEGER NOT NULL DEFAULT 0,
            sort_order  INTEGER NOT NULL DEFAULT 0,
            created_by  INTEGER,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # جدول الملفات المرفوعة
    db.execute("""
        CREATE TABLE IF NOT EXISTS platform_files (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            original_name TEXT  NOT NULL,
            file_path   TEXT    NOT NULL,
            file_size   INTEGER DEFAULT 0,
            file_type   TEXT    DEFAULT '',
            category    TEXT    DEFAULT 'عام',
            is_public   INTEGER NOT NULL DEFAULT 1,
            downloads   INTEGER NOT NULL DEFAULT 0,
            uploaded_by INTEGER,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)
    db.commit()


import os
from werkzeug.utils import secure_filename

ALLOWED_UPLOAD_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "gif", "webp", "mp4", "zip"}

def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_UPLOAD_EXTENSIONS


@bp.route("/catalog", methods=["GET", "POST"])
@admin_required
def platform_catalog():
    """إدارة المنتجات والخدمات — CRUD كامل"""
    db = get_db()
    _ensure_admin_tables(db)
    _ensure_platform_catalog(db)
    admin_id = session.get("user_id")

    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard

        action = request.form.get("action", "").strip()

        if action == "add":
            name        = request.form.get("name", "").strip()
            description = request.form.get("description", "").strip()
            price       = float(request.form.get("price", 0) or 0)
            category    = request.form.get("category", "عام").strip()
            is_featured = 1 if request.form.get("is_featured") else 0
            image_url   = request.form.get("image_url", "").strip()

            # رفع صورة اختياري
            f = request.files.get("image_file")
            if f and f.filename and _allowed_file(f.filename):
                safe_name = secure_filename(f.filename)
                upload_dir = os.path.join("uploads", "catalog")
                os.makedirs(upload_dir, exist_ok=True)
                dest = os.path.join(upload_dir, safe_name)
                f.save(dest)
                image_url = f"/uploads/catalog/{safe_name}"

            if not name:
                flash("الاسم مطلوب", "error")
            else:
                db.execute(
                    """INSERT INTO platform_catalog
                       (name, description, price, category, image_url, is_featured, created_by)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (name, description, price, category, image_url, is_featured, admin_id),
                )
                db.commit()
                flash(f"تمت إضافة «{name}»", "success")

        elif action == "edit":
            item_id     = int(request.form.get("item_id", 0) or 0)
            name        = request.form.get("name", "").strip()
            description = request.form.get("description", "").strip()
            price       = float(request.form.get("price", 0) or 0)
            category    = request.form.get("category", "عام").strip()
            is_featured = 1 if request.form.get("is_featured") else 0
            image_url   = request.form.get("image_url", "").strip()

            f = request.files.get("image_file")
            if f and f.filename and _allowed_file(f.filename):
                safe_name = secure_filename(f.filename)
                upload_dir = os.path.join("uploads", "catalog")
                os.makedirs(upload_dir, exist_ok=True)
                dest = os.path.join(upload_dir, safe_name)
                f.save(dest)
                image_url = f"/uploads/catalog/{safe_name}"

            db.execute(
                """UPDATE platform_catalog
                   SET name=?, description=?, price=?, category=?, image_url=?,
                       is_featured=?, updated_at=datetime('now')
                   WHERE id=?""",
                (name, description, price, category, image_url, is_featured, item_id),
            )
            db.commit()
            flash("تم تحديث العنصر", "success")

        elif action == "toggle":
            item_id = int(request.form.get("item_id", 0) or 0)
            db.execute(
                "UPDATE platform_catalog SET is_active = CASE WHEN is_active=1 THEN 0 ELSE 1 END WHERE id=?",
                (item_id,),
            )
            db.commit()
            flash("تم تغيير حالة العنصر", "success")

        elif action == "delete":
            item_id = int(request.form.get("item_id", 0) or 0)
            db.execute("DELETE FROM platform_catalog WHERE id=?", (item_id,))
            db.commit()
            flash("تم الحذف", "success")

        return redirect(url_for("admin.platform_catalog"))

    search = request.args.get("q", "").strip()
    cat_filter = request.args.get("cat", "").strip()

    where_parts = ["1=1"]
    params = []
    if search:
        where_parts.append("(name LIKE ? OR description LIKE ?)")
        params += [f"%{search}%", f"%{search}%"]
    if cat_filter:
        where_parts.append("category=?")
        params.append(cat_filter)

    items = _rows_to_dicts(_safe_fetchall(db,
        f"SELECT * FROM platform_catalog WHERE {' AND '.join(where_parts)} ORDER BY sort_order, id DESC",
        params,
    ))
    categories = [r["category"] for r in _rows_to_dicts(_safe_fetchall(db,
        "SELECT DISTINCT category FROM platform_catalog ORDER BY category"
    ))]

    return render_template("admin/catalog.html", items=items, categories=categories,
                           search=search, cat_filter=cat_filter)


@bp.route("/files", methods=["GET", "POST"])
@admin_required
def platform_files():
    """رفع وإدارة الملفات للمشتركين"""
    db = get_db()
    _ensure_admin_tables(db)
    _ensure_platform_catalog(db)
    admin_id = session.get("user_id")

    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard

        action = request.form.get("action", "").strip()

        if action == "upload":
            f = request.files.get("file")
            if not f or not f.filename:
                flash("لم يتم اختيار ملف", "error")
            elif not _allowed_file(f.filename):
                flash("نوع الملف غير مسموح به", "error")
            else:
                original = f.filename
                ext = original.rsplit(".", 1)[1].lower()
                safe_name = secure_filename(original)
                upload_dir = os.path.join("uploads", "platform_files")
                os.makedirs(upload_dir, exist_ok=True)
                dest = os.path.join(upload_dir, safe_name)
                f.save(dest)
                size = os.path.getsize(dest)
                label  = request.form.get("label", original).strip() or original
                cat    = request.form.get("category", "عام").strip()
                public = 1 if request.form.get("is_public") else 0
                db.execute(
                    """INSERT INTO platform_files
                       (name, original_name, file_path, file_size, file_type, category, is_public, uploaded_by)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (label, original, f"/uploads/platform_files/{safe_name}", size, ext, cat, public, admin_id),
                )
                db.commit()
                flash(f"تم رفع «{label}»", "success")

        elif action == "delete":
            fid = int(request.form.get("file_id", 0) or 0)
            row = db.execute("SELECT file_path FROM platform_files WHERE id=?", (fid,)).fetchone()
            if row:
                try:
                    local_path = row[0].lstrip("/")
                    if os.path.exists(local_path):
                        os.remove(local_path)
                except Exception:
                    pass
            db.execute("DELETE FROM platform_files WHERE id=?", (fid,))
            db.commit()
            flash("تم حذف الملف", "success")

        return redirect(url_for("admin.platform_files"))

    files = _rows_to_dicts(_safe_fetchall(db,
        "SELECT * FROM platform_files ORDER BY id DESC LIMIT 500"
    ))
    return render_template("admin/files.html", files=files)


# ═══════════════════════════════════════════════════════════════════════════════
# قسم 2 — التحليلات والرسوم البيانية + تصدير Excel
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/analytics")
@admin_required
def platform_analytics():
    """لوحة التحليلات الشاملة — مشتركون، إيرادات، سلوك"""
    db = get_db()
    _ensure_admin_tables(db)

    # ── المشتركون الجدد آخر 30 يوم ────────────────────────────────────────
    new_subs_30 = _rows_to_dicts(_safe_fetchall(db, """
        SELECT date(created_at) AS d, COUNT(*) AS cnt
        FROM businesses
        WHERE created_at >= date('now','-30 days')
        GROUP BY date(created_at) ORDER BY d
    """))

    # ── الإيرادات اليومية آخر 30 يوم (من الفواتير) ───────────────────────
    daily_revenue = _rows_to_dicts(_safe_fetchall(db, """
        SELECT date(created_at) AS d, ROUND(SUM(total_amount),2) AS rev
        FROM invoices
        WHERE created_at >= date('now','-30 days')
        GROUP BY date(created_at) ORDER BY d
    """))

    # ── الإيرادات الشهرية آخر 12 شهر ─────────────────────────────────────
    monthly_revenue = _rows_to_dicts(_safe_fetchall(db, """
        SELECT strftime('%Y-%m', created_at) AS m,
               ROUND(SUM(total_amount),2) AS rev,
               COUNT(*) AS cnt
        FROM invoices
        WHERE created_at >= date('now','-365 days')
        GROUP BY strftime('%Y-%m', created_at) ORDER BY m
    """))

    # ── أكثر المنشآت إصداراً للفواتير ────────────────────────────────────
    top_businesses = _rows_to_dicts(_safe_fetchall(db, """
        SELECT b.name, COUNT(i.id) AS inv_count,
               ROUND(SUM(i.total_amount),2) AS total_rev
        FROM invoices i JOIN businesses b ON b.id=i.business_id
        WHERE i.created_at >= date('now','-30 days')
        GROUP BY i.business_id ORDER BY inv_count DESC LIMIT 10
    """))

    # ── نشاط التدقيق: أكثر العمليات تكراراً ──────────────────────────────
    top_actions = _rows_to_dicts(_safe_fetchall(db, """
        SELECT action, COUNT(*) AS cnt
        FROM audit_logs
        WHERE created_at >= date('now','-30 days')
        GROUP BY action ORDER BY cnt DESC LIMIT 10
    """))

    # ── إحصائيات عامة ─────────────────────────────────────────────────────
    summary = {
        "total_businesses": _safe_scalar(db, "SELECT COUNT(*) FROM businesses") or 0,
        "total_users":      _safe_scalar(db, "SELECT COUNT(*) FROM users") or 0,
        "total_invoices":   _safe_scalar(db, "SELECT COUNT(*) FROM invoices") or 0,
        "total_revenue":    _safe_scalar(db, "SELECT ROUND(SUM(total_amount),2) FROM invoices") or 0,
        "new_this_month":   _safe_scalar(db, """
            SELECT COUNT(*) FROM businesses
            WHERE strftime('%Y-%m', created_at) = strftime('%Y-%m','now')
        """) or 0,
        "revenue_this_month": _safe_scalar(db, """
            SELECT ROUND(SUM(total_amount),2) FROM invoices
            WHERE strftime('%Y-%m', created_at) = strftime('%Y-%m','now')
        """) or 0,
    }

    return render_template("admin/analytics.html",
        summary=summary,
        new_subs_30=new_subs_30,
        daily_revenue=daily_revenue,
        monthly_revenue=monthly_revenue,
        top_businesses=top_businesses,
        top_actions=top_actions,
    )


@bp.route("/analytics/export")
@admin_required
def analytics_export():
    """تصدير تقارير Excel (CSV)"""
    report = request.args.get("report", "invoices")
    db = get_db()

    rows = []
    filename = "report.csv"

    if report == "invoices":
        filename = "invoices_report.csv"
        rows = _rows_to_dicts(_safe_fetchall(db, """
            SELECT i.id, b.name AS business, i.invoice_number, i.total_amount,
                   i.tax_amount, i.status, i.created_at
            FROM invoices i
            LEFT JOIN businesses b ON b.id=i.business_id
            ORDER BY i.created_at DESC LIMIT 5000
        """))
    elif report == "businesses":
        filename = "businesses_report.csv"
        rows = _rows_to_dicts(_safe_fetchall(db, """
            SELECT b.id, b.name, b.industry_type, b.account_status,
                   b.created_at,
                   (SELECT COUNT(*) FROM users WHERE business_id=b.id) AS users_count,
                   (SELECT COUNT(*) FROM invoices WHERE business_id=b.id) AS inv_count,
                   (SELECT ROUND(SUM(total_amount),2) FROM invoices WHERE business_id=b.id) AS total_rev
            FROM businesses b ORDER BY b.created_at DESC LIMIT 2000
        """))
    elif report == "users":
        filename = "users_report.csv"
        rows = _rows_to_dicts(_safe_fetchall(db, """
            SELECT u.id, u.username, u.full_name, u.email, u.is_active,
                   b.name AS business, r.name AS role, u.created_at
            FROM users u
            LEFT JOIN businesses b ON b.id=u.business_id
            LEFT JOIN roles r ON r.id=u.role_id
            ORDER BY u.created_at DESC LIMIT 5000
        """))
    elif report == "audit":
        filename = "audit_report.csv"
        rows = _rows_to_dicts(_safe_fetchall(db, """
            SELECT al.id, al.action, al.entity_type, al.entity_id,
                   u.username, b.name AS business, al.ip_address, al.created_at
            FROM audit_logs al
            LEFT JOIN users u ON u.id=al.user_id
            LEFT JOIN businesses b ON b.id=al.business_id
            ORDER BY al.created_at DESC LIMIT 10000
        """))

    if not rows:
        flash("لا توجد بيانات للتصدير", "error")
        return redirect(url_for("admin.platform_analytics"))

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)

    from flask import Response
    return Response(
        "\ufeff" + output.getvalue(),   # BOM for Excel Arabic support
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── API الإحصائيات الفورية (Live Analytics) ────────────────────────────
@bp.route("/analytics/live", methods=["GET"])
@admin_required
def analytics_live():
    """API للإحصائيات الفورية (تحديث كل 10 ثواني في الـ frontend)"""
    db = get_db()
    import time
    
    now = int(time.time() * 1000)  # milliseconds
    
    # ── آخر 24 ساعة ──
    today_revenue = _safe_scalar(db, """
        SELECT ROUND(SUM(total_amount),2) FROM invoices
        WHERE date(created_at)=date('now')
    """) or 0
    
    today_invoices = _safe_scalar(db, """
        SELECT COUNT(*) FROM invoices WHERE date(created_at)=date('now')
    """) or 0
    
    new_users_24h = _safe_scalar(db, """
        SELECT COUNT(*) FROM businesses
        WHERE created_at >= datetime('now', '-24 hours')
    """) or 0
    
    # ── آخر ساعة (فعالية عالية) ──
    online_metric = _safe_scalar(db, """
        SELECT COUNT(DISTINCT business_id) FROM audit_logs
        WHERE created_at >= datetime('now', '-1 hour')
    """) or 0
    
    # ── أكثر خدمات نشاطاً (آخر ساعة) ──
    top_actions = _rows_to_dicts(_safe_fetchall(db, """
        SELECT action, COUNT(*) AS cnt FROM audit_logs
        WHERE created_at >= datetime('now', '-1 hour')
        GROUP BY action ORDER BY cnt DESC LIMIT 5
    """))
    
    return jsonify({
        "success": True,
        "timestamp": now,
        "metrics": {
            "revenue_24h": today_revenue,
            "invoices_24h": today_invoices,
            "new_businesses": new_users_24h,
            "active_businesses": online_metric,
            "top_actions": [
                {"action": a["action"], "count": a["cnt"]}
                for a in top_actions
            ]
        }
    })


# ═══════════════════════════════════════════════════════════════════════════════
# قسم 3 — التحكم في تجربة المستخدم (UX Control)
# ═══════════════════════════════════════════════════════════════════════════════

def _ensure_notifications_table(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS platform_notifications (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT    NOT NULL,
            body        TEXT    NOT NULL DEFAULT '',
            ntype       TEXT    NOT NULL DEFAULT 'info',
            target_role TEXT    DEFAULT '',
            is_active   INTEGER NOT NULL DEFAULT 1,
            show_once   INTEGER NOT NULL DEFAULT 0,
            expires_at  TEXT    DEFAULT NULL,
            sort_order  INTEGER NOT NULL DEFAULT 0,
            created_by  INTEGER,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
        )
    """)
    # جدول تتبع من شاهد الإشعار
    db.execute("""
        CREATE TABLE IF NOT EXISTS notification_reads (
            notification_id INTEGER NOT NULL,
            user_id         INTEGER NOT NULL,
            read_at         TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (notification_id, user_id)
        )
    """)
    db.commit()


UX_FIELDS = [
    ("ux_login_bg_url",      "صورة خلفية صفحة الدخول",     "url"),
    ("ux_register_bg_url",   "صورة خلفية صفحة التسجيل",    "url"),
    ("ux_login_card_opacity","شفافية بطاقة الدخول (0-1)",   "text"),
    ("ux_sidebar_bg_image",  "صورة خلفية القائمة الجانبية", "url"),
    ("ux_topbar_bg_color",   "لون شريط التنقل العلوي",      "text"),
    ("ux_font_family",       "نوع الخط (مثل: Cairo, Tajawal)", "text"),
    ("ux_card_radius",       "نصف قطر البطاقات (مثل: 12px)", "text"),
    ("ux_hero_banner_url",   "بانر ترحيبي كبير (URL صورة)", "url"),
    ("ux_hero_banner_link",  "رابط البانر الترحيبي",        "url"),
    ("ux_hero_banner_title", "عنوان البانر الترحيبي",       "text"),
    ("ux_custom_css",        "CSS مخصص (يُحقن في كل الصفحات)", "textarea"),
]

@bp.route("/ux-control", methods=["GET", "POST"])
@admin_required
def ux_control():
    """التحكم في تجربة المستخدم — خلفيات، ألوان، CSS مخصص، بانرات"""
    db = get_db()
    _ensure_admin_tables(db)
    _ensure_notifications_table(db)
    admin_id = session.get("user_id")

    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard

        action = request.form.get("action", "save_ux")

        if action == "save_ux":
            for key, *_ in UX_FIELDS:
                val = request.form.get(key, "").strip()
                db.execute(
                    """INSERT INTO platform_settings (setting_key, setting_value, updated_by, updated_at)
                       VALUES (?, ?, ?, datetime('now'))
                       ON CONFLICT(setting_key) DO UPDATE
                       SET setting_value=excluded.setting_value,
                           updated_by=excluded.updated_by, updated_at=excluded.updated_at""",
                    (key, val, admin_id),
                )
            db.commit()
            flash("تم حفظ إعدادات تجربة المستخدم", "success")

        elif action == "add_notification":
            title   = request.form.get("ntitle", "").strip()
            body    = request.form.get("nbody", "").strip()
            ntype   = request.form.get("ntype", "info").strip()
            role    = request.form.get("ntarget_role", "").strip()
            expires = request.form.get("nexpirees", "").strip() or None
            once    = 1 if request.form.get("nshow_once") else 0
            if title:
                db.execute(
                    """INSERT INTO platform_notifications
                       (title, body, ntype, target_role, show_once, expires_at, created_by)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (title, body, ntype, role, once, expires, admin_id),
                )
                db.commit()
                flash(f"تمت إضافة الإشعار «{title}»", "success")

        elif action == "toggle_notification":
            nid = int(request.form.get("nid", 0) or 0)
            db.execute(
                "UPDATE platform_notifications SET is_active = CASE WHEN is_active=1 THEN 0 ELSE 1 END WHERE id=?",
                (nid,),
            )
            db.commit()
            flash("تم تغيير حالة الإشعار", "success")

        elif action == "delete_notification":
            nid = int(request.form.get("nid", 0) or 0)
            db.execute("DELETE FROM platform_notifications WHERE id=?", (nid,))
            db.execute("DELETE FROM notification_reads WHERE notification_id=?", (nid,))
            db.commit()
            flash("تم حذف الإشعار", "success")

        return redirect(url_for("admin.ux_control"))

    # GET
    rows = _safe_fetchall(db, "SELECT setting_key, setting_value FROM platform_settings")
    saved = {r["setting_key"]: r["setting_value"] for r in rows}
    fields_with_vals = [
        (key, label, ftype, saved.get(key, ""))
        for key, label, ftype in UX_FIELDS
    ]

    notifications = _rows_to_dicts(_safe_fetchall(db,
        "SELECT * FROM platform_notifications ORDER BY sort_order, id DESC"
    ))
    return render_template("admin/ux_control.html",
        fields=fields_with_vals, notifications=notifications)


# ── API: إشعارات المستخدم الحالي ────────────────────────────────────────────

@bp.route("/notifications/active")
def active_notifications():
    """JSON: الإشعارات النشطة للمستخدم الحالي (تُستدعى من JS)"""
    db = get_db()
    try:
        _ensure_notifications_table(db)
    except Exception:
        return jsonify([])

    user_id = session.get("user_id")
    user_role = ""
    if user_id:
        row = db.execute(
            "SELECT r.name FROM users u LEFT JOIN roles r ON r.id=u.role_id WHERE u.id=?",
            (user_id,),
        ).fetchone()
        if row:
            user_role = row[0] or ""

    notifs = _rows_to_dicts(_safe_fetchall(db, """
        SELECT n.*
        FROM platform_notifications n
        WHERE n.is_active = 1
          AND (n.expires_at IS NULL OR n.expires_at > datetime('now'))
          AND (n.target_role = '' OR n.target_role = ?)
          AND n.id NOT IN (
              SELECT notification_id FROM notification_reads WHERE user_id = ?
          )
        ORDER BY n.sort_order, n.id DESC
        LIMIT 10
    """, (user_role, user_id or -1)))

    return jsonify(notifs)


@bp.route("/notifications/mark-read/<int:nid>", methods=["POST"])
def mark_notification_read(nid: int):
    """تأشير إشعار كمقروء للمستخدم الحالي"""
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"ok": False})
    db = get_db()
    try:
        db.execute(
            "INSERT OR IGNORE INTO notification_reads (notification_id, user_id) VALUES (?, ?)",
            (nid, user_id),
        )
        db.commit()
    except Exception:
        pass
    return jsonify({"ok": True})


# ═══════════════════════════════════════════════════════════════════════════════
# نظام الأدوار والصلاحيات (Roles & Permissions Manager)
# ═══════════════════════════════════════════════════════════════════════════════

# جميع الصلاحيات المتاحة في النظام مع وصفها
ALL_PERMISSIONS = [
    # صلاحيات الوصول الشامل
    ("all",                          "🔑 وصول شامل (مالك)",       "system"),
    # الفواتير
    ("invoices",                     "📄 عرض الفواتير",           "invoices"),
    ("invoice_edit",                 "✏️ تعديل الفواتير",         "invoices"),
    ("invoice_cancel",               "❌ إلغاء الفواتير",         "invoices"),
    ("invoice_delete",               "🗑️ حذف الفواتير",          "invoices"),
    # المنتجات والمخزون
    ("products",                     "🛍️ عرض المنتجات",          "products"),
    ("products_edit",                "✏️ إضافة/تعديل المنتجات",   "products"),
    ("warehouse",                    "🏭 إدارة المخزون",          "products"),
    # التقارير
    ("reports",                      "📊 التقارير والتحليلات",    "reports"),
    ("reports_financial",            "💰 التقارير المالية",       "reports"),
    ("reports_export",               "📥 تصدير التقارير",        "reports"),
    # العملاء
    ("customers",                    "👥 عرض العملاء",           "customers"),
    ("customers_edit",               "✏️ إضافة/تعديل العملاء",   "customers"),
    # الموارد البشرية
    ("hr",                           "👔 الموارد البشرية",        "hr"),
    ("hr_payroll",                   "💵 الرواتب",               "hr"),
    # الإعدادات
    ("settings",                     "⚙️ الإعدادات",             "settings"),
    ("business_profile_edit",        "🏢 تعديل بيانات المنشأة",   "settings"),
    ("business_profile_reason_optional","✂️ تخطي سبب التعديل",   "settings"),
    # الخزينة
    ("treasury",                     "🏦 الخزينة",               "treasury"),
    ("treasury_withdraw",            "💸 سحب من الخزينة",        "treasury"),
]

PERM_CATEGORIES = {
    "system":    "🔐 النظام",
    "invoices":  "📄 الفواتير",
    "products":  "🛍️ المنتجات والمخزون",
    "reports":   "📊 التقارير",
    "customers": "👥 العملاء",
    "hr":        "👔 الموارد البشرية",
    "settings":  "⚙️ الإعدادات",
    "treasury":  "🏦 الخزينة",
}


@bp.route("/api-docs")
@admin_required
def api_docs():
    """صفحة توثيق REST API"""
    return render_template("admin/api_docs.html")


@bp.route("/roles", methods=["GET", "POST"])
@admin_required
def admin_roles():
    """إدارة الأدوار والصلاحيات"""
    db = get_db()
    _ensure_admin_tables(db)

    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard

        action = request.form.get("action", "").strip()

        if action == "create_role":
            name = request.form.get("role_name", "").strip()
            if not name:
                flash("اسم الدور مطلوب", "error")
            elif db.execute("SELECT id FROM roles WHERE name=?", (name,)).fetchone():
                flash("هذا الاسم موجود مسبقاً", "error")
            else:
                # جمع الصلاحيات المختارة
                selected = {p: True for p, *_ in ALL_PERMISSIONS if request.form.get(f"perm_{p}")}
                db.execute(
                    "INSERT INTO roles (name, permissions) VALUES (?, ?)",
                    (name, json.dumps(selected, ensure_ascii=False)),
                )
                db.commit()
                flash(f"تم إنشاء الدور «{name}»", "success")

        elif action == "update_role":
            role_id = int(request.form.get("role_id", 0) or 0)
            name    = request.form.get("role_name", "").strip()
            selected = {p: True for p, *_ in ALL_PERMISSIONS if request.form.get(f"perm_{p}")}
            db.execute(
                "UPDATE roles SET name=?, permissions=? WHERE id=?",
                (name, json.dumps(selected, ensure_ascii=False), role_id),
            )
            db.commit()
            flash(f"تم تحديث الدور «{name}»", "success")

        elif action == "delete_role":
            role_id = int(request.form.get("role_id", 0) or 0)
            # لا تحذف إذا فيه مستخدمون
            count = _safe_scalar(db, "SELECT COUNT(*) FROM users WHERE role_id=?", (role_id,)) or 0
            if count > 0:
                flash(f"لا يمكن الحذف — يوجد {count} مستخدم بهذا الدور", "error")
            else:
                db.execute("DELETE FROM roles WHERE id=?", (role_id,))
                db.commit()
                flash("تم حذف الدور", "success")

        return redirect(url_for("admin.admin_roles"))

    roles_raw = _rows_to_dicts(_safe_fetchall(db, """
        SELECT r.*, COUNT(u.id) AS user_count
        FROM roles r
        LEFT JOIN users u ON u.role_id = r.id
        GROUP BY r.id ORDER BY r.id
    """))

    # فكّ JSON الصلاحيات لكل دور
    roles = []
    for r in roles_raw:
        try:
            r["perms_dict"] = json.loads(r.get("permissions") or "{}")
        except Exception:
            r["perms_dict"] = {}
        r["perm_count"] = len([k for k, v in r["perms_dict"].items() if v])
        roles.append(r)

    return render_template("admin/roles.html",
        roles=roles,
        all_permissions=ALL_PERMISSIONS,
        perm_categories=PERM_CATEGORIES,
    )


@bp.route("/roles/<int:role_id>/json")
@admin_required
def role_permissions_json(role_id: int):
    """API: صلاحيات دور معين (لـ AJAX)"""
    db = get_db()
    row = db.execute("SELECT name, permissions FROM roles WHERE id=?", (role_id,)).fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    try:
        perms = json.loads((row[1] if not isinstance(row, dict) else row["permissions"]) or "{}")
    except Exception:
        perms = {}
    name = row[0] if not isinstance(row, dict) else row["name"]
    return jsonify({"id": role_id, "name": name, "permissions": perms})


# ═══════════════════════════════════════════════════════════════════════════════
# REST API Layer — /api/v1/*
# ═══════════════════════════════════════════════════════════════════════════════

api = Blueprint("api_v1", __name__, url_prefix="/api/v1")


def _api_auth():
    """تحقق من session أو API key في الـ Header"""
    # يسمح للمستخدمين المسجلين
    if session.get("user_id"):
        return True
    # يسمح لـ API key موثق
    api_key = request.headers.get("X-API-Key", "")
    if api_key:
        db = get_db()
        try:
            row = db.execute(
                "SELECT setting_value FROM platform_settings WHERE setting_key='platform_api_key'",
            ).fetchone()
            stored = row[0] if row and not isinstance(row, dict) else (row.get("setting_value","") if row else "")
            if stored and stored == api_key:
                return True
        except Exception:
            pass
    return False


def _api_require_auth():
    if not _api_auth():
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    return None


# ── المنشآت ──────────────────────────────────────────────────────────────────

@api.route("/businesses", methods=["GET"])
def api_businesses():
    guard = _api_require_auth()
    if guard:
        return guard
    db = get_db()
    page  = max(1, int(request.args.get("page", 1)))
    limit = min(100, int(request.args.get("limit", 20)))
    offset = (page - 1) * limit
    search = request.args.get("q", "").strip()

    where = "1=1"
    params = []
    if search:
        where = "(name LIKE ? OR industry_type LIKE ?)"
        params = [f"%{search}%", f"%{search}%"]

    total = _safe_scalar(get_db(), f"SELECT COUNT(*) FROM businesses WHERE {where}", params) or 0
    rows  = _rows_to_dicts(_safe_fetchall(db,
        f"SELECT id, name, industry_type, account_status, created_at FROM businesses WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ))
    return jsonify({"success": True, "total": total, "page": page, "data": rows})


@api.route("/businesses/<int:bid>", methods=["GET"])
def api_business_detail(bid: int):
    guard = _api_require_auth()
    if guard:
        return guard
    db = get_db()
    row = db.execute("""
        SELECT b.*, COUNT(u.id) AS user_count,
               COUNT(i.id) AS invoice_count,
               ROUND(SUM(i.total_amount),2) AS total_revenue
        FROM businesses b
        LEFT JOIN users u ON u.business_id=b.id
        LEFT JOIN invoices i ON i.business_id=b.id
        WHERE b.id=?
        GROUP BY b.id
    """, (bid,)).fetchone()
    if not row:
        return jsonify({"success": False, "error": "not found"}), 404
    return jsonify({"success": True, "data": dict(row)})


# ── المستخدمون ───────────────────────────────────────────────────────────────

@api.route("/users", methods=["GET"])
def api_users():
    guard = _api_require_auth()
    if guard:
        return guard
    db = get_db()
    page  = max(1, int(request.args.get("page", 1)))
    limit = min(100, int(request.args.get("limit", 20)))
    offset = (page - 1) * limit
    rows  = _rows_to_dicts(_safe_fetchall(db, """
        SELECT u.id, u.username, u.full_name, u.email, u.is_active,
               b.name AS business, r.name AS role, u.created_at
        FROM users u
        LEFT JOIN businesses b ON b.id=u.business_id
        LEFT JOIN roles r ON r.id=u.role_id
        ORDER BY u.id DESC LIMIT ? OFFSET ?
    """, (limit, offset)))
    total = _safe_scalar(db, "SELECT COUNT(*) FROM users") or 0
    return jsonify({"success": True, "total": total, "page": page, "data": rows})


@api.route("/users/<int:uid>", methods=["PATCH"])
def api_user_patch(uid: int):
    guard = _api_require_auth()
    if guard:
        return guard
    guard2 = csrf_protect()
    if guard2:
        return jsonify({"success": False, "error": "CSRF"}), 403

    data = request.get_json(silent=True) or {}
    db = get_db()
    allowed = {"is_active": int, "role_id": int}
    updates = {}
    for field, cast in allowed.items():
        if field in data:
            try:
                updates[field] = cast(data[field])
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": f"invalid {field}"}), 400

    if not updates:
        return jsonify({"success": False, "error": "no valid fields"}), 400

    set_clause = ", ".join(f"{k}=?" for k in updates)
    db.execute(f"UPDATE users SET {set_clause} WHERE id=?", list(updates.values()) + [uid])
    db.commit()
    return jsonify({"success": True, "updated": list(updates.keys())})


# ── الفواتير ─────────────────────────────────────────────────────────────────

@api.route("/invoices", methods=["GET"])
def api_invoices():
    guard = _api_require_auth()
    if guard:
        return guard
    db = get_db()
    page  = max(1, int(request.args.get("page", 1)))
    limit = min(200, int(request.args.get("limit", 50)))
    offset = (page - 1) * limit
    biz_id = request.args.get("business_id", "")
    since  = request.args.get("since", "")

    where_parts = ["1=1"]
    params = []
    if biz_id and biz_id.isdigit():
        where_parts.append("i.business_id=?")
        params.append(int(biz_id))
    if since:
        where_parts.append("i.created_at >= ?")
        params.append(since)

    total = _safe_scalar(db,
        f"SELECT COUNT(*) FROM invoices i WHERE {' AND '.join(where_parts)}", params) or 0
    rows = _rows_to_dicts(_safe_fetchall(db, f"""
        SELECT i.id, i.invoice_number, i.total_amount, i.tax_amount,
               i.status, i.created_at, b.name AS business
        FROM invoices i
        LEFT JOIN businesses b ON b.id=i.business_id
        WHERE {' AND '.join(where_parts)}
        ORDER BY i.created_at DESC LIMIT ? OFFSET ?
    """, params + [limit, offset]))
    return jsonify({"success": True, "total": total, "page": page, "data": rows})


# ── إعدادات المنصة ───────────────────────────────────────────────────────────

@api.route("/platform/settings", methods=["GET"])
def api_platform_settings():
    guard = _api_require_auth()
    if guard:
        return guard
    db = get_db()
    # مسموح فقط بالإعدادات العامة (غير السرية)
    ALLOWED_KEYS = {
        "platform_name", "platform_tagline", "platform_logo_url",
        "platform_support_email", "platform_support_phone",
        "platform_twitter", "platform_whatsapp", "platform_footer_text",
        "platform_announcement",
    }
    rows = _rows_to_dicts(_safe_fetchall(db, "SELECT setting_key, setting_value FROM platform_settings"))
    data = {r["setting_key"]: r["setting_value"] for r in rows if r["setting_key"] in ALLOWED_KEYS}
    return jsonify({"success": True, "data": data})


@api.route("/platform/settings", methods=["PATCH"])
def api_platform_settings_patch():
    guard = _api_require_auth()
    if guard:
        return guard
    data = request.get_json(silent=True) or {}
    WRITABLE_KEYS = {"platform_announcement", "platform_name", "platform_tagline", "platform_support_email"}
    db = get_db()
    updated = []
    for key, val in data.items():
        if key in WRITABLE_KEYS:
            db.execute(
                """INSERT INTO platform_settings (setting_key, setting_value, updated_at)
                   VALUES (?, ?, datetime('now'))
                   ON CONFLICT(setting_key) DO UPDATE SET setting_value=excluded.setting_value, updated_at=excluded.updated_at""",
                (key, str(val)),
            )
            updated.append(key)
    db.commit()
    return jsonify({"success": True, "updated": updated})


# ── الإحصائيات الفورية ───────────────────────────────────────────────────────

@api.route("/stats/summary", methods=["GET"])
def api_stats_summary():
    guard = _api_require_auth()
    if guard:
        return guard
    db = get_db()
    return jsonify({
        "success": True,
        "data": {
            "businesses":      _safe_scalar(db, "SELECT COUNT(*) FROM businesses") or 0,
            "users":           _safe_scalar(db, "SELECT COUNT(*) FROM users") or 0,
            "invoices_total":  _safe_scalar(db, "SELECT COUNT(*) FROM invoices") or 0,
            "revenue_total":   _safe_scalar(db, "SELECT ROUND(SUM(total_amount),2) FROM invoices") or 0,
            "revenue_today":   _safe_scalar(db, "SELECT ROUND(SUM(total_amount),2) FROM invoices WHERE date(created_at)=date('now')") or 0,
            "new_today":       _safe_scalar(db, "SELECT COUNT(*) FROM businesses WHERE date(created_at)=date('now')") or 0,
        }
    })


@api.route("/stats/revenue-chart", methods=["GET"])
def api_revenue_chart():
    guard = _api_require_auth()
    if guard:
        return guard
    days = min(90, int(request.args.get("days", 30)))
    db   = get_db()
    rows = _rows_to_dicts(_safe_fetchall(db, """
        SELECT date(created_at) AS d, ROUND(SUM(total_amount),2) AS rev, COUNT(*) AS cnt
        FROM invoices
        WHERE created_at >= date('now', ?)
        GROUP BY date(created_at) ORDER BY d
    """, (f"-{days} days",)))
    return jsonify({"success": True, "days": days, "data": rows})


# ── الكتالوج ─────────────────────────────────────────────────────────────────

@api.route("/catalog", methods=["GET"])
def api_catalog():
    """API عام للمنتجات/الخدمات (متاح بدون auth إذا is_active=1)"""
    db = get_db()
    try:
        rows = _rows_to_dicts(_safe_fetchall(db, """
            SELECT id, name, description, price, category, image_url, is_featured, sort_order
            FROM platform_catalog WHERE is_active=1 ORDER BY sort_order, id
        """))
    except Exception:
        rows = []
    return jsonify({"success": True, "data": rows})


# ═══════════════════════════════════════════════════════════════════════════════
# نظام الأسعار الديناميكية والكوبونات (Dynamic Pricing & Coupons)
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/pricing", methods=["GET", "POST"])
@admin_required
def admin_pricing():
    """إدارة الأسعار الديناميكية والكوبونات والخصومات"""
    db = get_db()
    
    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard
        
        action = request.form.get("action", "").strip()
        
        # ── إنشاء كوبون جديد ──
        if action == "create_coupon":
            code = request.form.get("code", "").strip().upper()
            discount_type = request.form.get("discount_type", "percentage")
            discount_value = float(request.form.get("discount_value", 0))
            max_uses = request.form.get("max_uses")
            expires_at = request.form.get("expires_at")
            
            if not code or not expires_at:
                flash("الكود والتاريخ مطلوبان", "error")
            elif db.execute("SELECT id FROM coupons WHERE code=?", (code,)).fetchone():
                flash("هذا الكود موجود بالفعل", "error")
            else:
                db.execute("""
                    INSERT INTO coupons (code, discount_type, discount_value, max_uses, expires_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (code, discount_type, discount_value, max_uses or None, expires_at))
                db.commit()
                flash(f"✅ تم إنشاء الكود «{code}»", "success")
        
        # ── تعديل كوبون ──
        elif action == "update_coupon":
            coupon_id = int(request.form.get("coupon_id", 0))
            is_active = int(request.form.get("is_active", 0))
            discount_value = float(request.form.get("discount_value", 0))
            max_uses = request.form.get("max_uses")
            expires_at = request.form.get("expires_at")
            
            db.execute("""
                UPDATE coupons SET is_active=?, discount_value=?, max_uses=?, expires_at=?
                WHERE id=?
            """, (is_active, discount_value, max_uses or None, expires_at, coupon_id))
            db.commit()
            flash("✅ تم تحديث الكود", "success")
        
        # ── حذف كوبون ──
        elif action == "delete_coupon":
            coupon_id = int(request.form.get("coupon_id", 0))
            db.execute("DELETE FROM coupons WHERE id=?", (coupon_id,))
            db.commit()
            flash("✅ تم حذف الكود", "success")
        
        # ── إنشاء سعر ديناميكي ──
        elif action == "create_dynamic_price":
            product_id = int(request.form.get("product_id", 0))
            new_price = float(request.form.get("new_price", 0))
            expires_at = request.form.get("expires_at")
            reason = request.form.get("reason", "عرض مؤقت")
            
            db.execute("""
                INSERT INTO dynamic_prices (product_id, new_price, expires_at, reason)
                VALUES (?, ?, ?, ?)
            """, (product_id, new_price, expires_at, reason))
            db.commit()
            flash("✅ تم تفعيل السعر الجديد", "success")
        
        # ── حذف سعر ديناميكي ──
        elif action == "delete_dynamic_price":
            price_id = int(request.form.get("price_id", 0))
            db.execute("DELETE FROM dynamic_prices WHERE id=?", (price_id,))
            db.commit()
            flash("✅ تم إلغاء السعر الجديد", "success")
        
        return redirect(url_for("admin.admin_pricing"))
    
    # ── عرض الصفحة ──
    coupons = _rows_to_dicts(_safe_fetchall(db, """
        SELECT c.*, COUNT(DISTINCT cu.id) AS usage_count,
               ROUND(SUM(cu.discount_amount),2) AS total_discount
        FROM coupons c
        LEFT JOIN coupon_usage cu ON cu.coupon_id=c.id
        GROUP BY c.id ORDER BY c.created_at DESC
    """))
    
    dyn_prices = _rows_to_dicts(_safe_fetchall(db, """
        SELECT dp.*, pc.name AS product_name, pc.price AS original_price
        FROM dynamic_prices dp
        LEFT JOIN platform_catalog pc ON pc.id=dp.product_id
        WHERE dp.is_active=1 ORDER BY dp.expires_at
    """))
    
    campaigns = _rows_to_dicts(_safe_fetchall(db, """
        SELECT * FROM seasonal_campaigns WHERE is_active=1 ORDER BY ends_at DESC
    """))
    
    products = _rows_to_dicts(_safe_fetchall(db, """
        SELECT id, name, price FROM platform_catalog WHERE is_active=1 ORDER BY name
    """))
    
    return render_template("admin/pricing.html",
        coupons=coupons,
        dyn_prices=dyn_prices,
        campaigns=campaigns,
        products=products,
    )


@bp.route("/pricing/validate-coupon", methods=["POST"])
def validate_coupon_api():
    """API للتحقق من صحة الكود (للاستخدام في الفواتير)"""
    data = request.get_json(silent=True) or {}
    code = data.get("code", "").strip().upper()
    amount = float(data.get("amount", 0))
    
    db = get_db()
    coupon = db.execute("""
        SELECT * FROM coupons WHERE code=? AND is_active=1 AND expires_at > datetime('now')
        AND (max_uses IS NULL OR current_uses < max_uses)
    """, (code,)).fetchone()
    
    if not coupon:
        return jsonify({"success": False, "error": "كود غير صحيح أو منتهي"}), 400
    
    # حساب الخصم
    if coupon["discount_type"] == "percentage":
        discount = amount * (coupon["discount_value"] / 100)
        if coupon["max_discount"]:
            discount = min(discount, coupon["max_discount"])
    else:
        discount = min(coupon["discount_value"], amount)
    
    if amount < (coupon["min_purchase"] or 0):
        return jsonify({"success": False, "error": f"الحد الأدنى للشراء: {coupon['min_purchase']} ريال"}), 400
    
    return jsonify({
        "success": True,
        "code": code,
        "discount": round(discount, 2),
        "discount_type": coupon["discount_type"]
    })
