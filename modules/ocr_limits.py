"""
modules/ocr_limits.py — OCR Rate Limiter حسب الباقة

المنطق:
  - كل منشأة لها حد شهري من صفحات OCR حسب الباقة
  - العمليات البسيطة (local) مجانية دائماً
  - العمليات الذكية (AI/Cloud) تُخصم من الرصيد الشهري
  - عند الوصول للحد → تُرفع OCRLimitExceeded

الباقات:
  free    → 10 صفحة/شهر
  starter → 100 صفحة/شهر
  pro     → 500 صفحة/شهر
  unlimited → ∞
"""
import logging
from datetime import datetime
from typing import Optional

_log = logging.getLogger(__name__)

# ── حدود الباقات (صفحات OCR شهرياً) ─────────────────────────────────────────
PLAN_LIMITS: dict[str, int] = {
    "free":      10,
    "starter":   100,
    "pro":       500,
    "unlimited": 999_999,
}

DEFAULT_PLAN = "free"

# ── Migration SQL ─────────────────────────────────────────────────────────────
USAGE_LOGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id  INTEGER NOT NULL,
    feature      TEXT    NOT NULL,   -- 'ocr_local' | 'ocr_ai' | 'zatca_xml'
    units        INTEGER NOT NULL DEFAULT 1,
    period       TEXT    NOT NULL,   -- 'YYYY-MM'
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_usage_logs_period
    ON usage_logs(business_id, feature, period);
"""


# ── إنشاء الجدول ──────────────────────────────────────────────────────────────

def init_usage_logs(db):
    for stmt in USAGE_LOGS_SCHEMA.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            db.execute(stmt)
    db.commit()
    _log.info("usage_logs table initialized")


# ── استثناء مخصص ─────────────────────────────────────────────────────────────

class OCRLimitExceeded(Exception):
    """
    تُرفع عند تجاوز حد OCR الشهري.
    attrs: used, limit, plan
    """
    def __init__(self, used: int, limit: int, plan: str):
        self.used  = used
        self.limit = limit
        self.plan  = plan
        super().__init__(
            f"تجاوزت حد OCR الشهري ({used}/{limit} صفحة) — الباقة: {plan}"
        )


# ── الدوال الرئيسية ───────────────────────────────────────────────────────────

def get_plan(db, business_id: int) -> str:
    """
    جلب باقة المنشأة من جدول settings أو businesses.
    إذا لم تُحدَّد → free.
    """
    row = db.execute(
        "SELECT value FROM settings WHERE business_id=? AND key='subscription_plan'",
        (business_id,)
    ).fetchone()
    if row and row["value"] in PLAN_LIMITS:
        return row["value"]
    # fallback: تحقق من businesses مباشرة
    biz = db.execute(
        "SELECT plan FROM businesses WHERE id=?", (business_id,)
    ).fetchone()
    if biz and biz["plan"] in PLAN_LIMITS:
        return biz["plan"]
    return DEFAULT_PLAN


def get_monthly_usage(db, business_id: int, feature: str = "ocr_ai",
                      period: Optional[str] = None) -> int:
    """استهلاك الشهر الحالي لميزة معيّنة"""
    if not period:
        period = datetime.now().strftime("%Y-%m")
    row = db.execute(
        "SELECT COALESCE(SUM(units), 0) FROM usage_logs WHERE business_id=? AND feature=? AND period=?",
        (business_id, feature, period)
    ).fetchone()
    return int(row[0])


def check_ocr_limit(db, business_id: int, units: int = 1) -> tuple[int, int]:
    """
    يتحقق من رصيد OCR الذكي قبل الاستخدام.
    يُعيد (used, limit) عند النجاح.
    يرفع OCRLimitExceeded عند تجاوز الحد.
    """
    plan    = get_plan(db, business_id)
    limit   = PLAN_LIMITS[plan]
    period  = datetime.now().strftime("%Y-%m")
    used    = get_monthly_usage(db, business_id, "ocr_ai", period)

    if used + units > limit:
        raise OCRLimitExceeded(used=used, limit=limit, plan=plan)
    return used, limit


def log_ocr_usage(db, business_id: int,
                  feature: str = "ocr_ai", units: int = 1):
    """
    يُسجّل استهلاك OCR بعد نجاح العملية.
    feature: 'ocr_local' | 'ocr_ai'
    """
    period = datetime.now().strftime("%Y-%m")
    db.execute(
        "INSERT INTO usage_logs (business_id, feature, units, period) VALUES (?,?,?,?)",
        (business_id, feature, units, period)
    )
    db.commit()
    _log.info(f"OCR usage logged: biz={business_id} feature={feature} units={units} period={period}")


def ocr_protected(f):
    """
    ديكوراتور يُغلّف دوال OCR الذكية بفحص الحد.

    الاستخدام:
        @ocr_protected
        def extract_invoice_ai(db, business_id, file_path):
            ...

    يتوقع أن تكون المعاملات (db, business_id, ...) أو يمكن جلبهم من session.
    """
    import functools
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        from flask import session, jsonify
        from .extensions import get_db
        db      = get_db()
        biz_id  = session.get("business_id")
        if not biz_id:
            return jsonify({"success": False, "error": "غير مصرح"}), 401
        try:
            check_ocr_limit(db, biz_id)
        except OCRLimitExceeded as e:
            return jsonify({
                "success": False,
                "error":   str(e),
                "code":    "OCR_LIMIT_EXCEEDED",
                "used":    e.used,
                "limit":   e.limit,
                "plan":    e.plan,
                "upgrade_url": "/settings#subscription",
            }), 429
        result = f(*args, **kwargs)
        # سجّل الاستهلاك بعد النجاح
        try:
            log_ocr_usage(db, biz_id, "ocr_ai", 1)
        except Exception as ex:
            _log.warning(f"Failed to log OCR usage: {ex}")
        return result
    return wrapper


# ── إحصائيات للـ dashboard ────────────────────────────────────────────────────

def get_usage_summary(db, business_id: int) -> dict:
    """ملخص الاستهلاك للشهر الحالي لعرضه في dashboard الإعدادات"""
    period = datetime.now().strftime("%Y-%m")
    plan   = get_plan(db, business_id)
    limit  = PLAN_LIMITS[plan]

    rows = db.execute(
        """SELECT feature, COALESCE(SUM(units), 0) as total
           FROM usage_logs
           WHERE business_id=? AND period=?
           GROUP BY feature""",
        (business_id, period)
    ).fetchall()

    usage = {r["feature"]: r["total"] for r in rows}
    ocr_ai_used = usage.get("ocr_ai", 0)

    return {
        "plan":          plan,
        "period":        period,
        "ocr_ai_used":   ocr_ai_used,
        "ocr_ai_limit":  limit,
        "ocr_ai_pct":    round(ocr_ai_used / limit * 100, 1) if limit > 0 else 0,
        "ocr_local_used": usage.get("ocr_local", 0),
        "features":      usage,
    }
