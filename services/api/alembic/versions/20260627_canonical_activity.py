"""Canonical activity ledger and first-class journey steps.

Revision ID: ca001b2c3d4e
Revises: m1e2a3s4u5r6
Create Date: 2026-06-27

Introduces two new tables and extends journey_versions:

  canonical_activity  — unified cross-rail activity ledger (Web2, Web3, campaign,
                        commerce, agent, x402, outcome) consumed by the journey compiler
  journey_steps       — first-class ordered steps within a journey version, individually
                        queryable and filterable without loading the full JSONB blob

Extends journey_versions with:
  step_count          — denormalized count for fast summary reads
  web3_activity_ids   — array of activity_ids for web3 family
  agent_activity_ids  — array of activity_ids for agent family
  x402_activity_ids   — array of activity_ids for x402 family

Design principles:
  - tenant_id on every row; no row is ever accessible without a tenant predicate
  - idempotency_key (tenant_id, idempotency_key) UNIQUE on canonical_activity for
    safe replay from any source
  - silver_fact_id / silver_table provide lineage back to the originating silver row
  - journey_steps references canonical_activity(activity_id) and is rebuilt wholesale
    for each new journey_version — steps from prior versions are never mutated
  - Monetary amounts use NUMERIC(20,6) matching the measurement_core convention
  - All TIMESTAMPTZ columns, no bare TIMESTAMP
"""

from __future__ import annotations

from alembic import op

revision = "ca001b2c3d4e"
down_revision = "m1e2a3s4u5r6"
branch_labels = None
depends_on = None


