"""Append-only, tenant-scoped canonical commerce intent declarations.

Revision ID: 20261023_commerce_intent_authority
Revises: 20261022_risk_poisoning_evidence
Create Date: 2026-10-23

Commerce intent facts are explicit declarations about exact canonical product
or offer IDs. They retain actor, effective/observed times, source revision,
idempotency, and evidence. Behavioral views and checkout activity do not write
intent records.
"""

from alembic import op

revision = "20261023_commerce_intent_authority"
down_revision = "20261022_risk_poisoning_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS commerce_intent_records (
            tenant_id TEXT NOT NULL,
            intent_id TEXT NOT NULL,
            source_revision_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            subject_kind TEXT NOT NULL CHECK (subject_kind IN ('product', 'offer')),
            subject_id TEXT NOT NULL,
            intent_kind TEXT NOT NULL CHECK (
                intent_kind IN ('purchase', 'subscription', 'renewal', 'replenishment', 'comparison')
            ),
            lifecycle_state TEXT NOT NULL CHECK (
                lifecycle_state IN ('declared', 'active', 'fulfilled', 'abandoned', 'withdrawn', 'expired')
            ),
            actor_kind TEXT NOT NULL CHECK (
                actor_kind IN ('human', 'org', 'wallet', 'agent', 'service', 'system')
            ),
            actor_id TEXT NOT NULL,
            effective_at TIMESTAMPTZ NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL,
            source_provider TEXT NOT NULL,
            source_record_id TEXT NOT NULL,
            evidence_refs JSONB NOT NULL,
            data JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, intent_id, source_revision_id),
            UNIQUE (tenant_id, idempotency_key),
            CHECK (
                length(btrim(tenant_id)) > 0 AND length(btrim(intent_id)) > 0
                AND length(btrim(source_revision_id)) > 0
                AND length(btrim(idempotency_key)) > 0
            ),
            CHECK (length(btrim(subject_id)) > 0 AND length(btrim(actor_id)) > 0),
            CHECK (
                length(btrim(source_provider)) > 0 AND length(btrim(source_record_id)) > 0
            ),
            CHECK (jsonb_typeof(evidence_refs) = 'array' AND jsonb_array_length(evidence_refs) > 0),
            CHECK (jsonb_typeof(data) = 'object')
        );
        CREATE INDEX IF NOT EXISTS commerce_intent_subject_asof
            ON commerce_intent_records
                (tenant_id, subject_kind, subject_id, effective_at DESC, observed_at DESC);
        CREATE INDEX IF NOT EXISTS commerce_intent_revision_asof
            ON commerce_intent_records
                (tenant_id, intent_id, effective_at DESC, observed_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS commerce_intent_revision_asof;")
    op.execute("DROP INDEX IF EXISTS commerce_intent_subject_asof;")
    op.execute("DROP TABLE IF EXISTS commerce_intent_records;")
