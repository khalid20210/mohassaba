-- ============================================================
-- Migration 007: تصحيح وإضافة الأعمدة الناقصة
-- يضمن عمل النظام على تثبيت جديد
-- ============================================================

-- 1. أعمدة تسجيل الدخول للمندوب
ALTER TABLE agents ADD COLUMN username      TEXT;
ALTER TABLE agents ADD COLUMN password_hash TEXT;
ALTER TABLE agents ADD COLUMN last_login    TEXT;

-- 2. UNIQUE index على username المندوب داخل نفس المنشأة
CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_username ON agents(business_id, username) WHERE username IS NOT NULL;

-- 3. صلاحيات المندوب الفردية
ALTER TABLE agents ADD COLUMN perm_discount    INTEGER DEFAULT NULL;
ALTER TABLE agents ADD COLUMN perm_edit_price  INTEGER DEFAULT NULL;
ALTER TABLE agents ADD COLUMN perm_view_cost   INTEGER DEFAULT NULL;
ALTER TABLE agents ADD COLUMN perm_collect     INTEGER DEFAULT NULL;
ALTER TABLE agents ADD COLUMN perm_add_client  INTEGER DEFAULT NULL;
ALTER TABLE agents ADD COLUMN perm_create_draft INTEGER DEFAULT NULL;
ALTER TABLE agents ADD COLUMN perm_send_offer  INTEGER DEFAULT NULL;
ALTER TABLE agents ADD COLUMN max_discount_pct REAL    DEFAULT NULL;

-- 4. إعدادات المندوبين في business_settings_ext
ALTER TABLE business_settings_ext ADD COLUMN agent_location_interval INTEGER DEFAULT 30;
ALTER TABLE business_settings_ext ADD COLUMN agent_reminder_days     INTEGER DEFAULT 30;
ALTER TABLE business_settings_ext ADD COLUMN agent_can_discount      INTEGER DEFAULT 0;
ALTER TABLE business_settings_ext ADD COLUMN agent_can_edit_price    INTEGER DEFAULT 0;
ALTER TABLE business_settings_ext ADD COLUMN agent_can_view_cost     INTEGER DEFAULT 0;
ALTER TABLE business_settings_ext ADD COLUMN agent_can_collect       INTEGER DEFAULT 1;
ALTER TABLE business_settings_ext ADD COLUMN agent_can_add_client    INTEGER DEFAULT 1;
ALTER TABLE business_settings_ext ADD COLUMN agent_can_create_draft  INTEGER DEFAULT 1;
ALTER TABLE business_settings_ext ADD COLUMN agent_can_send_offer    INTEGER DEFAULT 1;
ALTER TABLE business_settings_ext ADD COLUMN agent_max_discount_pct  REAL    DEFAULT 0;
