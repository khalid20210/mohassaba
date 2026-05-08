-- 019_social_oauth_users.sql
-- ربط المستخدمين بحسابات OAuth (Google / Apple / Microsoft)

ALTER TABLE users ADD COLUMN social_provider TEXT;
ALTER TABLE users ADD COLUMN social_sub TEXT;
ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0;

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_social_identity
ON users (social_provider, social_sub)
WHERE social_provider IS NOT NULL AND social_sub IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_users_email_nocase
ON users (email COLLATE NOCASE);
