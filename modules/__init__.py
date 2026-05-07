"""
modules/__init__.py — Application Factory
"""
from flask import Flask, g

from .config import _load_secret_key, FLASK_CONFIG
from .extensions import close_db


def create_app():
    app = Flask(
        __name__,
        template_folder="../templates",
        static_folder="../static",
    )
    app.secret_key = _load_secret_key()
    app.config.update(FLASK_CONFIG)

    # ── Teardown ──────────────────────────────────────────────────────────────
    app.teardown_appcontext(close_db)

    # ── Blueprints ────────────────────────────────────────────────────────────
    from .blueprints.auth.routes       import bp as auth_bp
    from .blueprints.core.routes       import bp as core_bp
    from .blueprints.accounting.routes import bp as accounting_bp
    from .blueprints.supply.routes     import bp as supply_bp
    from .blueprints.pos.routes        import bp as pos_bp
    from .blueprints.restaurant.routes import bp as restaurant_bp

    for bp in (auth_bp, core_bp, accounting_bp, supply_bp, pos_bp, restaurant_bp):
        app.register_blueprint(bp)

    # ── Middleware ─────────────────────────────────────────────────────────────
    from .middleware import load_user, inject_globals, add_security_headers

    app.before_request(load_user)
    app.context_processor(inject_globals)
    app.context_processor(_terminology_processor)
    app.after_request(add_security_headers)

    # ── DB Migrations (جداول جديدة) ───────────────────────────────────────────
    _run_migrations(app)

    # ── ZATCA Background Worker ────────────────────────────────────────────────
    _start_zatca_worker(app)

    # ── Backward-compat endpoint aliases ──────────────────────────────────────
    _register_endpoint_aliases(app)

    return app


def _terminology_processor():
    """Context processor: يُضيف T (مصطلحات القطاع) لكل القوالب"""
    from .terminology import get_terms
    industry_type = ""
    if hasattr(g, "business") and g.business:
        industry_type = g.business["industry_type"] or ""
    return {"T": get_terms(industry_type)}


def _run_migrations(app):
    """تشغيل migrations للجداول الجديدة مرة واحدة عند البدء"""
    import sqlite3
    from .config import DB_PATH
    from .zatca_queue import ZATCA_QUEUE_SCHEMA
    from .ocr_limits  import USAGE_LOGS_SCHEMA

    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        for schema in (ZATCA_QUEUE_SCHEMA, USAGE_LOGS_SCHEMA):
            for stmt in schema.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(stmt)
        conn.commit()
        conn.close()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Migration warning: {e}")


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
        "api_order_detail":         "restaurant.api_order_detail",
        "api_order_cancel":         "restaurant.api_order_cancel",
        "api_order_payment":        "restaurant.api_order_payment",
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
