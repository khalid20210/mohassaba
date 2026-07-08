-- ══════════════════════════════════════════════════════════════
-- 021_approval_policy_engine.sql
-- Approval Workflow + Unified Policy Engine
-- ══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS operation_policies (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id       INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    operation_key     TEXT NOT NULL,
    permission_key    TEXT,
    requires_approval INTEGER NOT NULL DEFAULT 0,
    min_approvals     INTEGER NOT NULL DEFAULT 1,
    owner_only        INTEGER NOT NULL DEFAULT 0,
    is_active         INTEGER NOT NULL DEFAULT 1,
    updated_by        INTEGER,
    updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(business_id, operation_key)
);

CREATE INDEX IF NOT EXISTS idx_operation_policies_biz_op
    ON operation_policies(business_id, operation_key);

CREATE TABLE IF NOT EXISTS approval_requests (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id        INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    operation_key      TEXT NOT NULL,
    entity_type        TEXT,
    entity_id          INTEGER,
    requested_by       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    status             TEXT NOT NULL DEFAULT 'pending', -- pending|approved|rejected|cancelled
    reason             TEXT,
    payload_json       TEXT,
    required_approvals INTEGER NOT NULL DEFAULT 1,
    current_approvals  INTEGER NOT NULL DEFAULT 0,
    requested_at       TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at        TEXT,
    resolved_by        INTEGER REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_approval_requests_biz_status
    ON approval_requests(business_id, status, requested_at DESC);

CREATE INDEX IF NOT EXISTS idx_approval_requests_operation
    ON approval_requests(business_id, operation_key, status);

CREATE TABLE IF NOT EXISTS approval_request_votes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id       INTEGER NOT NULL REFERENCES approval_requests(id) ON DELETE CASCADE,
    business_id      INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    approver_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    decision         TEXT NOT NULL, -- approved|rejected
    comment          TEXT,
    decided_at       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(request_id, approver_user_id)
);

CREATE INDEX IF NOT EXISTS idx_approval_votes_request
    ON approval_request_votes(request_id, decided_at DESC);
