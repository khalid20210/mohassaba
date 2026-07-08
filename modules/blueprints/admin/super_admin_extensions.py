"""
modules/blueprints/admin/super_admin_extensions.py
امتدادات سيادية لمالك البرنامج (Admin Core APIs)
"""

import json
from calendar import monthrange
from datetime import datetime
from flask import Blueprint, request, jsonify, session

from modules.config import SIDEBAR_CONFIG, get_sidebar_key
from modules.extensions import get_db, safe_sql_identifier
from modules.middleware import admin_required, write_audit_log
from modules.core_utils import table_exists as db_table_exists

bp = Blueprint("super_admin_extensions", __name__, url_prefix="/admin/core")


STRICT_CONFIRM_PHRASE = "I_UNDERSTAND_STRICT_MODE"


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


def _build_robot_seeds() -> list[dict]:
    """كتالوج روبوتات المنصة (مشتركة + قطاعية) قابل للتوسع لعدد أنشطة كبير."""
    rows: list[dict] = []

    def add(code: str, name: str, scope: str, sector: str | None, risk: str, desc: str):
        rows.append(
            {
                "robot_code": code,
                "robot_name": name,
                "scope_type": scope,
                "activity_sector": sector,
                "risk_level": risk,
                "description": desc,
            }
        )

    # Shared robots
    add("shared.anomaly.guard", "روبوت حارس الشذوذ المالي", "shared", None, "high", "يراقب الأنماط المالية الشاذة ويوقف القرارات الخطرة آلياً.")
    add("shared.compliance.guard", "روبوت الامتثال الذكي", "shared", None, "critical", "يتحقق من الالتزام الضريبي والقيود النظامية قبل اعتماد أي إجراء.")
    add("shared.cashflow.forecast", "روبوت التنبؤ بالتدفقات النقدية", "shared", None, "medium", "يتنبأ بحركة النقد ويكشف فجوات السيولة مبكراً.")
    add("shared.credit.watch", "روبوت الجدارة الائتمانية", "shared", None, "high", "يحدث تقييم مخاطر العملاء ويمنع التوسع الائتماني غير الآمن.")
    add("shared.dynamic.pricing", "روبوت مساعد التسعير الديناميكي", "shared", None, "medium", "يقترح أسعاراً قائمة على الطلب والهامش والسيولة.")
    add("shared.reorder.optimizer", "روبوت إعادة الطلب الذكي", "shared", None, "medium", "ينشئ اقتراحات شراء قبل النفاد وفق lead time.")
    add("shared.audit.story", "روبوت سرد الأثر الرقابي", "shared", None, "low", "يبني سجل قرارات واضح قابل للمراجعة والتدقيق.")
    add("shared.profit.guard", "روبوت حارس الربحية", "shared", None, "high", "يكشف حالات البيع بخسارة أو هامش غير مقبول.")
    add("shared.collections.optimizer", "روبوت تحسين التحصيل", "shared", None, "medium", "يبني أولويات التحصيل حسب سلوك السداد.")
    add("shared.policy.enforcer", "روبوت منفذ السياسات", "shared", None, "critical", "يفرض سياسات التشغيل ومنع التجاوزات.")

    # Education
    add("edu.fees.collector", "روبوت تحصيل الرسوم والأقساط المجدولة", "sector", "education", "medium", "يتتبع استحقاقات الطلاب ويربط التحصيل بملف الطالب.")
    add("edu.tax.splitter", "روبوت الفصل الضريبي الذكي للاستثناءات", "sector", "education", "critical", "يفصل المعفيين والخاضعين ضريبياً تلقائياً.")
    add("edu.payroll.academic", "روبوت رواتب وبدلات الكادر الأكاديمي", "sector", "education", "high", "يحتسب مستحقات المعلمين حسب العبء الفعلي.")
    add("edu.uniforms.stock", "روبوت رقابة مستودع الكتب والزي الموحد", "sector", "education", "medium", "يربط التسجيل بالمخزون وينبه بالنقص.")
    add("edu.transport.routes", "روبوت أتمتة اللوجستيات والنقل المدرسي", "sector", "education", "medium", "يبني مسارات نقل يومية محسنة.")
    add("edu.dropout.risk", "روبوت إنذار التسرب المالي للطالب", "sector", "education", "medium", "يرفع مؤشر خطر التعثر والتسرب.")
    add("edu.scholarship.validator", "روبوت مطابقة المنح والخصومات", "sector", "education", "high", "يتحقق من أهلية الخصومات والمنح ومنع التكرار.")
    add("edu.student.costing", "روبوت تكلفة الطالب الفعلية", "sector", "education", "medium", "يقيس ربحية البرامج التعليمية لكل طالب.")

    # Healthcare
    add("hc.insurance.claims", "روبوت مطالبات التأمين ومنع الرفض المالي", "sector", "healthcare", "critical", "يفحص المطالبات قبل الإرسال ويقلل الرفض.")
    add("hc.consumables.trace", "روبوت جرد وتتبع المستلزمات الطبية المستهلكة", "sector", "healthcare", "high", "يربط المواد المستهلكة بالخدمات والأطباء.")
    add("hc.controlled.drugs", "روبوت رقابة الأدوية المقيدة وتواريخ الصلاحية", "sector", "healthcare", "critical", "يراقب الصلاحية والأدوية الخاضعة للرقابة.")
    add("hc.doctor.commissions", "روبوت حساب وتوزيع عمولات الأطباء", "sector", "healthcare", "high", "يحتسب عمولات الأطباء مع خصم تكاليف المواد.")
    add("hc.waiting.list", "روبوت رعاية المواعيد وملء قائمة الانتظار", "sector", "healthcare", "medium", "يعيد جدولة المواعيد الشاغرة تلقائياً.")
    add("hc.coding.audit", "روبوت تدقيق الترميز الطبي", "sector", "healthcare", "critical", "يتحقق من صحة الأكواد الطبية قبل الفوترة.")
    add("hc.discount.guard", "روبوت إنذار الإفراط في الخصومات الطبية", "sector", "healthcare", "high", "يرصد الخصومات التي تضر هامش الربح.")
    add("hc.workload.margin", "روبوت عبء الطبيب التشغيلي", "sector", "healthcare", "medium", "يربط وقت الطبيب بالعائد الفعلي.")

    # Wholesale
    add("wh.credit.radar", "روبوت رادار الجدارة الائتمانية وسقوف البيع", "sector", "wholesale", "high", "يحدد سقف البيع الآجل ويوقفه عند الخطر.")
    add("wh.multi.pricing", "روبوت التسعير المتعدد وحساب الكميات", "sector", "wholesale", "medium", "يطبق سياسات سعر حسب العميل والكمية.")
    add("wh.reorder.leadtime", "روبوت التنبؤ بمدد الشحن وإعادة الطلب", "sector", "wholesale", "medium", "ينشئ طلبات شراء مبكرة بناءً على lead time.")
    add("wh.pallet.tracker", "روبوت تتبع الأصول اللوجستية والبليتات", "sector", "wholesale", "medium", "يوثق الأصول المعارة ويمنع الفقد.")
    add("wh.loss.sale.guard", "روبوت كشف البيع بخسارة مخفية", "sector", "wholesale", "high", "يرصد الفواتير تحت التكلفة بعد الحسومات.")
    add("wh.supplier.score", "روبوت تقييم جودة المورد", "sector", "wholesale", "medium", "يصنف الموردين حسب الالتزام والجودة.")
    add("wh.collection.routing", "روبوت توزيع التحصيل على المندوبين", "sector", "wholesale", "medium", "يوجه التحصيل حسب خطورة العميل.")

    # Retail / Ecommerce
    add("ret.pos.fraud", "روبوت رادار مكافحة الاحتيال وتلاعب POS", "sector", "retail", "critical", "يكشف الأنماط المشبوهة لحظياً.")
    add("ret.omni.sync", "روبوت المزامنة المتكاملة مع المتاجر الإلكترونية", "sector", "retail", "high", "يوحد المخزون بين المتجر الفعلي والإلكتروني.")
    add("ret.margin.pricing", "روبوت التسعير الديناميكي وإدارة الهوامش", "sector", "retail", "medium", "يقترح تسعيراً حسب المواسم والطلب.")
    add("ret.kitchen.waste", "روبوت مراقبة هدر المطبخ والمواد الخام", "sector", "retail", "high", "يطابق الاستهلاك الفعلي مع وصفات البيع.")
    add("ret.shelf.stockout", "روبوت اكتشاف نفاد الرف الحرج", "sector", "retail", "medium", "يتنبأ بنفاد المنتجات عالية الحركة.")
    add("ret.price.elasticity", "روبوت حساسية السعر", "sector", "retail", "medium", "يقترح نقطة سعر توازن الطلب والربحية.")
    add("ret.cashier.behavior", "روبوت سلوك الكاشير المتكرر", "sector", "retail", "high", "يراقب نمط الإلغاء والمرتجعات المشبوهة.")

    add("eco.stock.realtime", "روبوت مزامنة مخزون التجارة الإلكترونية", "sector", "ecommerce", "high", "يحدث المخزون عبر القنوات بزمن شبه لحظي.")
    add("eco.return.risk", "روبوت مخاطر المرتجعات الإلكترونية", "sector", "ecommerce", "medium", "يتنبأ بالمرتجعات ويضبط سياسة الاسترجاع.")
    add("eco.ad.roi", "روبوت عائد الحملات الإعلانية", "sector", "ecommerce", "medium", "يربط المبيعات مع الإنفاق التسويقي.")

    # Services / Contracting / Real estate
    add("srv.extracts.retention", "روبوت تتبع مستخلصات المشاريع وحجوزات الضمان", "sector", "services", "high", "يتابع المستخلصات والاستقطاعات النظامية.")
    add("srv.boq.pricing", "روبوت قراءة جداول الكميات وتسعير العطاءات", "sector", "services", "medium", "يقدر تكلفة BOQ ويقترح تسعير المناقصات.")
    add("srv.site.cash.custody", "روبوت رقابة العهد النقدية للمواقع", "sector", "services", "high", "يراقب العهد وفواتير الصرف الميداني.")
    add("srv.assets.maintenance", "روبوت صيانة وهلاك المعدات الثقيلة والأسطول", "sector", "services", "medium", "يتتبع التشغيل والصيانة والإهلاك.")
    add("srv.budget.variance", "روبوت انحراف ميزانية المشروع", "sector", "services", "high", "يرصد الانحراف بين المخطط والفعلي.")
    add("srv.subcontractor.delay", "روبوت تأخر المقاول الفرعي", "sector", "services", "medium", "يكشف أثر التأخير على التكلفة والربحية.")
    add("srv.changeorder.guard", "روبوت فحص أوامر التغيير", "sector", "services", "high", "يمنع اعتماد تغيير بلا أثر مالي موثق.")

    add("re.lease.billing", "روبوت أتمتة العقود الإيجارية والدفعات", "sector", "realestate", "medium", "يولد مطالبات الإيجار ويربط حالات السداد.")
    add("re.maintenance.dispatch", "روبوت صيانة العقارات وإدارة المقاولين", "sector", "realestate", "medium", "يوزع البلاغات ويحسب تكاليف التنفيذ.")
    add("re.owner.payout", "روبوت حساب وتوزيع إيرادات الملاك", "sector", "realestate", "high", "يفكك الإيراد ويحتسب صافي المالك.")
    add("re.vacancy.predict", "روبوت توقع الشواغر", "sector", "realestate", "medium", "يتنبأ بالوحدات المعرضة للفراغ.")
    add("re.ar.collections", "روبوت تحصيل متأخرات الإيجار", "sector", "realestate", "high", "يبني خطة تحصيل تدريجية للمستأجرين المتعثرين.")

    return rows


