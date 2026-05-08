"""
modules/__init__.py — Application Factory
"""
import logging
from flask import Flask, g

from .config import _load_secret_key, FLASK_CONFIG, DB_PATH, IS_PROD
from .extensions import close_db
from .observability import setup_logging
from .runtime_services import setup_runtime_services, validate_runtime_requirements

import os as _os
_BEHIND_PROXY = _os.environ.get("BEHIND_PROXY", "false").lower() in ("1", "true", "yes")

logger = logging.getLogger(__name__)


def create_app():
    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static",
    )
    app.secret_key = _load_secret_key()
    app.config.update(FLASK_CONFIG)

    # ── Runtime Services (Session/Redis/Queue) ─────────────────────────────
    try:
        setup_runtime_services(app)
    except Exception as e:
        logger.warning(f"Runtime services fallback mode: {e}")

    # ── Fail-Fast Startup (اختياري للإنتاج الصارم) ─────────────────────────
    from .config import FAIL_FAST_ON_STARTUP
    if FAIL_FAST_ON_STARTUP:
        ok, errors = validate_runtime_requirements()
        if not ok:
            raise RuntimeError(" | ".join(errors))
    
    # ── نظام المراقبة الشامل ──────────────────────────────────────────────────
    log_level = "INFO" if IS_PROD else "DEBUG"
    setup_logging(app, log_level)

    # ── ProxyFix: تفعيله عند وجود Proxy/nginx أمام التطبيق ─────────────────────
    if _BEHIND_PROXY:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    # ── Teardown ──────────────────────────────────────────────────────────────
    app.teardown_appcontext(close_db)

    # ── Blueprints ────────────────────────────────────────────────────────────
    from .blueprints.auth.routes       import bp as auth_bp
    from .blueprints.core.routes       import bp as core_bp
    from .blueprints.accounting.routes import bp as accounting_bp
    from .blueprints.supply.routes     import bp as supply_bp
    from .blueprints.pos.routes        import bp as pos_bp
    from .blueprints.restaurant.routes import bp as restaurant_bp
    from .blueprints.workforce.routes  import bp as workforce_bp
    from .blueprints.owner.routes      import bp as owner_bp
    from .blueprints.inventory.routes  import bp as inventory_bp
    from .blueprints.contacts.routes   import bp as contacts_bp
    from .blueprints.barcode.routes    import bp as barcode_bp
    from .blueprints.medical.routes    import bp as medical_bp
    from .blueprints.construction.routes import bp as construction_bp
    from .blueprints.rental.routes     import bp as rental_bp
    from .blueprints.wholesale.routes  import bp as wholesale_bp
    from .blueprints.services.routes   import bp as services_bp
    from .blueprints.invoices.routes   import bp as invoices_bp
    from .blueprints.recipes.routes    import bp as recipes_bp
    from .blueprints.admin.routes      import bp as admin_bp, api as api_v1_bp
    from .blueprints.receivables.routes import bp as receivables_bp
    from .blueprints.hr.routes         import bp as hr_bp

    for bp in (auth_bp, core_bp, accounting_bp, supply_bp, pos_bp, restaurant_bp, workforce_bp, owner_bp, inventory_bp, contacts_bp, barcode_bp, medical_bp, construction_bp, rental_bp, wholesale_bp, services_bp, invoices_bp, recipes_bp, admin_bp, api_v1_bp, receivables_bp, hr_bp):
        app.register_blueprint(bp)

    # ── Jinja2 Custom Filters ─────────────────────────────────────────────────
    import json as _json
    def _from_json(value, default=None):
        try:
            return _json.loads(value)
        except Exception:
            return default if default is not None else []
    app.jinja_env.filters["from_json"] = _from_json
    app.jinja_env.globals["enumerate"] = enumerate
    app.jinja_env.filters["enumerate"] = enumerate

    # ── i18n: دالة الترجمة t() ──────────────────────────────────────────────
    from .i18n import translate as _translate
    from flask import g as _flask_g
    def _t_global(key: str) -> str:
        lang = getattr(_flask_g, "lang", "ar")
        return _translate(key, lang)
    app.jinja_env.globals["t"] = _t_global

    # ── Middleware ─────────────────────────────────────────────────────────────
    from .middleware import platform_guard, load_user, inject_globals, add_security_headers, enforce_global_csrf
    from .request_tracking import track_request_start, track_request_end
    
    app.before_request(platform_guard)
    app.before_request(track_request_start)
    app.before_request(load_user)
    app.before_request(enforce_global_csrf)
    app.context_processor(inject_globals)
    app.context_processor(_terminology_processor)
    app.after_request(track_request_end)
    app.after_request(add_security_headers)

    # ── DB Migrations (نظام التهجير الجديد المرقّم) ───────────────────────────
    _run_migrations(app)

    # ── جداول HR (الموارد البشرية) ────────────────────────────────────────────
    try:
        import sqlite3
        from .config import DB_PATH as _DB_PATH_HR
        _hr_conn = sqlite3.connect(str(_DB_PATH_HR))
        _hr_conn.row_factory = sqlite3.Row
        from .blueprints.hr.routes import init_hr_tables
        init_hr_tables(_hr_conn)
        _hr_conn.commit()
        _hr_conn.close()
        logger.info("HR tables: ✅ تم التحقق/إنشاء جداول الموارد البشرية")
    except Exception as _hr_err:
        logger.warning(f"HR tables: تحذير — {_hr_err}")

    # ── Activity Seeder: حقن الأنشطة الـ 196 مرة واحدة عند بدء التشغيل ─────────
    try:
        from .activity_seeder import seed_activities
        seeded = seed_activities(str(DB_PATH))
        if seeded:
            logger.info("activity_seeder: ✅ تم حقن %d نشاط في قاعدة البيانات", seeded)
    except Exception as _seed_err:
        logger.warning("activity_seeder: تحذير — %s", _seed_err)

    # ── تهيئة الميثاق الدستوري الشامل ────────────────────────────────────────
    from .constitutional_integration import initialize_constitutional_framework, register_constitutional_health_checks
    success, message = initialize_constitutional_framework(app)
    logger.info(message)
    register_constitutional_health_checks(app)

    # ── ZATCA Background Worker ────────────────────────────────────────────────
    _start_zatca_worker(app)

    # ── Sync Storm Worker (معالج المزامنة اللامتزامن) ─────────────────────────
    try:
        from modules.sync_engine import start_worker as _start_sync_worker
        _start_sync_worker()
    except Exception as _se:
        logger.warning(f"SyncWorker لم يبدأ: {_se}")

    # ── Backward-compat endpoint aliases ──────────────────────────────────────
    _register_endpoint_aliases(app)

    env_label = "🟡 تطوير (dev)" if not IS_PROD else "🟢 إنتاج (prod)"
    logger.info(f"✅ جنان بيز تعمل | البيئة: {env_label} | DB: {DB_PATH.name}")

    return app