def upgrade() -> None:

    # ── 1. canonical_activity ────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS canonical_activity (
            activity_id          UUID         NOT NULL DEFAULT gen_random_uuid(),
            tenant_id            TEXT         NOT NULL,
            idempotency_key      TEXT         NOT NULL,

            -- Identity links (all optional; at least one must be set)
            profile_id           TEXT,
            cluster_id           TEXT,
            anonymous_id         TEXT,
            account_id           TEXT,
            organization_id      TEXT,
            session_id           TEXT,
            device_id            TEXT,
            browser_id           TEXT,
            install_id           TEXT,
            wallet_id            TEXT,
            wallet_address       TEXT,
            agent_id             TEXT,

            -- Classification
            activity_family      TEXT         NOT NULL,
            activity_type        TEXT         NOT NULL,
            actor_type           TEXT,

            -- Surface / location
            channel              TEXT,
            source               TEXT,
            medium               TEXT,
            platform             TEXT,
            domain               TEXT,
            app_id               TEXT,
            screen               TEXT,
            landing_url          TEXT,
            referrer             TEXT,
            dapp_id              TEXT,
            protocol_id          TEXT,
            chain_id             TEXT,
            contract_address     TEXT,

            -- Web3 specifics
            tx_hash              TEXT,
            block_number         BIGINT,

            -- Campaign linkage
            campaign_id          TEXT,
            conversion_id        TEXT,

            -- Timing
            occurred_at          TIMESTAMPTZ  NOT NULL,
            client_occurred_at   TIMESTAMPTZ,
            server_received_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
            chain_observed_at    TIMESTAMPTZ,
            chain_confirmed_at   TIMESTAMPTZ,

            -- Lifecycle status
            activity_status      TEXT         NOT NULL DEFAULT 'observed',

            -- Provenance
            source_event_id      TEXT         NOT NULL,
            source_system        TEXT,
            source_connector_id  TEXT,

            -- Identity evidence
            identity_method      TEXT,
            identity_confidence  NUMERIC(5,4),
            identity_version     TEXT,
            consent_snapshot_id  TEXT,
            privacy_class        TEXT         NOT NULL DEFAULT 'behavioral',

            -- Ordering / replay
            sequence_key         TEXT,
            schema_version       INTEGER      NOT NULL DEFAULT 1,
            processed_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),

            -- Silver lineage
            silver_fact_id       UUID,
            silver_table         TEXT,

            -- Economic semantics (family-specific; NULL when not applicable)
            gross_amount         NUMERIC(20,6),
            net_amount           NUMERIC(20,6),
            fee_amount           NUMERIC(20,6),
            currency             TEXT,
            token_address        TEXT,
            value_wei            TEXT,

            -- Constraints
            CONSTRAINT canonical_activity_pk       PRIMARY KEY (activity_id),
            CONSTRAINT canonical_activity_idem     UNIQUE (tenant_id, idempotency_key),
            CONSTRAINT canonical_activity_tenant   UNIQUE (tenant_id, activity_id)
        );

        -- Journey compiler: load all activity for a profile ordered by time
        CREATE INDEX IF NOT EXISTS ca_profile_time
            ON canonical_activity (tenant_id, profile_id, occurred_at ASC)
            WHERE profile_id IS NOT NULL;

        CREATE INDEX IF NOT EXISTS ca_anonymous_time
            ON canonical_activity (tenant_id, anonymous_id, occurred_at ASC)
            WHERE anonymous_id IS NOT NULL;

        CREATE INDEX IF NOT EXISTS ca_cluster_time
            ON canonical_activity (tenant_id, cluster_id, occurred_at ASC)
            WHERE cluster_id IS NOT NULL;

        CREATE INDEX IF NOT EXISTS ca_wallet_time
            ON canonical_activity (tenant_id, wallet_id, occurred_at ASC)
            WHERE wallet_id IS NOT NULL;

        CREATE INDEX IF NOT EXISTS ca_agent_time
            ON canonical_activity (tenant_id, agent_id, occurred_at ASC)
            WHERE agent_id IS NOT NULL;

        CREATE INDEX IF NOT EXISTS ca_campaign_time
            ON canonical_activity (tenant_id, campaign_id, occurred_at ASC)
            WHERE campaign_id IS NOT NULL;

        -- Session-level queries
        CREATE INDEX IF NOT EXISTS ca_session
            ON canonical_activity (tenant_id, session_id)
            WHERE session_id IS NOT NULL;

        -- Web3 lookup by tx_hash
        CREATE INDEX IF NOT EXISTS ca_tx_hash
            ON canonical_activity (tenant_id, tx_hash)
            WHERE tx_hash IS NOT NULL;

        -- Family + time (for range queries)
        CREATE INDEX IF NOT EXISTS ca_family_time
            ON canonical_activity (tenant_id, activity_family, occurred_at ASC);

        -- Status queries (reorg sweeps, consent rebuilds)
        CREATE INDEX IF NOT EXISTS ca_status_time
            ON canonical_activity (tenant_id, activity_status, occurred_at ASC);

        -- Silver lineage lookups
        CREATE INDEX IF NOT EXISTS ca_silver_fact
            ON canonical_activity (silver_fact_id)
            WHERE silver_fact_id IS NOT NULL;
    """)

    # ── 2. journey_steps ─────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS journey_steps (
            step_id              UUID         NOT NULL DEFAULT gen_random_uuid(),
            tenant_id            TEXT         NOT NULL,
            journey_id           UUID         NOT NULL,
            journey_version_id   UUID         NOT NULL,
            profile_id           TEXT,
            cluster_id           TEXT,

            -- Ordering within the journey version
            step_position        INTEGER      NOT NULL,
            occurred_at          TIMESTAMPTZ  NOT NULL,

            -- Reference to canonical activity
            activity_id          UUID         NOT NULL,
            activity_family      TEXT         NOT NULL,
            activity_type        TEXT         NOT NULL,

            -- Transition classification from the prior step
            transition_type      TEXT,
            transition_evidence  JSONB        NOT NULL DEFAULT '{}'::jsonb,

            -- Denormalized display fields (avoid joins on hot list path)
            actor_type           TEXT,
            channel              TEXT,
            source               TEXT,
            domain               TEXT,
            app_id               TEXT,
            dapp_id              TEXT,
            chain_id             TEXT,
            campaign_id          TEXT,
            conversion_id        TEXT,
            wallet_id            TEXT,
            agent_id             TEXT,
            session_id           TEXT,
            device_id            TEXT,
            activity_status      TEXT         NOT NULL DEFAULT 'observed',

            -- Identity evidence summary
            identity_confidence  NUMERIC(5,4),
            identity_method      TEXT,
            identity_version     TEXT,
            evidence_summary     JSONB        NOT NULL DEFAULT '{}'::jsonb,

            schema_version       INTEGER      NOT NULL DEFAULT 1,
            created_at           TIMESTAMPTZ  NOT NULL DEFAULT now(),

            CONSTRAINT journey_steps_pk
                PRIMARY KEY (step_id),
            CONSTRAINT journey_steps_tenant_step
                UNIQUE (tenant_id, step_id),
            CONSTRAINT journey_steps_version_position
                UNIQUE (tenant_id, journey_version_id, step_position),
            CONSTRAINT journey_steps_activity_fk
                FOREIGN KEY (activity_id) REFERENCES canonical_activity(activity_id)
        );

        -- Primary access pattern: ordered steps for a journey version
        CREATE INDEX IF NOT EXISTS js_version_position
            ON journey_steps (tenant_id, journey_version_id, step_position ASC);

        -- Journey-level summary
        CREATE INDEX IF NOT EXISTS js_journey_position
            ON journey_steps (tenant_id, journey_id, step_position ASC);

        -- Profile timeline (cross-journey)
        CREATE INDEX IF NOT EXISTS js_profile_time
            ON journey_steps (tenant_id, profile_id, occurred_at ASC)
            WHERE profile_id IS NOT NULL;

        -- Filter indexes
        CREATE INDEX IF NOT EXISTS js_family_time
            ON journey_steps (tenant_id, activity_family, occurred_at ASC);

        CREATE INDEX IF NOT EXISTS js_campaign
            ON journey_steps (tenant_id, campaign_id)
            WHERE campaign_id IS NOT NULL;

        CREATE INDEX IF NOT EXISTS js_wallet
            ON journey_steps (tenant_id, wallet_id)
            WHERE wallet_id IS NOT NULL;

        CREATE INDEX IF NOT EXISTS js_session
            ON journey_steps (tenant_id, session_id)
            WHERE session_id IS NOT NULL;

        CREATE INDEX IF NOT EXISTS js_chain
            ON journey_steps (tenant_id, chain_id)
            WHERE chain_id IS NOT NULL;

        CREATE INDEX IF NOT EXISTS js_status
            ON journey_steps (tenant_id, activity_status)
            WHERE activity_status != 'observed';
    """)

    # ── 3. Extend journey_versions ───────────────────────────────────────────
    op.execute("""
        ALTER TABLE journey_versions
            ADD COLUMN IF NOT EXISTS step_count         INTEGER      NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS web3_activity_ids  TEXT[]       NOT NULL DEFAULT '{}',
            ADD COLUMN IF NOT EXISTS agent_activity_ids TEXT[]       NOT NULL DEFAULT '{}',
            ADD COLUMN IF NOT EXISTS x402_activity_ids  TEXT[]       NOT NULL DEFAULT '{}';
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE journey_versions DROP COLUMN IF EXISTS step_count;")
    op.execute("ALTER TABLE journey_versions DROP COLUMN IF EXISTS web3_activity_ids;")
    op.execute("ALTER TABLE journey_versions DROP COLUMN IF EXISTS agent_activity_ids;")
    op.execute("ALTER TABLE journey_versions DROP COLUMN IF EXISTS x402_activity_ids;")
    op.execute("DROP TABLE IF EXISTS journey_steps CASCADE;")
    op.execute("DROP TABLE IF EXISTS canonical_activity CASCADE;")
