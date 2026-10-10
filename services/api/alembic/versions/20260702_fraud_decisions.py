"""Durable FraudDecision ledger and risk annotation columns.

Revision ID: 20260702_fraud_decisions
Revises: 20260702_delivery_infra
Create Date: 2026-07-02

Creates:
  fraud_decisions        — versioned, tenant-isolated fraud decision ledger
  fraud_decision_subjects — N:M link from decisions to activity/journey/wallet/agent

Extends:
  canonical_activity     — risk annotation columns (risk_score, risk_tier, fraud_status …)
  journey_steps          — matching risk annotation columns
"""

from __future__ import annotations

from alembic import op

revision = "20260702_fraud_decisions"
down_revision = "20260702_delivery_infra"
branch_labels = None
depends_on = None


def upgrade() -> None:

    # ── 1. fraud_decisions ───────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS fraud_decisions (
            decision_id             UUID         NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               TEXT         NOT NULL,

            -- Primary subject (one of entity, activity, journey, wallet, agent, cluster)
            subject_type            TEXT         NOT NULL,
            subject_id              TEXT         NOT NULL,

            -- Optional cross-rail links
            entity_id               TEXT,
            profile_id              TEXT,
            cluster_id              TEXT,
            wallet_id               TEXT,
            agent_id                TEXT,
            activity_id             UUID,
            journey_id              UUID,
            journey_version_id      UUID,

            -- Related fraud constructs
            fraud_network_ids       TEXT[]       NOT NULL DEFAULT '{}',
            flow_trace_ids          TEXT[]       NOT NULL DEFAULT '{}',

            -- Decision outcome
            decision                TEXT         NOT NULL,          -- allow|monitor|review|hold|block|suppress|escalate
            risk_score              NUMERIC(6,2) NOT NULL,
            risk_tier               TEXT         NOT NULL,          -- low|medium|high|critical
            signal_types            TEXT[]       NOT NULL DEFAULT '{}',
            reason_codes            TEXT[]       NOT NULL DEFAULT '{}',
            evidence_refs           JSONB        NOT NULL DEFAULT '[]'::jsonb,
            human_explanation       TEXT,
            machine_explanation     TEXT,

            -- Versioning
            detector_versions       JSONB        NOT NULL DEFAULT '{}'::jsonb,
            model_versions          JSONB        NOT NULL DEFAULT '{}'::jsonb,
            policy_version          TEXT         NOT NULL DEFAULT 'v1',

            -- Lifecycle
            evaluation_state        TEXT         NOT NULL DEFAULT 'evaluated',
            evaluated_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
            valid_from              TIMESTAMPTZ  NOT NULL DEFAULT now(),
            valid_until             TIMESTAMPTZ,
            status                  TEXT         NOT NULL DEFAULT 'active',

            -- Supersession chain
            supersedes_decision_id  UUID,
            superseded_by_decision_id UUID,

            -- Human review
            review_state            TEXT         NOT NULL DEFAULT 'not_required',
            reviewed_by             TEXT,
            reviewed_at             TIMESTAMPTZ,
            suppression_reason      TEXT,

            metadata                JSONB        NOT NULL DEFAULT '{}'::jsonb,
            created_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),

            CONSTRAINT fraud_decisions_pk
                PRIMARY KEY (decision_id),
            CONSTRAINT fraud_decisions_tenant
                UNIQUE (tenant_id, decision_id)
        );

        -- Primary lookup: current decision for a subject
        CREATE INDEX IF NOT EXISTS fd_subject
            ON fraud_decisions (tenant_id, subject_type, subject_id, evaluated_at DESC)
            WHERE status = 'active';

        -- Entity lookup
        CREATE INDEX IF NOT EXISTS fd_entity
            ON fraud_decisions (tenant_id, entity_id, evaluated_at DESC)
            WHERE entity_id IS NOT NULL;

        -- Activity lookup
        CREATE INDEX IF NOT EXISTS fd_activity
            ON fraud_decisions (tenant_id, activity_id, evaluated_at DESC)
            WHERE activity_id IS NOT NULL;

        -- Journey lookup
        CREATE INDEX IF NOT EXISTS fd_journey
            ON fraud_decisions (tenant_id, journey_id, evaluated_at DESC)
            WHERE journey_id IS NOT NULL;

        -- Wallet lookup
        CREATE INDEX IF NOT EXISTS fd_wallet
            ON fraud_decisions (tenant_id, wallet_id, evaluated_at DESC)
            WHERE wallet_id IS NOT NULL;

        -- Agent lookup
        CREATE INDEX IF NOT EXISTS fd_agent
            ON fraud_decisions (tenant_id, agent_id, evaluated_at DESC)
            WHERE agent_id IS NOT NULL;

        -- Risk tier queries
        CREATE INDEX IF NOT EXISTS fd_risk_tier
            ON fraud_decisions (tenant_id, risk_tier, evaluated_at DESC)
            WHERE status = 'active';

        -- Review queue
        CREATE INDEX IF NOT EXISTS fd_review_state
            ON fraud_decisions (tenant_id, review_state, created_at DESC)
            WHERE review_state IN ('required', 'in_review');

        -- Supersession chain
        CREATE INDEX IF NOT EXISTS fd_supersedes
            ON fraud_decisions (supersedes_decision_id)
            WHERE supersedes_decision_id IS NOT NULL;
    """)

    # ── 2. Risk annotation columns on canonical_activity ────────────────────
    op.execute("""
        ALTER TABLE canonical_activity
            ADD COLUMN IF NOT EXISTS risk_score           NUMERIC(6,2),
            ADD COLUMN IF NOT EXISTS risk_tier            TEXT,
            ADD COLUMN IF NOT EXISTS fraud_status         TEXT,
            ADD COLUMN IF NOT EXISTS fraud_disposition    TEXT,
            ADD COLUMN IF NOT EXISTS fraud_decision_id    UUID,
            ADD COLUMN IF NOT EXISTS fraud_network_ids    TEXT[]       NOT NULL DEFAULT '{}',
            ADD COLUMN IF NOT EXISTS fraud_signal_types   TEXT[]       NOT NULL DEFAULT '{}',
            ADD COLUMN IF NOT EXISTS fraud_evidence_refs  JSONB        NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN IF NOT EXISTS risk_evaluated_at    TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS risk_model_version   TEXT,
            ADD COLUMN IF NOT EXISTS risk_policy_version  TEXT,
            ADD COLUMN IF NOT EXISTS risk_explanation     TEXT,
            ADD COLUMN IF NOT EXISTS risk_evaluation_state TEXT        NOT NULL DEFAULT 'not_evaluated';

        -- Risk queries on activity
        CREATE INDEX IF NOT EXISTS ca_risk_tier
            ON canonical_activity (tenant_id, risk_tier, occurred_at DESC)
            WHERE risk_tier IS NOT NULL;

        CREATE INDEX IF NOT EXISTS ca_fraud_decision
            ON canonical_activity (fraud_decision_id)
            WHERE fraud_decision_id IS NOT NULL;

        CREATE INDEX IF NOT EXISTS ca_risk_eval_state
            ON canonical_activity (tenant_id, risk_evaluation_state, occurred_at DESC)
            WHERE risk_evaluation_state != 'not_evaluated';
    """)

    # ── 3. Risk annotation columns on journey_steps ──────────────────────────
    op.execute("""
        ALTER TABLE journey_steps
            ADD COLUMN IF NOT EXISTS risk_score           NUMERIC(6,2),
            ADD COLUMN IF NOT EXISTS risk_tier            TEXT,
            ADD COLUMN IF NOT EXISTS fraud_status         TEXT,
            ADD COLUMN IF NOT EXISTS fraud_disposition    TEXT,
            ADD COLUMN IF NOT EXISTS fraud_decision_id    UUID,
            ADD COLUMN IF NOT EXISTS fraud_network_ids    TEXT[]       NOT NULL DEFAULT '{}',
            ADD COLUMN IF NOT EXISTS fraud_signal_types   TEXT[]       NOT NULL DEFAULT '{}',
            ADD COLUMN IF NOT EXISTS fraud_evidence_refs  JSONB        NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN IF NOT EXISTS risk_evaluated_at    TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS risk_model_version   TEXT,
            ADD COLUMN IF NOT EXISTS risk_policy_version  TEXT,
            ADD COLUMN IF NOT EXISTS risk_explanation     TEXT,
            ADD COLUMN IF NOT EXISTS risk_evaluation_state TEXT        NOT NULL DEFAULT 'not_evaluated';

        -- Risk queries on steps
        CREATE INDEX IF NOT EXISTS js_risk_tier
            ON journey_steps (tenant_id, risk_tier, occurred_at DESC)
            WHERE risk_tier IS NOT NULL;

        CREATE INDEX IF NOT EXISTS js_fraud_decision
            ON journey_steps (fraud_decision_id)
            WHERE fraud_decision_id IS NOT NULL;
    """)


def downgrade() -> None:
    # Remove risk columns from journey_steps
    for col in [
        "risk_score", "risk_tier", "fraud_status", "fraud_disposition",
        "fraud_decision_id", "fraud_network_ids", "fraud_signal_types",
        "fraud_evidence_refs", "risk_evaluated_at", "risk_model_version",
        "risk_policy_version", "risk_explanation", "risk_evaluation_state",
    ]:
        op.execute(f"ALTER TABLE journey_steps DROP COLUMN IF EXISTS {col};")

    # Remove risk columns from canonical_activity
    for col in [
        "risk_score", "risk_tier", "fraud_status", "fraud_disposition",
        "fraud_decision_id", "fraud_network_ids", "fraud_signal_types",
        "fraud_evidence_refs", "risk_evaluated_at", "risk_model_version",
        "risk_policy_version", "risk_explanation", "risk_evaluation_state",
    ]:
        op.execute(f"ALTER TABLE canonical_activity DROP COLUMN IF EXISTS {col};")

    op.execute("DROP TABLE IF EXISTS fraud_decisions CASCADE;")
