"""
blueprints/auth/routes.py — المصادقة: تسجيل دخول، تسجيل، استعادة كلمة المرور
"""
import os
import re
import secrets
from datetime import datetime

from flask import (
    Blueprint, current_app, flash, g, jsonify, redirect, render_template,
    request, session, url_for
)
from authlib.integrations.flask_client import OAuth

from modules.config import INDUSTRY_TYPES, _load_secret_key
from modules.extensions import (
    check_password, csrf_protect, get_db, hash_password, seed_business_accounts, safe_sql_identifier
)
from modules.middleware import write_audit_log
from modules.terminology import get_terms
from modules.unit_localization import ensure_unit_localization_defaults

bp = Blueprint("auth", __name__)

# متغير Rate Limiting (يُشارك عبر الـ import)
_login_attempts: dict = {}
_MAX_ATTEMPTS    = 10
_WINDOW_SECONDS  = 300

_SOCIAL_PROVIDER_LABELS = {
    "google": "Google",
    "apple": "Apple",
    "microsoft": "Microsoft",
}


def _oauth_redirect_uri(provider: str) -> str:
    """يبني Callback URI ثابتاً عبر PUBLIC_BASE_URL عند التشغيل عبر الإنترنت."""
    provider = (provider or "").strip().lower()
    path = f"/auth/social/{provider}/callback"
    public_base = (os.environ.get("PUBLIC_BASE_URL", "") or "").strip().rstrip("/")
    if public_base:
        return f"{public_base}{path}"
    return url_for("auth.auth_social_callback", provider=provider, _external=True)