def _terminology_processor():
    """Context processor: يُضيف T (مصطلحات القطاع) لكل القوالب"""
    from .terminology import get_terms
    industry_type = ""
    if hasattr(g, "business") and g.business:
        industry_type = g.business["industry_type"] or ""
    return {"T": get_terms(industry_type)}


def _run_migrations(app):
    """
    تشغيل جميع migrations المرقّمة عند بدء التشغيل
    (نظام versioned لـ raw SQLite — بديل Flask-Migrate لمشاريع بدون SQLAlchemy)
    """
    from .config import DB_PATH
    from .migration_runner import run_migrations
    from .zatca_queue import ZATCA_QUEUE_SCHEMA
    from .ocr_limits  import USAGE_LOGS_SCHEMA
    import sqlite3

    # أولاً: الـ migrations المرقّمة (الملفات في migrations/)
    try:
        run_migrations(DB_PATH)
    except Exception as e:
        logger.error(f"❌ فشل في تشغيل migrations: {e}")

    # ثانياً: جداول inline الخاصة بـ ZATCA وـ OCR (احتياطي — ستُدمج لاحقاً في sql files)
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("PRAGMA foreign_keys = ON")
        for schema in (ZATCA_QUEUE_SCHEMA, USAGE_LOGS_SCHEMA):
            for stmt in schema.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(stmt)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Migration inline warning: {e}")
    
    # ثالثاً: تهيئة جداول الميثاق الدستوري
    try:
        from .smart_recycle_bin import RECYCLE_BIN_SCHEMA
        from .enhanced_audit import ENHANCED_AUDIT_SCHEMA
        from .resilience_engine import BackupRecoveryManager
        
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("PRAGMA foreign_keys = ON")

        # ترقية آمنة للجداول القديمة قبل تطبيق schema الكامل.
        recycle_cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(recycle_bin)").fetchall()
        }
        if recycle_cols:
            missing_defs = {
                "table_name": "TEXT NOT NULL DEFAULT ''",
                "record_id": "INTEGER NOT NULL DEFAULT 0",
                "retention_until": "TEXT NOT NULL DEFAULT ''",
                "is_admin_locked": "INTEGER DEFAULT 0",
                "restoration_count": "INTEGER DEFAULT 0",
                "last_restored_at": "TEXT",
                "notes": "TEXT",
            }
            for col, col_def in missing_defs.items():
                if col not in recycle_cols:
                    conn.execute(f"ALTER TABLE recycle_bin ADD COLUMN {col} {col_def}")
        
        # سلة المهملات
        for stmt in RECYCLE_BIN_SCHEMA.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError as oe:
                    if "already exists" not in str(oe):
                        logger.warning(f"Recycle bin schema warning: {oe}")
        
        # الرقابة المحسّنة
        for stmt in ENHANCED_AUDIT_SCHEMA.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError as oe:
                    if "already exists" not in str(oe):
                        logger.warning(f"Enhanced audit schema warning: {oe}")
        
        # النسخ الاحتياطية
        for stmt in BackupRecoveryManager.BACKUP_SCHEMA.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError as oe:
                    if "already exists" not in str(oe):
                        logger.warning(f"Backup schema warning: {oe}")
        
        conn.commit()
        conn.close()
        logger.info("✓ جداول الميثاق الدستوري جاهزة")
    except Exception as e:
        logger.warning(f"Constitutional schema warning: {e}")


