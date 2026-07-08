"""
modules/middleware.py — RBAC، ديكوراتورات الحماية، before/after request
"""
import json
import secrets
from collections import deque
from datetime import datetime, timedelta
from functools import wraps
from threading import BoundedSemaphore, Lock
from time import monotonic
from typing import Optional

from flask import g, redirect, session, url_for, flash, request, jsonify

from .audit_service import record_audit_event
from .rbac_service import get_effective_permissions

from .config import SIDEBAR_CONFIG, SIDEBAR_PERM, get_sidebar_key
from .extensions import get_db, generate_csrf_token
from .config import (
    RATE_LIMIT_WINDOW_SEC,
    RATE_LIMIT_MAX_REQUEST,
    MAX_INFLIGHT_REQUESTS,
    OVERLOAD_RETRY_AFTER_SEC,
    IS_PROD,
    CSP_MODE,
)
from .runtime_services import (
    should_use_distributed_rate_limit,
    check_rate_limit_distributed,
)
from .i18n import SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE
from .notifications_service import create_notifications_for_users


_rate_limit_state: dict[str, deque] = {}
_rate_lock = Lock()
_inflight_semaphore = BoundedSemaphore(max(1, MAX_INFLIGHT_REQUESTS))

_EXPIRY_WARNING_HOURS = 71
_EXPIRY_GRACE_HOURS = 24


def _parse_expiry_datetime(raw_value: Optional[str]) -> Optional[datetime]:
    value = (raw_value or "").strip()
    if not value:
        return None

    # صيغة تاريخ فقط => نهاية اليوم لتجنب الإغلاق المبكر.
    if len(value) == 10:
        try:
            d = datetime.strptime(value, "%Y-%m-%d")
            return d.replace(hour=23, minute=59, second=59)
        except Exception:
            return None

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    ):
        try:
            return datetime.strptime(value, fmt)
        except Exception:
            continue

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _setting_get(db, business_id: int, key: str) -> Optional[str]:
    row = db.execute(
        "SELECT value FROM settings WHERE business_id=? AND key=? LIMIT 1",
        (int(business_id), str(key)),
    ).fetchone()
    if not row:
        return None
    return row["value"] if isinstance(row, dict) else row[0]


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


def _business_has_column(db, column_name: str) -> bool:
    try:
        cols = db.execute("PRAGMA table_info(businesses)").fetchall()
        return any((c[1] if not isinstance(c, dict) else c.get("name")) == column_name for c in cols)
    except Exception:
        return False


def _resolve_business_expiry(db, business_id: int, business_row: dict) -> tuple[Optional[datetime], Optional[str], Optional[str]]:
    # أولوية الاشتراك المدفوع ثم التجربة.
    subscription_keys = ("subscription_expires_at", "subscription_end_at", "plan_expires_at")
    trial_keys = ("trial_expires_at", "trial_end_at", "trial_ends_at")

    for k in subscription_keys:
        dt = _parse_expiry_datetime(_setting_get(db, business_id, k))
        if dt:
            return dt, "subscription", k

    for k in trial_keys:
        dt = _parse_expiry_datetime(_setting_get(db, business_id, k))
        if dt:
            return dt, "trial", k

    # fallback من الأعمدة إن وجدت.
    for col, src in (
        ("subscription_expires_at", "subscription"),
        ("trial_expires_at", "trial"),
        ("trial_end_at", "trial"),
        ("trial_ends_at", "trial"),
        ("expires_at", "subscription"),
    ):
        if col in business_row:
            dt = _parse_expiry_datetime(str(business_row.get(col) or ""))
            if dt:
                return dt, src, f"businesses.{col}"

    return None, None, None