def _ensure_robot_tables(db):
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


def _sync_robot_catalog(db, admin_id: int | None = None) -> dict:
    _ensure_robot_tables(db)
    seeds = _build_robot_seeds()

    before_rows = db.execute("SELECT robot_code FROM platform_robot_catalog").fetchall()
    before = {str((r[0] if not isinstance(r, dict) else r.get("robot_code")) or "") for r in (before_rows or [])}

    for seed in seeds:
        db.execute(
            """
            INSERT INTO platform_robot_catalog
                (robot_code, robot_name, scope_type, activity_sector, risk_level, strict_mode, requires_confirm, rollout_state, is_active, description, created_by, updated_by)
            VALUES (?, ?, ?, ?, ?, 1, 1, 'off', 0, ?, ?, ?)
            ON CONFLICT(robot_code) DO UPDATE SET
                robot_name=excluded.robot_name,
                scope_type=excluded.scope_type,
                activity_sector=excluded.activity_sector,
                risk_level=excluded.risk_level,
                description=excluded.description,
                updated_by=excluded.updated_by,
                updated_at=datetime('now')
            """,
            (
                seed["robot_code"],
                seed["robot_name"],
                seed["scope_type"],
                seed["activity_sector"],
                seed["risk_level"],
                seed["description"],
                admin_id,
                admin_id,
            ),
        )

    db.commit()

    after_rows = db.execute("SELECT robot_code FROM platform_robot_catalog").fetchall()
    after = {str((r[0] if not isinstance(r, dict) else r.get("robot_code")) or "") for r in (after_rows or [])}
    return {"seed_count": len(seeds), "inserted": len(after - before), "total": len(after)}


