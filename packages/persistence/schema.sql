CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    task        TEXT        NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'running',
    answer      TEXT,
    stop_reason TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS run_created_at_idx ON runs (created_at DESC);

CREATE TABLE IF NOT EXISTS journal (
    id          BIGSERIAL PRIMARY KEY,
    run_id      TEXT      NOT NULL REFERENCES runs (run_id) ON DELETE CASCADE,
    step_id     INT       NOT NULL,
    worker_id   TEXT,
    action      TEXT      NOT NULL,
    inputs      JSONB,
    result      TEXT,
    model       TEXT,
    prompt_ver  TEXT,
    tool_ver    TEXT,
    approval    TEXT,
    taint       TEXT,
    retry_count INT         NOT NULL DEFAULT 0,
    error       TEXT,
    meta        JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS journal_run_step_idx ON journal (run_id, step_id);
CREATE INDEX IF NOT EXISTS journal_created_at_idx ON journal (created_at DESC);

CREATE TABLE IF NOT EXISTS source_registry (
    id           TEXT PRIMARY KEY,
    jurisdiction TEXT        NOT NULL,
    regulator    TEXT        NOT NULL,
    url          TEXT        NOT NULL,
    doc_type     TEXT,
    cadence      TEXT,
    last_hash    TEXT,
    last_checked TIMESTAMPTZ,
    enabled      BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS source_registry_jurisdiction_idx ON source_registry (jurisdiction);