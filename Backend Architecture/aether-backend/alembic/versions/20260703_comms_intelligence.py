"""Communications Intelligence — silver_comms_facts enrichment, communication
state, message/link dimensions, initiatives, and scoped suppressions.

Revision ID: 20260703_comms_intel
Revises: 20260702_fraud_decisions, 20260702_semantic_sentiment (merge point)
Create Date: 2026-07-03

All changes are additive: nullable columns on existing tables, new tables,
and new indexes. Nothing is rewritten in place; rollback drops only what this
revision created (see downgrade()). Safe to run online — no table rewrites,
no exclusive locks beyond brief ALTERs.
"""

from __future__ import annotations

from alembic import op

revision = "20260703_comms_intel"
down_revision = ("20260702_fraud_decisions", "20260702_semantic_sentiment")
branch_labels = None
depends_on = None

# Additive columns for silver_comms_facts (Phase 4). All nullable — existing
# rows remain valid; the CommsProjector populates them for new events and the
# backfill job (docs/comms/COMMS_BACKFILL_RUNBOOK.md) fills history.
_COMMS_FACT_COLUMNS: list[tuple[str, str]] = [
    ("provider", "TEXT"),
    ("provider_account_id", "TEXT"),
    ("provider_event_id", "TEXT"),
    ("source_connector_id", "TEXT"),
    ("direction", "TEXT"),
    ("message_category", "TEXT"),
    ("communication_state", "TEXT"),
    ("journey_role", "TEXT"),
    ("actor_kind", "TEXT"),
    ("sender_entity_id", "TEXT"),
    ("recipient_entity_id", "TEXT"),
    ("recipient_alias_id", "TEXT"),
    ("recipient_display", "TEXT"),
    ("recipient_is_shared_mailbox", "BOOLEAN"),
    ("profile_id", "TEXT"),
    ("cluster_id", "TEXT"),
    ("organization_id", "TEXT"),
    ("agent_id", "TEXT"),
    ("external_campaign_id", "TEXT"),
    ("external_flow_id", "TEXT"),
    ("external_message_id", "TEXT"),
    ("external_thread_id", "TEXT"),
    ("external_template_id", "TEXT"),
    ("sequence_step", "INTEGER"),
    ("variant_id", "TEXT"),
    ("link_id", "TEXT"),
    ("link_url_hash", "TEXT"),
    ("audience_id", "TEXT"),
    ("segment_id", "TEXT"),
    ("delivery_status", "TEXT"),
    ("bounce_type", "TEXT"),
    ("suppression_scope", "TEXT"),
    ("unsubscribe_scope", "TEXT"),
    ("engagement_type", "TEXT"),
    ("engagement_confidence", "NUMERIC(5,4)"),
    ("engagement_strength", "TEXT"),
    ("machine_activity_probability", "NUMERIC(5,4)"),
    ("suspected_machine_activity", "BOOLEAN"),
    ("automated_response_kind", "TEXT"),
    ("classifier_version", "TEXT"),
    ("identity_resolution_method", "TEXT"),
    ("identity_confidence", "NUMERIC(5,4)"),
    ("campaign_resolution_method", "TEXT"),
    ("campaign_resolution_confidence", "NUMERIC(5,4)"),
    ("campaign_resolution_status", "TEXT"),
    ("campaign_resolution_version", "TEXT"),
    ("raw_evidence_ref", "TEXT"),
    ("evidence_ids", "TEXT[]"),
    ("provenance", "JSONB"),
    ("canonical_activity_key", "TEXT"),
]

# Comms lineage columns on the touchpoint ledger (Phase 7).
_TOUCHPOINT_COLUMNS: list[tuple[str, str]] = [
    ("communication_fact_id", "TEXT"),
    ("external_message_id", "TEXT"),
    ("sequence_step", "INTEGER"),
    ("variant_id", "TEXT"),
    ("link_id", "TEXT"),
    ("engagement_confidence", "NUMERIC(5,4)"),
    ("machine_activity_probability", "NUMERIC(5,4)"),
]


