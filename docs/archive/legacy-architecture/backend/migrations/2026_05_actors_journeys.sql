-- =============================================================================
-- Aether — Multi-Actor Journey Intelligence v1
-- Strictly additive migration. No existing tables are altered.
-- Postgres / TimescaleDB.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- ENUMS
-- -----------------------------------------------------------------------------

DO $$ BEGIN
    CREATE TYPE actor_kind AS ENUM ('human', 'agent', 'system');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE actor_relationship_kind AS ENUM (
        'owns', 'delegates_to', 'collaborates_with', 'manages'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE journey_state AS ENUM (
        'open', 'converted', 'abandoned', 'closed'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE journey_exit_reason AS ENUM (
        'conversion', 'inactivity', 'new_origin', 'manual'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- -----------------------------------------------------------------------------
-- actors — polymorphic principal (human | agent | system)
-- Humans link 1:1 to existing user_profiles via human_user_id; no identity dup.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS actors (
    actor_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind              actor_kind NOT NULL,
    human_user_id     UUID,
    agent_worker_id   TEXT,
    system_name       TEXT,
    display_name      TEXT,
    tenant_id         TEXT,
    org_id            TEXT,
    metadata          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT actors_kind_identifier CHECK (
        (kind = 'human'  AND human_user_id   IS NOT NULL) OR
        (kind = 'agent'  AND agent_worker_id IS NOT NULL) OR
        (kind = 'system' AND system_name     IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS actors_human_uq
    ON actors (human_user_id)   WHERE kind = 'human';
CREATE UNIQUE INDEX IF NOT EXISTS actors_agent_uq
    ON actors (agent_worker_id) WHERE kind = 'agent';
CREATE UNIQUE INDEX IF NOT EXISTS actors_system_uq
    ON actors (system_name)     WHERE kind = 'system';
CREATE INDEX IF NOT EXISTS actors_tenant_idx ON actors (tenant_id, kind);

-- -----------------------------------------------------------------------------
-- actor_relationships — ownership / delegation / collaboration graph mirror
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS actor_relationships (
    relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_actor_id   UUID NOT NULL REFERENCES actors(actor_id) ON DELETE CASCADE,
    to_actor_id     UUID NOT NULL REFERENCES actors(actor_id) ON DELETE CASCADE,
    kind            actor_relationship_kind NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at        TIMESTAMPTZ,
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
    CONSTRAINT actor_rel_self_loop CHECK (from_actor_id <> to_actor_id)
);
CREATE INDEX IF NOT EXISTS actor_rel_from_idx ON actor_relationships (from_actor_id, kind);
CREATE INDEX IF NOT EXISTS actor_rel_to_idx   ON actor_relationships (to_actor_id, kind);

-- -----------------------------------------------------------------------------
-- delegations — explicit, revocable authorization
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS delegations (
    delegation_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    delegator_actor_id   UUID NOT NULL REFERENCES actors(actor_id),
    delegatee_actor_id   UUID NOT NULL REFERENCES actors(actor_id),
    scope                TEXT[] NOT NULL,
    constraints          JSONB NOT NULL DEFAULT '{}'::jsonb,
    issued_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at           TIMESTAMPTZ,
    revoked_at           TIMESTAMPTZ,
    revoked_reason       TEXT,
    signature            BYTEA,
    CONSTRAINT delegation_no_self CHECK (delegator_actor_id <> delegatee_actor_id)
);
CREATE INDEX IF NOT EXISTS delegations_active_idx
    ON delegations (delegatee_actor_id, expires_at)
    WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS delegations_scope_gin
    ON delegations USING GIN (scope);

-- -----------------------------------------------------------------------------
-- journeys — multi-session aggregate, the heart of v1
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS journeys (
    journey_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id                UUID NOT NULL REFERENCES actors(actor_id),
    beneficiary_actor_id    UUID REFERENCES actors(actor_id),
    project_id              TEXT NOT NULL,
    state                   journey_state NOT NULL DEFAULT 'open',
    started_at              TIMESTAMPTZ NOT NULL,
    ended_at                TIMESTAMPTZ,
    entry_event_id          UUID NOT NULL,
    entry_attribution       JSONB NOT NULL DEFAULT '{}'::jsonb,  -- frozen first-touch
    last_event_at           TIMESTAMPTZ NOT NULL,
    session_count           INT  NOT NULL DEFAULT 0,
    event_count             INT  NOT NULL DEFAULT 0,
    conversion_event_id     UUID,
    exit_reason             journey_exit_reason,
    preceded_by_journey_id  UUID REFERENCES journeys(journey_id),
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS journeys_actor_started_idx
    ON journeys (actor_id, started_at DESC);
CREATE INDEX IF NOT EXISTS journeys_project_state_last_idx
    ON journeys (project_id, state, last_event_at DESC);
CREATE INDEX IF NOT EXISTS journeys_open_by_actor_idx
    ON journeys (actor_id) WHERE state = 'open';

-- -----------------------------------------------------------------------------
-- journey_sessions — n-to-1 link table (a journey contains many sessions)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS journey_sessions (
    journey_id  UUID NOT NULL REFERENCES journeys(journey_id) ON DELETE CASCADE,
    session_id  TEXT NOT NULL,
    sequence    INT  NOT NULL,
    joined_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (journey_id, session_id)
);
CREATE INDEX IF NOT EXISTS journey_sessions_session_idx
    ON journey_sessions (session_id);

-- -----------------------------------------------------------------------------
-- journey_policies — per-project journey-boundary rules
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS journey_policies (
    project_id              TEXT PRIMARY KEY,
    inactivity_window_days  INT  NOT NULL DEFAULT 30,
    new_origin_breaks       BOOLEAN NOT NULL DEFAULT TRUE,
    conversion_event_types  TEXT[] NOT NULL DEFAULT ARRAY[
        'payment_completed', 'entitlement_granted', 'conversion'
    ],
    cross_journey_lookback_days INT NOT NULL DEFAULT 365,
    metadata                JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- attribution_policies — per-project actor-weighted credit configuration
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS attribution_policies (
    project_id          TEXT PRIMARY KEY,
    actor_weights       JSONB NOT NULL DEFAULT
        '{"human": 1.0, "agent": 0.4, "system": 0.1}'::jsonb,
    exposure_weight     NUMERIC(5,3) NOT NULL DEFAULT 0.100,
    multi_touch_model   TEXT NOT NULL DEFAULT 'linear', -- linear|position|time_decay
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- -----------------------------------------------------------------------------
-- updated_at triggers (idempotent helper)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_actors_updated   ON actors;
CREATE TRIGGER trg_actors_updated   BEFORE UPDATE ON actors
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_journeys_updated ON journeys;
CREATE TRIGGER trg_journeys_updated BEFORE UPDATE ON journeys
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMIT;