def _enforce_subscription_lifecycle(db, user_id: int, business_row: dict):
    biz_id = int(business_row.get("id") or 0)
    if not biz_id:
        return None

    expiry_at, expiry_source, expiry_key = _resolve_business_expiry(db, biz_id, business_row)
    if not expiry_at or not expiry_source:
        return None

    now = datetime.utcnow()
    notice_key = f"{expiry_source}_notice_71h_sent_at"
    suspended_key = "subscription_auto_suspended_at"

    # إذا حصل تجديد لاحقاً وتم تمديد النهاية بعيداً عن نافذة التنبيه نعيد ضبط علامة التنبيه.
    if expiry_at > now + timedelta(hours=_EXPIRY_WARNING_HOURS):
        if _setting_get(db, biz_id, notice_key):
            _setting_delete(db, biz_id, notice_key)
            db.commit()
        return None

    # إشعار استباقي قبل انتهاء المدة بـ 71 ساعة.
    if now < expiry_at <= now + timedelta(hours=_EXPIRY_WARNING_HOURS):
        if not _setting_get(db, biz_id, notice_key):
            active_users = db.execute(
                "SELECT id FROM users WHERE business_id=? AND is_active=1",
                (biz_id,),
            ).fetchall()
            user_ids = [int((r[0] if not isinstance(r, dict) else r.get("id")) or 0) for r in active_users]
            user_ids = [uid for uid in user_ids if uid > 0]
            if user_ids:
                create_notifications_for_users(
                    db,
                    user_ids=user_ids,
                    notif_type="subscription_expiry_warning",
                    title="تنبيه قرب انتهاء الاشتراك",
                    message="سيتوقف النظام تلقائياً إذا لم يتم التجديد خلال المهلة المحددة.",
                )
            _setting_upsert(db, biz_id, notice_key, now.strftime("%Y-%m-%d %H:%M:%S"))
            db.commit()
        return None

    # إيقاف تلقائي بعد 24 ساعة من الانتهاء إذا لم يتجدد الاشتراك/التجربة.
    if now >= (expiry_at + timedelta(hours=_EXPIRY_GRACE_HOURS)):
        already_suspended = str(business_row.get("account_status") or "").lower() == "suspended"
        if not already_suspended:
            if _business_has_column(db, "account_status"):
                db.execute(
                    "UPDATE businesses SET account_status='suspended' WHERE id=?",
                    (biz_id,),
                )
            if _business_has_column(db, "status"):
                db.execute(
                    "UPDATE businesses SET status='suspended' WHERE id=?",
                    (biz_id,),
                )
            if _business_has_column(db, "is_active"):
                db.execute(
                    "UPDATE businesses SET is_active=0 WHERE id=?",
                    (biz_id,),
                )

            db.execute(
                "UPDATE users SET is_active=0 WHERE business_id=?",
                (biz_id,),
            )

            write_audit_log(
                db,
                biz_id,
                action="business_auto_suspended_expiry",
                entity_type="business",
                entity_id=biz_id,
                new_value=json.dumps(
                    {
                        "expiry_source": expiry_source,
                        "expiry_key": expiry_key,
                        "expired_at": expiry_at.strftime("%Y-%m-%d %H:%M:%S"),
                        "grace_hours": _EXPIRY_GRACE_HOURS,
                    },
                    ensure_ascii=False,
                ),
            )
            _setting_upsert(db, biz_id, suspended_key, now.strftime("%Y-%m-%d %H:%M:%S"))
            db.commit()

        # إنهاء الجلسة الحالية للمنشأة المتوقفة.
        if session.get("business_id") == biz_id and session.get("user_id") == user_id:
            session.clear()
            flash("تم إيقاف المنشأة تلقائياً لانتهاء الاشتراك وعدم التجديد خلال المهلة.", "error")
            return redirect(url_for("auth.auth_login"))

    return None


def _is_onboarding_complete() -> bool:
    """التحقق من اكتمال تهيئة المنشأة الحالية."""
    biz_id = session.get("business_id")
    if not biz_id:
        return False
    try:
        db = get_db()
        row = db.execute(
            "SELECT value FROM settings WHERE business_id=? AND key='onboarding_complete' LIMIT 1",
            (biz_id,),
        ).fetchone()
        return bool(row and str(row["value"]) == "1")
    except Exception:
        return False


def _needs_onboarding_redirect() -> bool:
    """هل يجب إعادة توجيه المستخدم إلى /onboarding؟"""
    if not session.get("user_id") or not session.get("business_id"):
        return False

    path = request.path or ""
    exempt_prefixes = ("/auth", "/static", "/onboarding")
    exempt_paths = ("/healthz", "/readyz", "/sw.js")

    if path.startswith(exempt_prefixes) or path in exempt_paths:
        return False

    return not _is_onboarding_complete()


# ─── التحقق من الصلاحية ───────────────────────────────────────────────────────

def user_has_perm(perm_key: str) -> bool:
    if not g.user:
        return False
    try:
        db = get_db()
        perms = get_effective_permissions(db, g.user)
    except Exception:
        try:
            perms = json.loads(g.user["permissions"] or "{}")
        except Exception:
            perms = {}
    return bool(perms.get("all") or perms.get(perm_key))


