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

from modules.extensions import get_db, safe_sql_identifier, csrf_protect
from modules.middleware import owner_required, write_audit_log

bp = Blueprint("owner", __name__, url_prefix="/owner")


def _table_exists(db, table_name: str) -> bool:
    row = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _column_exists(db, table_name: str, column_name: str) -> bool:
    try:
        safe_table = safe_sql_identifier(table_name)
        rows = db.execute(f"PRAGMA table_info({safe_table})").fetchall()
        return any(r[1] == column_name for r in rows)
    except Exception:
        return False


def _detect_activity_family(industry_type: str) -> str:
    industry_type = (industry_type or "").strip().lower()
    if industry_type.startswith("wholesale_") or industry_type == "wholesale":
        if industry_type.startswith("wholesale_fashion_"):
            return "wholesale_fashion"
        if industry_type.startswith("wholesale_fnb_"):
            return "wholesale_food"
        return "wholesale_general"

    if industry_type.startswith("retail_fnb_"):
        return "retail_food"
    if industry_type.startswith("retail_fashion_"):
        return "retail_fashion"
    if industry_type.startswith("retail_") or industry_type == "retail":
        return "retail_general"
    return "general"


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

    if activity_family in {"retail_food", "wholesale_food"}:
        if any(k in txt for k in ["قهوة", "coffee", "شاي", "tea", "مشروب", "drink"]):
            return "مشروبات"
        if any(k in txt for k in ["حلويات", "حلو", "cake", "chocolate"]):
            return "حلويات"
        return "مواد غذائية"

    if activity_family in {"retail_fashion", "wholesale_fashion"}:
        if any(k in txt for k in ["حذاء", "shoe", "شنطة", "bag"]):
            return "اكسسوارات"
        return "ملابس"

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
    )


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

    business_row = db.execute(
        "SELECT industry_type FROM businesses WHERE id=?",
        (biz_id,)
    ).fetchone()
    activity_family = _detect_activity_family((business_row["industry_type"] if business_row else "retail") or "retail")

    inserted = 0
    updated = 0
    skipped = 0
    seen_keys = set()

    for raw in raw_rows:
        item = _normalize_uploaded_product(raw or {}, activity_family)
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
                (biz_id, item["barcode"])
            ).fetchone()
        else:
            existing = db.execute(
                """SELECT id FROM products
                   WHERE business_id=?
                     AND LOWER(TRIM(name))=LOWER(TRIM(?))
                     AND (barcode IS NULL OR barcode='')
                   LIMIT 1""",
                (biz_id, item["name"])
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
                    biz_id,
                    item["barcode"] or None,
                    item["name"],
                    item["description"],
                    item["category_name"],
                    item["price"],
                )
            )
            inserted += 1

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
                "activity_family": activity_family,
                "filename": uploaded.filename,
            },
            ensure_ascii=False,
        ),
    )

    flash(
        f"تم دمج الملف فوراً: إضافة {inserted} | تحديث {updated} | تخطي {skipped} (اختصاص: {activity_family})",
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

