-- ╔══════════════════════════════════════════════════════════════════════╗
-- ║  004_owner_intelligence.sql — قمرة القيادة                         ║
-- ║  Owner Intelligence Dashboard: Audit Logs, API Keys, Settings Ext  ║
-- ╚══════════════════════════════════════════════════════════════════════╝

-- ── 1. سجل النشاط (Audit Log) — كل حركة كاشير / مندوب / مستخدم ────────────
CREATE TABLE IF NOT EXISTS audit_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
    actor_name      TEXT    NOT NULL DEFAULT '',
    actor_role      TEXT    NOT NULL DEFAULT '',
    action          TEXT    NOT NULL,           -- 'invoice_created', 'login', 'blind_close', etc.
    entity_type     TEXT,                        -- 'invoice', 'employee', 'agent', 'setting'
    entity_id       INTEGER,
    old_value       TEXT,                        -- JSON snapshot قبل التغيير
    new_value       TEXT,                        -- JSON snapshot بعد التغيير
    ip_address      TEXT,
    user_agent      TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_logs_biz_created ON audit_logs(business_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action      ON audit_logs(action);

-- ── 2. مفاتيح API (API Keys) — لوحة ربط المنصات الخارجية ───────────────────
CREATE TABLE IF NOT EXISTS api_keys (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    created_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    label           TEXT    NOT NULL,            -- 'مدونة جنان بيز', 'منصة المتاجر', إلخ
    key_prefix      TEXT    NOT NULL,            -- أول 8 أحرف تُعرض للمستخدم  e.g. 'jb_live_a'
    key_hash        TEXT    NOT NULL UNIQUE,     -- SHA-256 hash للمفتاح الكامل
    scopes          TEXT    NOT NULL DEFAULT '["read"]',  -- JSON array: "read","write","pos","hr"
    last_used_at    TEXT,
    expires_at      TEXT,                        -- NULL = لا تنتهي
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_api_keys_biz ON api_keys(business_id);

-- ── 3. إعدادات المنشأة الموسّعة (Business Settings Extension) ──────────────
-- وضع العرض: basic = بسيط (لا قيود)، pro = احترافي (كل شيء)
-- إخفاء / إظهار وحدات معينة حسب دور المستخدم
CREATE TABLE IF NOT EXISTS business_settings_ext (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL UNIQUE REFERENCES businesses(id) ON DELETE CASCADE,
    display_mode    TEXT    NOT NULL DEFAULT 'pro'  CHECK(display_mode IN ('basic','pro')),
    hide_accounting INTEGER NOT NULL DEFAULT 0,     -- في basic mode: أخفِ المحاسبة عن غير المالك
    hide_workforce  INTEGER NOT NULL DEFAULT 0,     -- إخفاء وحدة الموظفين عن غير المالك
    hide_agent_portal INTEGER NOT NULL DEFAULT 0,  -- إخفاء بوابة المناديب بشكل كامل
    auto_deduct_deficit INTEGER NOT NULL DEFAULT 1, -- خصم العجز من راتب الكاشير آلياً
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ── 4. سجل عمليات API (طلبات الربط الخارجية) ───────────────────────────────
CREATE TABLE IF NOT EXISTS api_request_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    api_key_id      INTEGER REFERENCES api_keys(id) ON DELETE SET NULL,
    business_id     INTEGER,
    endpoint        TEXT    NOT NULL,
    method          TEXT    NOT NULL DEFAULT 'GET',
    status_code     INTEGER,
    ip_address      TEXT,
    request_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_api_req_log_key ON api_request_log(api_key_id, request_at DESC);
