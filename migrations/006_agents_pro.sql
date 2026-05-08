-- ============================================================
-- Migration 006: نظام المناديب الاحترافي الكامل
-- ============================================================

-- 1. بيانات المنشآت التي يزورها المندوب
CREATE TABLE IF NOT EXISTS agent_client_profiles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id),
    agent_id        INTEGER NOT NULL REFERENCES agents(id),
    contact_id      INTEGER REFERENCES contacts(id),
    company_name    TEXT NOT NULL,
    manager_name    TEXT,
    phone           TEXT,
    region          TEXT,
    address         TEXT,
    notes           TEXT,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_acp_business ON agent_client_profiles(business_id);
CREATE INDEX IF NOT EXISTS idx_acp_agent    ON agent_client_profiles(agent_id);
CREATE INDEX IF NOT EXISTS idx_acp_contact  ON agent_client_profiles(contact_id);

-- 2. تتبع موقع المندوب (كل 30 دقيقة)
CREATE TABLE IF NOT EXISTS agent_locations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    agent_id    INTEGER NOT NULL REFERENCES agents(id),
    latitude    REAL    NOT NULL,
    longitude   REAL   NOT NULL,
    accuracy    REAL,
    battery     REAL,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_aloc_agent ON agent_locations(agent_id, recorded_at);

-- 3. حضور وانصراف المندوب
CREATE TABLE IF NOT EXISTS agent_attendance (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id),
    agent_id        INTEGER NOT NULL REFERENCES agents(id),
    work_date       TEXT    NOT NULL,
    checkin_at      TEXT,
    checkin_lat     REAL,
    checkin_lng     REAL,
    checkout_at     TEXT,
    checkout_lat    REAL,
    checkout_lng    REAL,
    total_hours     REAL,
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_aatt_agent_date ON agent_attendance(agent_id, work_date);

-- 4. سجل الزيارات والمكالمات
CREATE TABLE IF NOT EXISTS agent_visits (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id),
    agent_id        INTEGER NOT NULL REFERENCES agents(id),
    contact_id      INTEGER REFERENCES contacts(id),
    client_profile_id INTEGER REFERENCES agent_client_profiles(id),
    visit_type      TEXT NOT NULL DEFAULT 'visit',  -- visit | call | online
    outcome         TEXT NOT NULL DEFAULT 'neutral', -- sale | interested | rejected | neutral
    notes           TEXT,
    rejection_reason TEXT,
    lat             REAL,
    lng             REAL,
    visited_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_avis_agent ON agent_visits(agent_id, visited_at);

-- 5. الأهداف الشهرية للمندوب
CREATE TABLE IF NOT EXISTS agent_targets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id),
    agent_id        INTEGER NOT NULL REFERENCES agents(id),
    target_month    TEXT    NOT NULL,  -- YYYY-MM
    target_amount   REAL    NOT NULL DEFAULT 0,
    bonus_amount    REAL    NOT NULL DEFAULT 0,
    bonus_threshold REAL    NOT NULL DEFAULT 0,  -- تجاوز الهدف بنسبة %
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(business_id, agent_id, target_month)
);

-- 6. طلبات مسودة (draft orders)
CREATE TABLE IF NOT EXISTS agent_draft_orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id),
    agent_id        INTEGER NOT NULL REFERENCES agents(id),
    contact_id      INTEGER REFERENCES contacts(id),
    client_name     TEXT,
    items_json      TEXT    NOT NULL DEFAULT '[]',  -- [{product_id, qty, price}]
    total           REAL    NOT NULL DEFAULT 0,
    notes           TEXT,
    status          TEXT    NOT NULL DEFAULT 'pending', -- pending | approved | rejected | invoiced
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_adraft_agent ON agent_draft_orders(agent_id, status);

-- 7. قائمة انتظار المزامنة أوفلاين
CREATE TABLE IF NOT EXISTS agent_sync_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id),
    agent_id        INTEGER NOT NULL REFERENCES agents(id),
    action_type     TEXT    NOT NULL,   -- create_invoice | record_payment | create_visit
    payload_json    TEXT    NOT NULL DEFAULT '{}',
    status          TEXT    NOT NULL DEFAULT 'pending',  -- pending | done | failed
    error_msg       TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    synced_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_asq_agent_status ON agent_sync_queue(agent_id, status);

-- 8. تحصيل دفعات من العملاء بالميدان
CREATE TABLE IF NOT EXISTS agent_collections (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id     INTEGER NOT NULL REFERENCES businesses(id),
    agent_id        INTEGER NOT NULL REFERENCES agents(id),
    contact_id      INTEGER REFERENCES contacts(id),
    invoice_id      INTEGER REFERENCES invoices(id),
    amount          REAL    NOT NULL,
    payment_method  TEXT    NOT NULL DEFAULT 'cash',
    notes           TEXT,
    collected_at    TEXT NOT NULL DEFAULT (datetime('now')),
    confirmed       INTEGER NOT NULL DEFAULT 0,  -- 0=pending confirmation, 1=confirmed
    confirmed_by    INTEGER REFERENCES users(id),
    confirmed_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_acoll_agent ON agent_collections(agent_id, collected_at);

-- تحديث جدول agents لإضافة حقول جديدة إن لم تكن موجودة
ALTER TABLE agents ADD COLUMN region        TEXT;
ALTER TABLE agents ADD COLUMN employee_code TEXT;
ALTER TABLE agents ADD COLUMN target_amount REAL NOT NULL DEFAULT 0;
ALTER TABLE agents ADD COLUMN notes         TEXT;
