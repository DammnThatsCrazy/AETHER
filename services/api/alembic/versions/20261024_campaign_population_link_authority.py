"""Append-only exact Campaign360 population association events.

Revision ID: 20261024_campaign_population_link_authority
Revises: 20261024_merge_360_wave_heads
Create Date: 2026-10-24

An operator link is explicit campaign audience evidence. It does not derive
population membership from touchpoint or conversion identity fields.
"""

from alembic import op

revision = "20261024_campaign_population_link_authority"
down_revision = "20261024_merge_360_wave_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS campaign_population_link_events (
            tenant_id TEXT NOT NULL,
            link_event_id UUID NOT NULL,
            campaign_id UUID NOT NULL,
            population_id TEXT NOT NULL,
            event_type TEXT NOT NULL CHECK (event_type IN ('linked', 'unlinked')),
            source_id TEXT NOT NULL,
            source_record_id TEXT NOT NULL,
            source_revision_id TEXT NOT NULL,
            source_event_id TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            source_observed_at TIMESTAMPTZ NOT NULL,
            effective_at TIMESTAMPTZ NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL,
            evidence_refs JSONB NOT NULL,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, link_event_id),
            UNIQUE (tenant_id, source_id, source_event_id),
            CHECK (
                length(btrim(tenant_id)) > 0
                AND length(btrim(population_id)) > 0
                AND length(btrim(source_id)) > 0
                AND length(btrim(source_record_id)) > 0
                AND length(btrim(source_revision_id)) > 0
                AND length(btrim(source_event_id)) > 0
                AND length(btrim(actor_id)) > 0
                AND length(btrim(actor_type)) > 0
            ),
            CHECK (
                jsonb_typeof(evidence_refs) = 'array'
                AND jsonb_array_length(evidence_refs) >= 2
            ),
            CHECK (jsonb_typeof(payload) = 'object'),
            CHECK (payload->>'tenant_id' = tenant_id),
            CHECK (payload->>'campaign_id' = campaign_id::text),
            CHECK (payload->>'population_id' = population_id)
        );

        CREATE INDEX IF NOT EXISTS campaign_population_links_exact_latest
            ON campaign_population_link_events (
                tenant_id, campaign_id, population_id,
                effective_at DESC, recorded_at DESC, link_event_id DESC
            );

        CREATE OR REPLACE FUNCTION reject_campaign_population_link_event_update()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'campaign_population_link_events is append-only';
        END;
        $$ LANGUAGE plpgsql;

        DROP TRIGGER IF EXISTS campaign_population_link_events_append_only
            ON campaign_population_link_events;
        CREATE TRIGGER campaign_population_link_events_append_only
            BEFORE UPDATE ON campaign_population_link_events
            FOR EACH ROW EXECUTE FUNCTION reject_campaign_population_link_event_update();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS campaign_population_link_events;
        DROP FUNCTION IF EXISTS reject_campaign_population_link_event_update();
        """
    )