def upgrade() -> None:
    for col, coltype in _COMMS_FACT_COLUMNS:
        op.execute(
            f"ALTER TABLE silver_comms_facts ADD COLUMN IF NOT EXISTS {col} {coltype};"
        )
    for col, coltype in _TOUCHPOINT_COLUMNS:
        op.execute(
            f"ALTER TABLE silver_campaign_touchpoint_facts ADD COLUMN IF NOT EXISTS {col} {coltype};"
        )

    # High-frequency query paths (Phase 4) — no unbounded JSON-only queries.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS silver_comms_idem
            ON silver_comms_facts (tenant_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL;
        CREATE INDEX IF NOT EXISTS silver_comms_profile
            ON silver_comms_facts (tenant_id, profile_id, occurred_at DESC)
            WHERE profile_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS silver_comms_campaign_occurred
            ON silver_comms_facts (tenant_id, campaign_id, occurred_at DESC)
            WHERE campaign_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS silver_comms_ext_message
            ON silver_comms_facts (tenant_id, external_message_id)
            WHERE external_message_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS silver_comms_provider_event
            ON silver_comms_facts (tenant_id, provider_event_id)
            WHERE provider_event_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS silver_comms_alias
            ON silver_comms_facts (tenant_id, recipient_alias_id, occurred_at DESC)
            WHERE recipient_alias_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS silver_comms_state
            ON silver_comms_facts (tenant_id, communication_state)
            WHERE communication_state IS NOT NULL;
        CREATE INDEX IF NOT EXISTS silver_comms_suppression
            ON silver_comms_facts (tenant_id, suppression_scope)
            WHERE suppression_scope IS NOT NULL;
    """)

    # ── Communication state (Phase 8): rebuildable reducer output ────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS communication_state (
            state_id                  UUID        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id                 TEXT        NOT NULL,
            entity_id                 TEXT        NOT NULL,
            channel                   TEXT        NOT NULL DEFAULT 'email',
            scope                     TEXT        NOT NULL DEFAULT 'marketing',
            subscription_status       TEXT        NOT NULL DEFAULT 'unknown',
            deliverability_status     TEXT        NOT NULL DEFAULT 'unknown',
            last_sent_at              TIMESTAMPTZ,
            last_delivered_at         TIMESTAMPTZ,
            last_reported_open_at     TIMESTAMPTZ,
            last_human_engagement_at  TIMESTAMPTZ,
            last_click_at             TIMESTAMPTZ,
            last_reply_at             TIMESTAMPTZ,
            total_sent                INTEGER     NOT NULL DEFAULT 0,
            total_delivered           INTEGER     NOT NULL DEFAULT 0,
            total_reported_opens      INTEGER     NOT NULL DEFAULT 0,
            total_human_clicks        INTEGER     NOT NULL DEFAULT 0,
            total_replies             INTEGER     NOT NULL DEFAULT 0,
            hard_bounce_count         INTEGER     NOT NULL DEFAULT 0,
            soft_bounce_count         INTEGER     NOT NULL DEFAULT 0,
            complaint_count           INTEGER     NOT NULL DEFAULT 0,
            suppression_scope         TEXT,
            unsubscribe_scope         TEXT,
            provider_profiles         JSONB       NOT NULL DEFAULT '{}'::jsonb,
            source_freshness_at       TIMESTAMPTZ,
            computed_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
            schema_version            INTEGER     NOT NULL DEFAULT 1,
            PRIMARY KEY (tenant_id, entity_id, channel, scope)
        );
        CREATE INDEX IF NOT EXISTS communication_state_status
            ON communication_state (tenant_id, channel, subscription_status);
    """)

    # ── Campaign message/link dimensions (Phase 10, ADR-C9) ──────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS campaign_messages (
            message_id            UUID        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id             TEXT        NOT NULL,
            campaign_id           UUID        NOT NULL,
            provider              TEXT        NOT NULL,
            provider_account_id   TEXT,
            external_message_id   TEXT        NOT NULL,
            external_template_id  TEXT,
            name                  TEXT,
            subject_redacted      TEXT,
            sequence_step         INTEGER,
            variant_id            TEXT,
            channel               TEXT        NOT NULL DEFAULT 'email',
            message_category      TEXT        NOT NULL DEFAULT 'marketing',
            status                TEXT        NOT NULL DEFAULT 'active',
            first_seen_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_seen_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            source_connector_id   TEXT,
            properties            JSONB       NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (tenant_id, message_id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS campaign_messages_external
            ON campaign_messages (tenant_id, provider, external_message_id);
        CREATE INDEX IF NOT EXISTS campaign_messages_campaign
            ON campaign_messages (tenant_id, campaign_id);

        CREATE TABLE IF NOT EXISTS campaign_links (
            link_row_id           UUID        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id             TEXT        NOT NULL,
            campaign_id           UUID,
            message_id            UUID,
            link_id               TEXT        NOT NULL,
            url_hash              TEXT,
            display_url           TEXT,
            first_seen_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_seen_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, link_row_id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS campaign_links_natural
            ON campaign_links (tenant_id, link_id, COALESCE(message_id, '00000000-0000-0000-0000-000000000000'::uuid));
    """)

    # ── Cross-channel initiatives (Phase 10, ADR-C9) ─────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS campaign_initiatives (
            initiative_id  UUID        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id      TEXT        NOT NULL,
            name           TEXT        NOT NULL,
            description    TEXT,
            status         TEXT        NOT NULL DEFAULT 'active',
            created_by     TEXT        NOT NULL DEFAULT 'tenant',
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            properties     JSONB       NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (tenant_id, initiative_id)
        );
        CREATE TABLE IF NOT EXISTS campaign_initiative_members (
            tenant_id      TEXT        NOT NULL,
            initiative_id  UUID        NOT NULL,
            campaign_id    UUID        NOT NULL,
            added_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            added_by       TEXT        NOT NULL DEFAULT 'tenant',
            PRIMARY KEY (tenant_id, initiative_id, campaign_id)
        );
        CREATE INDEX IF NOT EXISTS campaign_initiative_members_campaign
            ON campaign_initiative_members (tenant_id, campaign_id);
    """)

    # ── Aggregated communication relationships (Phase 17, ADR-C6) ────────────
    # Durable aggregate ledger; the graph carries ONE edge per relationship,
    # created on first observation and selectively refreshed — never one edge
    # per event.
    op.execute("""
        CREATE TABLE IF NOT EXISTS communication_relationships (
            relationship_id    UUID        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id          TEXT        NOT NULL,
            sender_ref         TEXT        NOT NULL,
            recipient_ref      TEXT        NOT NULL,
            channel            TEXT        NOT NULL DEFAULT 'email',
            edge_type          TEXT        NOT NULL,
            relationship_context TEXT,
            first_observed_at  TIMESTAMPTZ,
            last_observed_at   TIMESTAMPTZ,
            message_count      INTEGER     NOT NULL DEFAULT 0,
            delivered_count    INTEGER     NOT NULL DEFAULT 0,
            human_click_count  INTEGER     NOT NULL DEFAULT 0,
            reply_count        INTEGER     NOT NULL DEFAULT 0,
            campaign_ids       TEXT[]      NOT NULL DEFAULT '{}',
            confidence         NUMERIC(5,4),
            consent_purpose    TEXT,
            evidence_refs      TEXT[]      NOT NULL DEFAULT '{}',
            valid_from         TIMESTAMPTZ,
            valid_to           TIMESTAMPTZ,
            graph_emitted      BOOLEAN     NOT NULL DEFAULT false,
            message_promoted   BOOLEAN     NOT NULL DEFAULT false,
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, sender_ref, recipient_ref, channel, edge_type)
        );
        CREATE INDEX IF NOT EXISTS communication_relationships_recipient
            ON communication_relationships (tenant_id, recipient_ref);
    """)

    # ── Scoped communication suppressions (Phase 23, ADR-C7) ─────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS communication_suppressions (
            suppression_id   UUID        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id        TEXT        NOT NULL,
            entity_id        TEXT,
            recipient_alias_id TEXT,
            channel          TEXT        NOT NULL DEFAULT 'email',
            scope            TEXT        NOT NULL,
            scope_ref        TEXT,
            reason           TEXT        NOT NULL,
            source_event_id  TEXT,
            provider         TEXT,
            active           BOOLEAN     NOT NULL DEFAULT true,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            revoked_at       TIMESTAMPTZ,
            PRIMARY KEY (tenant_id, suppression_id)
        );
        CREATE INDEX IF NOT EXISTS communication_suppressions_entity
            ON communication_suppressions (tenant_id, entity_id, channel)
            WHERE active;
        CREATE INDEX IF NOT EXISTS communication_suppressions_alias
            ON communication_suppressions (tenant_id, recipient_alias_id, channel)
            WHERE active;
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS communication_relationships;
        DROP TABLE IF EXISTS communication_suppressions;
        DROP TABLE IF EXISTS campaign_initiative_members;
        DROP TABLE IF EXISTS campaign_initiatives;
        DROP TABLE IF EXISTS campaign_links;
        DROP TABLE IF EXISTS campaign_messages;
        DROP TABLE IF EXISTS communication_state;
    """)
    for col, _ in _TOUCHPOINT_COLUMNS:
        op.execute(
            f"ALTER TABLE silver_campaign_touchpoint_facts DROP COLUMN IF EXISTS {col};"
        )
    for col, _ in _COMMS_FACT_COLUMNS:
        op.execute(f"ALTER TABLE silver_comms_facts DROP COLUMN IF EXISTS {col};")