# ─── ديكوراتورات الحماية ──────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.auth_login"))
        if _needs_onboarding_redirect():
            return redirect(url_for("core.onboarding"))
        return f(*args, **kwargs)
    return decorated


def onboarding_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.auth_login"))
        if not session.get("business_id"):
            return redirect(url_for("core.onboarding"))
        if _needs_onboarding_redirect():
            return redirect(url_for("core.onboarding"))
        return f(*args, **kwargs)
    return decorated


def require_perm(perm_key: str):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("auth.auth_login"))
            if not session.get("business_id"):
                return redirect(url_for("core.onboarding"))
            if _needs_onboarding_redirect():
                return redirect(url_for("core.onboarding"))
            if not user_has_perm(perm_key):
                flash("ليس لديك صلاحية للوصول لهذه الصفحة", "error")
                return redirect(url_for("core.dashboard"))
            return f(*args, **kwargs)
        return decorated
    return decorator


def owner_required(f):
    """ديكوراتور: يسمح فقط للمالك (permissions.all = true)"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.auth_login"))
        if not session.get("business_id"):
            return redirect(url_for("core.onboarding"))
        if _needs_onboarding_redirect():
            return redirect(url_for("core.onboarding"))
        try:
            perms = json.loads(g.user["permissions"] or "{}") if g.user else {}
        except Exception:
            perms = {}
        if not perms.get("all"):
            flash("هذه الصفحة مخصصة للمالك فقط", "error")
            return redirect(url_for("core.dashboard"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """ديكوراتور: يسمح فقط لمالك البرنامج (is_platform_admin=1)"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.auth_login"))

        is_platform_admin = (
            g.user
            and (
                g.user.get("is_platform_admin") == 1
                or g.user.get("username") == "admin"
                or g.user.get("level") == "owner"
            )
        )

        if not is_platform_admin:
            flash("هذه الصفحة مخصصة لمالك البرنامج فقط", "error")
            if "user_id" in session:
                return redirect(url_for("core.dashboard"))
            else:
                return redirect(url_for("auth.auth_login"))

        return f(*args, **kwargs)
    return decorated


def write_audit_log(
    db,
    business_id: int,
    action: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
    reason: Optional[str] = None,
    metadata: Optional[dict] = None,
):
    """تسجيل حدث تدقيقي عبر خدمة موحدة (audit_logs + enhanced_audit_logs)."""
    try:
        record_audit_event(
            db,
            business_id=business_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            metadata=metadata,
        )
    except Exception:
        pass  # لا نوقف العملية بسبب فشل الـ audit log


# ─── Hooks: before_request و after_request ────────────────────────────────────

