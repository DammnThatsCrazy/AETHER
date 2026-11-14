"""Append-only, canonical Support360 agent assignment and handoff evidence.

Revision ID: 20261024_support_agent_assignment_authority
Revises: 20261024_merge_360_wave_heads
Create Date: 2026-10-24

Assignment event rows are tenant/case/provider-connection scoped. A case hard
erase cascades to its assignment history; ordinary updates cannot rewrite an
accepted source observation.
"""

from alembic import op

revision = "20261024_support_agent_assignment_authority"
down_revision = "20261024_merge_360_wave_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS support_case_agent_assignment_events (
            tenant_id TEXT NOT NULL,
            assignment_event_id UUID NOT NULL,
            case_id UUID NOT NULL,
            source_connection_id TEXT NOT NULL,
            source_provider_identity TEXT NOT NULL,
            source_assignment_id TEXT NOT NULL,
            source_revision_id TEXT NOT NULL,
            source_event_id TEXT NOT NULL,
            event_type TEXT NOT NULL CHECK (
                event_type IN (
                    'support_agent_assigned',
                    'support_agent_handoff',
                    'support_agent_unassigned'
                )
            ),
            agent_entity_id TEXT,
            previous_agent_entity_id TEXT,
            assigning_principal_id TEXT NOT NULL,
            assigning_principal_type TEXT NOT NULL,
            source_observed_at TIMESTAMPTZ NOT NULL,
            effective_at TIMESTAMPTZ NOT NULL,
            received_at TIMESTAMPTZ NOT NULL,
            evidence_refs JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, assignment_event_id),
            UNIQUE (tenant_id, source_connection_id, source_event_id),
            UNIQUE (
                tenant_id, case_id, source_connection_id,
                source_assignment_id, source_revision_id
            ),
            FOREIGN KEY (tenant_id, case_id, source_connection_id)
                REFERENCES support_cases (tenant_id, case_id, source_connection_id)
                ON DELETE CASCADE,
            CHECK (
                length(btrim(tenant_id)) > 0
                AND length(btrim(source_connection_id)) > 0
                AND length(btrim(source_provider_identity)) > 0
                AND length(btrim(source_assignment_id)) > 0
                AND length(btrim(source_revision_id)) > 0
                AND length(btrim(source_event_id)) > 0
                AND length(btrim(assigning_principal_id)) > 0
                AND length(btrim(assigning_principal_type)) > 0
            ),
            CHECK (jsonb_typeof(evidence_refs) = 'array' AND jsonb_array_length(evidence_refs) > 0),
            CHECK (
                (event_type = 'support_agent_assigned'
                    AND agent_entity_id IS NOT NULL
                    AND previous_agent_entity_id IS NULL)
                OR (event_type = 'support_agent_handoff'
                    AND agent_entity_id IS NOT NULL
                    AND previous_agent_entity_id IS NOT NULL
                    AND agent_entity_id <> previous_agent_entity_id)
                OR (event_type = 'support_agent_unassigned'
                    AND agent_entity_id IS NULL
                    AND previous_agent_entity_id IS NOT NULL)
            )
        );
        CREATE INDEX IF NOT EXISTS support_case_agent_assignments_case_effective
            ON support_case_agent_assignment_events (
                tenant_id, case_id, source_connection_id,
                effective_at DESC, received_at DESC, assignment_event_id DESC
            );
        CREATE INDEX IF NOT EXISTS support_case_agent_assignments_agent_effective
            ON support_case_agent_assignment_events (
                tenant_id, agent_entity_id, effective_at DESC
            ) WHERE agent_entity_id IS NOT NULL;

        CREATE OR REPLACE FUNCTION reject_support_case_agent_assignment_event_update()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'support_case_agent_assignment_events is append-only';
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS support_case_agent_assignment_events_append_only
            ON support_case_agent_assignment_events;
        CREATE TRIGGER support_case_agent_assignment_events_append_only
            BEFORE UPDATE ON support_case_agent_assignment_events
            FOR EACH ROW EXECUTE FUNCTION reject_support_case_agent_assignment_event_update();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS support_case_agent_assignment_events;
        DROP FUNCTION IF EXISTS reject_support_case_agent_assignment_event_update();
        """
    )
