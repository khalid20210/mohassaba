-- ══════════════════════════════════════════════════════════════
-- 025_execution_queue.sql
-- عقد المرحلة 4: execution_queue
-- ══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS execution_queue (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    approval_request_id  INTEGER NOT NULL REFERENCES approval_requests(id) ON DELETE CASCADE,
    status               TEXT NOT NULL DEFAULT 'pending', -- pending|executed|failed
    executed_at          TEXT,
    result               TEXT,
    created_at           TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(approval_request_id)
);

CREATE INDEX IF NOT EXISTS idx_execution_queue_status
    ON execution_queue(status, created_at DESC);
