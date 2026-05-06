"""
modules/middleware.py — RBAC، ديكوراتورات الحماية، before/after request
"""
import json
import secrets
from collections import deque
from datetime import datetime
from functools import wraps
from threading import Lock
from time import monotonic

from flask import g, redirect, session, url_for, flash, request, jsonify

from .config import SIDEBAR_CONFIG, SIDEBAR_PERM, get_sidebar_key
from .extensions import get_db, generate_csrf_token
from .config import RATE_LIMIT_WINDOW_SEC, RATE_LIMIT_MAX_REQUEST
from .runtime_services import (
    should_use_distributed_rate_limit,
    check_rate_limit_distributed,
)
from .i18n import SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE


_rate_limit_state: dict[str, deque] = {}
_rate_lock = Lock()


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
    """ديكوراتور: يسمح فقط لـ الأدمن (role = 'admin')"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.auth_login"))
        
        if not g.user or g.user.get("role") != "admin":
            flash("هذه الصفحة مخصصة للأدمن فقط", "error")
            if "user_id" in session:
                return redirect(url_for("core.dashboard"))
            else:
                return redirect(url_for("auth.auth_login"))
        
        return f(*args, **kwargs)
    return decorated


def write_audit_log(db, business_id: int, action: str,
                    entity_type: str = None, entity_id: int = None,
                    old_value: str = None, new_value: str = None):
    """تسجيل حدث في جدول audit_logs"""
    try:
        user_id    = session.get("user_id")
        actor_name = ""
        actor_role = ""
        if g.user:
            actor_name = g.user["full_name"] or g.user.get("username", "")
            actor_role = g.user.get("role_name", "")
        ip_address = request.remote_addr or ""
        user_agent = (request.user_agent.string or "")[:255]
        db.execute(
            """INSERT INTO audit_logs
                   (business_id, user_id, actor_name, actor_role, action,
                    entity_type, entity_id, old_value, new_value, ip_address, user_agent)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (business_id, user_id, actor_name, actor_role, action,
             entity_type, entity_id, old_value, new_value, ip_address, user_agent)
        )
        db.commit()
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
                        if itype not in allowed_set and itype_sidebar not in allowed_set:
                            flash("هذا القسم غير متاح لنشاطك التجاري", "error")
                            return redirect(url_for("core.dashboard"))
                        break


def platform_guard():
    """حماية أساسية: request id + rate limit بسيط على مستوى التطبيق."""
    g.request_id = request.headers.get("X-Request-ID") or secrets.token_hex(12)

    path = request.path or ""
    if path.startswith("/static") or path == "/sw.js":
        return None

    # استثناءات صحة المنصة والصفحة الهابطة
    if path in ("/healthz", "/readyz", "/offline"):
        return None

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
    return {
        "current_user":     g.user,
        "current_business": g.business,
        "sidebar_items":    g.sidebar_items,
        "user_perms":       g.user_perms,
        "industry_types":   INDUSTRY_TYPES,
        "request":          request,
        "now_date":         datetime.now().strftime("%Y-%m-%d"),
        "csrf_token":       generate_csrf_token(),
        "user_has_perm":    user_has_perm,
        "country_profile":  g.country_profile,
        "lang":             lang,
        "is_rtl":           lang == "ar",
        "text_dir":         "rtl" if lang == "ar" else "ltr",
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
    response.headers["X-XSS-Protection"]       = "1; mode=block"
    response.headers["Referrer-Policy"]        = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' cdn.jsdelivr.net unpkg.com; "
        "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net fonts.googleapis.com; "
        "font-src 'self' fonts.gstatic.com cdn.jsdelivr.net data:; "
        "img-src 'self' data: blob:; "
        "connect-src 'self';"
    )
    if request.is_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Request-ID"] = getattr(g, "request_id", "")
    return response
