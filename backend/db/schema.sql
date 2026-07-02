-- Aegis Mail AI — Postgres schema (Phase 2).
-- Single source of truth: state + embeddings (pgvector) + full-text (tsvector)
-- + the action queue (created now, exercised from Phase 4/5).
--
-- NOTE: the vector(768) dimension MUST match Settings.embedding_dim. It is 768
-- for Google Gemini text-embedding-004 (the default). If you change the embedding
-- model/dimension, change both here and in config.py (e.g. OpenAI = 1536).

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------------
-- users: one row per connected Google account. Holds the encrypted OAuth token
-- (Phase 2 moves token storage here from the interim file store).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,          -- the account email
    encrypted_token TEXT,                      -- Fernet-encrypted OAuth JSON
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- emails: metadata + body + triage outputs + embedding + full-text vector.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS emails (
    id                  TEXT PRIMARY KEY,      -- gmail message id
    user_id             TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    thread_id           TEXT,
    sender              TEXT,
    recipient           TEXT,
    subject             TEXT,
    snippet             TEXT,
    body                TEXT,
    internal_date       TIMESTAMPTZ,
    unread              BOOLEAN NOT NULL DEFAULT false,

    -- triage processor outputs
    category            TEXT,
    category_confidence REAL,
    priority            INTEGER,               -- 0..100
    priority_reason     TEXT,
    summary_one_line    TEXT,
    summary_detailed    TEXT,

    embedding           vector(768),
    -- generated full-text column over sender + subject + body (Phase 3 search;
    -- sender is included so person-name queries like "what did X ask" match)
    tsv                 tsvector GENERATED ALWAYS AS (
                            to_tsvector('english',
                                coalesce(sender, '') || ' ' ||
                                coalesce(subject, '') || ' ' || coalesce(body, ''))
                        ) STORED,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_emails_user            ON emails(user_id);
CREATE INDEX IF NOT EXISTS idx_emails_user_priority   ON emails(user_id, priority DESC);
CREATE INDEX IF NOT EXISTS idx_emails_thread          ON emails(thread_id);
CREATE INDEX IF NOT EXISTS idx_emails_tsv             ON emails USING GIN(tsv);
-- IVFFlat index for semantic search (cosine). Built here; tune lists in Phase 3.
CREATE INDEX IF NOT EXISTS idx_emails_embedding
    ON emails USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ---------------------------------------------------------------------------
-- tasks: action items extracted from emails.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tasks (
    id          BIGSERIAL PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    email_id    TEXT REFERENCES emails(id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    due_date    DATE,
    status      TEXT NOT NULL DEFAULT 'open',   -- open | done | dismissed
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id, status);

-- ---------------------------------------------------------------------------
-- action_queue: the safety gate. Every irreversible action lands here as
-- 'pending' and only executes after explicit approval (Phase 5). Unused until
-- Phase 4, but the schema exists now.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS action_queue (
    id               BIGSERIAL PRIMARY KEY,
    user_id          TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    action_type      TEXT NOT NULL,             -- send_email | create_event | ...
    status           TEXT NOT NULL DEFAULT 'pending',
                     -- pending | approved | rejected | executed | failed
    payload          JSONB NOT NULL,            -- what would be sent/created
    thread_id        TEXT,
    related_email_id TEXT REFERENCES emails(id) ON DELETE SET NULL,
    result           JSONB,                     -- execution result / error
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_at      TIMESTAMPTZ,
    executed_at      TIMESTAMPTZ,
    CONSTRAINT chk_action_status CHECK (
        status IN ('pending', 'approved', 'rejected', 'executed', 'failed')
    )
);

CREATE INDEX IF NOT EXISTS idx_action_queue_user_status
    ON action_queue(user_id, status);

-- LangGraph thread id for the reply agent run that created this action, so the
-- approval endpoint can resume the interrupted graph from its checkpoint (Phase 5).
ALTER TABLE action_queue ADD COLUMN IF NOT EXISTS graph_thread_id TEXT;

-- Rebuild the full-text column to include the sender (Phase 6 chat retrieval).
-- Generated-column expressions can't be altered in place, so drop + re-add.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_attrdef d
        JOIN pg_attribute a ON a.attrelid = d.adrelid AND a.attnum = d.adnum
        WHERE a.attrelid = 'emails'::regclass AND a.attname = 'tsv'
          AND pg_get_expr(d.adbin, d.adrelid) NOT LIKE '%sender%'
    ) THEN
        ALTER TABLE emails DROP COLUMN tsv;
        ALTER TABLE emails ADD COLUMN tsv tsvector GENERATED ALWAYS AS (
            to_tsvector('english',
                coalesce(sender, '') || ' ' ||
                coalesce(subject, '') || ' ' || coalesce(body, ''))
        ) STORED;
        CREATE INDEX IF NOT EXISTS idx_emails_tsv ON emails USING GIN(tsv);
    END IF;
END $$;
