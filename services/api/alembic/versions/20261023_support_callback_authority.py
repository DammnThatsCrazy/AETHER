"""Canonical tenant-scoped support callback schedule and execution evidence.

Revision ID: 20261023_support_callback_authority
Revises: 20261022_risk_poisoning_evidence
Create Date: 2026-10-23

Callbacks are connection-scoped source records bound to the canonical SupportCase
and backed by an append-only event ledger.
"""

from alembic import op

revision = "20261023_support_callback_authority"
down_revision = "20261022_risk_poisoning_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'support_cases_tenant_case_connection_uq'
                  AND conrelid = 'support_cases'::regclass
            ) THEN
                ALTER TABLE support_cases
                    ADD CONSTRAINT support_cases_tenant_case_connection_uq
                    UNIQUE (tenant_id, case_id, source_connection_id);
            END IF;
        END $$;

        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'support_case_events_tenant_case_connection_event_uq'
                  AND conrelid = 'support_case_events'::regclass
            ) THEN
                ALTER TABLE support_case_events
                    ADD CONSTRAINT support_case_events_tenant_case_connection_event_uq
                    UNIQUE (tenant_id, case_id, source_connection_id, source_event_id);
            END IF;
        END $$;

        CREATE TABLE IF NOT EXISTS support_callbacks (
            tenant_id TEXT NOT NULL,
            callback_id UUID NOT NULL,
            case_id UUID NOT NULL,
            source_connection_id TEXT NOT NULL,
            source_provider_identity TEXT NOT NULL,
            source_callback_id TEXT NOT NULL,
            callback_state TEXT NOT NULL CHECK (
                callback_state IN ('scheduled', 'attempted', 'completed', 'failed', 'cancelled')
            ),
            scheduled_for TIMESTAMPTZ NOT NULL,
            schedule_observed_at TIMESTAMPTZ NOT NULL,
            latest_event_occurred_at TIMESTAMPTZ NOT NULL,
            first_observed_at TIMESTAMPTZ NOT NULL,
            last_observed_at TIMESTAMPTZ NOT NULL,
            last_source_event_id TEXT NOT NULL,
            event_count INTEGER NOT NULL DEFAULT 0 CHECK (event_count >= 0),
            retention_class TEXT NOT NULL,
            retention_expires_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, callback_id),
            UNIQUE (tenant_id, source_connection_id, source_callback_id),
            UNIQUE (tenant_id, callback_id, case_id, source_connection_id),
            FOREIGN KEY (tenant_id, case_id, source_connection_id)
                REFERENCES support_cases (tenant_id, case_id, source_connection_id)
                ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS support_callbacks_tenant_case_schedule
            ON support_callbacks (tenant_id, case_id, scheduled_for DESC, callback_id DESC);
        CREATE INDEX IF NOT EXISTS support_callbacks_retention_expiry
            ON support_callbacks (retention_expires_at ASC);

        CREATE TABLE IF NOT EXISTS support_callback_events (
            tenant_id TEXT NOT NULL,
            callback_id UUID NOT NULL,
            case_id UUID NOT NULL,
            source_connection_id TEXT NOT NULL,
            source_event_id TEXT NOT NULL,
            case_source_event_id TEXT NOT NULL,
            event_type TEXT NOT NULL CHECK (
                event_type IN (
                    'support_callback_scheduled', 'support_callback_rescheduled',
                    'support_callback_attempted', 'support_callback_completed',
                    'support_callback_failed', 'support_callback_cancelled'
                )
            ),
            source_occurred_at TIMESTAMPTZ NOT NULL,
            received_at TIMESTAMPTZ NOT NULL,
            scheduled_for TIMESTAMPTZ,
            state_applied BOOLEAN NOT NULL,
            evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
            PRIMARY KEY (tenant_id, source_connection_id, source_event_id),
            FOREIGN KEY (tenant_id, callback_id, case_id, source_connection_id)
                REFERENCES support_callbacks (tenant_id, callback_id, case_id, source_connection_id)
                ON DELETE CASCADE,
            FOREIGN KEY (tenant_id, case_id, source_connection_id, case_source_event_id)
                REFERENCES support_case_events (tenant_id, case_id, source_connection_id, source_event_id),
            CHECK (
                (event_type IN ('support_callback_scheduled', 'support_callback_rescheduled')
                    AND scheduled_for IS NOT NULL)
                OR (event_type NOT IN ('support_callback_scheduled', 'support_callback_rescheduled')
                    AND scheduled_for IS NULL)
            )
        );
        CREATE INDEX IF NOT EXISTS support_callback_events_tenant_case_time
            ON support_callback_events (
                tenant_id, case_id, callback_id, source_occurred_at DESC, received_at DESC
            );

        CREATE OR REPLACE FUNCTION reject_support_callback_event_update()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'support_callback_events is append-only';
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS support_callback_events_append_only
            ON support_callback_events;
        CREATE TRIGGER support_callback_events_append_only
            BEFORE UPDATE ON support_callback_events
            FOR EACH ROW EXECUTE FUNCTION reject_support_callback_event_update();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS support_callback_events;
        DROP TABLE IF EXISTS support_callbacks;
        DROP FUNCTION IF EXISTS reject_support_callback_event_update();
        ALTER TABLE support_case_events
            DROP CONSTRAINT IF EXISTS support_case_events_tenant_case_connection_event_uq;
        ALTER TABLE support_cases
            DROP CONSTRAINT IF EXISTS support_cases_tenant_case_connection_uq;
        """
    )
