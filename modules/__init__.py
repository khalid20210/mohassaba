"""
modules/__init__.py — Application Factory
"""
import logging
from flask import Flask, g

from .config import _load_secret_key, FLASK_CONFIG, DB_PATH, IS_PROD
from .extensions import close_db

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

    for bp in (auth_bp, core_bp, accounting_bp, supply_bp, pos_bp, restaurant_bp, workforce_bp, owner_bp, inventory_bp, contacts_bp, barcode_bp, medical_bp, construction_bp, rental_bp, wholesale_bp, services_bp):
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

    # ── Middleware ─────────────────────────────────────────────────────────────
    from .middleware import load_user, inject_globals, add_security_headers

    app.before_request(load_user)
    app.context_processor(inject_globals)
    app.context_processor(_terminology_processor)
    app.after_request(add_security_headers)

    # ── DB Migrations (نظام التهجير الجديد المرقّم) ───────────────────────────
    _run_migrations(app)

    # ── ZATCA Background Worker ────────────────────────────────────────────────
    _start_zatca_worker(app)

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
