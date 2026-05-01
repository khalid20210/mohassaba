"""
modules/middleware.py — RBAC، ديكوراتورات الحماية، before/after request
"""
import json
from datetime import datetime
from functools import wraps

from flask import g, redirect, session, url_for, flash, request

from .config import SIDEBAR_CONFIG, SIDEBAR_PERM, get_sidebar_key
from .extensions import get_db, generate_csrf_token


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
        return f(*args, **kwargs)
    return decorated


def onboarding_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.auth_login"))
        if not session.get("business_id"):
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
        try:
            perms = json.loads(g.user["permissions"] or "{}") if g.user else {}
        except Exception:
            perms = {}
        if not perms.get("all"):
            flash("هذه الصفحة مخصصة للمالك فقط", "error")
            return redirect(url_for("core.dashboard"))
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
    g.user         = None
    g.business     = None
    g.sidebar_items= []
    g.user_perms   = {}

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


def inject_globals():
    """Context processor: يُضاف لكل القوالب"""
    from .config import INDUSTRY_TYPES
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
    }


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
        "font-src 'self' fonts.gstatic.com data:; "
        "img-src 'self' data: blob:; "
        "connect-src 'self';"
    )
    return response
