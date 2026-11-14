"""Append-only Social360 trust and contagion evidence ledger.

Revision ID: 20261024_social_relationship_evidence_authority
Revises: 20261024_merge_360_wave_heads
Create Date: 2026-10-24

The ledger stores exact tenant-scoped evidence assertions. It does not mutate
the graph and does not treat correlation as causal contagion.
"""

from alembic import op

revision = "20261024_social_relationship_evidence_authority"
down_revision = "20261024_merge_360_wave_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS social_relationship_evidence_events (
            tenant_id TEXT NOT NULL,
            record_id UUID NOT NULL,
            assertion_kind TEXT NOT NULL CHECK (
                assertion_kind IN ('trust_edge', 'social_contagion')
            ),
            subject_entity_id TEXT NOT NULL,
            source_entity_id TEXT NOT NULL,
            target_entity_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            source_observation_id TEXT NOT NULL,
            source_revision_id TEXT NOT NULL,
            source_event_id TEXT NOT NULL,
            observed_at TIMESTAMPTZ NOT NULL,
            effective_at TIMESTAMPTZ NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, record_id),
            UNIQUE (tenant_id, source_id, source_event_id),
            CHECK (
                length(btrim(tenant_id)) > 0
                AND length(btrim(subject_entity_id)) > 0
                AND length(btrim(source_entity_id)) > 0
                AND length(btrim(target_entity_id)) > 0
                AND length(btrim(source_id)) > 0
                AND length(btrim(source_observation_id)) > 0
                AND length(btrim(source_revision_id)) > 0
                AND length(btrim(source_event_id)) > 0
            ),
            CHECK (source_entity_id <> target_entity_id),
            CHECK (jsonb_typeof(payload) = 'object'),
            CHECK (payload->>'tenant_id' = tenant_id),
            CHECK (payload->>'record_id' = record_id::text),
            CHECK (payload->>'subject_entity_id' = subject_entity_id)
        );

        CREATE INDEX IF NOT EXISTS social_relationship_evidence_subject_kind_effective
            ON social_relationship_evidence_events (
                tenant_id, subject_entity_id, assertion_kind,
                effective_at DESC, recorded_at DESC, record_id DESC
            );
        CREATE INDEX IF NOT EXISTS social_relationship_evidence_path_subjects
            ON social_relationship_evidence_events (
                tenant_id, source_entity_id, target_entity_id,
                assertion_kind, effective_at DESC
            );

        CREATE OR REPLACE FUNCTION reject_social_relationship_evidence_event_update()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'social_relationship_evidence_events is append-only';
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS social_relationship_evidence_events_append_only
            ON social_relationship_evidence_events;
        CREATE TRIGGER social_relationship_evidence_events_append_only
            BEFORE UPDATE ON social_relationship_evidence_events
            FOR EACH ROW EXECUTE FUNCTION reject_social_relationship_evidence_event_update();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS social_relationship_evidence_events;
        DROP FUNCTION IF EXISTS reject_social_relationship_evidence_event_update();
        """
    )
