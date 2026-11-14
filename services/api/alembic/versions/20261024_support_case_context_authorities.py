"""Append-only support SLA and journey-link observations.

Revision ID: 20261024_support_case_context_authorities
Revises: 20261024_support_agent_assignment_authority
Create Date: 2026-10-24

These exact case/provider-scoped observations fill Support360 joins that had no
canonical source. Participant bindings remain in Communication360's authenticated
participant fact authority. Hard case erasure cascades through this ledger.
"""

from alembic import op

revision = "20261024_support_case_context_authorities"
down_revision = "20261024_support_agent_assignment_authority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS support_case_context_events (
            tenant_id TEXT NOT NULL,
            context_event_id UUID NOT NULL,
            case_id UUID NOT NULL,
            source_connection_id TEXT NOT NULL,
            source_provider_identity TEXT NOT NULL,
            context_kind TEXT NOT NULL CHECK (
                context_kind IN ('sla', 'journey_links')
            ),
            source_record_id TEXT NOT NULL,
            source_revision_id TEXT NOT NULL,
            source_item_id TEXT NOT NULL,
            source_event_id TEXT NOT NULL,
            event_type TEXT NOT NULL CHECK (
                event_type IN (
                    'support_sla_contract_observed',
                    'support_sla_timer_started',
                    'support_sla_timer_paused',
                    'support_sla_timer_resumed',
                    'support_sla_timer_met',
                    'support_sla_timer_breached',
                    'support_sla_timer_cancelled',
                    'support_sla_contract_withdrawn',
                    'support_case_journey_linked',
                    'support_case_journey_unlinked'
                )
            ),
            actor_id TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            source_observed_at TIMESTAMPTZ NOT NULL,
            effective_at TIMESTAMPTZ NOT NULL,
            received_at TIMESTAMPTZ NOT NULL,
            payload JSONB NOT NULL,
            evidence_refs JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, context_event_id),
            UNIQUE (tenant_id, source_connection_id, source_event_id),
            UNIQUE (
                tenant_id, case_id, source_connection_id, context_kind,
                source_record_id, source_revision_id, source_item_id
            ),
            FOREIGN KEY (tenant_id, case_id, source_connection_id)
                REFERENCES support_cases (tenant_id, case_id, source_connection_id)
                ON DELETE CASCADE,
            CHECK (
                length(btrim(tenant_id)) > 0
                AND length(btrim(source_connection_id)) > 0
                AND length(btrim(source_provider_identity)) > 0
                AND length(btrim(source_record_id)) > 0
                AND length(btrim(source_revision_id)) > 0
                AND length(btrim(source_item_id)) > 0
                AND length(btrim(source_event_id)) > 0
                AND length(btrim(actor_id)) > 0
                AND length(btrim(actor_type)) > 0
            ),
            CHECK (jsonb_typeof(payload) = 'object'),
            CHECK (
                jsonb_typeof(evidence_refs) = 'array'
                AND jsonb_array_length(evidence_refs) > 0
            ),
            CHECK (
                (context_kind = 'sla' AND event_type IN (
                    'support_sla_contract_observed', 'support_sla_timer_started',
                    'support_sla_timer_paused', 'support_sla_timer_resumed',
                    'support_sla_timer_met', 'support_sla_timer_breached',
                    'support_sla_timer_cancelled', 'support_sla_contract_withdrawn'
                ))
                OR (context_kind = 'journey_links' AND event_type IN (
                    'support_case_journey_linked', 'support_case_journey_unlinked'
                ))
            )
        );

        CREATE INDEX IF NOT EXISTS support_case_context_events_case_kind_effective
            ON support_case_context_events (
                tenant_id, case_id, source_connection_id, context_kind,
                effective_at DESC, received_at DESC, context_event_id DESC
            );
        CREATE INDEX IF NOT EXISTS support_case_context_events_record_revision
            ON support_case_context_events (
                tenant_id, source_connection_id, context_kind,
                source_record_id, source_revision_id
            );

        CREATE OR REPLACE FUNCTION reject_support_case_context_event_update()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'support_case_context_events is append-only';
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS support_case_context_events_append_only
            ON support_case_context_events;
        CREATE TRIGGER support_case_context_events_append_only
            BEFORE UPDATE ON support_case_context_events
            FOR EACH ROW EXECUTE FUNCTION reject_support_case_context_event_update();

        CREATE INDEX IF NOT EXISTS communication360_participant_scope_exact
            ON communication360_facts (
                tenant_id,
                (payload->>'provider'),
                (payload->>'provider_account_id'),
                (payload->>'provider_conversation_id'),
                occurred_at DESC,
                fact_id DESC
            )
            WHERE kind = 'participant_binding'
              AND payload->>'communication_scope_kind' = 'provider_conversation';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS support_case_context_events;
        DROP FUNCTION IF EXISTS reject_support_case_context_event_update();
        DROP INDEX IF EXISTS communication360_participant_scope_exact;
        """
    )