def _get_oauth_client(provider: str):
    """بناء عميل OAuth ديناميكياً اعتماداً على متغيرات البيئة."""
    provider = (provider or "").strip().lower()
    if provider not in _SOCIAL_PROVIDER_LABELS:
        return None, None

    client_id = os.environ.get(f"{provider.upper()}_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.environ.get(f"{provider.upper()}_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None, None

    if provider == "google":
        settings = {
            "client_id": client_id,
            "client_secret": client_secret,
            "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
            "client_kwargs": {"scope": "openid email profile"},
        }
    elif provider == "microsoft":
        tenant = os.environ.get("MICROSOFT_OAUTH_TENANT", "common").strip() or "common"
        settings = {
            "client_id": client_id,
            "client_secret": client_secret,
            "server_metadata_url": f"https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration",
            "client_kwargs": {"scope": "openid profile email User.Read"},
        }
    else:  # Apple
        settings = {
            "client_id": client_id,
            "client_secret": client_secret,
            "authorize_url": "https://appleid.apple.com/auth/authorize",
            "access_token_url": "https://appleid.apple.com/auth/token",
            "jwks_uri": "https://appleid.apple.com/auth/keys",
            "client_kwargs": {"scope": "name email", "response_mode": "form_post"},
        }

    oauth = current_app.extensions.get("oauth_client")
    if oauth is None:
        oauth = OAuth(current_app)
        current_app.extensions["oauth_client"] = oauth

    client_name = f"social_{provider}"
    client = oauth.create_client(client_name)
    if client is None:
        oauth.register(name=client_name, **settings)
        client = oauth.create_client(client_name)

    return client, settings


def _build_unique_username(db, seed_text: str) -> str:
    base = re.sub(r"[^a-z0-9_]", "", (seed_text or "").lower().replace(" ", "_"))
    if not base:
        base = "user"
    if base[0].isdigit():
        base = f"u_{base}"
    base = base[:20]

    candidate = base
    i = 1
    while db.execute("SELECT 1 FROM users WHERE username = ?", (candidate,)).fetchone():
        i += 1
        candidate = f"{base[:16]}_{i}"
    return candidate


def _complete_login_session(db, user_id: int, biz_id_val: int):
    """توحيد منطق إنشاء الجلسة بعد أي نوع تسجيل دخول."""
    session.clear()
    session["user_id"] = user_id
    session["business_id"] = biz_id_val
    session.permanent = True

    db.execute("UPDATE users SET last_login=datetime('now') WHERE id=?", (user_id,))
    db.commit()

    onboarding_row = db.execute(
        "SELECT value FROM settings WHERE business_id=? AND key='onboarding_complete' LIMIT 1",
        (biz_id_val,),
    ).fetchone()
    needs_onboarding = not (onboarding_row and str(onboarding_row["value"]) == "1")
    session["needs_onboarding"] = bool(needs_onboarding)

    write_audit_log(db, biz_id_val, "login", entity_type="user", entity_id=user_id)
    if needs_onboarding:
        flash(
            "نتمنى منك اختيار نشاطك التجاري لنقوم بتهيئة البرنامج بما يتناسب مع تجارتك، لتبدأ العمل بسهولة واحترافية.",
            "info",
        )
        return redirect(url_for("core.onboarding"))
    return redirect(url_for("core.dashboard"))


def _social_signin_or_register(db, provider: str, social_sub: str, email: str, full_name: str):
    """تسجيل دخول اجتماعي: ربط بحساب موجود أو إنشاء حساب جديد."""
    provider = provider.lower().strip()
    email = (email or "").strip().lower()
    full_name = (full_name or "").strip() or _SOCIAL_PROVIDER_LABELS.get(provider, "مستخدم")

    linked_user = db.execute(
        "SELECT * FROM users WHERE social_provider=? AND social_sub=? AND is_active=1 LIMIT 1",
        (provider, social_sub),
    ).fetchone()
    if linked_user:
        return _complete_login_session(db, int(linked_user["id"]), int(linked_user["business_id"]))

    if email:
        existing = db.execute(
            "SELECT * FROM users WHERE LOWER(email)=LOWER(?) AND is_active=1 LIMIT 1",
            (email,),
        ).fetchone()
        if existing:
            db.execute(
                """
                UPDATE users
                SET social_provider=?, social_sub=?, email_verified=1,
                    full_name=COALESCE(NULLIF(full_name,''), ?)
                WHERE id=?
                """,
                (provider, social_sub, full_name, existing["id"]),
            )
            db.commit()
            flash("تم ربط حسابك الاجتماعي بالحساب الحالي بنجاح", "success")
            return _complete_login_session(db, int(existing["id"]), int(existing["business_id"]))

    username_seed = email.split("@")[0] if email else full_name
    username = _build_unique_username(db, username_seed)

    try:
        db.execute(
            "INSERT INTO businesses (name, is_active, country_code) VALUES (?, 0, ?)",
            (f"منشأة {username}", "SA"),
        )
        biz_id = int(db.execute("SELECT last_insert_rowid()").fetchone()[0])

        db.execute(
            "INSERT INTO roles (business_id, name, permissions, is_system) VALUES (?,?,?,1)",
            (biz_id, "مدير", '{"all":true}'),
        )
        role_id = int(db.execute("SELECT last_insert_rowid()").fetchone()[0])

        random_pass = hash_password(secrets.token_urlsafe(32))
        db.execute(
            """
            INSERT INTO users
            (business_id, role_id, username, full_name, email, password_hash,
             social_provider, social_sub, email_verified)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (biz_id, role_id, username, full_name, email, random_pass, provider, social_sub, 1 if email else 0),
        )
        user_id = int(db.execute("SELECT last_insert_rowid()").fetchone()[0])
        db.commit()
    except Exception:
        db.rollback()
        flash("تعذر إنشاء الحساب عبر المزود الاجتماعي، حاول مرة أخرى", "error")
        return redirect(url_for("auth.auth_login"))

    try:
        ensure_unit_localization_defaults(db, biz_id, country_code="SA")
        db.commit()
    except Exception:
        pass

    write_audit_log(db, biz_id, "register", entity_type="user", entity_id=user_id)
    flash("تم إنشاء حسابك عبر الدخول الاجتماعي بنجاح", "success")
    return _complete_login_session(db, user_id, biz_id)


@bp.route("/")
def index():
    if session.get("user_id") and session.get("business_id"):
        return redirect(url_for("core.dashboard"))
    return redirect(url_for("auth.auth_register"))


@bp.route("/auth/landing-metrics")
def auth_landing_metrics():
    """مؤشرات حقيقية لصفحة الدخول (بدون بيانات حساسة)."""
    db = get_db()

    def _column_exists(table: str, column: str) -> bool:
        try:
            safe_table = safe_sql_identifier(table)
            rows = db.execute(f"PRAGMA table_info({safe_table})").fetchall()
            return any(r[1] == column for r in rows)
        except Exception:
            return False

    def _scalar(sql: str, params=(), default=0):
        try:
            row = db.execute(sql, params).fetchone()
            if not row:
                return default
            val = row[0]
            return default if val is None else val
        except Exception:
            return default

    total_invoices = int(_scalar("SELECT COUNT(*) FROM invoices", default=0))
    paid_invoices = int(_scalar("SELECT COUNT(*) FROM invoices WHERE status='paid'", default=0))
    total_products = int(_scalar("SELECT COUNT(*) FROM products WHERE is_active=1", default=0))

    # ─── إحصائيات المنتجات حسب نوع الصناعة ─────────────────────────────────
    industry_stats: dict = {}
    try:
        rows = db.execute("""
            SELECT b.industry_type,
                   COUNT(p.id)          AS prod_cnt,
                   COUNT(DISTINCT b.id) AS biz_cnt
            FROM businesses b
            JOIN products p ON p.business_id = b.id AND p.is_active = 1
            WHERE b.is_active = 1
            GROUP BY b.industry_type
        """).fetchall()
        for r in rows:
            industry_stats[r[0]] = {"prods": r[1], "bizs": r[2]}
    except Exception:
        pass

    # عدد المنشآت الفعلية (التي تحتوي على منتجات — تستثني المنشآت الفارغة)
    total_businesses = int(_scalar("""
        SELECT COUNT(DISTINCT b.id) FROM businesses b
        JOIN products p ON p.business_id = b.id AND p.is_active = 1
        WHERE b.is_active = 1
    """, default=0))
    total_users = int(_scalar("SELECT COUNT(*) FROM users WHERE is_active=1", default=0))
    total_contacts = int(_scalar("SELECT COUNT(*) FROM contacts", default=0))
    new_customers_30 = int(_scalar(
        "SELECT COUNT(*) FROM contacts WHERE contact_type='customer' AND DATE(created_at) >= DATE('now','-30 days')",
        default=0,
    ))
    table_orders_30 = int(_scalar(
        "SELECT COUNT(*) FROM invoices WHERE invoice_type='table' AND status='paid' AND DATE(created_at) >= DATE('now','-30 days')",
        default=0,
    ))
    wholesale_clients = int(_scalar(
        "SELECT COUNT(DISTINCT party_name) FROM invoices WHERE invoice_type='sale' AND status='paid' AND party_name IS NOT NULL AND TRIM(party_name) <> ''",
        default=0,
    ))
    open_orders = int(_scalar(
        "SELECT COUNT(*) FROM invoices WHERE status IN ('draft','pending')",
        default=0,
    ))
    expiring_products = 0
    if _column_exists("products", "expiry_date"):
        expiring_products = int(_scalar(
            "SELECT COUNT(*) FROM products WHERE is_active=1 AND expiry_date IS NOT NULL AND DATE(expiry_date) BETWEEN DATE('now') AND DATE('now','+30 days')",
            default=0,
        ))

    ocr_processed = int(_scalar("SELECT COUNT(*) FROM invoices WHERE invoice_type='purchase'", default=0))
    fashion_top_qty = int(_scalar("""
        SELECT COALESCE(SUM(il.quantity), 0)
        FROM invoice_lines il
        JOIN invoices i ON i.id = il.invoice_id
        WHERE i.invoice_type IN ('sale','table')
          AND i.status='paid'
          AND DATE(i.created_at) >= DATE('now','-30 days')
    """, default=0))
    fashion_margin = float(_scalar("""
        SELECT COALESCE(ROUND(AVG(
            CASE WHEN sale_price > 0 THEN ((sale_price - purchase_price) / sale_price) * 100 ELSE 0 END
        ), 1), 0)
        FROM products WHERE is_active=1
    """, default=0))
    construction_open_debt = float(_scalar("""
        SELECT COALESCE(ROUND(SUM(total),2),0)
        FROM invoices
        WHERE invoice_type='sale' AND status IN ('draft','pending')
    """, default=0))
    construction_open_projects = int(_scalar("""
        SELECT COUNT(*)
        FROM invoices
        WHERE invoice_type='sale' AND status IN ('draft','pending')
    """, default=0))

    ai_accuracy = round((paid_invoices / total_invoices) * 100, 1) if total_invoices > 0 else 99.9

    accent_map = {
        "standard": {"from": "#dbeafe", "to": "#ecfeff", "border": "#bfdbfe", "text": "#0b3a63"},
        "restaurant": {"from": "#fef3c7", "to": "#fffbeb", "border": "#fde68a", "text": "#92400e"},
        "pharmacy": {"from": "#dcfce7", "to": "#ecfdf5", "border": "#86efac", "text": "#166534"},
        "fashion": {"from": "#fce7f3", "to": "#fff1f2", "border": "#f9a8d4", "text": "#9d174d"},
        "wholesale": {"from": "#ede9fe", "to": "#f5f3ff", "border": "#c4b5fd", "text": "#5b21b6"},
        "construction": {"from": "#ffedd5", "to": "#fff7ed", "border": "#fdba74", "text": "#9a3412"},
        "workshop": {"from": "#e0f2fe", "to": "#f8fafc", "border": "#7dd3fc", "text": "#075985"},
        "rental": {"from": "#ecfccb", "to": "#f7fee7", "border": "#bef264", "text": "#4d7c0f"},
        "medical": {"from": "#cffafe", "to": "#ecfeff", "border": "#67e8f9", "text": "#155e75"},
    }

    feature_map = {
        "standard": [
            "بيع سريع بالباركود مع تحديث المخزون فوراً",
            "استيراد فواتير المشتريات بـ OCR وExcel",
            "تنبيهات الصلاحية والحد الأدنى بشكل لحظي",
        ],
        "restaurant": [
            "إدارة الطاولات والطلبات وربط المطبخ في نفس المسار",
            "متابعة متوسط الطلب والأطباق الأعلى طلباً",
            "تجربة خدمة أسرع مع شاشة طلبات واضحة للفريق",
        ],
        "pharmacy": [
            "متابعة تاريخ الصلاحية والدفعات والتشغيلة",
            "بحث دوائي سريع بالاسم التجاري أو العلمي",
            "تقليل الهدر الدوائي بتنبيهات قرب الانتهاء",
        ],
        "fashion": [
            "مصفوفة مقاسات وألوان لكل موديل بصورة واضحة",
            "معرفة الموديلات الأعلى طلباً حسب الموسم",
            "حساب ربحية كل تشكيلة قبل إعادة الشراء",
        ],
        "wholesale": [
            "تسعير كميات وجملة بطريقة عملية ومرنة",
            "إدارة الموزعين والطلبيات الدورية بسهولة",
            "ربط المشتريات والمخزون مع حركة المبيعات",
        ],
        "construction": [
            "متابعة الديون والمشاريع والمستخلصات في شاشة واحدة",
            "تقارير Cash Flow مرتبطة بالفواتير المفتوحة",
            "تحكم أعلى في حدود العملاء والتحصيل المرحلي",
        ],
        "workshop": [
            "أوامر إصلاح ومتابعة الفني وقطع الغيار",
            "فصل إيراد الخدمة عن القطعة بشكل دقيق",
            "تتبع الأعمال المفتوحة وسرعة الإنجاز اليومية",
        ],
        "rental": [
            "إدارة العقود والفترات والحجوزات بسهولة",
            "تنبيهات تواريخ التسليم والاستحقاق تلقائياً",
            "ربط الأصل المؤجر بالفاتورة والعميل في نفس اللحظة",
        ],
        "medical": [
            "هيكلة أوضح للمريض والخدمة والزيارة",
            "تجهيز أسرع للفواتير والخدمات الطبية اليومية",
            "متابعة نشاط العيادة بإحصاءات تشغيلية مبسطة",
        ],
    }

    metric_map = {
        "standard": [
            {"label": "فواتير OCR المعالجة", "value": ocr_processed, "color": "teal"},
            {"label": "المنتجات النشطة", "value": total_products, "color": "primary"},
        ],
        "restaurant": [
            {"label": "طلبات طاولات 30 يوم", "value": table_orders_30, "color": "gold"},
            {"label": "العملاء الحاليون", "value": total_contacts, "color": "primary"},
        ],
        "pharmacy": [
            {"label": "منتجات قرب الانتهاء", "value": expiring_products, "color": "gold"},
            {"label": "أصناف دوائية نشطة", "value": total_products, "color": "teal"},
        ],
        "fashion": [
            {"label": "طلبات شهرية", "value": fashion_top_qty, "color": "primary"},
            {"label": "متوسط هامش الربح %", "value": round(fashion_margin, 1), "suffix": "%", "color": "gold"},
        ],
        "wholesale": [
            {"label": "موزعون نشطون", "value": wholesale_clients, "color": "primary"},
            {"label": "مشتريات OCR", "value": ocr_processed, "color": "teal"},
        ],
        "construction": [
            {"label": "الذمم المفتوحة", "value": construction_open_debt, "color": "gold"},
            {"label": "مشاريع نشطة", "value": construction_open_projects, "color": "primary"},
        ],
        "workshop": [
            {"label": "أوامر مفتوحة", "value": open_orders, "color": "gold"},
            {"label": "أصناف وخدمات", "value": total_products, "color": "primary"},
        ],
        "rental": [
            {"label": "عقود / أوامر مفتوحة", "value": open_orders, "color": "primary"},
            {"label": "عملاء جدد 30 يوم", "value": new_customers_30, "color": "teal"},
        ],
        "medical": [
            {"label": "مرضى / عملاء", "value": total_contacts, "color": "primary"},
            {"label": "زيارات / فواتير", "value": total_invoices, "color": "teal"},
        ],
    }

    showcase = []
    seen_keys = set()
    for industry_key, industry_label in INDUSTRY_TYPES:
        if industry_key in seen_keys:
            continue
        seen_keys.add(industry_key)

        terms    = get_terms(industry_key)
        pos_mode = terms.get("pos_mode", "standard")
        real_st  = industry_stats.get(industry_key, {})
        real_prods = int(real_st.get("prods", 0))
        real_bizs  = int(real_st.get("bizs",  0))

        # بناء الـ subheadline مع عدد الأصناف الحقيقية إذا وُجدت
        if real_prods > 0:
            sub = f"{real_prods:,} صنف مسجل • {terms.get('invoice', 'فاتورة')} + {terms.get('customer', 'عميل')} في تجربة واحدة."
        else:
            sub = f"{terms.get('product', 'منتج')} + {terms.get('invoice', 'فاتورة')} + {terms.get('customer', 'عميل')} ضمن تجربة تشغيل واحدة واضحة."

        showcase.append({
            "key":            industry_key,
            "title":          terms.get("industry_label", industry_label or "نشاط تجاري"),
            "icon":           terms.get("industry_icon", "🏪"),
            "pos_mode":       pos_mode,
            "headline":       terms.get("industry_label", industry_label or "نشاط تجاري"),
            "subheadline":    sub,
            "features":       feature_map.get(pos_mode, feature_map["standard"]),
            "metrics":        metric_map.get(pos_mode, metric_map["standard"]),
            "accent":         accent_map.get(pos_mode, accent_map["standard"]),
            "products_count": real_prods,
            "biz_count":      real_bizs,
        })

    return jsonify({
        "success": True,
        "global": {
            "total_invoices": total_invoices,
            "ai_accuracy": ai_accuracy,
            "profiles_count": len(showcase),
            "businesses_count": total_businesses,
            "users_count": total_users,
        },
        "showcase": showcase,
    })


@bp.route("/auth/login", methods=["GET", "POST"])
def auth_login():
    if session.get("user_id"):
        return redirect(url_for("core.dashboard"))

    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard

        # Rate Limiting
        ip  = request.remote_addr or "unknown"
        now = datetime.now().timestamp()
        _login_attempts.setdefault(ip, [])
        _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < _WINDOW_SECONDS]
        if len(_login_attempts[ip]) >= _MAX_ATTEMPTS:
            flash("تم تجاوز الحد المسموح به من المحاولات. حاول بعد 5 دقائق.", "error")
            return render_template("auth/login.html")

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("يرجى إدخال اسم المستخدم وكلمة المرور", "error")
            return render_template("auth/login.html")

        db   = get_db()
        user = db.execute(
            "SELECT u.*, b.account_status FROM users u "
            "JOIN businesses b ON b.id = u.business_id "
            "WHERE u.username = ?", (username,)
        ).fetchone()

        if not user or not check_password(user["password_hash"], password):
            _login_attempts[ip].append(now)
            flash("اسم المستخدم أو كلمة المرور غير صحيحة", "error")
            # تسجيل محاولة دخول فاشلة
            try:
                write_audit_log(db, 0, "login_failed",
                    entity_type="user", new_value=username[:50])
            except Exception:
                pass
            return render_template("auth/login.html")

        # ── فحص حالة الموافقة ────────────────────────────────────────────
        status = (user["account_status"] or "approved") if user else "approved"
        if status == "pending":
            return render_template("auth/pending_approval.html",
                                   username=username, full_name=user["full_name"])
        if status == "rejected":
            flash("تم رفض طلب تسجيلك. تواصل مع الإدارة لمزيد من المعلومات.", "error")
            try:
                from modules.blueprints.admin.routes import get_active_badges
                _badges = get_active_badges(db, on_login=True)
            except Exception:
                _badges = []
            return render_template("auth/login.html", marketing_badges=_badges)
        if not user["is_active"]:
            flash("هذا الحساب موقوف. تواصل مع الإدارة.", "error")
            try:
                from modules.blueprints.admin.routes import get_active_badges
                _badges = get_active_badges(db, on_login=True)
            except Exception:
                _badges = []
            return render_template("auth/login.html", marketing_badges=_badges)

        _login_attempts.pop(ip, None)
        return _complete_login_session(db, int(user["id"]), int(user["business_id"]))

    db = get_db()
    try:
        from modules.blueprints.admin.routes import get_active_badges
        badges = get_active_badges(db, on_login=True)
    except Exception:
        badges = []
    return render_template("auth/login.html", marketing_badges=badges)


@bp.route("/auth/register", methods=["GET", "POST"])
def auth_register():
    if session.get("user_id"):
        return redirect(url_for("core.dashboard"))

    # ── وضع التجربة: إغلاق التسجيل ──────────────────────────────────────
    if os.environ.get("REGISTRATION_CLOSED", "").lower() in ("1", "true", "yes"):
        return render_template("registration_closed.html"), 503

    if request.method == "POST":
        guard = csrf_protect()
        if guard:
            return guard

        username     = request.form.get("username",  "").strip()
        full_name    = request.form.get("full_name",  "").strip()
        email        = request.form.get("email",      "").strip().lower()
        password     = request.form.get("password",   "")
        confirm      = request.form.get("confirm_password", "")
        country_code = request.form.get("country_code", "SA").strip().upper() or "SA"

        errors = []
        if not username:        errors.append("اسم المستخدم مطلوب")
        if not full_name:       errors.append("الاسم الكامل مطلوب")
        if not password:        errors.append("كلمة المرور مطلوبة")
        if len(password) < 8:  errors.append("كلمة المرور يجب أن تكون 8 أحرف على الأقل")
        if password != confirm: errors.append("كلمتا المرور غير متطابقتين")

        if errors:
            for e in errors:
                flash(e, "error")
            db2 = get_db()
            from modules.country_engine import list_countries
            return render_template("auth/register.html",
                                   countries=list_countries(db2),
                                   selected_country=country_code)

        db = get_db()
        if db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
            flash("اسم المستخدم مستخدم بالفعل، جرّب اسماً آخر", "error")
            from modules.country_engine import list_countries
            return render_template("auth/register.html",
                                   countries=list_countries(db),
                                   selected_country=country_code)

        if email and db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
            flash("هذا البريد الإلكتروني مسجّل مسبقاً — سجّل الدخول أو استخدم بريداً آخر", "error")
            from modules.country_engine import list_countries
            return render_template("auth/register.html",
                                   countries=list_countries(db),
                                   selected_country=country_code)

        try:
            db.execute(
                "INSERT INTO businesses (name, is_active, country_code, account_status) VALUES (?, 0, ?, 'pending')",
                (f"منشأة {username}", country_code)
            )
            biz_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

            db.execute(
                "INSERT INTO roles (business_id, name, permissions, is_system) VALUES (?,?,?,1)",
                (biz_id, "مدير", '{"all":true}')
            )
            role_id = db.execute("SELECT last_insert_rowid()" ).fetchone()[0]

            db.execute(
                """INSERT INTO users
                   (business_id, role_id, username, full_name, email, password_hash, is_active)
                   VALUES (?,?,?,?,?,?,0)""",
                (biz_id, role_id, username, full_name, email, hash_password(password))
            )
            user_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.commit()
        except Exception:
            db.rollback()
            flash("حدث خطأ أثناء إنشاء الحساب — يرجى المحاولة مرة أخرى", "error")
            from modules.country_engine import list_countries
            return render_template("auth/register.html",
                                   countries=list_countries(get_db()),
                                   selected_country=country_code)

        # ضبط ضريبة افتراضية من بروفايل الدولة (tax_settings)
        try:
            from modules.country_engine import get_country
            cp = get_country(db, country_code)
            if cp and cp.get("default_tax_rate", 0) > 0:
                db.execute(
                    """INSERT OR IGNORE INTO tax_settings
                       (business_id, rate, tax_name, is_active)
                       VALUES (?, ?, ?, 1)""",
                    (biz_id, cp["default_tax_rate"],
                     cp.get("tax_label_ar", "ضريبة"))
                )

            # تهيئة سياسة الوحدات العالمية من لحظة إنشاء المنشأة.
            ensure_unit_localization_defaults(db, int(biz_id), country_code=country_code)
            db.commit()
        except Exception:
            pass  # الضريبة غير معيقة للتسجيل

        # ── لا دخول تلقائي — الحساب بانتظار موافقة المالك ─────────────────
        write_audit_log(db, biz_id, "register_pending", entity_type="user", entity_id=user_id)
        return render_template("auth/pending_approval.html",
                               username=username, full_name=full_name)

    # GET: جلب قائمة الدول للقالب
    try:
        from modules.country_engine import list_countries
        countries = list_countries(get_db())
    except Exception:
        countries = []
    try:
        from modules.blueprints.admin.routes import get_active_badges
        reg_badges = get_active_badges(get_db(), on_register=True)
    except Exception:
        reg_badges = []
    return render_template("auth/register.html", countries=countries, selected_country="SA",
                           marketing_badges=reg_badges)


@bp.route("/auth/social/<provider>")
def auth_social(provider):
    """بدء تسجيل الدخول عبر OAuth لمزود اجتماعي."""
    provider = (provider or "").strip().lower()
    provider_name = _SOCIAL_PROVIDER_LABELS.get(provider, provider.capitalize())

    if provider not in _SOCIAL_PROVIDER_LABELS:
        flash("مزود الدخول الاجتماعي غير مدعوم", "error")
        return redirect(url_for("auth.auth_login"))

    client, _settings = _get_oauth_client(provider)
    if client is None:
        flash(
            f"تسجيل الدخول عبر {provider_name} غير مفعّل بعد. أضف متغيرات {provider.upper()}_OAUTH_CLIENT_ID و {provider.upper()}_OAUTH_CLIENT_SECRET",
            "error",
        )
        return redirect(url_for("auth.auth_login"))

    session["oauth_provider"] = provider
    session["oauth_nonce"] = secrets.token_urlsafe(24)
    redirect_uri = _oauth_redirect_uri(provider)

    if provider == "apple":
        return client.authorize_redirect(redirect_uri, nonce=session["oauth_nonce"])
    return client.authorize_redirect(redirect_uri, nonce=session["oauth_nonce"])


@bp.route("/auth/social/<provider>/callback", methods=["GET", "POST"])
def auth_social_callback(provider):
    """استقبال callback من مزود OAuth وإتمام تسجيل الدخول/التسجيل."""
    provider = (provider or "").strip().lower()
    provider_name = _SOCIAL_PROVIDER_LABELS.get(provider, provider.capitalize())

    if provider not in _SOCIAL_PROVIDER_LABELS:
        flash("مزود الدخول الاجتماعي غير مدعوم", "error")
        return redirect(url_for("auth.auth_login"))

    if session.get("oauth_provider") != provider:
        flash("انتهت جلسة المصادقة الاجتماعية، حاول مجدداً", "error")
        return redirect(url_for("auth.auth_login"))

    client, _settings = _get_oauth_client(provider)
    if client is None:
        flash(f"تسجيل الدخول عبر {provider_name} غير مفعّل في إعدادات الخادم", "error")
        return redirect(url_for("auth.auth_login"))

    try:
        token = client.authorize_access_token()
    except Exception:
        flash(f"فشل تسجيل الدخول عبر {provider_name}", "error")
        return redirect(url_for("auth.auth_login"))

    userinfo = token.get("userinfo") or {}
    nonce = session.pop("oauth_nonce", None)
    session.pop("oauth_provider", None)

    if not userinfo and token.get("id_token"):
        try:
            parsed = client.parse_id_token(token, nonce=nonce)
            if parsed:
                userinfo = dict(parsed)
        except Exception:
            userinfo = {}

    if not userinfo and provider != "apple":
        try:
            profile = client.get("userinfo")
            if profile.ok:
                userinfo = profile.json()
        except Exception:
            pass

    social_sub = str(userinfo.get("sub") or userinfo.get("id") or "").strip()
    email = str(userinfo.get("email") or "").strip().lower()
    name = (
        str(userinfo.get("name") or "").strip()
        or " ".join(
            [
                str(userinfo.get("given_name") or "").strip(),
                str(userinfo.get("family_name") or "").strip(),
            ]
        ).strip()
    )

    if not social_sub:
        flash(f"لم نتمكن من قراءة هوية المستخدم من {provider_name}", "error")
        return redirect(url_for("auth.auth_login"))

    db = get_db()
    return _social_signin_or_register(db, provider, social_sub, email, name)


@bp.route("/auth/forgot-password", methods=["GET", "POST"])
def auth_forgot_password():
    if session.get("user_id"):
        return redirect(url_for("core.dashboard"))

    step = request.form.get("step", "1")

    if request.method == "POST":
        db = get_db()

        if step == "1":
            username = request.form.get("username", "").strip()
            email    = request.form.get("email",    "").strip().lower()

            if not username or not email:
                flash("يرجى إدخال اسم المستخدم والبريد الإلكتروني", "error")
                return render_template("auth/forgot_password.html", step=1)

            user = db.execute(
                "SELECT id FROM users WHERE username=? AND LOWER(email)=? AND is_active=1",
                (username, email)
            ).fetchone()
            if not user:
                flash("لم يتم العثور على حساب بهذه البيانات", "error")
                return render_template("auth/forgot_password.html", step=1)

            session["reset_uid"] = user["id"]
            return render_template("auth/forgot_password.html", step=2)

        elif step == "2":
            uid      = session.pop("reset_uid", None)
            new_pass = request.form.get("new_password",     "")
            confirm  = request.form.get("confirm_password", "")

            if not uid:
                flash("انتهت صلاحية الجلسة، يرجى المحاولة مجدداً", "error")
                return redirect(url_for("auth.auth_forgot_password"))

            if len(new_pass) < 8:
                session["reset_uid"] = uid
                flash("كلمة المرور يجب أن تكون 8 أحرف على الأقل", "error")
                return render_template("auth/forgot_password.html", step=2)

            if new_pass != confirm:
                session["reset_uid"] = uid
                flash("كلمتا المرور غير متطابقتين", "error")
                return render_template("auth/forgot_password.html", step=2)

            try:
                db.execute(
                    "UPDATE users SET password_hash=? WHERE id=?",
                    (hash_password(new_pass), uid)
                )
                db.commit()
            except Exception:
                db.rollback()
                flash("حدث خطأ أثناء تغيير كلمة المرور — يرجى المحاولة مرة أخرى", "error")
                session["reset_uid"] = uid
                return render_template("auth/forgot_password.html", step=2)
            flash("تم تغيير كلمة المرور بنجاح، يمكنك تسجيل الدخول الآن", "success")
            return redirect(url_for("auth.auth_login"))

    return render_template("auth/forgot_password.html", step=1)


@bp.route("/auth/logout")
def auth_logout():
    uid    = session.get("user_id")
    biz_id = session.get("business_id")
    if uid and biz_id:
        try:
            db = get_db()
            write_audit_log(db, biz_id, "logout", entity_type="user", entity_id=uid)
        except Exception:
            pass
    session.clear()
    flash("تم تسجيل الخروج بنجاح", "info")
    return redirect(url_for("auth.auth_login"))