def _table_exists(db, table_name: str) -> bool:
    return db_table_exists(db, table_name)


def _column_exists(db, table_name: str, column_name: str) -> bool:
    try:
        safe_table = safe_sql_identifier(table_name)
        cols = db.execute(f"PRAGMA table_info({safe_table})").fetchall()
        return any((c[1] if not isinstance(c, dict) else c.get("name")) == column_name for c in cols)
    except Exception:
        return False


def _ensure_core_tables(db):
    """إنشاء جداول الامتدادات عند الحاجة."""
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
        CREATE TABLE IF NOT EXISTS platform_dynamic_features (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feature_code TEXT NOT NULL UNIQUE,
            feature_name TEXT NOT NULL,
            category TEXT,
            is_premium INTEGER NOT NULL DEFAULT 0,
            price_monthly REAL NOT NULL DEFAULT 0,
            offer_text TEXT,
            display_order INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            sidebar_config TEXT NOT NULL DEFAULT '{}',
            created_by INTEGER,
            updated_by INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
        """
    )

    # ترحيل آمن للنسخ القديمة التي أُنشئت قبل إضافة أعمدة التسعير/العروض/الترتيب.
    if not _column_exists(db, "platform_dynamic_features", "price_monthly"):
        db.execute("ALTER TABLE platform_dynamic_features ADD COLUMN price_monthly REAL NOT NULL DEFAULT 0")
    if not _column_exists(db, "platform_dynamic_features", "offer_text"):
        db.execute("ALTER TABLE platform_dynamic_features ADD COLUMN offer_text TEXT")
    if not _column_exists(db, "platform_dynamic_features", "display_order"):
        db.execute("ALTER TABLE platform_dynamic_features ADD COLUMN display_order INTEGER NOT NULL DEFAULT 0")

    db.commit()


def _setting_upsert(db, business_id: int, key: str, value: str) -> None:
    db.execute(
        """
        INSERT OR REPLACE INTO settings (business_id, key, value)
        VALUES (?, ?, ?)
        """,
        (int(business_id), str(key), str(value)),
    )


def _setting_delete(db, business_id: int, key: str) -> None:
    db.execute(
        "DELETE FROM settings WHERE business_id=? AND key=?",
        (int(business_id), str(key)),
    )


def _parse_date_ymd(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d")


def _month_cycle_proration(monthly_price: float, join_date: datetime) -> dict:
    """
    قواعد التسعير:
    - دورة الفوترة تقويمية (من 1 حتى آخر يوم بالشهر).
    - التجديد الكامل يبدأ من أول الشهر التالي.
    - اشتراك منتصف الشهر يحسب للأيام المتبقية حتى نهاية الشهر.
    - لتطابق أمثلة المستخدم (اليوم 20 => 10 أيام في شهر 30):
      الأيام المحتسبة = (عدد أيام الشهر - يوم الاشتراك).
      ويستثنى يوم الاشتراك نفسه من الاحتساب النسبي.
    """
    dim = monthrange(join_date.year, join_date.month)[1]

    if join_date.day <= 1:
        prorated_days = dim
    else:
        prorated_days = max(0, dim - join_date.day)

    daily_price = float(monthly_price) / float(dim)
    prorated_amount = round(daily_price * prorated_days, 2)

    month_end = join_date.replace(day=dim, hour=23, minute=59, second=59, microsecond=0)
    if join_date.month == 12:
        next_month_start = join_date.replace(year=join_date.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        next_month_start = join_date.replace(month=join_date.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)

    return {
        "days_in_month": dim,
        "prorated_days": int(prorated_days),
        "daily_price": round(daily_price, 4),
        "prorated_amount": prorated_amount,
        "month_end": month_end,
        "next_month_start": next_month_start,
        "full_month_amount_next_cycle": round(float(monthly_price), 2),
    }


def _build_sidebar_feature_seeds() -> list[dict]:
    """يبني قائمة ميزات افتراضية من SIDEBAR_CONFIG لتظهر تلقائياً في لوحة الأدمن."""
    seeds = []
    seen_codes = set()

    for raw_sector, items in (SIDEBAR_CONFIG or {}).items():
        sector = "common" if raw_sector == "_common" else get_sidebar_key(raw_sector)
        for item in (items or []):
            if not isinstance(item, dict):
                continue

            item_key = str(item.get("key") or "").strip()
            if not item_key:
                continue

            feature_code = f"{sector}:{item_key}"
            if feature_code in seen_codes:
                continue
            seen_codes.add(feature_code)

            sidebar_payload = {
                "sector_key": sector,
                "key": item_key,
                "label": item.get("label") or item_key,
                "label_en": item.get("label_en") or item_key,
                "icon": item.get("icon") or "📌",
                "url": item.get("url") or "#",
            }

            seeds.append(
                {
                    "feature_code": feature_code,
                    "feature_name": str(item.get("label") or item_key),
                    "category": sector,
                    "is_premium": 0,
                    "price_monthly": 0,
                    "offer_text": "",
                    "display_order": 0,
                    "is_active": 1,
                    "sidebar_config": json.dumps(sidebar_payload, ensure_ascii=False),
                }
            )
    return seeds


def _sync_default_sidebar_features(db, admin_id: int | None = None) -> dict:
    """
    مزامنة تلقائية: أي خدمة معرفة داخل SIDEBAR_CONFIG يتم إدراجها/تحديثها في الكتالوج الديناميكي.
    """
    _ensure_core_tables(db)
    seeds = _build_sidebar_feature_seeds()

    existing_rows = db.execute("SELECT feature_code FROM platform_dynamic_features").fetchall()
    existing = {
        str((r[0] if not isinstance(r, dict) else r.get("feature_code")) or "")
        for r in (existing_rows or [])
    }

    for seed in seeds:
        db.execute(
            """
            INSERT INTO platform_dynamic_features
                (feature_code, feature_name, category, is_premium, price_monthly, offer_text, display_order, is_active, sidebar_config, created_by, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(feature_code) DO UPDATE SET
                feature_name=excluded.feature_name,
                category=excluded.category,
                sidebar_config=excluded.sidebar_config,
                updated_by=excluded.updated_by,
                updated_at=datetime('now')
            """,
            (
                seed["feature_code"],
                seed["feature_name"],
                seed["category"],
                seed["is_premium"],
                seed["price_monthly"],
                seed["offer_text"],
                seed["display_order"],
                seed["is_active"],
                seed["sidebar_config"],
                admin_id,
                admin_id,
            ),
        )

    db.commit()

    after_rows = db.execute("SELECT feature_code FROM platform_dynamic_features").fetchall()
    after = {
        str((r[0] if not isinstance(r, dict) else r.get("feature_code")) or "")
        for r in (after_rows or [])
    }

    inserted = len(after - existing)
    return {
        "seed_count": len(seeds),
        "inserted": inserted,
        "total": len(after),
    }


# ==========================================
# 1) حارس البوابة الديناميكي (Gatekeeper System)
# ==========================================

@bp.route('/api/gatekeeper/status', methods=['GET', 'POST'])
@admin_required
def manage_gatekeeper():
    db = get_db()
    _ensure_core_tables(db)

    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        is_active = bool(data.get('active', True))
        value_str = 'True' if is_active else 'False'
        admin_id = session.get('user_id')

        db.execute(
            """
            INSERT INTO platform_settings (setting_key, setting_value, updated_by, updated_at)
            VALUES ('require_owner_approval', ?, ?, datetime('now'))
            ON CONFLICT(setting_key) DO UPDATE
            SET setting_value=excluded.setting_value,
                updated_by=excluded.updated_by,
                updated_at=excluded.updated_at
            """,
            (value_str, admin_id),
        )
        db.commit()

        write_audit_log(
            db,
            0,
            action='gatekeeper_status_updated',
            entity_type='platform_setting',
            entity_id=0,
            new_value=json.dumps({'require_owner_approval': is_active}, ensure_ascii=False),
        )
        return jsonify({'status': 'success', 'message': f'تم تحديث حالة حارس البوابة إلى: {value_str}'})

    # GET: جلب الوضع الحالي للحارس
    setting = db.execute(
        "SELECT setting_value FROM platform_settings WHERE setting_key='require_owner_approval'"
    ).fetchone()
    raw = '' if not setting else (setting['setting_value'] if isinstance(setting, dict) else setting[0])
    current_status = str(raw).strip().lower() in ('1', 'true', 'yes', 'on') if raw else True
    return jsonify({'status': 'success', 'gatekeeper_active': current_status})


# ==========================================
# 2) إدارة الأقسام والخدمات والميزات ديناميكياً
# ==========================================

@bp.route('/api/features/manage', methods=['POST'])
@admin_required
def manage_platform_features():
    """
    إضافة أو تحديث ميزة/قسم تشغيلي بشكل ديناميكي.
    """
    db = get_db()
    _ensure_core_tables(db)
    data = request.get_json(silent=True) or {}

    feature_code = (data.get('feature_code') or '').strip()
    feature_name = (data.get('feature_name') or '').strip()
    category = (data.get('category') or '').strip() or 'General'
    is_premium = 1 if bool(data.get('is_premium', 0)) else 0
    is_active = 1 if bool(data.get('is_active', 1)) else 0
    sidebar_payload = data.get('sidebar_json', {})
    try:
        monthly_price = float(data.get('monthly_price', 0) or 0)
    except Exception:
        monthly_price = 0.0
    offer_text = (data.get('offer_text') or '').strip()
    try:
        display_order = int(data.get('display_order', 0) or 0)
    except Exception:
        display_order = 0
    admin_id = session.get('user_id')

    if not feature_code or not feature_name:
        return jsonify({'status': 'error', 'message': 'كود الميزة والاسم حقول إلزامية'}), 400

    # حفظ sidebar_json كنص JSON صالح.
    try:
        if isinstance(sidebar_payload, str):
            parsed = json.loads(sidebar_payload) if sidebar_payload.strip() else {}
        else:
            parsed = sidebar_payload
        sidebar_config = json.dumps(parsed, ensure_ascii=False)
    except Exception:
        return jsonify({'status': 'error', 'message': 'sidebar_json يجب أن يكون JSON صالح'}), 400

    try:
        db.execute(
            """
            INSERT INTO platform_dynamic_features
                (feature_code, feature_name, category, is_premium, price_monthly, offer_text, display_order, is_active, sidebar_config, created_by, updated_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(feature_code) DO UPDATE SET
                feature_name=excluded.feature_name,
                category=excluded.category,
                is_premium=excluded.is_premium,
                price_monthly=excluded.price_monthly,
                offer_text=excluded.offer_text,
                display_order=excluded.display_order,
                is_active=excluded.is_active,
                sidebar_config=excluded.sidebar_config,
                updated_by=excluded.updated_by,
                updated_at=datetime('now')
            """,
            (
                feature_code,
                feature_name,
                category,
                is_premium,
                monthly_price,
                offer_text,
                display_order,
                is_active,
                sidebar_config,
                admin_id,
                admin_id,
            ),
        )
        db.commit()

        write_audit_log(
            db,
            0,
            action='platform_dynamic_feature_upserted',
            entity_type='platform_dynamic_feature',
            entity_id=0,
            new_value=json.dumps(
                {
                    'feature_code': feature_code,
                    'feature_name': feature_name,
                    'category': category,
                    'is_premium': is_premium,
                    'price_monthly': round(monthly_price, 2),
                    'offer_text': offer_text,
                    'display_order': display_order,
                    'is_active': is_active,
                },
                ensure_ascii=False,
            ),
        )
        return jsonify({'status': 'success', 'message': f'تم حفظ وتفعيل القسم/الميزة [{feature_name}] بنجاح في المنظومة'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'فشل تحديث الأقسام: {str(e)}'}), 500


@bp.route('/api/features/catalog', methods=['GET'])
@admin_required
def get_platform_features_catalog():
    """
    كتالوج الخدمات المركزي للوحة التحكم.
    - يقوم بالمزامنة التلقائية من SIDEBAR_CONFIG قبل الإرجاع.
    - يعيد كل الخدمات لتفعيل/تعطيل فوري.
    """
    db = get_db()
    _ensure_core_tables(db)
    sync_info = _sync_default_sidebar_features(db, admin_id=session.get('user_id'))

    rows = db.execute(
        """
        SELECT feature_code, feature_name, category, is_premium, is_active, sidebar_config, updated_at
        FROM platform_dynamic_features
        ORDER BY display_order ASC, category ASC, feature_name ASC
        """
    ).fetchall()

    features = []
    for row in rows or []:
        data = dict(row) if not isinstance(row, dict) else row
        raw_sidebar = data.get('sidebar_config') or '{}'
        try:
            sidebar_cfg = json.loads(raw_sidebar)
        except Exception:
            sidebar_cfg = {}
        features.append(
            {
                'feature_code': data.get('feature_code'),
                'feature_name': data.get('feature_name'),
                'category': data.get('category') or 'general',
                'is_premium': int(data.get('is_premium') or 0),
                'monthly_price': float(data.get('price_monthly') or 0),
                'offer_text': data.get('offer_text') or '',
                'display_order': int(data.get('display_order') or 0),
                'is_active': int(data.get('is_active') or 0),
                'updated_at': data.get('updated_at'),
                'sidebar': sidebar_cfg,
            }
        )

    return jsonify(
        {
            'status': 'success',
            'sync': sync_info,
            'features': features,
        }
    )


@bp.route('/api/features/<path:feature_code>/toggle', methods=['POST'])
@admin_required
def toggle_platform_feature(feature_code: str):
    """تفعيل/تعطيل خدمة مباشرة من لوحة التحكم بدون أي تعديل برمجي."""
    db = get_db()
    _ensure_core_tables(db)

    clean_code = (feature_code or '').strip()
    if not clean_code:
        return jsonify({'status': 'error', 'message': 'feature_code غير صالح'}), 400

    data = request.get_json(silent=True) or {}
    target_active = 1 if bool(data.get('active', True)) else 0
    admin_id = session.get('user_id')

    _sync_default_sidebar_features(db, admin_id=admin_id)
    exists = db.execute(
        "SELECT feature_code FROM platform_dynamic_features WHERE feature_code=? LIMIT 1",
        (clean_code,),
    ).fetchone()
    if not exists:
        return jsonify({'status': 'error', 'message': 'الخدمة غير موجودة في الكتالوج'}), 404

    db.execute(
        """
        UPDATE platform_dynamic_features
        SET is_active=?, updated_by=?, updated_at=datetime('now')
        WHERE feature_code=?
        """,
        (target_active, admin_id, clean_code),
    )

    db.commit()

    write_audit_log(
        db,
        0,
        action='platform_feature_toggled',
        entity_type='platform_dynamic_feature',
        entity_id=0,
        new_value=json.dumps(
            {
                'feature_code': clean_code,
                'is_active': target_active,
                'updated_by': admin_id,
            },
            ensure_ascii=False,
        ),
    )

    return jsonify(
        {
            'status': 'success',
            'message': 'تم تحديث حالة الخدمة بنجاح',
            'feature_code': clean_code,
            'is_active': target_active,
        }
    )


# ==========================================
# 2-bis) مركز الروبوتات (مشتركة + حسب النشاط)
# ==========================================

@bp.route('/api/robots/catalog', methods=['GET'])
@admin_required
def get_robots_catalog():
    db = get_db()
    sync_info = _sync_robot_catalog(db, admin_id=session.get('user_id'))

    rows = db.execute(
        """
        SELECT robot_code, robot_name, scope_type, activity_sector,
               risk_level, strict_mode, requires_confirm,
               rollout_state, is_active, description, updated_at
        FROM platform_robot_catalog
        ORDER BY scope_type ASC, activity_sector ASC, robot_name ASC
        """
    ).fetchall()

    businesses = db.execute("SELECT id, industry_type FROM businesses WHERE is_active=1").fetchall()
    sector_counts: dict[str, int] = {}
    for b in businesses or []:
        row = dict(b) if not isinstance(b, dict) else b
        sector = _sector_from_industry_type(row.get('industry_type') or '')
        sector_counts[sector] = sector_counts.get(sector, 0) + 1

    robots = []
    for r in rows or []:
        row = dict(r) if not isinstance(r, dict) else r
        scope_type = (row.get('scope_type') or 'shared').strip().lower()
        activity_sector = (row.get('activity_sector') or '').strip().lower()
        if scope_type == 'shared':
            matched_businesses = int(sum(sector_counts.values()))
        else:
            matched_businesses = int(sector_counts.get(activity_sector, 0))

        robots.append(
            {
                'robot_code': row.get('robot_code'),
                'robot_name': row.get('robot_name'),
                'scope_type': scope_type,
                'activity_sector': activity_sector,
                'risk_level': row.get('risk_level') or 'medium',
                'strict_mode': int(row.get('strict_mode') or 0),
                'requires_confirm': int(row.get('requires_confirm') or 0),
                'rollout_state': row.get('rollout_state') or 'off',
                'is_active': int(row.get('is_active') or 0),
                'description': row.get('description') or '',
                'matched_businesses': matched_businesses,
                'updated_at': row.get('updated_at'),
            }
        )

    return jsonify({'status': 'success', 'sync': sync_info, 'robots': robots})


@bp.route('/api/robots/<path:robot_code>/state', methods=['POST'])
@admin_required
def set_robot_state(robot_code: str):
    db = get_db()
    _sync_robot_catalog(db, admin_id=session.get('user_id'))

    clean_code = (robot_code or '').strip()
    if not clean_code:
        return jsonify({'status': 'error', 'message': 'robot_code غير صالح'}), 400

    payload = request.get_json(silent=True) or {}
    requested_state = str(payload.get('rollout_state', 'off') or 'off').strip().lower()
    if requested_state not in {'off', 'pilot', 'on'}:
        return jsonify({'status': 'error', 'message': 'rollout_state يجب أن يكون off أو pilot أو on'}), 400

    row = db.execute(
        """
        SELECT robot_code, robot_name, scope_type, activity_sector,
               risk_level, strict_mode, requires_confirm
        FROM platform_robot_catalog WHERE robot_code=? LIMIT 1
        """,
        (clean_code,),
    ).fetchone()
    if not row:
        return jsonify({'status': 'error', 'message': 'الروبوت غير موجود'}), 404

    robot = dict(row) if not isinstance(row, dict) else row
    scope_type = (robot.get('scope_type') or 'shared').strip().lower()
    sector = (robot.get('activity_sector') or '').strip().lower()
    risk = (robot.get('risk_level') or 'medium').strip().lower()
    strict_mode = int(robot.get('strict_mode') or 0)
    requires_confirm = int(robot.get('requires_confirm') or 0)

    if requested_state != 'off' and strict_mode:
        if requires_confirm:
            phrase = str(payload.get('confirm_phrase') or '').strip()
            if phrase != STRICT_CONFIRM_PHRASE:
                return jsonify(
                    {
                        'status': 'error',
                        'message': 'رفض التفعيل: يلزم تأكيد العبارة الصارمة قبل تشغيل الروبوت.',
                        'required_confirm_phrase': STRICT_CONFIRM_PHRASE,
                    }
                ), 400

        if risk in {'critical', 'high'} and requested_state == 'on':
            if not bool(payload.get('allow_high_risk', False)):
                return jsonify(
                    {
                        'status': 'error',
                        'message': 'الروبوت عالي الحساسية. فعّل allow_high_risk=true أو ابدأ بوضع pilot.',
                    }
                ), 400

        if scope_type == 'sector':
            biz_rows = db.execute("SELECT industry_type FROM businesses WHERE is_active=1").fetchall()
            match_count = 0
            for b in biz_rows or []:
                item = dict(b) if not isinstance(b, dict) else b
                if _sector_from_industry_type(item.get('industry_type') or '') == sector:
                    match_count += 1

            if match_count <= 0:
                return jsonify(
                    {
                        'status': 'error',
                        'message': 'رفض التفعيل: لا توجد منشآت مطابقة لهذا النشاط حالياً.',
                    }
                ), 400

    target_active = 0 if requested_state == 'off' else 1
    db.execute(
        """
        UPDATE platform_robot_catalog
        SET rollout_state=?, is_active=?, updated_by=?, updated_at=datetime('now')
        WHERE robot_code=?
        """,
        (requested_state, target_active, session.get('user_id'), clean_code),
    )
    db.commit()

    write_audit_log(
        db,
        0,
        action='platform_robot_state_updated',
        entity_type='platform_robot',
        entity_id=0,
        new_value=json.dumps(
            {
                'robot_code': clean_code,
                'robot_name': robot.get('robot_name') or clean_code,
                'scope_type': scope_type,
                'activity_sector': sector,
                'risk_level': risk,
                'rollout_state': requested_state,
                'is_active': target_active,
                'updated_by': session.get('user_id'),
            },
            ensure_ascii=False,
        ),
    )

    return jsonify(
        {
            'status': 'success',
            'message': 'تم تحديث حالة الروبوت بنجاح',
            'robot_code': clean_code,
            'rollout_state': requested_state,
            'is_active': target_active,
        }
    )


# ==========================================
# 3) نظام الحظر والتعليق الفوري (Kill Switch)
# ==========================================

@bp.route('/api/business/<int:business_id>/suspend', methods=['POST'])
@admin_required
def toggle_business_suspension(business_id: int):
    """
    حظر/إعادة تنشيط منشأة كاملة مع تعطيل/تفعيل مستخدميها.
    """
    db = get_db()
    data = request.get_json(silent=True) or {}
    suspend = bool(data.get('suspend', True))
    reason = (data.get('reason') or 'لم يذكر سبب').strip()

    target_status = 'suspended' if suspend else 'active'
    is_active_value = 0 if suspend else 1

    try:
        exists = db.execute("SELECT id FROM businesses WHERE id=?", (business_id,)).fetchone()
        if not exists:
            return jsonify({'status': 'error', 'message': 'المنشأة غير موجودة'}), 404

        # تحديث حقول متاحة فعلياً في هذا النظام.
        if _column_exists(db, 'businesses', 'status'):
            db.execute(
                "UPDATE businesses SET status=?, updated_at=datetime('now') WHERE id=?",
                (target_status, business_id),
            )

        if _column_exists(db, 'businesses', 'account_status'):
            db.execute(
                "UPDATE businesses SET account_status=?, updated_at=datetime('now') WHERE id=?",
                ('suspended' if suspend else 'approved', business_id),
            )

        if _column_exists(db, 'businesses', 'is_active'):
            db.execute(
                "UPDATE businesses SET is_active=?, updated_at=datetime('now') WHERE id=?",
                (is_active_value, business_id),
            )

        # تعطيل/تفعيل كل مستخدمي المنشأة.
        if _table_exists(db, 'users') and _column_exists(db, 'users', 'is_active'):
            db.execute(
                "UPDATE users SET is_active=? WHERE business_id=?",
                (is_active_value, business_id),
            )

        write_audit_log(
            db,
            business_id,
            action='business_status_change',
            entity_type='business',
            entity_id=business_id,
            new_value=json.dumps(
                {
                    'target_status': target_status,
                    'suspend': suspend,
                    'reason': reason,
                    'updated_by': session.get('user_id'),
                },
                ensure_ascii=False,
            ),
        )

        db.commit()
        return jsonify({'status': 'success', 'message': f'تم تحويل المنشأة بنجاح إلى وضع: {target_status}'})
    except Exception as e:
        db.rollback()
        return jsonify({'status': 'error', 'message': f'فشل تنفيذ العملية: {str(e)}'}), 500


# ==========================================
# 4) تسعير اشتراك شهري نسبي + ضبط دورة التجديد
# ==========================================

@bp.route('/api/business/<int:business_id>/subscription/prorate', methods=['POST'])
@admin_required
def set_business_subscription_proration(business_id: int):
    """
    يحسب الاشتراك النسبي حتى نهاية الشهر ويخزنه في settings.

    body JSON:
    {
      "monthly_price": 100,
      "join_date": "2026-06-20",   # optional, default=today UTC
      "apply": true                  # optional, default=true
    }
    """
    db = get_db()
    data = request.get_json(silent=True) or {}

    exists = db.execute("SELECT id FROM businesses WHERE id=?", (business_id,)).fetchone()
    if not exists:
        return jsonify({'status': 'error', 'message': 'المنشأة غير موجودة'}), 404

    try:
        monthly_price = float(data.get('monthly_price', 0) or 0)
    except Exception:
        monthly_price = 0.0

    if monthly_price <= 0:
        return jsonify({'status': 'error', 'message': 'monthly_price يجب أن يكون أكبر من صفر'}), 400

    join_date_raw = (data.get('join_date') or '').strip()
    if join_date_raw:
        try:
            join_date = _parse_date_ymd(join_date_raw)
        except Exception:
            return jsonify({'status': 'error', 'message': 'join_date يجب أن يكون بصيغة YYYY-MM-DD'}), 400
    else:
        join_date = datetime.utcnow()

    calc = _month_cycle_proration(monthly_price=monthly_price, join_date=join_date)
    apply_changes = bool(data.get('apply', True))

    response_payload = {
        'status': 'success',
        'business_id': business_id,
        'billing_cycle': {
            'anchor_day': 1,
            'renews_at_month_end': True,
            'next_full_cycle_starts_at': calc['next_month_start'].strftime('%Y-%m-%d %H:%M:%S'),
        },
        'calculation': {
            'monthly_price': round(monthly_price, 2),
            'days_in_month': calc['days_in_month'],
            'prorated_days': calc['prorated_days'],
            'daily_price': calc['daily_price'],
            'prorated_amount': calc['prorated_amount'],
            'current_cycle_expires_at': calc['month_end'].strftime('%Y-%m-%d %H:%M:%S'),
            'next_cycle_full_amount': calc['full_month_amount_next_cycle'],
        },
        'applied': apply_changes,
    }

    if not apply_changes:
        return jsonify(response_payload)

    try:
        _setting_upsert(db, business_id, 'subscription_cycle_anchor_day', '1')
        _setting_upsert(db, business_id, 'subscription_monthly_price', f"{monthly_price:.2f}")
        _setting_upsert(db, business_id, 'subscription_started_at', join_date.strftime('%Y-%m-%d %H:%M:%S'))
        _setting_upsert(db, business_id, 'subscription_proration_days', str(calc['prorated_days']))
        _setting_upsert(db, business_id, 'subscription_proration_amount', f"{calc['prorated_amount']:.2f}")
        _setting_upsert(db, business_id, 'subscription_expires_at', calc['month_end'].strftime('%Y-%m-%d %H:%M:%S'))
        _setting_upsert(db, business_id, 'subscription_next_renewal_at', calc['next_month_start'].strftime('%Y-%m-%d %H:%M:%S'))

        # تجديد فعلي => إزالة أعلام الإنذار/الإيقاف التلقائي القديمة.
        _setting_delete(db, business_id, 'subscription_notice_71h_sent_at')
        _setting_delete(db, business_id, 'trial_notice_71h_sent_at')
        _setting_delete(db, business_id, 'subscription_auto_suspended_at')

        # إعادة تنشيط المنشأة والمستخدمين عند التجديد.
        if _column_exists(db, 'businesses', 'status'):
            db.execute("UPDATE businesses SET status='active', updated_at=datetime('now') WHERE id=?", (business_id,))
        if _column_exists(db, 'businesses', 'account_status'):
            db.execute("UPDATE businesses SET account_status='approved', updated_at=datetime('now') WHERE id=?", (business_id,))
        if _column_exists(db, 'businesses', 'is_active'):
            db.execute("UPDATE businesses SET is_active=1, updated_at=datetime('now') WHERE id=?", (business_id,))
        if _table_exists(db, 'users') and _column_exists(db, 'users', 'is_active'):
            db.execute("UPDATE users SET is_active=1 WHERE business_id=?", (business_id,))

        write_audit_log(
            db,
            business_id,
            action='subscription_proration_applied',
            entity_type='business',
            entity_id=business_id,
            new_value=json.dumps(
                {
                    'monthly_price': round(monthly_price, 2),
                    'prorated_days': calc['prorated_days'],
                    'prorated_amount': calc['prorated_amount'],
                    'current_cycle_expires_at': calc['month_end'].strftime('%Y-%m-%d %H:%M:%S'),
                    'next_cycle_starts_at': calc['next_month_start'].strftime('%Y-%m-%d %H:%M:%S'),
                },
                ensure_ascii=False,
            ),
        )

        db.commit()
        return jsonify(response_payload)
    except Exception as e:
        db.rollback()
        return jsonify({'status': 'error', 'message': f'فشل حفظ إعدادات الاشتراك: {str(e)}'}), 500