def load_user():
    """حقن بيانات المستخدم والمنشأة في g قبل كل request"""
    import logging
    g.user           = None
    g.business       = None
    g.sidebar_items  = []
    g.user_perms     = {}
    g.country_profile = None

    # ── تحديد اللغة (جلسة → مستخدم → افتراضي) ───────────────────────────
    lang = session.get("lang", DEFAULT_LANGUAGE)
    if lang not in SUPPORTED_LANGUAGES:
        lang = DEFAULT_LANGUAGE
    g.lang = lang

    user_id = session.get("user_id")
    if user_id:
        db = get_db()
        g.user = db.execute(
            """SELECT u.*, r.name as role_name, r.permissions
               FROM users u
               LEFT JOIN roles r ON r.id = u.role_id
               WHERE u.id = ?""",
            (user_id,)
        ).fetchone()

        if g.user:
            g.user = dict(g.user)
            # ── تحديث اللغة من تفضيل المستخدم المحفوظ ─────────────────────
            user_lang = g.user.get("preferred_language") or DEFAULT_LANGUAGE
            if user_lang in SUPPORTED_LANGUAGES and "lang" not in session:
                g.lang = user_lang

        # ── RLS Guard: تحقق أن business_id في الجلسة يطابق قاعدة البيانات ──────
        # يمنع تلاعب المستخدم بالجلسة للوصول لبيانات منشأة أخرى
        if g.user and session.get("business_id"):
            actual_biz = int(g.user["business_id"] or 0)
            session_biz = int(session["business_id"])
            if actual_biz != session_biz:
                logging.getLogger(__name__).warning(
                    f"RLS VIOLATION: user_id={user_id} tried business_id={session_biz} "
                    f"but owns={actual_biz} — session cleared"
                )
                session.clear()
                g.user = None
                g.business = None
                return

        if g.user:
            try:
                g.user_perms = get_effective_permissions(db, g.user)
            except Exception:
                try:
                    g.user_perms = json.loads(g.user["permissions"] or "{}")
                except Exception:
                    g.user_perms = {}

        biz_id = session.get("business_id")
        if biz_id:
            g.business = db.execute(
                "SELECT * FROM businesses WHERE id = ?", (biz_id,)
            ).fetchone()

            if g.business:
                g.business = dict(g.business)

            if g.business:
                lifecycle_response = _enforce_subscription_lifecycle(db, int(user_id), g.business)
                if lifecycle_response is not None:
                    return lifecycle_response

            if g.business:
                itype       = g.business["industry_type"] or "retail_other"
                sidebar_key = get_sidebar_key(itype)
                common      = SIDEBAR_CONFIG.get("_common", [])
                dynamic     = SIDEBAR_CONFIG.get(sidebar_key, SIDEBAR_CONFIG.get("retail", []))
                all_items   = common + dynamic

                has_all  = bool(g.user_perms.get("all"))
                filtered = []
                for item in all_items:
                    perm_needed = SIDEBAR_PERM.get(item["key"])
                    if perm_needed is None or has_all or g.user_perms.get(perm_needed):
                        filtered.append(item)

                settings_item = [x for x in filtered if x["key"] == "settings"]
                rest_items    = [x for x in filtered if x["key"] != "settings"]
                g.sidebar_items = rest_items + settings_item

                # ── تطبيق تخصيصات القائمة الجانبية من لوحة المالك ──────────
                try:
                    overrides_rows = db.execute(
                        "SELECT item_key, is_enabled FROM platform_sidebar_overrides WHERE sector_key=?",
                        (sidebar_key,)
                    ).fetchall()
                    if overrides_rows:
                        overrides = {r[0] if not isinstance(r, dict) else r["item_key"]:
                                     (r[1] if not isinstance(r, dict) else r["is_enabled"])
                                     for r in overrides_rows}
                        g.sidebar_items = [item for item in g.sidebar_items
                                           if overrides.get(item["key"], 1)]
                except Exception:
                    pass  # الجدول غير موجود بعد — تجاهل

            # ── بروفايل الدولة (عملة + ضريبة) ──────────────────────────
            try:
                from modules.country_engine import get_business_country
                g.country_profile = get_business_country(db, int(biz_id))
            except Exception:
                g.country_profile = None

        # ── حماية المسارات حسب نوع النشاط ─────────────────────────────────
        if g.business and not g.user_perms.get("all"):
            from .config import INDUSTRY_ROUTE_GUARDS
            path = request.path or ""
            if not path.startswith(("/static", "/api", "/auth", "/healthz", "/readyz")):
                itype = g.business.get("industry_type") or ""
                itype_sidebar = get_sidebar_key(itype)
                for prefix, allowed_set in INDUSTRY_ROUTE_GUARDS.items():
                    if path.startswith(prefix):
                        allowed = allowed_set or set()
                        if itype not in allowed and itype_sidebar not in allowed:
                            flash("هذا القسم غير متاح لنشاطك التجاري", "error")
                            return redirect(url_for("core.dashboard"))
                        break


