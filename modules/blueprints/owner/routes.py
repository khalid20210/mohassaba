"""
blueprints/owner/routes.py
قمرة القيادة — Owner Intelligence Dashboard
السيادة المطلقة للمالك: أرباح، رقابة، موارد بشرية، API Keys، وضع العرض
"""
import hashlib
import io
import csv
import json
import os
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for, flash

from modules.core_utils import table_exists as db_table_exists
from modules.extensions import get_db, safe_sql_identifier, csrf_protect
from modules.middleware import owner_required, write_audit_log
from modules.sovereign_controls import (
    create_owner_action_request,
    ensure_sovereign_tables,
    get_owner_policy_map,
    log_owner_impact,
    release_cashier_lock,
    set_owner_policy,
)

bp = Blueprint("owner", __name__, url_prefix="/owner")


TARGET_ACTIVITY_FAMILIES = {
    "retail_food",
    "wholesale_food",
    "ecommerce_food",
    "retail_fashion",
    "wholesale_fashion",
    "ecommerce_fashion",
    "retail_shoes",
    "wholesale_shoes",
    "ecommerce_shoes",
    "health_pharmacy",
    "health_hospital",
    "retail_general",
    "wholesale_general",
    "ecommerce_general",
    "general",
}

OWNER_ROBOT_OPTIONS = {
    "invoice_thresholds": [3, 6, 9, 12],
    "activation_states": ["off", "sandbox", "active"],
    "operation_modes": ["warn_only", "assistive", "auto_after_confirm"],
    "warning_levels": ["low", "medium", "high"],
    "check_frequencies": ["realtime", "daily", "weekly"],
    "notify_channels": ["in_app", "email", "sms", "whatsapp"],
    "presets": ["conservative", "balanced", "aggressive"],
}

OWNER_ROBOT_PRESETS = {
    "conservative": {
        "operation_mode": "warn_only",
        "alert_invoice_threshold": 12,
        "warning_level": "high",
        "check_frequency": "daily",
        "notify_channel": "in_app",
    },
    "balanced": {
        "operation_mode": "assistive",
        "alert_invoice_threshold": 6,
        "warning_level": "medium",
        "check_frequency": "daily",
        "notify_channel": "in_app",
    },
    "aggressive": {
        "operation_mode": "auto_after_confirm",
        "alert_invoice_threshold": 3,
        "warning_level": "low",
        "check_frequency": "realtime",
        "notify_channel": "in_app",
    },
}


def _sector_from_industry_type(industry_type: str) -> str:
    code = (industry_type or "").strip().lower()
    if not code:
        return "general"
    if any(k in code for k in ("school", "education", "academy", "university", "edu", "retail_education")):
        return "education"
    if any(k in code for k in ("health", "medical", "pharmacy", "clinic", "hospital", "dental", "lab")):
        return "healthcare"
    if code.startswith("wholesale"):
        return "wholesale"
    if code.startswith("ecommerce"):
        return "ecommerce"
    if code.startswith("retail") or any(k in code for k in ("restaurant", "cafe", "market", "supermarket", "grocery", "pos")):
        return "retail"
    if any(k in code for k in ("realestate", "property", "rental", "estate", "leasing")):
        return "realestate"
    if any(k in code for k in ("contract", "construction", "services", "maintenance", "operation", "facility")):
        return "services"
    return "general"


def _ensure_owner_robot_settings_table(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS business_robot_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            robot_code TEXT NOT NULL,
            owner_enabled INTEGER NOT NULL DEFAULT 0,
            preset_mode TEXT NOT NULL DEFAULT 'balanced',
            operation_mode TEXT NOT NULL DEFAULT 'assistive',
            alert_invoice_threshold INTEGER NOT NULL DEFAULT 6,
            warning_level TEXT NOT NULL DEFAULT 'medium',
            check_frequency TEXT NOT NULL DEFAULT 'daily',
            notify_channel TEXT NOT NULL DEFAULT 'in_app',
            activation_state TEXT NOT NULL DEFAULT 'sandbox',
            updated_by INTEGER,
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(business_id, robot_code)
        )
        """
    )
    if not _column_exists(db, "business_robot_settings", "activation_state"):
        try:
            db.execute("ALTER TABLE business_robot_settings ADD COLUMN activation_state TEXT NOT NULL DEFAULT 'sandbox'")
        except Exception:
            pass
    db.commit()


def _ensure_platform_robot_catalog_table(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_robot_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            robot_code TEXT NOT NULL UNIQUE,
            robot_name TEXT NOT NULL,
            scope_type TEXT NOT NULL DEFAULT 'shared',
            activity_sector TEXT,
            risk_level TEXT NOT NULL DEFAULT 'medium',
            strict_mode INTEGER NOT NULL DEFAULT 1,
            requires_confirm INTEGER NOT NULL DEFAULT 1,
            rollout_state TEXT NOT NULL DEFAULT 'off',
            is_active INTEGER NOT NULL DEFAULT 0,
            description TEXT,
            created_by INTEGER,
            updated_by INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    db.commit()


def _ensure_robot_runtime_events_table(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS robot_runtime_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            robot_code TEXT NOT NULL,
            event_type TEXT NOT NULL,
            event_bucket TEXT,
            payload_json TEXT,
            created_by INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(business_id, robot_code, event_type, event_bucket)
        )
        """
    )
    db.commit()