def _start_zatca_worker(app):
    """تشغيل ZATCA background worker (في بيئة الإنتاج فقط)"""
    import os
    if os.environ.get("FLASK_ENV") == "production" or not app.debug:
        try:
            from .zatca_queue import ZATCAWorker
            ZATCAWorker.start(app)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"ZATCA worker not started: {e}")


def _register_endpoint_aliases(app):
    """
    Allow templates to use old endpoint names (e.g. url_for('dashboard'))
    while the real endpoints live inside blueprints (e.g. 'core.dashboard').
    We add each alias into app.view_functions AND add a duplicate URL rule so
    that url_for(alias, ...) resolves correctly.
    """
    import werkzeug.routing

    aliases = {
        # auth
        "auth_login":            "auth.auth_login",
        "auth_register":         "auth.auth_register",
        "auth_logout":           "auth.auth_logout",
        "auth_forgot_password":  "auth.auth_forgot_password",
        # core
        "dashboard":    "core.dashboard",
        "analytics":    "core.analytics",
        "onboarding":   "core.onboarding",
        "settings":     "core.settings",
        "offline":      "core.offline",
        "service_worker": "core.service_worker",
        "stub_page":    "core.stub_page",
        "audit_log_page": "core.audit_log_page",
        "api_audit_log":  "core.api_audit_log",
        # accounting
        "accounting":           "accounting.accounting",
        "reports":              "accounting.reports",
        "invoice_print":        "accounting.invoice_print",
        "api_zatca_qr":         "accounting.api_zatca_qr",
        "api_zatca_xml":        "accounting.api_zatca_xml",
        # supply
        "purchases":                    "supply.purchases",
        "purchase_import":              "supply.purchase_import",
        "api_purchase_import_upload":   "supply.api_purchase_import_upload",
        "api_purchase_import_confirm":  "supply.api_purchase_import_confirm",
        "excel_import":                 "supply.excel_import",
        "api_excel_import_preview":     "supply.api_excel_import_preview",
        "api_excel_import_confirm":     "supply.api_excel_import_confirm",
        # pos
        "pos":              "pos.pos",
        "api_pos_search":   "pos.api_pos_search",
        "api_pos_checkout": "pos.api_pos_checkout",
        "api_pos_config":   "pos.api_pos_config",
        # restaurant
        "orders":                   "restaurant.orders",
        "pricing":                  "restaurant.pricing",
        "api_pricing_update":       "restaurant.api_pricing_update",
        "tables":                   "restaurant.tables",
        "api_tables_open":          "restaurant.api_tables_open",
        "api_tables_add_item":      "restaurant.api_tables_add_item",
        "api_tables_remove_item":   "restaurant.api_tables_remove_item",
        "api_tables_send_kitchen":  "restaurant.api_tables_send_kitchen",
        "api_tables_checkout":      "restaurant.api_tables_checkout",
        "api_tables_order_lines":   "restaurant.api_tables_order_lines",
        "kitchen":          "restaurant.kitchen",
        "api_kitchen_done": "restaurant.api_kitchen_done",
        "api_me":           "restaurant.api_me",
        # workforce
        "workforce_portal":              "workforce.workforce_portal",
        "agent_mobile_portal":           "workforce.agent_mobile_portal",
        "api_v1_health":                 "workforce.api_v1_health",
        "api_v1_openapi":                "workforce.api_v1_openapi",
        "api_v1_employees_list":         "workforce.api_v1_employees_list",
        "api_v1_employees_create":       "workforce.api_v1_employees_create",
        "api_v1_shift_close_blind":      "workforce.api_v1_shift_close_blind",
        "api_v1_agents_list":            "workforce.api_v1_agents_list",
        "api_v1_agents_create":          "workforce.api_v1_agents_create",
        "api_v1_agent_assign_invoice":   "workforce.api_v1_agent_assign_invoice",
        "api_v1_agent_commissions_summary":"workforce.api_v1_agent_commissions_summary",
        "api_v1_agent_whatsapp_campaign": "workforce.api_v1_agent_whatsapp_campaign",
        # owner (قمرة القيادة)
        "owner_dashboard":       "owner.owner_dashboard",
        "owner_audit_logs":      "owner.audit_logs",
        "owner_blind_closures":  "owner.blind_closures",
        "owner_hr_panel":        "owner.hr_panel",
        "owner_api_keys":        "owner.api_keys_page",
    }

    for alias, real in aliases.items():
        if real not in app.view_functions:
            continue
        app.view_functions[alias] = app.view_functions[real]
        rules = [r for r in app.url_map.iter_rules() if r.endpoint == real]
        for rule in rules:
            try:
                new_rule = werkzeug.routing.Rule(
                    rule.rule,
                    endpoint=alias,
                    methods=rule.methods,
                )
                app.url_map.add(new_rule)
            except Exception:
                pass