def platform_guard():
    """حماية أساسية: request id + rate limit بسيط على مستوى التطبيق."""
    g.request_id = request.headers.get("X-Request-ID") or secrets.token_hex(12)
    g._inflight_acquired = False

    path = request.path or ""
    if path.startswith("/static") or path == "/sw.js":
        return None

    # استثناءات صحة المنصة والصفحة الهابطة
    if path in ("/healthz", "/readyz", "/offline"):
        return None

    # حماية من التشبع: إذا امتلأت سعة الطلبات المتزامنة نرجع 503 سريعاً.
    acquired = _inflight_semaphore.acquire(blocking=False)
    if not acquired:
        resp = jsonify({
            "success": False,
            "error": "service_overloaded",
            "message": "الخدمة تحت ضغط مرتفع، حاول بعد قليل",
            "request_id": g.request_id,
        })
        resp.status_code = 503
        resp.headers["Retry-After"] = str(max(1, OVERLOAD_RETRY_AFTER_SEC))
        return resp
    g._inflight_acquired = True

    # Force Update Gate: إغلاق إجباري للنسخ القديمة لتطبيق المندوب
    if path.startswith(("/api/v1/agents", "/api/v2/agents")):
        try:
            db = get_db()
            biz_id = session.get("business_id") or session.get("agent_biz_id")
            if not biz_id:
                hdr_biz = request.headers.get("X-Business-ID")
                if hdr_biz and str(hdr_biz).isdigit():
                    biz_id = int(hdr_biz)

            from .security_hardening import enforce_agent_app_version
            app_version = request.headers.get("X-App-Version") or request.headers.get("App-Version")
            ok, policy = enforce_agent_app_version(db, int(biz_id) if biz_id else None, app_version)
            if not ok:
                return jsonify({
                    "success": False,
                    "error": "force_update_required",
                    "message": "يرجى تحديث التطبيق قبل المتابعة",
                    "policy": policy,
                    "request_id": g.request_id,
                }), 426
        except Exception:
            # لا نعطل المنصة بالكامل في حال خطأ عارض هنا
            pass

    key = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or "unknown"

    # استثناء localhost من Rate Limiting (تطوير واختبارات)
    if key in ("127.0.0.1", "::1", "localhost"):
        return None

    now = monotonic()

    # Rate limit موزع (Redis) عند تفعيله
    if should_use_distributed_rate_limit():
        allowed, current_count, backend = check_rate_limit_distributed(key)
        if not allowed:
            return jsonify({
                "success": False,
                "error": "too_many_requests",
                "message": "تم تجاوز حد الطلبات المؤقت",
                "backend": backend,
                "current_count": current_count,
                "request_id": g.request_id,
            }), 429
        return None

    with _rate_lock:
        q = _rate_limit_state.get(key)
        if q is None:
            q = deque()
            _rate_limit_state[key] = q

        cutoff = now - RATE_LIMIT_WINDOW_SEC
        while q and q[0] < cutoff:
            q.popleft()

        if len(q) >= RATE_LIMIT_MAX_REQUEST:
            return jsonify({
                "success": False,
                "error": "too_many_requests",
                "message": "تم تجاوز حد الطلبات المؤقت",
                "request_id": g.request_id,
            }), 429

        q.append(now)
    return None


def inject_globals():
    """Context processor: يُضاف لكل القوالب"""
    from .config import INDUSTRY_TYPES
    lang = getattr(g, "lang", DEFAULT_LANGUAGE)

    # ── إعدادات المنصة الديناميكية ──────────────────────────────────────────
    platform_name       = "Jinan Biz"
    platform_logo_url   = ""
    platform_announcement = ""
    platform_tagline    = ""
    try:
        from .db_adapter import get_db_adapter
        _db = get_db_adapter()
        # إنشاء جدول platform_settings إن لم يوجد
        _db.execute("""
            CREATE TABLE IF NOT EXISTS platform_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                setting_key TEXT UNIQUE NOT NULL,
                setting_value TEXT,
                updated_at DATETIME DEFAULT (datetime('now'))
            )
        """)
        if hasattr(_db, 'commit'):
            _db.commit()
        def _get_ps(key, default=""):
            cur = _db.execute(
                "SELECT setting_value FROM platform_settings WHERE setting_key=?", (key,)
            )
            row = cur.fetchone() if cur is not None else None
            if row:
                v = row[0] if not isinstance(row, dict) else row.get("setting_value", "")
                return v or default
            return default
        platform_name         = _get_ps("platform_name", "Jinan Biz")
        platform_logo_url     = _get_ps("platform_logo_url", "")
        platform_announcement = _get_ps("platform_announcement", "")
        platform_tagline      = _get_ps("platform_tagline", "")
    except Exception:
        pass

    # ── إعدادات UX المخصصة ─────────────────────────────────────────────────
    ux_login_bg_url    = ""
    ux_register_bg_url = ""
    ux_custom_css      = ""
    ux_font_family     = ""
    try:
        from .db_adapter import get_db_adapter as _gda
        _db2 = _gda()
        def _ux(k):
            cur = _db2.execute("SELECT setting_value FROM platform_settings WHERE setting_key=?", (k,))
            r = cur.fetchone() if cur is not None else None
            return (r[0] if r and not isinstance(r, dict) else (r.get("setting_value","") if r else "")) or ""
        ux_login_bg_url    = _ux("ux_login_bg_url")
        ux_register_bg_url = _ux("ux_register_bg_url")
        ux_custom_css      = _ux("ux_custom_css")
        ux_font_family     = _ux("ux_font_family")
    except Exception:
        pass

    return {
        "current_user":         g.user,
        "current_business":     g.business,
        "sidebar_items":        g.sidebar_items,
        "user_perms":           g.user_perms,
        "industry_types":       INDUSTRY_TYPES,
        "request":              request,
        "now_date":             datetime.now().strftime("%Y-%m-%d"),
        "csrf_token":           generate_csrf_token(),
        "user_has_perm":        user_has_perm,
        "country_profile":      g.country_profile,
        "lang":                 lang,
        "is_rtl":               lang == "ar",
        "text_dir":             "rtl" if lang == "ar" else "ltr",
        # محتوى المنصة الديناميكي
        "platform_name":        platform_name,
        "platform_logo_url":    platform_logo_url,
        "platform_announcement":platform_announcement,
        "platform_tagline":     platform_tagline,
        # UX مخصص
        "ux_login_bg_url":      ux_login_bg_url,
        "ux_register_bg_url":   ux_register_bg_url,
        "ux_custom_css":        ux_custom_css,
        "ux_font_family":       ux_font_family,
    }


