"""
modules/middleware.py — RBAC، ديكوراتورات الحماية، before/after request
"""
import json
from datetime import datetime
from functools import wraps

from flask import g, redirect, session, url_for, flash, request

from .config import INDUSTRY_TYPES, SIDEBAR_CONFIG, SIDEBAR_PERM, get_sidebar_key
from .extensions import get_db, generate_csrf_token

_UI_TEXT = {
    "app_name": {"ar": "محاسبة", "en": "Mohassaba"},
    "app_subtitle": {"ar": "نظام المحاسبة", "en": "Accounting System"},
    "default_role": {"ar": "مستخدم", "en": "User"},
    "logout": {"ar": "تسجيل الخروج", "en": "Logout"},
    "menu": {"ar": "القائمة", "en": "Menu"},
    "offline_banner": {
        "ar": "📡 أنت حاليًا بدون اتصال — بعض الميزات غير متاحة",
        "en": "📡 You are offline — some features are unavailable",
    },
    "update_prompt": {
        "ar": "🔄 يوجد تحديث جديد — هل تريد تطبيقه؟",
        "en": "🔄 A new update is available — apply it now?",
    },
    "language_toggle": {"ar": "EN", "en": "ع"},
}

_SIDEBAR_LABELS_EN = {
    "dashboard": "Dashboard",
    "analytics": "Analytics",
    "contacts": "Contacts",
    "accounting": "Accounting",
    "purchase-import": "Import Invoice",
    "reports": "Reports",
    "settings": "Settings",
    "pos": "Point of Sale",
    "inventory": "Inventory",
    "purchases": "Purchases",
    "barcode": "Barcodes",
    "invoices": "Invoices",
    "kitchen": "Kitchen",
    "tables": "Tables",
    "recipes": "Recipes",
    "pricing": "Pricing",
    "projects": "Projects",
    "extracts": "Extracts",
    "equipment": "Equipment",
    "fleet": "Fleet",
    "contracts": "Contracts",
    "maintenance": "Maintenance",
    "patients": "Patients",
    "appointments": "Appointments",
    "prescriptions": "Prescriptions",
    "jobs": "Jobs",
}

_ROLE_LABELS_EN = {
    "مدير": "Owner",
    "مدير فرع": "Branch Manager",
    "كاشير": "Cashier",
    "محاسب": "Accountant",
    "أمين مخزن": "Storekeeper",
}


def _get_lang() -> str:
    lang = (request.args.get("lang") or session.get("lang") or "ar").strip().lower()
    if lang not in {"ar", "en"}:
        lang = "ar"
    session["lang"] = lang
    return lang


def _t(key: str, lang: str) -> str:
    return _UI_TEXT.get(key, {}).get(lang) or _UI_TEXT.get(key, {}).get("ar") or key


def _industry_label(industry_type: str, lang: str) -> str:
    if lang == "ar":
        for k, v in INDUSTRY_TYPES:
            if k == industry_type:
                return v
    return industry_type.replace("_", " ").replace("-", " ").title()


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


# ─── Hooks: before_request و after_request ────────────────────────────────────

def load_user():
    """حقن بيانات المستخدم والمنشأة في g قبل كل request"""
    import logging
    lang = _get_lang()
    g.user         = None
    g.business     = None
    g.sidebar_items= []
    g.user_perms   = {}
    g.lang         = lang
    g.dir          = "rtl" if lang == "ar" else "ltr"

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

                localized = []
                for item in filtered:
                    row = dict(item)
                    if lang == "en":
                        row["label"] = _SIDEBAR_LABELS_EN.get(item["key"], item["label"])
                    localized.append(row)

                settings_item = [x for x in localized if x["key"] == "settings"]
                rest_items    = [x for x in localized if x["key"] != "settings"]
                g.sidebar_items = rest_items + settings_item


def inject_globals():
    """Context processor: يُضاف لكل القوالب"""
    lang = getattr(g, "lang", "ar")
    role_name = ""
    if g.user:
        role_name = g.user["role_name"] or _t("default_role", lang)
        if lang == "en":
            role_name = _ROLE_LABELS_EN.get(role_name, role_name)

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
        "current_lang":     lang,
        "current_dir":      getattr(g, "dir", "rtl"),
        "ui_text":          {k: _t(k, lang) for k in _UI_TEXT},
        "current_role_label": role_name,
        "current_industry_label": _industry_label(
            g.business["industry_type"] if g.business else "", lang
        ) if g.business else "",
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