def _ensure_robot_runtime_dispatches_table(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS robot_runtime_dispatches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_id INTEGER NOT NULL,
            robot_code TEXT NOT NULL,
            event_type TEXT NOT NULL,
            notify_channel TEXT NOT NULL DEFAULT 'in_app',
            attempted_count INTEGER NOT NULL DEFAULT 0,
            delivered_count INTEGER NOT NULL DEFAULT 0,
            delivery_status TEXT NOT NULL DEFAULT 'queued',
            details_json TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
        """
    )
    db.commit()


def _table_exists(db, table_name: str) -> bool:
    return db_table_exists(db, table_name)


def _column_exists(db, table_name: str, column_name: str) -> bool:
    try:
        safe_table = safe_sql_identifier(table_name)
        rows = db.execute(f"PRAGMA table_info({safe_table})").fetchall()
        return any(r[1] == column_name for r in rows)
    except Exception:
        return False


def _detect_activity_family(industry_type: str) -> str:
    industry_type = (industry_type or "").strip().lower()

    if industry_type.startswith("ecommerce_") or industry_type == "ecommerce":
        if any(industry_type.startswith(prefix) for prefix in (
            "ecommerce_food",
            "ecommerce_fnb",
            "ecommerce_sweets",
            "ecommerce_beverages",
        )):
            return "ecommerce_food"
        if any(industry_type.startswith(prefix) for prefix in (
            "ecommerce_fashion",
            "ecommerce_clothing",
            "ecommerce_shoes",
            "ecommerce_bags",
            "ecommerce_watches",
            "ecommerce_jewelry",
            "ecommerce_accessories",
        )):
            return "ecommerce_fashion"
        return "ecommerce_general"

    if industry_type.startswith("wholesale_") or industry_type == "wholesale":
        if "shoe" in industry_type or "shoes" in industry_type or "احذ" in industry_type:
            return "wholesale_shoes"
        if industry_type.startswith("wholesale_fashion_"):
            return "wholesale_fashion"
        if industry_type.startswith("wholesale_fnb_"):
            return "wholesale_food"
        return "wholesale_general"

    if industry_type.startswith("retail_fnb_"):
        return "retail_food"
    if industry_type.startswith("retail_health_pharmacy"):
        return "health_pharmacy"
    if industry_type.startswith("retail_health_medical") or industry_type.startswith("medical"):
        return "health_hospital"
    if "shoe" in industry_type or "shoes" in industry_type or "احذ" in industry_type:
        return "retail_shoes"
    if industry_type.startswith("retail_fashion_"):
        return "retail_fashion"
    if industry_type.startswith("retail_") or industry_type == "retail":
        return "retail_general"
    return "general"


def _infer_activity_family_from_product(name: str, description: str, category_name: str) -> str:
    txt = f"{name} {description} {category_name}".strip().lower()
    if not txt:
        return "unknown"

    # صيدلية/مستشفى أولاً لأنها حساسة ومحددة
    if any(k in txt for k in [
        "دواء", "صيدل", "pharma", "pharmacy", "tablet", "capsule", "كبسول", "شراب", "مضاد",
        "vitamin", "فيتامين", "panadol", "antibiotic"
    ]):
        return "health_pharmacy"

    if any(k in txt for k in [
        "مستشفى", "عيادة", "طبي", "medical", "hospital", "clinic", "جراحة", "اشعة", "تحاليل"
    ]):
        return "health_hospital"

    # أحذية قبل ملابس
    if any(k in txt for k in ["حذاء", "احذية", "shoe", "sneaker", "boot", "صندل"]):
        return "retail_shoes"

    if any(k in txt for k in [
        "قميص", "بنطال", "فستان", "عباية", "حجاب", "ملابس", "clothing", "fashion", "dress", "shirt", "jeans"
    ]):
        return "retail_fashion"

    if any(k in txt for k in [
        "غذ", "تموين", "قهوة", "شاي", "مشروب", "عصير", "لحم", "دجاج", "مخبوز", "supermarket", "grocery", "food"
    ]):
        return "retail_food"

    # قطاعات خارج نطاق الحقن التلقائي (مثال: مدارس) تحتاج قرار المالك
    if any(k in txt for k in [
        "مدرس", "مدرسة", "school", "edu", "education", "جامعة", "academy"
    ]):
        return "unknown"

    return "unknown"


def _family_group(family: str) -> str:
    fam = (family or "").strip().lower()
    if fam.endswith("_food"):
        return "food"
    if fam.endswith("_fashion"):
        return "fashion"
    if fam.endswith("_shoes"):
        return "shoes"
    if fam == "health_pharmacy":
        return "pharmacy"
    if fam == "health_hospital":
        return "hospital"
    if fam.endswith("_general"):
        return "general"
    return "unknown"


def _family_matches_target(item_family: str, target_family: str) -> bool:
    item = (item_family or "").strip().lower()
    target = (target_family or "").strip().lower()

    if not target or target == "general":
        return True
    if target == item:
        return True

    # قبول التطابق المنطقي داخل القناة نفسها (retail/wholesale/ecommerce)
    if target in {"retail_food", "wholesale_food", "ecommerce_food"}:
        return item.endswith("_food")
    if target in {"retail_fashion", "wholesale_fashion", "ecommerce_fashion"}:
        return item.endswith("_fashion")
    if target in {"retail_shoes", "wholesale_shoes", "ecommerce_shoes"}:
        return item.endswith("_shoes")
    if target in {"retail_general", "wholesale_general", "ecommerce_general"}:
        return item.endswith("_general")

    if target == "health_pharmacy":
        return item == "health_pharmacy"
    if target == "health_hospital":
        return item == "health_hospital"

    return False


def _adapt_item_family_for_channel(item_family: str, target_family: str) -> str:
    """يوحّد عائلة العنصر مع قناة الهدف (تجزئة/جملة/متجر إلكتروني) عند الحاجة."""
    item = (item_family or "unknown").strip().lower()
    target = (target_family or "").strip().lower()

    if item == "unknown":
        return "unknown"

    if target.startswith("wholesale_"):
        if item.endswith("_food"):
            return "wholesale_food"
        if item.endswith("_fashion"):
            return "wholesale_fashion"
        if item.endswith("_shoes"):
            return "wholesale_shoes"
        return "wholesale_general"

    if target.startswith("ecommerce_"):
        if item.endswith("_food"):
            return "ecommerce_food"
        if item.endswith("_fashion"):
            return "ecommerce_fashion"
        if item.endswith("_shoes"):
            return "ecommerce_shoes"
        return "ecommerce_general"

    if target.startswith("retail_"):
        if item.endswith("_food"):
            return "retail_food"
        if item.endswith("_fashion"):
            return "retail_fashion"
        if item.endswith("_shoes"):
            return "retail_shoes"
        return "retail_general"

    return item


def _expand_family_scope(item_family: str) -> set[str]:
    """يوسّع عائلة الصنف إلى كل القنوات المناظرة (تجزئة/جملة/متجر إلكتروني)."""
    fam = (item_family or "").strip().lower()
    if fam.endswith("_food"):
        return {"retail_food", "wholesale_food", "ecommerce_food"}
    if fam.endswith("_fashion"):
        return {"retail_fashion", "wholesale_fashion", "ecommerce_fashion"}
    if fam.endswith("_shoes"):
        return {"retail_shoes", "wholesale_shoes", "ecommerce_shoes"}
    if fam.endswith("_general"):
        return {"retail_general", "wholesale_general", "ecommerce_general"}
    if fam in {"health_pharmacy", "health_hospital"}:
        return {fam}
    if fam == "unknown":
        return set()
    return {"general"}


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
    raw = (str(val or "").strip().replace(",", ""))
    if not raw:
        return 0.0
    try:
        return float(raw)
    except Exception:
        return 0.0


def _default_category_for_activity(activity_family: str, name: str, description: str) -> str:
    txt = f"{name} {description}".lower()

    if activity_family in {"retail_food", "wholesale_food", "ecommerce_food"}:
        if any(k in txt for k in ["قهوة", "coffee", "شاي", "tea", "مشروب", "drink"]):
            return "مشروبات"
        if any(k in txt for k in ["حلويات", "حلو", "cake", "chocolate"]):
            return "حلويات"
        return "مواد غذائية"

    if activity_family in {"retail_fashion", "wholesale_fashion", "ecommerce_fashion"}:
        if any(k in txt for k in ["حذاء", "shoe", "شنطة", "bag"]):
            return "اكسسوارات"
        return "ملابس"

    if activity_family in {"retail_shoes", "wholesale_shoes", "ecommerce_shoes"}:
        return "أحذية"

    if activity_family == "health_pharmacy":
        return "منتجات صيدلية"

    if activity_family == "health_hospital":
        return "مستلزمات طبية"

    if activity_family.startswith("ecommerce"):
        return "منتجات متجر إلكتروني"

    if activity_family.startswith("wholesale"):
        return "جملة عامة"
    return "منتجات عامة"


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


def _normalize_uploaded_product(row: dict, activity_family: str):
    name = _extract_first(row, ["الاسم", "اسم المنتج", "name", "product name"])
    if not name:
        return None

    barcode = _extract_first(row, ["الباركود", "barcode", "ean", "sku"]) or ""
    barcode = barcode.replace(" ", "").replace('"', "")

    price = _to_float(_extract_first(row, ["السعر", "سعر البيع", "sale_price", "price"]))
    description = _extract_first(row, ["الوصف", "description", "desc"]) or ""
    category_name = _extract_first(row, ["صنف المنتج", "التصنيف", "category", "category_name"])
    if not category_name:
        category_name = _default_category_for_activity(activity_family, name, description)

    return {
        "name": name,
        "barcode": barcode,
        "price": price,
        "description": description,
        "category_name": category_name,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  الصفحة الرئيسية — قمرة القيادة
# ══════════════════════════════════════════════════════════════════════════════

@bp.route("/")
@owner_required
def owner_dashboard():
    """الشاشة الموحدة: صافي الأرباح + مبيعات المناديب + رواتب الموظفين"""
    db     = get_db()
    biz_id = session["business_id"]

    # ── KPIs ──────────────────────────────────────────────────────────────────
    today   = datetime.now().strftime("%Y-%m-%d")
    month   = datetime.now().strftime("%Y-%m")

    sales_today = db.execute(
        """SELECT COALESCE(SUM(total), 0) FROM invoices
           WHERE business_id=? AND invoice_type='sale'
             AND date(created_at)=?""",
        (biz_id, today)
    ).fetchone()[0]

    sales_month = db.execute(
        """SELECT COALESCE(SUM(total), 0) FROM invoices
           WHERE business_id=? AND invoice_type='sale'
             AND strftime('%Y-%m', created_at)=?""",
        (biz_id, month)
    ).fetchone()[0]

    cost_month = db.execute(
        """SELECT COALESCE(SUM(total), 0) FROM invoices
           WHERE business_id=? AND invoice_type='purchase'
             AND strftime('%Y-%m', created_at)=?""",
        (biz_id, month)
    ).fetchone()[0]

    net_profit = float(sales_month) - float(cost_month)

    # ── إحصاء الموظفين والمناديب ─────────────────────────────────────────────
    emp_count = db.execute(
        "SELECT COUNT(*) FROM employees WHERE business_id=? AND is_active=1", (biz_id,)
    ).fetchone()[0]

    agent_count = db.execute(
        "SELECT COUNT(*) FROM agents WHERE business_id=? AND is_active=1", (biz_id,)
    ).fetchone()[0]

    pending_deductions = db.execute(
        """SELECT COUNT(*) FROM shift_blind_closures
           WHERE business_id=? AND shortage_amount > 0""",
        (biz_id,)
    ).fetchone()[0]

    # ── مبيعات اليوم حسب الكاشير ─────────────────────────────────────────────
    sales_by_cashier_today = []
    if _table_exists(db, "invoices") and _column_exists(db, "invoices", "created_by"):
        sales_by_cashier_today = db.execute(
            """SELECT
                   COALESCE(u.full_name, 'مستخدم #' || CAST(i.created_by AS TEXT)) AS actor_name,
                   COUNT(i.id) AS invoices_count,
                   ROUND(COALESCE(SUM(i.total), 0), 2) AS sales_total
               FROM invoices i
               LEFT JOIN users u ON u.id = i.created_by
               WHERE i.business_id=?
                 AND i.invoice_type IN ('sale','table')
                 AND i.status='paid'
                 AND DATE(COALESCE(i.invoice_date, i.created_at)) = ?
                 AND i.created_by IS NOT NULL
               GROUP BY i.created_by
               ORDER BY sales_total DESC
               LIMIT 12""",
            (biz_id, today),
        ).fetchall()

    # ── مبيعات اليوم حسب المندوب ─────────────────────────────────────────────
    sales_by_agent_today = []
    if _table_exists(db, "agent_invoice_links") and _table_exists(db, "agents"):
        sales_by_agent_today = db.execute(
            """SELECT
                   a.full_name AS actor_name,
                   COUNT(i.id) AS invoices_count,
                   ROUND(COALESCE(SUM(i.total), 0), 2) AS sales_total
               FROM agent_invoice_links ail
               JOIN agents a ON a.id = ail.agent_id AND a.business_id = ail.business_id
               JOIN invoices i ON i.id = ail.invoice_id AND i.business_id = ail.business_id
               WHERE ail.business_id=?
                 AND i.invoice_type IN ('sale','table')
                 AND i.status='paid'
                 AND DATE(COALESCE(i.invoice_date, i.created_at)) = ?
               GROUP BY a.id
               ORDER BY sales_total DESC
               LIMIT 12""",
            (biz_id, today),
        ).fetchall()

    # ── ملخص المقاولات (مشاريع/مستخلصات) ───────────────────────────────────
    construction_summary = {
        "total_projects": 0,
        "active_projects": 0,
        "completed_projects": 0,
        "completed_this_month": 0,
        "extracts_this_month": 0,
        "invoiced_extracts_this_month": 0,
    }
    if _table_exists(db, "projects"):
        p = db.execute(
            """SELECT
                   COUNT(*) AS total_projects,
                   SUM(CASE WHEN project_status IN ('in_progress','planning','on_hold') THEN 1 ELSE 0 END) AS active_projects,
                   SUM(CASE WHEN project_status='completed' THEN 1 ELSE 0 END) AS completed_projects,
                   SUM(CASE
                         WHEN project_status='completed'
                          AND actual_end_date IS NOT NULL
                          AND strftime('%Y-%m', actual_end_date)=?
                         THEN 1 ELSE 0 END
                   ) AS completed_this_month
               FROM projects
               WHERE business_id=?""",
            (month, biz_id),
        ).fetchone()
        construction_summary.update({
            "total_projects": int((p[0] or 0) if p else 0),
            "active_projects": int((p[1] or 0) if p else 0),
            "completed_projects": int((p[2] or 0) if p else 0),
            "completed_this_month": int((p[3] or 0) if p else 0),
        })

    if _table_exists(db, "project_extracts"):
        e = db.execute(
            """SELECT
                   COUNT(*) AS extracts_this_month,
                   SUM(CASE WHEN status='invoiced' THEN 1 ELSE 0 END) AS invoiced_extracts_this_month
               FROM project_extracts
               WHERE business_id=?
                 AND strftime('%Y-%m', extract_date)=?""",
            (biz_id, month),
        ).fetchone()
        construction_summary.update({
            "extracts_this_month": int((e[0] or 0) if e else 0),
            "invoiced_extracts_this_month": int((e[1] or 0) if e else 0),
        })

    # ── نبض تشغيلي عام (ملخص سريع من كل الوحدات) ─────────────────────────
    operational_snapshot = {
        "invoices_today": 0,
        "receivables_open": 0.0,
        "products_count": 0,
        "contacts_count": 0,
    }
    if _table_exists(db, "invoices"):
        inv_row = db.execute(
            """SELECT
                   COUNT(CASE WHEN DATE(COALESCE(invoice_date, created_at))=? THEN 1 END) AS invoices_today,
                   ROUND(COALESCE(SUM(CASE
                        WHEN invoice_type IN ('sale','table') AND status IN ('pending','partial')
                        THEN (COALESCE(total,0) - COALESCE(paid_amount,0))
                        ELSE 0 END), 0), 2) AS receivables_open
               FROM invoices
               WHERE business_id=?""",
            (today, biz_id),
        ).fetchone()
        operational_snapshot.update({
            "invoices_today": int((inv_row[0] or 0) if inv_row else 0),
            "receivables_open": float((inv_row[1] or 0) if inv_row else 0),
        })

    if _table_exists(db, "products"):
        operational_snapshot["products_count"] = int(
            db.execute("SELECT COUNT(*) FROM products WHERE business_id=?", (biz_id,)).fetchone()[0] or 0
        )

    if _table_exists(db, "contacts"):
        operational_snapshot["contacts_count"] = int(
            db.execute("SELECT COUNT(*) FROM contacts WHERE business_id=?", (biz_id,)).fetchone()[0] or 0
        )

    # ── آخر 30 يوم: مبيعات يومية ─────────────────────────────────────────────
    daily_sales = db.execute(
        """SELECT date(created_at) as day, COALESCE(SUM(total),0) as total
           FROM invoices
           WHERE business_id=? AND invoice_type='sale'
             AND created_at >= date('now','-29 days')
           GROUP BY day ORDER BY day""",
        (biz_id,)
    ).fetchall()

    # ── مبيعات المناديب (top agents) ─────────────────────────────────────────
    agent_sales = db.execute(
        """SELECT a.full_name, a.employee_code,
                  COALESCE(SUM(ac.commission_amount),0) as total_commission,
                  COUNT(ac.id) as invoice_count
           FROM agents a
           LEFT JOIN agent_commissions ac ON ac.agent_id=a.id AND ac.business_id=?
           WHERE a.business_id=? AND a.is_active=1
           GROUP BY a.id
           ORDER BY total_commission DESC LIMIT 10""",
        (biz_id, biz_id)
    ).fetchall()

    # ── إجمالي الرواتب والخصومات للشهر الحالي ────────────────────────────────
    payroll_total = db.execute(
        """SELECT COALESCE(SUM(base_salary),0) FROM employees
           WHERE business_id=? AND is_active=1""",
        (biz_id,)
    ).fetchone()[0]

    deductions_total = db.execute(
        """SELECT COALESCE(SUM(amount),0) FROM payroll_deductions
           WHERE business_id=?
             AND strftime('%Y-%m', created_at)=?""",
        (biz_id, month)
    ).fetchone()[0]

    # ── إعدادات العرض ────────────────────────────────────────────────────────
    ext = db.execute(
        "SELECT * FROM business_settings_ext WHERE business_id=?", (biz_id,)
    ).fetchone()
    display_mode = (dict(ext)["display_mode"] if ext else "pro")

    # ── آخر 10 سجلات نشاط ────────────────────────────────────────────────────
    recent_logs = db.execute(
        """SELECT actor_name, actor_role, action, entity_type, created_at
           FROM audit_logs WHERE business_id=?
           ORDER BY created_at DESC LIMIT 10""",
        (biz_id,)
    ).fetchall()

    kpis = {
        "sales_today":        float(sales_today),
        "sales_month":        float(sales_month),
        "cost_month":         float(cost_month),
        "net_profit":         net_profit,
        "emp_count":          emp_count,
        "agent_count":        agent_count,
        "pending_deductions": pending_deductions,
        "payroll_total":      float(payroll_total),
        "deductions_total":   float(deductions_total),
    }

    _ensure_owner_robot_settings_table(db)
    _ensure_platform_robot_catalog_table(db)
    ensure_sovereign_tables(db)

    biz_row = db.execute("SELECT industry_type FROM businesses WHERE id=? LIMIT 1", (biz_id,)).fetchone()
    biz_sector = _sector_from_industry_type((biz_row["industry_type"] if biz_row else "") or "")
    owner_policy_map = get_owner_policy_map(db, int(biz_id))
    pending_owner_requests = db.execute(
        "SELECT COUNT(*) FROM owner_action_requests WHERE business_id=? AND status='pending'",
        (biz_id,),
    ).fetchone()[0]
    active_cashier_locks = db.execute(
        "SELECT COUNT(*) FROM pos_cashier_locks WHERE business_id=? AND status='active'",
        (biz_id,),
    ).fetchone()[0]
    impact_logs_24h = db.execute(
        "SELECT COUNT(*) FROM owner_impact_logs WHERE business_id=? AND datetime(created_at) >= datetime('now', '-24 hours')",
        (biz_id,),
    ).fetchone()[0]

    return render_template(
        "owner_dashboard.html",
        kpis=kpis,
        daily_sales=[dict(r) for r in daily_sales],
        agent_sales=[dict(r) for r in agent_sales],
        recent_logs=[dict(r) for r in recent_logs],
        sales_by_cashier_today=[dict(r) for r in sales_by_cashier_today],
        sales_by_agent_today=[dict(r) for r in sales_by_agent_today],
        construction_summary=construction_summary,
        operational_snapshot=operational_snapshot,
        display_mode=display_mode,
        owner_robot_options=OWNER_ROBOT_OPTIONS,
        owner_business_sector=biz_sector,
        owner_policy_map=owner_policy_map,
        pending_owner_requests=int(pending_owner_requests or 0),
        active_cashier_locks=int(active_cashier_locks or 0),
        impact_logs_24h=int(impact_logs_24h or 0),
    )


@bp.route("/api/robots/settings", methods=["GET"])
@owner_required
def owner_robot_settings_catalog():
    db = get_db()
    biz_id = session["business_id"]

    _ensure_owner_robot_settings_table(db)
    _ensure_platform_robot_catalog_table(db)
    _ensure_robot_runtime_events_table(db)
    _ensure_robot_runtime_dispatches_table(db)

    biz_row = db.execute("SELECT industry_type FROM businesses WHERE id=? LIMIT 1", (biz_id,)).fetchone()
    biz_sector = _sector_from_industry_type((biz_row["industry_type"] if biz_row else "") or "")

    robots = db.execute(
        """
        SELECT robot_code, robot_name, scope_type, activity_sector, risk_level,
               strict_mode, rollout_state, is_active, description
        FROM platform_robot_catalog
        WHERE scope_type='shared' OR LOWER(COALESCE(activity_sector,'')) = LOWER(?)
        ORDER BY scope_type ASC, robot_name ASC
        """,
        (biz_sector,),
    ).fetchall()

    settings_rows = db.execute(
        """
        SELECT robot_code, owner_enabled, preset_mode, operation_mode,
             alert_invoice_threshold, warning_level, check_frequency, notify_channel,
             activation_state,
               updated_at
        FROM business_robot_settings WHERE business_id=?
        """,
        (biz_id,),
    ).fetchall()
    settings_map = {
        (dict(r) if not isinstance(r, dict) else r).get("robot_code"): (dict(r) if not isinstance(r, dict) else r)
        for r in (settings_rows or [])
    }

    last_event_rows = db.execute(
        """
        SELECT e.robot_code, e.event_type, e.payload_json, e.created_at
        FROM robot_runtime_events e
        JOIN (
            SELECT robot_code, MAX(id) AS max_id
            FROM robot_runtime_events
            WHERE business_id=?
            GROUP BY robot_code
        ) x ON x.max_id = e.id
        WHERE e.business_id=?
        """,
        (biz_id, biz_id),
    ).fetchall()
    last_event_map = {
        (dict(r) if not isinstance(r, dict) else r).get("robot_code"): (dict(r) if not isinstance(r, dict) else r)
        for r in (last_event_rows or [])
    }

    dispatch_rows = db.execute(
        """
        SELECT d.robot_code, d.notify_channel, d.delivery_status,
               d.attempted_count, d.delivered_count, d.created_at
        FROM robot_runtime_dispatches d
        JOIN (
            SELECT robot_code, notify_channel, MAX(id) AS max_id
            FROM robot_runtime_dispatches
            WHERE business_id=?
            GROUP BY robot_code, notify_channel
        ) x ON x.max_id = d.id
        WHERE d.business_id=?
        """,
        (biz_id, biz_id),
    ).fetchall()
    dispatch_map: dict[str, dict[str, dict]] = {}
    for d in dispatch_rows or []:
        item = dict(d) if not isinstance(d, dict) else d
        code = str(item.get("robot_code") or "").strip()
        ch = str(item.get("notify_channel") or "in_app").strip().lower()
        if not code:
            continue
        dispatch_map.setdefault(code, {})[ch] = {
            "delivery_status": item.get("delivery_status") or "queued",
            "attempted_count": int(item.get("attempted_count") or 0),
            "delivered_count": int(item.get("delivered_count") or 0),
            "created_at": item.get("created_at"),
        }

    dispatch_24h_rows = db.execute(
        """
        SELECT notify_channel,
               SUM(COALESCE(attempted_count, 0)) AS attempted,
               SUM(COALESCE(delivered_count, 0)) AS delivered
        FROM robot_runtime_dispatches
        WHERE business_id=?
          AND datetime(created_at) >= datetime('now', '-24 hours')
        GROUP BY notify_channel
        """,
        (biz_id,),
    ).fetchall()
    channels_24h = {
        "in_app": {"attempted": 0, "delivered": 0, "failed": 0},
        "email": {"attempted": 0, "delivered": 0, "failed": 0},
        "sms": {"attempted": 0, "delivered": 0, "failed": 0},
        "whatsapp": {"attempted": 0, "delivered": 0, "failed": 0},
    }
    for row in dispatch_24h_rows or []:
        item = dict(row) if not isinstance(row, dict) else row
        channel = str(item.get("notify_channel") or "in_app").strip().lower()
        if channel not in channels_24h:
            continue
        attempted = int(item.get("attempted") or 0)
        delivered = int(item.get("delivered") or 0)
        channels_24h[channel] = {
            "attempted": attempted,
            "delivered": delivered,
            "failed": max(0, attempted - delivered),
        }

    failed_dispatch_24h_rows = db.execute(
        """
        SELECT robot_code, COUNT(*) AS c
        FROM robot_runtime_dispatches
        WHERE business_id=?
          AND datetime(created_at) >= datetime('now', '-24 hours')
          AND COALESCE(attempted_count, 0) > COALESCE(delivered_count, 0)
        GROUP BY robot_code
        """,
        (biz_id,),
    ).fetchall()
    failed_dispatch_24h_map = {
        (dict(r) if not isinstance(r, dict) else r).get("robot_code"): int((dict(r) if not isinstance(r, dict) else r).get("c") or 0)
        for r in (failed_dispatch_24h_rows or [])
    }

    alerts_24h = db.execute(
        """
        SELECT COUNT(*) AS c
        FROM robot_runtime_events
        WHERE business_id=?
          AND datetime(created_at) >= datetime('now', '-24 hours')
        """,
        (biz_id,),
    ).fetchone()
    alerts_24h_count = int((alerts_24h[0] if alerts_24h else 0) or 0)

    alerts_24h_robot_rows = db.execute(
        """
        SELECT robot_code, COUNT(*) AS c
        FROM robot_runtime_events
        WHERE business_id=?
          AND datetime(created_at) >= datetime('now', '-24 hours')
        GROUP BY robot_code
        """,
        (biz_id,),
    ).fetchall()
    alerts_24h_robot_map = {
        (dict(r) if not isinstance(r, dict) else r).get("robot_code"): int((dict(r) if not isinstance(r, dict) else r).get("c") or 0)
        for r in (alerts_24h_robot_rows or [])
    }

    data = []
    for item in robots or []:
        r = dict(item) if not isinstance(item, dict) else item
        s = settings_map.get(r.get("robot_code"), {}) or {}
        ev = last_event_map.get(r.get("robot_code"), {}) or {}
        dispatch_by_channel = dispatch_map.get(r.get("robot_code"), {}) or {}
        ev_payload = {}
        try:
            ev_payload = json.loads(ev.get("payload_json") or "{}") if ev else {}
        except Exception:
            ev_payload = {}
        row = {
            "robot_code": r.get("robot_code"),
            "robot_name": r.get("robot_name"),
            "scope_type": r.get("scope_type") or "shared",
            "activity_sector": r.get("activity_sector") or "",
            "risk_level": r.get("risk_level") or "medium",
            "strict_mode": int(r.get("strict_mode") or 0),
            "rollout_state": r.get("rollout_state") or "off",
            "platform_active": int(r.get("is_active") or 0),
            "description": r.get("description") or "",
            "owner_enabled": int(s.get("owner_enabled") or 0),
            "preset_mode": s.get("preset_mode") or "balanced",
            "operation_mode": s.get("operation_mode") or "assistive",
            "alert_invoice_threshold": int(s.get("alert_invoice_threshold") or 6),
            "warning_level": s.get("warning_level") or "medium",
            "check_frequency": s.get("check_frequency") or "daily",
            "notify_channel": s.get("notify_channel") or "in_app",
            "activation_state": s.get("activation_state") or "sandbox",
            "updated_at": s.get("updated_at"),
            "last_event_at": ev.get("created_at"),
            "last_event_type": ev.get("event_type"),
            "last_event_payload": ev_payload,
            "last_dispatch_by_channel": dispatch_by_channel,
                "has_alert_24h": bool(alerts_24h_robot_map.get(r.get("robot_code"), 0)),
                "has_failed_dispatch_24h": bool(failed_dispatch_24h_map.get(r.get("robot_code"), 0)),
        }
        data.append(row)

    robots_with_alerts_24h = sum(1 for r in data if bool(r.get("has_alert_24h")))
    robots_with_failed_dispatch_24h = sum(1 for r in data if bool(r.get("has_failed_dispatch_24h")))

    return jsonify(
        {
            "status": "success",
            "business_sector": biz_sector,
            "options": OWNER_ROBOT_OPTIONS,
            "summary": {
                "total": len(data),
                "platform_active": sum(1 for r in data if int(r.get("platform_active") or 0) == 1),
                "owner_enabled": sum(1 for r in data if int(r.get("owner_enabled") or 0) == 1),
                "alerts_24h": alerts_24h_count,
                "robots_with_alerts_24h": robots_with_alerts_24h,
                "robots_with_failed_dispatch_24h": robots_with_failed_dispatch_24h,
                "channels_24h": channels_24h,
            },
            "robots": data,
        }
    )


@bp.route("/api/robots/<path:robot_code>/settings", methods=["POST"])
@owner_required
def owner_update_robot_settings(robot_code: str):
    db = get_db()
    biz_id = session["business_id"]
    user_id = session["user_id"]

    guard = csrf_protect()
    if guard:
        return guard

    _ensure_owner_robot_settings_table(db)
    _ensure_platform_robot_catalog_table(db)

    clean_code = (robot_code or "").strip()
    if not clean_code:
        return jsonify({"status": "error", "message": "robot_code غير صالح"}), 400

    robot_row = db.execute(
        """
        SELECT robot_code, robot_name, scope_type, activity_sector, rollout_state, is_active
        FROM platform_robot_catalog WHERE robot_code=? LIMIT 1
        """,
        (clean_code,),
    ).fetchone()
    if not robot_row:
        return jsonify({"status": "error", "message": "الروبوت غير موجود في الكتالوج"}), 404

    robot = dict(robot_row) if not isinstance(robot_row, dict) else robot_row

    payload = request.get_json(silent=True) or {}
    owner_enabled = 1 if bool(payload.get("owner_enabled", False)) else 0
    preset_mode = str(payload.get("preset_mode", "balanced") or "balanced").strip().lower()
    operation_mode = str(payload.get("operation_mode", "assistive") or "assistive").strip().lower()
    warning_level = str(payload.get("warning_level", "medium") or "medium").strip().lower()
    check_frequency = str(payload.get("check_frequency", "daily") or "daily").strip().lower()
    notify_channel = str(payload.get("notify_channel", "in_app") or "in_app").strip().lower()
    activation_state = str(payload.get("activation_state", "sandbox") or "sandbox").strip().lower()
    try:
        alert_invoice_threshold = int(payload.get("alert_invoice_threshold", 6) or 6)
    except Exception:
        alert_invoice_threshold = 6

    if preset_mode not in OWNER_ROBOT_OPTIONS["presets"]:
        return jsonify({"status": "error", "message": "preset_mode غير صالح"}), 400
    if operation_mode not in OWNER_ROBOT_OPTIONS["operation_modes"]:
        return jsonify({"status": "error", "message": "operation_mode غير صالح"}), 400
    if warning_level not in OWNER_ROBOT_OPTIONS["warning_levels"]:
        return jsonify({"status": "error", "message": "warning_level غير صالح"}), 400
    if check_frequency not in OWNER_ROBOT_OPTIONS["check_frequencies"]:
        return jsonify({"status": "error", "message": "check_frequency غير صالح"}), 400
    if notify_channel not in OWNER_ROBOT_OPTIONS["notify_channels"]:
        return jsonify({"status": "error", "message": "notify_channel غير صالح"}), 400
    if activation_state not in OWNER_ROBOT_OPTIONS["activation_states"]:
        return jsonify({"status": "error", "message": "activation_state غير صالح"}), 400
    if alert_invoice_threshold not in OWNER_ROBOT_OPTIONS["invoice_thresholds"]:
        return jsonify({"status": "error", "message": "قيمة التنبيه يجب أن تكون من القائمة المحددة"}), 400

    # منع تفعيل روبوت غير مفعل مركزيًا
    rollout_state = (robot.get("rollout_state") or "off").strip().lower()
    platform_active = int(robot.get("is_active") or 0)
    if owner_enabled and (platform_active != 1 or rollout_state == "off"):
        return jsonify({"status": "error", "message": "الروبوت غير متاح للتشغيل حالياً من لوحة المنصة"}), 400

    # تطبيق Preset عند الطلب (مع إمكانية الكتابة اليدوية بعده)
    apply_preset = bool(payload.get("apply_preset", False))
    if apply_preset:
        preset = OWNER_ROBOT_PRESETS.get(preset_mode, OWNER_ROBOT_PRESETS["balanced"])
        operation_mode = preset["operation_mode"]
        alert_invoice_threshold = int(preset["alert_invoice_threshold"])
        warning_level = preset["warning_level"]
        check_frequency = preset["check_frequency"]
        notify_channel = preset["notify_channel"]

    db.execute(
        """
        INSERT INTO business_robot_settings
            (business_id, robot_code, owner_enabled, preset_mode, operation_mode,
             alert_invoice_threshold, warning_level, check_frequency, notify_channel, activation_state,
             updated_by, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(business_id, robot_code) DO UPDATE SET
            owner_enabled=excluded.owner_enabled,
            preset_mode=excluded.preset_mode,
            operation_mode=excluded.operation_mode,
            alert_invoice_threshold=excluded.alert_invoice_threshold,
            warning_level=excluded.warning_level,
            check_frequency=excluded.check_frequency,
            notify_channel=excluded.notify_channel,
            activation_state=excluded.activation_state,
            updated_by=excluded.updated_by,
            updated_at=datetime('now')
        """,
        (
            biz_id,
            clean_code,
            owner_enabled,
            preset_mode,
            operation_mode,
            alert_invoice_threshold,
            warning_level,
            check_frequency,
            notify_channel,
            activation_state,
            user_id,
        ),
    )
    db.commit()

    write_audit_log(
        db,
        biz_id,
        action="owner_robot_settings_updated",
        entity_type="robot_setting",
        new_value=json.dumps(
            {
                "robot_code": clean_code,
                "owner_enabled": owner_enabled,
                "preset_mode": preset_mode,
                "operation_mode": operation_mode,
                "alert_invoice_threshold": alert_invoice_threshold,
                "warning_level": warning_level,
                "check_frequency": check_frequency,
                "notify_channel": notify_channel,
                "activation_state": activation_state,
                "updated_by": user_id,
            },
            ensure_ascii=False,
        ),
    )
    log_owner_impact(
        db,
        business_id=int(biz_id),
        category="robot_governance",
        action_key="robot.settings_updated",
        summary=f"تحديث إعدادات الروبوت {clean_code} إلى حالة {activation_state}",
        entity_type="robot_setting",
        actor_user_id=int(user_id or 0) or None,
        payload={
            "robot_code": clean_code,
            "owner_enabled": owner_enabled,
            "activation_state": activation_state,
        },
    )
    db.commit()

    return jsonify(
        {
            "status": "success",
            "message": "تم حفظ إعدادات الروبوت بنجاح",
            "robot_code": clean_code,
            "owner_enabled": owner_enabled,
        }
    )


@bp.route("/api/robots/settings/bulk", methods=["POST"])
@owner_required
def owner_bulk_robot_settings():
    db = get_db()
    biz_id = session["business_id"]
    user_id = session["user_id"]

    guard = csrf_protect()
    if guard:
        return guard

    _ensure_owner_robot_settings_table(db)
    _ensure_platform_robot_catalog_table(db)

    payload = request.get_json(silent=True) or {}
    preset_mode = str(payload.get("preset_mode", "balanced") or "balanced").strip().lower()
    if preset_mode not in OWNER_ROBOT_OPTIONS["presets"]:
        return jsonify({"status": "error", "message": "preset_mode غير صالح"}), 400

    owner_enabled = None
    if "owner_enabled" in payload:
        owner_enabled = 1 if bool(payload.get("owner_enabled")) else 0

    preset = OWNER_ROBOT_PRESETS.get(preset_mode, OWNER_ROBOT_PRESETS["balanced"])

    biz_row = db.execute("SELECT industry_type FROM businesses WHERE id=? LIMIT 1", (biz_id,)).fetchone()
    biz_sector = _sector_from_industry_type((biz_row["industry_type"] if biz_row else "") or "")

    robots = db.execute(
        """
        SELECT robot_code, rollout_state, is_active
        FROM platform_robot_catalog
        WHERE scope_type='shared' OR LOWER(COALESCE(activity_sector,'')) = LOWER(?)
        """,
        (biz_sector,),
    ).fetchall()

    updated = 0
    blocked = 0
    for row in robots or []:
        r = dict(row) if not isinstance(row, dict) else row
        code = (r.get("robot_code") or "").strip()
        if not code:
            continue

        effective_enabled = owner_enabled
        if effective_enabled is None:
            existing = db.execute(
                "SELECT owner_enabled FROM business_robot_settings WHERE business_id=? AND robot_code=? LIMIT 1",
                (biz_id, code),
            ).fetchone()
            effective_enabled = int((existing[0] if existing else 0) or 0)

        rollout_state = str(r.get("rollout_state") or "off").strip().lower()
        platform_active = int(r.get("is_active") or 0)
        if int(effective_enabled or 0) == 1 and (platform_active != 1 or rollout_state == "off"):
            blocked += 1
            continue

        db.execute(
            """
            INSERT INTO business_robot_settings
                (business_id, robot_code, owner_enabled, preset_mode, operation_mode,
                 alert_invoice_threshold, warning_level, check_frequency, notify_channel, activation_state,
                 updated_by, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(business_id, robot_code) DO UPDATE SET
                owner_enabled=excluded.owner_enabled,
                preset_mode=excluded.preset_mode,
                operation_mode=excluded.operation_mode,
                alert_invoice_threshold=excluded.alert_invoice_threshold,
                warning_level=excluded.warning_level,
                check_frequency=excluded.check_frequency,
                notify_channel=excluded.notify_channel,
                activation_state=excluded.activation_state,
                updated_by=excluded.updated_by,
                updated_at=datetime('now')
            """,
            (
                biz_id,
                code,
                int(effective_enabled or 0),
                preset_mode,
                preset["operation_mode"],
                int(preset["alert_invoice_threshold"]),
                preset["warning_level"],
                preset["check_frequency"],
                preset["notify_channel"],
                "sandbox",
                user_id,
            ),
        )
        updated += 1

    db.commit()

    write_audit_log(
        db,
        biz_id,
        action="owner_robot_settings_bulk_updated",
        entity_type="robot_setting",
        new_value=json.dumps(
            {
                "preset_mode": preset_mode,
                "owner_enabled": owner_enabled,
                "updated": updated,
                "blocked": blocked,
                "updated_by": user_id,
            },
            ensure_ascii=False,
        ),
    )

    return jsonify(
        {
            "status": "success",
            "message": f"تم تطبيق الإعدادات على {updated} روبوت",
            "updated": updated,
            "blocked": blocked,
        }
    )


@bp.route("/api/robots/events", methods=["GET"])
@owner_required
def owner_robot_events_feed():
    db = get_db()
    biz_id = session["business_id"]

    _ensure_robot_runtime_events_table(db)
    _ensure_platform_robot_catalog_table(db)

    try:
        limit = int(request.args.get("limit", 20) or 20)
    except Exception:
        limit = 20
    limit = max(5, min(limit, 100))

    rows = db.execute(
        """
        SELECT e.id, e.robot_code, e.event_type, e.event_bucket, e.payload_json, e.created_at,
               c.robot_name
        FROM robot_runtime_events e
        LEFT JOIN platform_robot_catalog c ON c.robot_code = e.robot_code
        WHERE e.business_id=?
        ORDER BY e.id DESC
        LIMIT ?
        """,
        (biz_id, limit),
    ).fetchall()

    events = []
    for row in rows or []:
        item = dict(row) if not isinstance(row, dict) else row
        payload = {}
        try:
            payload = json.loads(item.get("payload_json") or "{}")
        except Exception:
            payload = {}
        events.append(
            {
                "id": item.get("id"),
                "robot_code": item.get("robot_code"),
                "robot_name": item.get("robot_name") or item.get("robot_code"),
                "event_type": item.get("event_type"),
                "event_bucket": item.get("event_bucket"),
                "payload": payload,
                "created_at": item.get("created_at"),
            }
        )

    return jsonify({"status": "success", "events": events})


@bp.route("/api/sovereign/policies", methods=["GET", "POST"])
@owner_required
def owner_sovereign_policies_api():
    db = get_db()
    biz_id = session["business_id"]
    user_id = session["user_id"]
    ensure_sovereign_tables(db)

    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard
        payload = request.get_json(silent=True) or {}
        updates = {
            "pos_cancel_daily_threshold": max(1, min(int(payload.get("pos_cancel_daily_threshold", 3) or 3), 50)),
            "inventory_damage_requires_owner": 1 if bool(payload.get("inventory_damage_requires_owner", True)) else 0,
            "payroll_manual_edit_requires_owner": 1 if bool(payload.get("payroll_manual_edit_requires_owner", True)) else 0,
            "journal_posted_requires_owner": 1 if bool(payload.get("journal_posted_requires_owner", True)) else 0,
            "robot_urgent_channel": str(payload.get("robot_urgent_channel", "whatsapp") or "whatsapp").strip().lower(),
            "robot_default_activation_state": str(payload.get("robot_default_activation_state", "sandbox") or "sandbox").strip().lower(),
        }
        if updates["robot_urgent_channel"] not in OWNER_ROBOT_OPTIONS["notify_channels"]:
            return jsonify({"status": "error", "message": "قناة التنبيه غير صالحة"}), 400
        if updates["robot_default_activation_state"] not in OWNER_ROBOT_OPTIONS["activation_states"]:
            return jsonify({"status": "error", "message": "حالة الروبوت الافتراضية غير صالحة"}), 400
        for key, value in updates.items():
            set_owner_policy(db, int(biz_id), key, value, updated_by=int(user_id or 0) or None)
        write_audit_log(
            db,
            biz_id,
            action="owner_sovereign_policies_updated",
            entity_type="owner_policy",
            new_value=json.dumps(updates, ensure_ascii=False),
        )
        log_owner_impact(
            db,
            business_id=int(biz_id),
            category="governance",
            action_key="owner.policies_updated",
            summary="تم تحديث سياسات المالك السيادية",
            entity_type="owner_policy",
            actor_user_id=int(user_id or 0) or None,
            payload=updates,
        )
        db.commit()
        return jsonify({"status": "success", "message": "تم حفظ سياسات المالك", "policies": get_owner_policy_map(db, int(biz_id))})

    return jsonify({"status": "success", "policies": get_owner_policy_map(db, int(biz_id))})


@bp.route("/api/impact-logs", methods=["GET"])
@owner_required
def owner_impact_logs_api():
    db = get_db()
    biz_id = session["business_id"]
    ensure_sovereign_tables(db)
    rows = db.execute(
        """
        SELECT id, category, action_key, entity_type, entity_id, actor_user_id,
               summary, reason, protected_amount, payload_json, created_at
        FROM owner_impact_logs
        WHERE business_id=?
        ORDER BY id DESC
        LIMIT 40
        """,
        (biz_id,),
    ).fetchall()
    logs = []
    for row in rows or []:
        item = dict(row) if not isinstance(row, dict) else row
        try:
            payload = json.loads(item.get("payload_json") or "{}")
        except Exception:
            payload = {}
        item["payload"] = payload
        item.pop("payload_json", None)
        logs.append(item)
    return jsonify({"status": "success", "logs": logs})


@bp.route("/api/action-requests", methods=["GET"])
@owner_required
def owner_action_requests_api():
    db = get_db()
    biz_id = session["business_id"]
    ensure_sovereign_tables(db)
    rows = db.execute(
        """
        SELECT id, request_type, entity_type, entity_id, requested_by, status, reason,
               payload_json, owner_note, reviewed_by, reviewed_at, created_at
        FROM owner_action_requests
        WHERE business_id=?
        ORDER BY CASE WHEN status='pending' THEN 0 ELSE 1 END, id DESC
        LIMIT 50
        """,
        (biz_id,),
    ).fetchall()
    data = []
    for row in rows or []:
        item = dict(row) if not isinstance(row, dict) else row
        try:
            payload = json.loads(item.get("payload_json") or "{}")
        except Exception:
            payload = {}
        item["payload"] = payload
        item.pop("payload_json", None)
        data.append(item)
    return jsonify({"status": "success", "requests": data})


@bp.route("/api/cashier-locks", methods=["GET"])
@owner_required
def owner_cashier_locks_api():
    db = get_db()
    biz_id = session["business_id"]
    ensure_sovereign_tables(db)
    rows = db.execute(
        """
        SELECT id, user_id, lock_reason, trigger_count, source_entity_type, source_entity_id,
               status, locked_at, released_at, released_by, release_note
        FROM pos_cashier_locks
        WHERE business_id=?
        ORDER BY CASE WHEN status='active' THEN 0 ELSE 1 END, id DESC
        LIMIT 40
        """,
        (biz_id,),
    ).fetchall()
    locks = [dict(row) if not isinstance(row, dict) else row for row in (rows or [])]
    return jsonify({"status": "success", "locks": locks})


def _owner_request_payload(item: dict) -> dict:
    try:
        payload = json.loads(item.get("payload_json") or "{}")
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _execute_owner_action_request(db, *, business_id: int, item: dict, reviewer_id: int | None, note: str) -> None:
    request_type = str(item.get("request_type") or "").strip().lower()
    payload = _owner_request_payload(item)

    if request_type == "inventory.damage.writeoff":
        product_id = int(item.get("entity_id") or 0)
        quantity = float(payload.get("quantity") or 0)
        if product_id <= 0 or quantity <= 0:
            raise ValueError("بيانات طلب التالف غير مكتملة")

        product = db.execute(
            "SELECT id, product_id, sku, current_qty, min_qty FROM product_inventory WHERE id=? AND business_id=? LIMIT 1",
            (product_id, business_id),
        ).fetchone()
        if not product:
            raise ValueError("الصنف المطلوب غير موجود")

        current_qty = float(product["current_qty"] or 0)
        new_qty = current_qty - quantity
        if new_qty < 0:
            raise ValueError("الكمية المطلوبة للشطب تتجاوز المخزون المتاح")

        reason = str(item.get("reason") or payload.get("movement_type") or "damage").strip()
        movement_product_id = int(product["product_id"] or product_id)
        db.execute(
            """
            INSERT INTO inventory_movements
                (business_id, product_id, movement_type, quantity, reason, performed_by, created_at)
            VALUES (?, ?, 'damage', ?, ?, ?, datetime('now'))
            """,
            (business_id, movement_product_id, quantity, reason, reviewer_id),
        )
        db.execute(
            "UPDATE product_inventory SET current_qty=?, updated_at=datetime('now') WHERE id=? AND business_id=?",
            (new_qty, product_id, business_id),
        )
        log_owner_impact(
            db,
            business_id=business_id,
            category="anti_fraud",
            action_key="inventory.damage_request_executed",
            summary=f"اعتمد المالك شطب/تالف الصنف {product['sku']}",
            reason=note or reason,
            entity_type="product_inventory",
            entity_id=product_id,
            actor_user_id=reviewer_id,
            protected_amount=quantity,
            payload={"new_qty": new_qty, "request_id": item.get("id")},
        )
        return

    if request_type == "payroll.salary_override":
        employee_id = int(item.get("entity_id") or 0)
        if employee_id <= 0:
            raise ValueError("طلب تعديل الراتب لا يحمل موظفاً صالحاً")
        new_base = float(payload.get("new_base_salary") or 0)
        new_allowances = float(payload.get("new_allowances") or 0)
        if not _column_exists(db, "employees", "allowances"):
            try:
                db.execute("ALTER TABLE employees ADD COLUMN allowances REAL DEFAULT 0")
            except Exception:
                pass
        db.execute(
            "UPDATE employees SET base_salary=?, allowances=? WHERE id=? AND business_id=?",
            (new_base, new_allowances, employee_id, business_id),
        )
        log_owner_impact(
            db,
            business_id=business_id,
            category="payroll_guard",
            action_key="employee.salary_override_executed",
            summary=f"اعتمد المالك تعديل راتب الموظف #{employee_id}",
            reason=note or str(item.get("reason") or ""),
            entity_type="employee",
            entity_id=employee_id,
            actor_user_id=reviewer_id,
            protected_amount=abs(float(payload.get("old_base_salary") or 0) - new_base) + abs(float(payload.get("old_allowances") or 0) - new_allowances),
            payload={"request_id": item.get("id")},
        )
        return

    if request_type == "payroll.manual_payment":
        payroll_id = int(item.get("entity_id") or 0)
        if payroll_id <= 0:
            raise ValueError("طلب صرف الراتب غير صالح")
        db.execute(
            "UPDATE hr_payroll SET status='paid', payment_date=date('now') WHERE id=? AND business_id=?",
            (payroll_id, business_id),
        )
        log_owner_impact(
            db,
            business_id=business_id,
            category="payroll_guard",
            action_key="payroll.manual_payment_executed",
            summary=f"اعتمد المالك صرف الراتب #{payroll_id}",
            reason=note or str(item.get("reason") or ""),
            entity_type="hr_payroll",
            entity_id=payroll_id,
            actor_user_id=reviewer_id,
            protected_amount=float(payload.get("net_salary") or 0),
            payload={"request_id": item.get("id")},
        )
        return

    if request_type == "accounting.posted_journal_edit":
        journal_id = int(item.get("entity_id") or 0)
        if journal_id <= 0:
            raise ValueError("طلب استثناء القيد المرحّل غير صالح")

        row = db.execute(
            "SELECT id, entry_number, is_posted FROM journal_entries WHERE id=? AND business_id=? LIMIT 1",
            (journal_id, business_id),
        ).fetchone()
        if not row:
            raise ValueError("القيد المحاسبي غير موجود")
        if int(row["is_posted"] or 0) != 1:
            raise ValueError("الاستثناء مخصص فقط للقيود المرحّلة")

        if not _column_exists(db, "journal_entries", "owner_edit_exception_until"):
            db.execute("ALTER TABLE journal_entries ADD COLUMN owner_edit_exception_until TEXT")
        if not _column_exists(db, "journal_entries", "owner_edit_exception_by"):
            db.execute("ALTER TABLE journal_entries ADD COLUMN owner_edit_exception_by INTEGER")
        if not _column_exists(db, "journal_entries", "owner_edit_exception_note"):
            db.execute("ALTER TABLE journal_entries ADD COLUMN owner_edit_exception_note TEXT")

        db.execute(
            """
            UPDATE journal_entries
            SET owner_edit_exception_until=datetime('now', '+30 minutes'),
                owner_edit_exception_by=?,
                owner_edit_exception_note=?
            WHERE id=? AND business_id=?
            """,
            (reviewer_id, note, journal_id, business_id),
        )
        log_owner_impact(
            db,
            business_id=business_id,
            category="accounting_guard",
            action_key="journal.posted_edit_exception_granted",
            summary=f"اعتمد المالك استثناء تعديل القيد المرحّل {row['entry_number']}",
            reason=note or str(item.get("reason") or ""),
            entity_type="journal_entry",
            entity_id=journal_id,
            actor_user_id=reviewer_id,
            payload={
                "request_id": item.get("id"),
                "valid_for_minutes": 30,
            },
        )
        return


@bp.route("/api/action-requests/<int:req_id>/resolve", methods=["POST"])
@owner_required
def owner_action_request_resolve(req_id: int):
    db = get_db()
    biz_id = session["business_id"]
    user_id = session["user_id"]
    ensure_sovereign_tables(db)

    guard = csrf_protect()
    if guard:
        return guard

    payload = request.get_json(silent=True) or {}
    decision = str(payload.get("decision", "reject") or "reject").strip().lower()
    note = str(payload.get("owner_note") or "").strip()[:500]
    if decision not in {"approve", "reject"}:
        return jsonify({"status": "error", "message": "قرار غير صالح"}), 400

    row = db.execute(
        "SELECT * FROM owner_action_requests WHERE id=? AND business_id=? LIMIT 1",
        (req_id, biz_id),
    ).fetchone()
    if not row:
        return jsonify({"status": "error", "message": "الطلب غير موجود"}), 404
    item = dict(row) if not isinstance(row, dict) else row
    if str(item.get("status") or "") != "pending":
        return jsonify({"status": "error", "message": "تمت معالجة الطلب مسبقاً"}), 400

    new_status = "approved" if decision == "approve" else "rejected"
    if new_status == "approved":
        try:
            _execute_owner_action_request(
                db,
                business_id=int(biz_id),
                item=item,
                reviewer_id=int(user_id or 0) or None,
                note=note,
            )
        except Exception as exc:
            return jsonify({"status": "error", "message": f"تعذر تنفيذ القرار: {exc}"}), 400

    db.execute(
        """
        UPDATE owner_action_requests
        SET status=?, owner_note=?, reviewed_by=?, reviewed_at=datetime('now')
        WHERE id=? AND business_id=?
        """,
        (new_status, note, user_id, req_id, biz_id),
    )
    write_audit_log(
        db,
        biz_id,
        action="owner_action_request_resolved",
        entity_type=item.get("entity_type") or "owner_request",
        entity_id=item.get("entity_id"),
        new_value=json.dumps({"request_id": req_id, "decision": new_status, "owner_note": note}, ensure_ascii=False),
    )
    log_owner_impact(
        db,
        business_id=int(biz_id),
        category="governance",
        action_key="owner.action_request_resolved",
        summary=f"تم {('اعتماد' if new_status == 'approved' else 'رفض')} طلب سيادي #{req_id}",
        reason=note,
        entity_type=item.get("entity_type") or "owner_request",
        entity_id=item.get("entity_id"),
        actor_user_id=int(user_id or 0) or None,
        payload={"request_type": item.get("request_type"), "decision": new_status},
    )
    db.commit()
    return jsonify({"status": "success", "message": "تم حفظ القرار", "request_id": req_id, "decision": new_status})


@bp.route("/api/cashier-locks/<int:lock_id>/release", methods=["POST"])
@owner_required
def owner_release_cashier_lock(lock_id: int):
    db = get_db()
    biz_id = session["business_id"]
    user_id = session["user_id"]
    ensure_sovereign_tables(db)

    guard = csrf_protect()
    if guard:
        return guard

    payload = request.get_json(silent=True) or {}
    note = str(payload.get("release_note") or "").strip()[:500]
    if not release_cashier_lock(db, business_id=int(biz_id), lock_id=int(lock_id), released_by=int(user_id or 0) or None, release_note=note):
        return jsonify({"status": "error", "message": "القفل غير موجود أو غير نشط"}), 404
    write_audit_log(
        db,
        biz_id,
        action="owner_cashier_lock_released",
        entity_type="pos_cashier_lock",
        entity_id=lock_id,
        new_value=json.dumps({"release_note": note}, ensure_ascii=False),
    )
    log_owner_impact(
        db,
        business_id=int(biz_id),
        category="anti_fraud",
        action_key="pos.cashier_lock_released",
        summary=f"تم فك تجميد كاشير مقفل #{lock_id}",
        reason=note,
        entity_type="pos_cashier_lock",
        entity_id=int(lock_id),
        actor_user_id=int(user_id or 0) or None,
    )
    db.commit()
    return jsonify({"status": "success", "message": "تم فك تجميد الكاشير"})


@bp.route("/products/upload", methods=["POST"])
@owner_required
def upload_products_file():
    db = get_db()
    biz_id = session["business_id"]

    guard = csrf_protect()
    if guard:
        return guard

    uploaded = request.files.get("products_file")
    if not uploaded or not (uploaded.filename or "").strip():
        flash("اختر ملف المنتجات أولاً", "error")
        return redirect(url_for("owner.owner_dashboard"))

    try:
        raw_rows = _read_uploaded_product_rows(uploaded)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("owner.owner_dashboard"))
    except Exception:
        flash("فشل قراءة الملف، تأكد من صحة التنسيق", "error")
        return redirect(url_for("owner.owner_dashboard"))

    if not raw_rows:
        flash("الملف فارغ. يرجى رفع ملف يحتوي منتجات فعلية.", "error")
        return redirect(url_for("owner.owner_dashboard"))

    business_row = db.execute("SELECT industry_type FROM businesses WHERE id=?", (biz_id,)).fetchone()
    auto_activity_family = _detect_activity_family((business_row["industry_type"] if business_row else "retail") or "retail")
    selected_activity_family = (request.form.get("target_activity_family") or "").strip().lower()
    manual_target_active = selected_activity_family in TARGET_ACTIVITY_FAMILIES

    # تحليل صارم للملف قبل الحقن: أي غموض => إيقاف + سؤال توجيهي للمالك.
    detected_families: set[str] = set()
    detected_base_families: set[str] = set()
    unknown_samples: list[str] = []
    for raw in raw_rows:
        rr = raw or {}
        row_name = (rr.get("name", "") or rr.get("الاسم", "") or "").strip()
        guess = _infer_activity_family_from_product(
            rr.get("name", "") or rr.get("الاسم", ""),
            rr.get("description", "") or rr.get("الوصف", ""),
            rr.get("category", "") or rr.get("category_name", "") or rr.get("التصنيف", ""),
        )
        if guess == "unknown":
            if row_name and len(unknown_samples) < 5:
                unknown_samples.append(row_name)
            continue
        detected_base_families.add(guess)
        detected_families.update(_expand_family_scope(guess))

    if not manual_target_active:
        if unknown_samples:
            flash(
                (
                    "تعذر التصنيف الآمن لبعض المنتجات. سؤال للمالك: "
                    "ما النشاط المستهدف لهذه المنتجات؟ "
                    f"(أمثلة: {', '.join(unknown_samples)})"
                ),
                "error",
            )
            return redirect(url_for("owner.owner_dashboard"))

        detected_groups = {_family_group(f) for f in detected_base_families if _family_group(f) != "unknown"}
        if not detected_groups:
            flash("تعذر تحديد نشاط الملف بدقة. الرجاء اختيار النشاط المستهدف يدويًا.", "error")
            return redirect(url_for("owner.owner_dashboard"))
        if len(detected_groups) > 1:
            flash(
                (
                    "الملف يحتوي أكثر من نشاط مختلف. "
                    "للدقة الصارمة: افصل الملف لكل نشاط أو اختر نشاطًا مستهدفًا واحدًا يدويًا."
                ),
                "error",
            )
            return redirect(url_for("owner.owner_dashboard"))

    if manual_target_active:
        selected_group = _family_group(selected_activity_family)
        mismatch_samples: list[str] = []
        for raw in raw_rows:
            rr = raw or {}
            row_name = (rr.get("name", "") or rr.get("الاسم", "") or "").strip() or "منتج بدون اسم"
            guess = _infer_activity_family_from_product(
                rr.get("name", "") or rr.get("الاسم", ""),
                rr.get("description", "") or rr.get("الوصف", ""),
                rr.get("category", "") or rr.get("category_name", "") or rr.get("التصنيف", ""),
            )
            if guess == "unknown" or _family_group(guess) != selected_group:
                if len(mismatch_samples) < 5:
                    mismatch_samples.append(row_name)
        if mismatch_samples:
            flash(
                (
                    "تم إيقاف الحقن الصارم لأن الملف لا يطابق النشاط المستهدف بالكامل. "
                    f"سؤال للمالك: هل تريد تغيير النشاط المستهدف أو تعديل الملف؟ أمثلة: {', '.join(mismatch_samples)}"
                ),
                "error",
            )
            return redirect(url_for("owner.owner_dashboard"))

        target_families = {selected_activity_family}
    else:
        target_families = detected_families or {auto_activity_family}

    inserted = 0
    updated = 0
    skipped = 0
    skipped_by_activity = 0
    target_businesses = db.execute(
        "SELECT id, industry_type FROM businesses WHERE is_active=1"
    ).fetchall()
    selected_business_ids: list[int] = []

    for biz in target_businesses:
        target_biz_id = int(biz["id"])
        target_family = _detect_activity_family((biz["industry_type"] or "").strip())
        if target_family not in target_families:
            continue
        selected_business_ids.append(target_biz_id)
        seen_keys = set()

        for raw in raw_rows:
            rr = raw or {}
            item_family_guess = _infer_activity_family_from_product(
                rr.get("name", "") or rr.get("الاسم", ""),
                rr.get("description", "") or rr.get("الوصف", ""),
                rr.get("category", "") or rr.get("category_name", "") or rr.get("التصنيف", ""),
            )
            item_family = _adapt_item_family_for_channel(item_family_guess, target_family)

            if not _family_matches_target(item_family, target_family):
                skipped += 1
                skipped_by_activity += 1
                continue

            item = _normalize_uploaded_product(rr, item_family)
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
                    (target_biz_id, item["barcode"])
                ).fetchone()
            else:
                existing = db.execute(
                    """SELECT id FROM products
                       WHERE business_id=?
                         AND LOWER(TRIM(name))=LOWER(TRIM(?))
                         AND (barcode IS NULL OR barcode='')
                       LIMIT 1""",
                    (target_biz_id, item["name"])
                ).fetchone()

            if existing:
                db.execute(
                    """UPDATE products
                       SET name=?,
                           description=?,
                           category_name=?,
                           sale_price=?,
                           can_sell=1,
                           is_pos=1,
                           updated_at=datetime('now')
                       WHERE id=?""",
                    (
                        item["name"],
                        item["description"],
                        item["category_name"],
                        item["price"],
                        existing["id"],
                    )
                )
                updated += 1
            else:
                db.execute(
                    """INSERT INTO products (
                           business_id, barcode, name, description,
                           category_name, sale_price, purchase_price,
                           can_sell, can_purchase, track_stock, is_pos,
                           product_type, is_active
                       ) VALUES (?, ?, ?, ?, ?, ?, 0, 1, 1, 1, 1, 'product', 1)""",
                    (
                        target_biz_id,
                        item["barcode"] or None,
                        item["name"],
                        item["description"],
                        item["category_name"],
                        item["price"],
                    )
                )
                inserted += 1

    if not selected_business_ids:
        flash(
            (
                "تم تحليل الملف لكن لا توجد منشآت مطابقة للأنشطة المكتشفة. "
                "سؤال للمالك: هل ترغب بتحديد نشاط مستهدف مختلف؟"
            ),
            "error",
        )
        return redirect(url_for("owner.owner_dashboard"))

    db.commit()
    write_audit_log(
        db,
        biz_id,
        action="owner_products_uploaded",
        entity_type="products_file",
        new_value=json.dumps(
            {
                "inserted": inserted,
                "updated": updated,
                "skipped": skipped,
                "skipped_by_activity": skipped_by_activity,
                "activity_families_detected": sorted(detected_families),
                "target_families": sorted(target_families),
                "target_businesses_count": len(selected_business_ids),
                "auto_activity_family": auto_activity_family,
                "filename": uploaded.filename,
            },
            ensure_ascii=False,
        ),
    )

    flash(
        (
            f"تم التحليل والحقن التلقائي: إضافة {inserted} | تحديث {updated} | "
            f"تخطي {skipped} (عدم تطابق نشاط: {skipped_by_activity}) | "
            f"الأنشطة المستهدفة: {', '.join(sorted(target_families))} | المنشآت المطابقة: {len(selected_business_ids)}"
        ),
        "success",
    )
    return redirect(url_for("owner.owner_dashboard"))


# ══════════════════════════════════════════════════════════════════════════════
#  وضع العرض — Basic / Pro Toggle
# ══════════════════════════════════════════════════════════════════════════════

@bp.route("/display-mode", methods=["POST"])
@owner_required
def toggle_display_mode():
    """تبديل وضع العرض البسيط ↔ الاحترافي"""
    db     = get_db()
    biz_id = session["business_id"]
    mode   = request.form.get("mode", "pro")
    if mode not in ("basic", "pro"):
        return jsonify({"error": "قيمة غير مقبولة"}), 400

    # إخفاء المحاسبة في الوضع البسيط
    hide_acc = 1 if mode == "basic" else 0

    db.execute(
        """INSERT INTO business_settings_ext
               (business_id, display_mode, hide_accounting, updated_at)
           VALUES (?, ?, ?, datetime('now'))
           ON CONFLICT(business_id) DO UPDATE
               SET display_mode    = excluded.display_mode,
                   hide_accounting = excluded.hide_accounting,
                   updated_at      = excluded.updated_at""",
        (biz_id, mode, hide_acc)
    )
    db.commit()

    write_audit_log(
        db, biz_id,
        action="display_mode_changed",
        entity_type="setting",
        new_value=json.dumps({"display_mode": mode})
    )

    label = "بسيط (Basic)" if mode == "basic" else "احترافي (Pro)"
    flash(f"تم تفعيل الوضع {label} بنجاح", "success")
    return redirect(url_for("owner.owner_dashboard"))


# ══════════════════════════════════════════════════════════════════════════════
#  لوحة إعدادات الرقابة
# ══════════════════════════════════════════════════════════════════════════════

@bp.route("/control-panel", methods=["POST"])
@owner_required
def update_control_panel():
    """تحديث إعدادات الرقابة: إخفاء الوحدات، الخصم التلقائي"""
    db     = get_db()
    biz_id = session["business_id"]

    hide_wf     = 1 if request.form.get("hide_workforce") else 0
    hide_agent  = 1 if request.form.get("hide_agent_portal") else 0
    auto_deduct = 1 if request.form.get("auto_deduct_deficit") else 0

    db.execute(
        """INSERT INTO business_settings_ext
               (business_id, hide_workforce, hide_agent_portal, auto_deduct_deficit, updated_at)
           VALUES (?, ?, ?, ?, datetime('now'))
           ON CONFLICT(business_id) DO UPDATE
               SET hide_workforce      = excluded.hide_workforce,
                   hide_agent_portal   = excluded.hide_agent_portal,
                   auto_deduct_deficit = excluded.auto_deduct_deficit,
                   updated_at          = excluded.updated_at""",
        (biz_id, hide_wf, hide_agent, auto_deduct)
    )
    db.commit()

    write_audit_log(db, biz_id, action="control_panel_updated", entity_type="setting")
    flash("تم حفظ إعدادات الرقابة", "success")
    return redirect(url_for("owner.owner_dashboard"))


# ══════════════════════════════════════════════════════════════════════════════
#  سجل النشاط (Audit Logs)
# ══════════════════════════════════════════════════════════════════════════════

@bp.route("/audit-logs")
@owner_required
def audit_logs():
    db     = get_db()
    biz_id = session["business_id"]
    page   = max(1, int(request.args.get("page", 1)))
    per    = 50
    offset = (page - 1) * per

    action_filter = request.args.get("action", "")
    params = [biz_id]
    where  = "WHERE al.business_id=?"
    if action_filter:
        where += " AND al.action=?"
        params.append(action_filter)

    logs = db.execute(
        f"""SELECT al.*, u.full_name as user_full_name
            FROM audit_logs al
            LEFT JOIN users u ON u.id = al.user_id
            {where}
            ORDER BY al.created_at DESC
            LIMIT ? OFFSET ?""",
        params + [per, offset]
    ).fetchall()

    total = db.execute(
        f"SELECT COUNT(*) FROM audit_logs al {where}", params
    ).fetchone()[0]

    actions = db.execute(
        "SELECT DISTINCT action FROM audit_logs WHERE business_id=? ORDER BY action",
        (biz_id,)
    ).fetchall()

    return render_template(
        "owner_audit_logs.html",
        logs=[dict(r) for r in logs],
        page=page,
        per=per,
        total=total,
        pages=(total + per - 1) // per,
        action_filter=action_filter,
        actions=[r["action"] for r in actions],
    )


# ══════════════════════════════════════════════════════════════════════════════
#  تقارير الإقفال الأعمى واعتماد الخصم
# ══════════════════════════════════════════════════════════════════════════════

@bp.route("/blind-closures")
@owner_required
def blind_closures():
    db     = get_db()
    biz_id = session["business_id"]

    closures = db.execute(
        """SELECT sbc.*, e.full_name as employee_name
           FROM shift_blind_closures sbc
           LEFT JOIN employees e ON e.id = sbc.employee_id
           WHERE sbc.business_id=?
           ORDER BY sbc.shift_date DESC, sbc.id DESC LIMIT 100""",
        (biz_id,)
    ).fetchall()

    return render_template("owner_blind_closures.html", closures=[dict(c) for c in closures])


@bp.route("/blind-closures/<int:closure_id>/approve", methods=["POST"])
@owner_required
def approve_blind_closure(closure_id: int):
    """اعتماد خصم العجز من راتب الموظف"""
    db     = get_db()
    biz_id = session["business_id"]
    user_id = session["user_id"]

    closure = db.execute(
        "SELECT * FROM shift_blind_closures WHERE id=? AND business_id=?",
        (closure_id, biz_id)
    ).fetchone()
    if not closure:
        return jsonify({"error": "إقفال غير موجود"}), 404

    deficit = float(closure["shortage_amount"] or 0)

    # تسجيل خصم الرواتب إذا كان هناك عجز
    if deficit > 0:
        db.execute(
            """INSERT INTO payroll_deductions
                   (business_id, employee_id, source_type, source_id, amount, reason)
               VALUES (?, ?, 'blind_deficit', ?, ?, ?)""",
            (biz_id, closure["employee_id"],
             closure_id,
             deficit,
             f"عجز إقفال أعمى بتاريخ {closure['shift_date']}")
        )

    db.commit()

    write_audit_log(
        db, biz_id,
        action="blind_closure_approved",
        entity_type="shift_blind_closure",
        entity_id=closure_id,
        new_value=json.dumps({"deficit": deficit, "approved_by": user_id})
    )
    return jsonify({"success": True, "deficit_deducted": deficit})


# ══════════════════════════════════════════════════════════════════════════════
#  مفاتيح API — لوحة ربط المنصات الخارجية
# ══════════════════════════════════════════════════════════════════════════════

@bp.route("/api-keys")
@owner_required
def api_keys_page():
    db     = get_db()
    biz_id = session["business_id"]

    keys = db.execute(
        """SELECT id, label, key_prefix, scopes, last_used_at, expires_at, is_active, created_at
           FROM api_keys WHERE business_id=? ORDER BY created_at DESC""",
        (biz_id,)
    ).fetchall()

    return render_template("owner_api_keys.html", api_keys=[dict(k) for k in keys])


@bp.route("/api-keys/create", methods=["POST"])
@owner_required
def create_api_key():
    """توليد مفتاح API جديد — يُعرض مرة واحدة فقط"""
    db     = get_db()
    biz_id = session["business_id"]
    user_id = session["user_id"]

    label  = request.form.get("label", "").strip()
    scopes = request.form.getlist("scopes") or ["read"]
    expires_days = request.form.get("expires_days")

    if not label:
        flash("يجب إدخال اسم/وصف للمفتاح", "error")
        return redirect(url_for("owner.api_keys_page"))

    # توليد المفتاح: jb_live_{32 حرف عشوائي}
    raw_key = "jb_live_" + secrets.token_urlsafe(32)
    prefix  = raw_key[:12]                              # أول 12 حرفاً تُعرض للمستخدم
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    expires_at = None
    if expires_days and int(expires_days) > 0:
        expires_at = (datetime.now() + timedelta(days=int(expires_days))).strftime("%Y-%m-%d %H:%M:%S")

    db.execute(
        """INSERT INTO api_keys
               (business_id, created_by, label, key_prefix, key_hash, scopes, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (biz_id, user_id, label, prefix, key_hash, json.dumps(scopes), expires_at)
    )
    db.commit()

    write_audit_log(
        db, biz_id,
        action="api_key_created",
        entity_type="api_key",
        new_value=json.dumps({"label": label, "scopes": scopes, "prefix": prefix})
    )

    # المفتاح يُعرض مرة واحدة فقط ثم يختفي
    flash(f"المفتاح الجديد (احتفظ به الآن — لن يُعرض مرة أخرى): {raw_key}", "key_reveal")
    return redirect(url_for("owner.api_keys_page"))


@bp.route("/api-keys/<int:key_id>/revoke", methods=["POST"])
@owner_required
def revoke_api_key(key_id: int):
    """إلغاء تفعيل مفتاح API"""
    db     = get_db()
    biz_id = session["business_id"]

    db.execute(
        "UPDATE api_keys SET is_active=0 WHERE id=? AND business_id=?",
        (key_id, biz_id)
    )
    db.commit()
    write_audit_log(db, biz_id, action="api_key_revoked", entity_type="api_key", entity_id=key_id)
    return jsonify({"success": True})


# ══════════════════════════════════════════════════════════════════════════════
#  إدارة الموارد البشرية والرواتب (HR Control)
# ══════════════════════════════════════════════════════════════════════════════

@bp.route("/hr")
@owner_required
def hr_panel():
    db     = get_db()
    biz_id = session["business_id"]

    employees = db.execute(
        """SELECT e.*,
                  COALESCE(SUM(pd.amount),0) as month_deductions
           FROM employees e
           LEFT JOIN payroll_deductions pd
               ON pd.employee_id=e.id
              AND pd.business_id=?
              AND strftime('%Y-%m', pd.created_at)=strftime('%Y-%m','now')
           WHERE e.business_id=? AND e.is_active=1
           GROUP BY e.id
           ORDER BY e.full_name""",
        (biz_id, biz_id)
    ).fetchall()

    agents = db.execute(
        """SELECT a.*,
                  COALESCE(SUM(ac.commission_amount),0) as pending_commission
           FROM agents a
           LEFT JOIN agent_commissions ac
               ON ac.agent_id=a.id AND ac.status != 'paid'
           WHERE a.business_id=? AND a.is_active=1
           GROUP BY a.id
           ORDER BY a.full_name""",
        (biz_id,)
    ).fetchall()

    return render_template(
        "owner_hr.html",
        employees=[dict(e) for e in employees],
        agents=[dict(a) for a in agents],
    )


@bp.route("/hr/employee/<int:emp_id>/salary", methods=["POST"])
@owner_required
def update_employee_salary(emp_id: int):
    """تعديل راتب موظف"""
    db     = get_db()
    biz_id = session["business_id"]

    new_salary = request.form.get("base_salary", type=float)
    if new_salary is None or new_salary < 0:
        return jsonify({"error": "راتب غير صحيح"}), 400

    old = db.execute(
        "SELECT base_salary FROM employees WHERE id=? AND business_id=?",
        (emp_id, biz_id)
    ).fetchone()
    if not old:
        return jsonify({"error": "موظف غير موجود"}), 404

    db.execute(
        "UPDATE employees SET base_salary=? WHERE id=? AND business_id=?",
        (new_salary, emp_id, biz_id)
    )
    db.commit()

    write_audit_log(
        db, biz_id,
        action="salary_updated",
        entity_type="employee",
        entity_id=emp_id,
        old_value=json.dumps({"base_salary": old["base_salary"]}),
        new_value=json.dumps({"base_salary": new_salary})
    )
    return jsonify({"success": True, "new_salary": new_salary})


@bp.route("/hr/agent/<int:agent_id>/commission", methods=["POST"])
@owner_required
def update_agent_commission(agent_id: int):
    """تعديل نسبة عمولة مندوب"""
    db     = get_db()
    biz_id = session["business_id"]

    rate = request.form.get("commission_rate", type=float)
    if rate is None or not (0 <= rate <= 100):
        return jsonify({"error": "نسبة عمولة غير صحيحة (0-100)"}), 400

    old = db.execute(
        "SELECT commission_rate FROM agents WHERE id=? AND business_id=?",
        (agent_id, biz_id)
    ).fetchone()
    if not old:
        return jsonify({"error": "مندوب غير موجود"}), 404

    db.execute(
        "UPDATE agents SET commission_rate=? WHERE id=? AND business_id=?",
        (rate, agent_id, biz_id)
    )
    db.commit()

    write_audit_log(
        db, biz_id,
        action="commission_rate_updated",
        entity_type="agent",
        entity_id=agent_id,
        old_value=json.dumps({"commission_rate": old["commission_rate"]}),
        new_value=json.dumps({"commission_rate": rate})
    )
    return jsonify({"success": True, "new_rate": rate})


# ══════════════════════════════════════════════════════════════════════════════
#  API: بيانات الرسوم البيانية (Charts JSON)
# ══════════════════════════════════════════════════════════════════════════════

@bp.route("/api/chart-data")
@owner_required
def chart_data():
    """JSON لرسم خرائط قمرة القيادة (مبيعات يومية + مناديب + رواتب)"""
    db     = get_db()
    biz_id = session["business_id"]

    # مبيعات آخر 30 يوم
    daily = db.execute(
        """SELECT date(created_at) as day, COALESCE(SUM(total),0) as total
           FROM invoices
           WHERE business_id=? AND invoice_type='sale'
             AND created_at >= date('now','-29 days')
           GROUP BY day ORDER BY day""",
        (biz_id,)
    ).fetchall()

    # مبيعات المناديب
    agents = db.execute(
        """SELECT a.full_name,
                  COUNT(ac.id) as invoice_count,
                  COALESCE(SUM(ac.commission_amount),0) as commission
           FROM agents a
           LEFT JOIN agent_commissions ac ON ac.agent_id=a.id
           WHERE a.business_id=? AND a.is_active=1
           GROUP BY a.id ORDER BY commission DESC LIMIT 8""",
        (biz_id,)
    ).fetchall()

    # رواتب vs خصومات (آخر 6 أشهر)
    payroll_chart = db.execute(
        """SELECT strftime('%Y-%m', pd.created_at) as month,
                  COALESCE(SUM(pd.amount),0) as deductions
           FROM payroll_deductions pd
           WHERE pd.business_id=?
             AND pd.created_at >= date('now','-6 months')
           GROUP BY month ORDER BY month""",
        (biz_id,)
    ).fetchall()

    return jsonify({
        "daily_sales": [{"day": r["day"], "total": float(r["total"])} for r in daily],
        "agent_commissions": [
            {"name": r["full_name"], "invoices": r["invoice_count"], "commission": float(r["commission"])}
            for r in agents
        ],
        "payroll_deductions": [
            {"month": r["month"], "deductions": float(r["deductions"])}
            for r in payroll_chart
        ],
    })


# ══════════════════════════════════════════════════════════════════════════════
# OAuth Social Login Settings
# ══════════════════════════════════════════════════════════════════════════════

_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"

_OAUTH_KEYS = [
    ("GOOGLE_OAUTH_CLIENT_ID",      "Google Client ID"),
    ("GOOGLE_OAUTH_CLIENT_SECRET",  "Google Client Secret"),
    ("MICROSOFT_OAUTH_CLIENT_ID",   "Microsoft Client ID"),
    ("MICROSOFT_OAUTH_CLIENT_SECRET","Microsoft Client Secret"),
    ("PUBLIC_BASE_URL",             "رابط التطبيق العام (Tunnel / Domain)"),
]


def _read_env_file() -> dict:
    """قراءة ملف .env وإرجاع dict بالقيم."""
    result = {}
    if not _ENV_PATH.exists():
        return result
    for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def _write_env_key(key: str, value: str):
    """كتابة/تحديث مفتاح واحد في ملف .env بشكل آمن."""
    if not _ENV_PATH.exists():
        _ENV_PATH.write_text(f"{key}={value}\n", encoding="utf-8")
        return

    content = _ENV_PATH.read_text(encoding="utf-8")
    pattern = re.compile(rf"^{re.escape(key)}\s*=.*$", re.MULTILINE)

    if pattern.search(content):
        new_content = pattern.sub(f"{key}={value}", content)
    else:
        new_content = content.rstrip("\n") + f"\n{key}={value}\n"

    _ENV_PATH.write_text(new_content, encoding="utf-8")


def _mask(val: str) -> str:
    if not val:
        return ""
    if len(val) <= 8:
        return "••••"
    return val[:4] + "••••••••" + val[-4:]


@bp.route("/oauth-settings", methods=["GET", "POST"])
@owner_required
def oauth_settings():
    """صفحة إعداد تسجيل الدخول عبر Google / Microsoft."""
    if request.method == "POST":
        csrf_protect()
        for key, _ in _OAUTH_KEYS:
            val = request.form.get(key, "").strip()
            if val:  # لا تمسح القيم الموجودة إن كان الحقل فارغاً
                _write_env_key(key, val)
                os.environ[key] = val  # تحديث فوري في هذه الجلسة

        write_audit_log(
            db=get_db(),
            action="oauth_settings_updated",
            actor_id=session.get("user_id"),
            actor_name=session.get("user_name", "Owner"),
            actor_role="owner",
            business_id=session.get("business_id"),
            details="تم تحديث إعدادات OAuth"
        )
        flash("✅ تم حفظ الإعدادات — أعد تشغيل التطبيق لتفعيل التغييرات", "success")
        return redirect(url_for("owner.oauth_settings"))

    env = _read_env_file()
    # دمج مع os.environ (الأولوية لما في الذاكرة)
    for k, _ in _OAUTH_KEYS:
        if k not in env and os.environ.get(k):
            env[k] = os.environ[k]

    # تحضير بيانات العرض
    keys_info = []
    for key, label in _OAUTH_KEYS:
        val = env.get(key, "")
        keys_info.append({
            "key":       key,
            "label":     label,
            "masked":    _mask(val),
            "is_set":    bool(val),
            "is_secret": "SECRET" in key,
        })

    # حساب روابط OAuth callback (للعرض في الصفحة)
    base = env.get("PUBLIC_BASE_URL", "").rstrip("/") or request.host_url.rstrip("/")
    google_callback    = base + "/auth/social/google/callback"
    microsoft_callback = base + "/auth/social/microsoft/callback"

    return render_template(
        "owner_oauth_settings.html",
        keys_info=keys_info,
        google_callback=google_callback,
        microsoft_callback=microsoft_callback,
        google_ready=bool(env.get("GOOGLE_OAUTH_CLIENT_ID") and env.get("GOOGLE_OAUTH_CLIENT_SECRET")),
        microsoft_ready=bool(env.get("MICROSOFT_OAUTH_CLIENT_ID") and env.get("MICROSOFT_OAUTH_CLIENT_SECRET")),
    )


# ══════════════════════════════════════════════════════════════════════════════
#  دمج الأنشطة الفرعية — Merge Sub-Activities
# ══════════════════════════════════════════════════════════════════════════════

def _get_sector_prefix(industry_type: str) -> str:
    """استخراج القطاع الرئيسي من كود النشاط."""
    code = (industry_type or "").strip().lower()
    for prefix in ("retail_", "wholesale_", "ecommerce_", "food_", "hospitality_",
                   "medical_", "industrial_", "agriculture_", "transport_",
                   "services_", "education_", "real_estate_", "auto_service_"):
        if code.startswith(prefix):
            return prefix.rstrip("_")
    if code in ("retail", "wholesale", "restaurant", "cafe"):
        return code
    return code.split("_")[0] if "_" in code else code


# ═══════════════════════════════════════════════════════════════════════════════
# ■ إدارة طلبات التسجيل (موافقة / رفض)
# ═══════════════════════════════════════════════════════════════════════════════

@bp.route("/registrations")
@owner_required
def registrations_page():
    """قائمة بجميع طلبات التسجيل المعلّقة وتاريخ الموافقات."""
    db = get_db()

    # تأكد من وجود العمود
    try:
        db.execute("ALTER TABLE businesses ADD COLUMN account_status TEXT DEFAULT 'approved'")
        db.commit()
    except Exception:
        pass

    pending = db.execute("""
        SELECT b.id AS biz_id, b.name AS biz_name, b.created_at, b.country_code,
               u.username, u.full_name, u.email
        FROM businesses b
        JOIN users u ON u.business_id = b.id
        WHERE b.account_status = 'pending'
        ORDER BY b.created_at DESC
    """).fetchall()

    history = db.execute("""
        SELECT b.id AS biz_id, b.name AS biz_name, b.created_at, b.country_code,
               b.account_status,
               u.username, u.full_name, u.email
        FROM businesses b
        JOIN users u ON u.business_id = b.id
        WHERE b.account_status IN ('approved','rejected')
        ORDER BY b.created_at DESC
        LIMIT 50
    """).fetchall()

    return render_template("owner_registrations.html",
                           pending=pending, history=history)


@bp.route("/registrations/approve", methods=["POST"])
@owner_required
def approve_registration():
    """موافقة على طلب تسجيل — تفعيل الحساب."""
    guard = csrf_protect()
    if guard:
        return guard

    db     = get_db()
    biz_id = request.form.get("biz_id", "").strip()
    if not biz_id or not biz_id.isdigit():
        flash("طلب غير صالح", "error")
        return redirect(url_for("owner.registrations_page"))

    biz_id = int(biz_id)
    db.execute(
        "UPDATE businesses SET account_status='approved', is_active=1 WHERE id=?",
        (biz_id,)
    )
    db.execute("UPDATE users SET is_active=1 WHERE business_id=?", (biz_id,))
    db.commit()
    write_audit_log(db, biz_id, "registration_approved",
                    entity_type="business", entity_id=biz_id)
    flash("تمت الموافقة وتفعيل الحساب بنجاح.", "success")
    return redirect(url_for("owner.registrations_page"))


@bp.route("/registrations/reject", methods=["POST"])
@owner_required
def reject_registration():
    """رفض طلب تسجيل."""
    guard = csrf_protect()
    if guard:
        return guard

    db     = get_db()
    biz_id = request.form.get("biz_id", "").strip()
    if not biz_id or not biz_id.isdigit():
        flash("طلب غير صالح", "error")
        return redirect(url_for("owner.registrations_page"))

    biz_id = int(biz_id)
    db.execute("UPDATE businesses SET account_status='rejected' WHERE id=?", (biz_id,))
    db.commit()
    write_audit_log(db, biz_id, "registration_rejected",
                    entity_type="business", entity_id=biz_id)
    flash("تم رفض الطلب.", "info")
    return redirect(url_for("owner.registrations_page"))


@bp.route("/activities")
@owner_required
def activities_page():
    """صفحة دمج الأنشطة الفرعية — عرض الأنشطة المتاحة من نفس القطاع."""
    from modules.config import INDUSTRY_TYPES, get_sidebar_key
    db     = get_db()
    biz_id = session["business_id"]

    # ── تأكد من وجود عمود merged_activities ─────────────────────────────
    try:
        db.execute("ALTER TABLE businesses ADD COLUMN merged_activities TEXT DEFAULT '[]'")
        db.commit()
    except Exception:
        pass  # العمود موجود بالفعل

    biz = db.execute(
        "SELECT industry_type, merged_activities FROM businesses WHERE id=?", (biz_id,)
    ).fetchone()

    primary = (biz["industry_type"] if biz else "retail") or "retail"
    try:
        merged = json.loads(biz["merged_activities"] or "[]") if biz else []
    except Exception:
        merged = []

    # ── الأنشطة من نفس القطاع الرئيسي ─────────────────────────────────
    sector = get_sidebar_key(primary)
    all_same_sector = [
        (code, label)
        for code, label in INDUSTRY_TYPES
        if get_sidebar_key(code) == sector and code != primary
    ]

    # إحصاء المنتجات والتصنيفات لكل نشاط
    cat_count   = db.execute("SELECT COUNT(*) FROM categories WHERE business_id=?",  (biz_id,)).fetchone()[0]
    prod_count  = db.execute("SELECT COUNT(*) FROM products  WHERE business_id=?",  (biz_id,)).fetchone()[0]

    industry_labels = {k: v for k, v in INDUSTRY_TYPES}

    return render_template(
        "owner_activities.html",
        primary=primary,
        primary_label=industry_labels.get(primary, primary),
        merged=merged,
        all_same_sector=all_same_sector,
        sector=sector,
        cat_count=cat_count,
        prod_count=prod_count,
        industry_labels=industry_labels,
    )


@bp.route("/activities/merge", methods=["POST"])
@owner_required
def merge_activities():
    """تنفيذ دمج الأنشطة المختارة — يُضيف تصنيفاتها ومنتجاتها فوراً."""
    from modules.config import INDUSTRY_TYPES
    from modules.industry_seeds import seed_industry_defaults

    guard = csrf_protect()
    if guard:
        return guard

    db     = get_db()
    biz_id = session["business_id"]

    # ── تأكد من وجود عمود merged_activities ─────────────────────────────
    try:
        db.execute("ALTER TABLE businesses ADD COLUMN merged_activities TEXT DEFAULT '[]'")
        db.commit()
    except Exception:
        pass

    biz = db.execute(
        "SELECT industry_type, merged_activities FROM businesses WHERE id=?", (biz_id,)
    ).fetchone()
    primary = (biz["industry_type"] if biz else "retail") or "retail"
    try:
        merged = json.loads(biz["merged_activities"] or "[]") if biz else []
    except Exception:
        merged = []

    valid_codes = {k for k, _ in INDUSTRY_TYPES}
    selected    = request.form.getlist("activities")

    total_cats  = 0
    total_prods = 0
    newly_added = []

    for code in selected:
        if code not in valid_codes or code == primary or code in merged:
            continue
        result = seed_industry_defaults(db, biz_id, code)
        total_cats  += result.get("categories_inserted", 0)
        total_prods += result.get("products_inserted", 0)
        merged.append(code)
        newly_added.append(code)

    if newly_added:
        db.execute(
            "UPDATE businesses SET merged_activities=? WHERE id=?",
            (json.dumps(merged, ensure_ascii=False), biz_id)
        )
        db.commit()
        write_audit_log(db, biz_id, action="merge_activities", entity_type="business",
                        entity_id=biz_id, details=json.dumps({"added": newly_added}, ensure_ascii=False))
        flash(f"✅ تم دمج {len(newly_added)} نشاط — أُضيف {total_cats} تصنيف و{total_prods} منتج فوراً", "success")
    else:
        flash("لم يتم اختيار أنشطة جديدة للدمج.", "info")

    return redirect(url_for("owner.activities_page"))


@bp.route("/activities/remove", methods=["POST"])
@owner_required
def remove_merged_activity():
    """إلغاء ربط نشاط مدموج (لا يحذف المنتجات)."""
    guard = csrf_protect()
    if guard:
        return guard

    db     = get_db()
    biz_id = session["business_id"]
    code   = request.form.get("code", "").strip()

    biz = db.execute(
        "SELECT merged_activities FROM businesses WHERE id=?", (biz_id,)
    ).fetchone()
    try:
        merged = json.loads(biz["merged_activities"] or "[]") if biz else []
    except Exception:
        merged = []

    if code in merged:
        merged.remove(code)
        db.execute(
            "UPDATE businesses SET merged_activities=? WHERE id=?",
            (json.dumps(merged, ensure_ascii=False), biz_id)
        )
        db.commit()
        flash(f"🗑️ تم إلغاء ربط النشاط. المنتجات المضافة لا تزال محفوظة.", "info")

    return redirect(url_for("owner.activities_page"))