def enforce_global_csrf():
    """
    حماية CSRF عالمية: تُطبَّق تلقائياً على جميع طلبات POST غير-API.
    استثناءات:
      - طلبات JSON (Content-Type: application/json) — تحمي CORS عوضاً
      - مسارات /auth/** — تتضمن CSRF token في الـ form مباشرة
      - مسارات /api/** — مؤمنة بـ API key + session
      - Webhooks خارجية — محددة صراحةً
    """
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return None

    path = request.path or ""

    # استثنِ الـ static files وصحة المنصة
    if path.startswith("/static") or path in ("/healthz", "/readyz", "/sw.js"):
        return None

    # استثنِ JSON API (محمية بـ CORS + session)
    if request.is_json:
        return None

    # استثنِ مسارات /auth/** — تتضمن CSRF token في الـ form مباشرة وتتحقق منه داخلياً
    if path.startswith("/auth/"):
        return None

    # استثنِ مسارات /api/** — مؤمنة بـ API key + session
    if path.startswith("/api/"):
        return None

    # استثنِ Webhooks المُعلنة صراحةً
    webhook_prefixes = ("/api/v1/webhook", "/api/webhook")
    if any(path.startswith(p) for p in webhook_prefixes):
        return None

    # تحقق من CSRF token
    from .extensions import validate_csrf
    if not validate_csrf():
        # طلب من مستخدم مُسجَّل دخول: أعد توجيهه مع رسالة خطأ
        if session.get("user_id"):
            from flask import flash, redirect
            flash("انتهت صلاحية الجلسة، يرجى المحاولة مجدداً", "error")
            return redirect(request.referrer or "/")
        # طلب غير مُصادق: أعد خطأ JSON
        return jsonify({
            "success": False,
            "error":   "csrf_invalid",
            "message": "CSRF token مفقود أو غير صالح",
        }), 403
    return None


def add_security_headers(response):
    """Security Headers على كل استجابة"""
    response.headers["X-Frame-Options"]        = "SAMEORIGIN"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"]       = "0"
    response.headers["Referrer-Policy"]        = "strict-origin-when-cross-origin"
    response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    response.headers["Origin-Agent-Cluster"] = "?1"

    if CSP_MODE == "strict":
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "base-uri 'self'; "
            "object-src 'none'; "
            "frame-ancestors 'self'; "
            "form-action 'self'; "
            "script-src 'self' cdn.jsdelivr.net unpkg.com; "
            "style-src 'self' cdn.jsdelivr.net fonts.googleapis.com; "
            "font-src 'self' fonts.gstatic.com cdn.jsdelivr.net data:; "
            "img-src 'self' data: blob:; "
            "connect-src 'self';"
        )
    else:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "base-uri 'self'; "
            "object-src 'none'; "
            "frame-ancestors 'self'; "
            "form-action 'self'; "
            "script-src 'self' 'unsafe-inline' cdn.jsdelivr.net unpkg.com; "
            "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net fonts.googleapis.com; "
            "font-src 'self' fonts.gstatic.com cdn.jsdelivr.net data:; "
            "img-src 'self' data: blob:; "
            "connect-src 'self';"
        )

    if request.is_secure or (IS_PROD and request.headers.get("X-Forwarded-Proto", "").lower() == "https"):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
    response.headers["X-Request-ID"] = getattr(g, "request_id", "")

    # تحرير slot الطلب المتزامن بعد إنهاء المعالجة.
    if getattr(g, "_inflight_acquired", False):
        try:
            _inflight_semaphore.release()
        except Exception:
            pass
        g._inflight_acquired = False

    return response
