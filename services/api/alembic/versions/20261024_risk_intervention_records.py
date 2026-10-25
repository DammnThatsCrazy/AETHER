"""Create the append-only tenant-scoped Risk360 intervention authority.

Revision ID: 20261024_risk_intervention_records
Revises: 20261024_merge_360_wave_heads
Create Date: 2026-10-24

Risk360 decisions and source-reported outcomes are separate immutable events.
The projection reads them; this table does not execute an intervention or
independently verify an externally reported effect.
"""

from __future__ import annotations

from alembic import op

revision = "20261024_risk_intervention_records"
down_revision = "20261024_merge_360_wave_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS risk_intervention_records (
            id TEXT PRIMARY KEY,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            tenant_id TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (jsonb_typeof(data) = 'object'),
            CHECK (length(btrim(tenant_id)) > 0),
            CHECK (data->>'tenant_id' = tenant_id),
            CHECK (data->>'record_id' IS NOT NULL AND length(btrim(data->>'record_id')) > 0),
            CHECK (id = tenant_id || ':' || (data->>'record_id')),
            CHECK (data->>'intervention_id' IS NOT NULL AND length(btrim(data->>'intervention_id')) > 0),
            CHECK (data->>'intervention_type' IS NOT NULL AND length(btrim(data->>'intervention_type')) > 0),
            CHECK (data->>'subject_kind' IS NOT NULL AND length(btrim(data->>'subject_kind')) > 0),
            CHECK (data->>'subject_id' IS NOT NULL AND length(btrim(data->>'subject_id')) > 0),
            CHECK (data->>'label' IS NOT NULL AND length(btrim(data->>'label')) > 0),
            CHECK (data->>'actor_id' IS NOT NULL AND length(btrim(data->>'actor_id')) > 0),
            CHECK (data->>'actor_kind' IS NOT NULL AND data->>'actor_kind' IN ('human', 'org', 'wallet', 'agent', 'service', 'system')),
            CHECK (data->>'source_system' IS NOT NULL AND length(btrim(data->>'source_system')) > 0),
            CHECK (data->>'source_record_id' IS NOT NULL AND length(btrim(data->>'source_record_id')) > 0),
            CHECK (data->>'observed_at' IS NOT NULL AND data->>'effective_at' IS NOT NULL AND data->>'recorded_at' IS NOT NULL),
            CHECK (data->>'record_kind' IS NOT NULL AND data->>'record_kind' IN ('decision', 'outcome')),
            CHECK (
                jsonb_typeof(data->'evidence_refs') = 'array'
                AND jsonb_array_length(data->'evidence_refs') > 0
                AND jsonb_typeof(data->'actor_evidence_refs') = 'array'
                AND jsonb_array_length(data->'actor_evidence_refs') > 0
            ),
            CHECK (
                (data->>'record_kind' = 'decision'
                    AND data->>'decision_state' IS NOT NULL
                    AND data->>'decision_state' IN ('proposed', 'approved', 'rejected', 'withdrawn')
                    AND data->>'reported_outcome' IS NULL
                    AND data->>'decision_record_id' IS NULL)
                OR
                (data->>'record_kind' = 'outcome'
                    AND data->>'reported_outcome' IS NOT NULL
                    AND data->>'reported_outcome' IN (
                        'reported_applied', 'reported_partially_applied',
                        'reported_failed', 'reported_not_applied'
                    )
                    AND data->>'decision_state' IS NULL
                    AND COALESCE(length(btrim(data->>'decision_record_id')), 0) > 0)
            )
        );
        CREATE INDEX IF NOT EXISTS ix_risk_intervention_subject_recorded
            ON risk_intervention_records (
                tenant_id,
                (data->>'subject_kind'),
                (data->>'subject_id'),
                ((data->>'recorded_at')::timestamptz) DESC,
                id ASC
            );
        CREATE INDEX IF NOT EXISTS ix_risk_intervention_id
            ON risk_intervention_records (tenant_id, (data->>'intervention_id'));
        CREATE OR REPLACE FUNCTION reject_risk_intervention_update()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'risk intervention records are append-only';
        END;
        $$ LANGUAGE plpgsql;
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_trigger
                WHERE tgname = 'trg_risk_intervention_records_append_only'
                  AND tgrelid = 'risk_intervention_records'::regclass
                  AND NOT tgisinternal
            ) THEN
                CREATE TRIGGER trg_risk_intervention_records_append_only
                    BEFORE UPDATE ON risk_intervention_records
                    FOR EACH ROW EXECUTE FUNCTION reject_risk_intervention_update();
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_risk_intervention_records_append_only
            ON risk_intervention_records;
        DROP FUNCTION IF EXISTS reject_risk_intervention_update();
        DROP INDEX IF EXISTS ix_risk_intervention_id;
        DROP INDEX IF EXISTS ix_risk_intervention_subject_recorded;
        DROP TABLE IF EXISTS risk_intervention_records;
        """
    )
