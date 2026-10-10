"""Canonical measurement tables — touchpoints, conversions, spend, journeys, attribution.

Revision ID: m1e2a3s4u5r6
Revises: 9a1b2c3d4e5f
Create Date: 2026-06-22

This migration creates the nine core tables for the canonical measurement domain:

  silver_campaign_touchpoint_facts — durable campaign touchpoint ledger
  canonical_conversions            — authoritative conversion truth
  revenue_adjustments              — append-only refund/chargeback/adjustment log
  spend_records                    — actual advertising and marketing spend
  journey_versions                 — versioned, durable journey compiler output
  attribution_model_configs        — versioned attribution model configurations
  attribution_runs                 — immutable attribution calculation history
  attribution_credits              — per-touchpoint per-conversion credit weights
  measurement_connectors           — connector configuration and cursor state

Design principles:
  - Every table has tenant_id for isolation
  - Every write has an idempotency_key with UNIQUE constraint for safe replay
  - Monetary values use NUMERIC(18,6) for deterministic decimal arithmetic
  - Append-only tables (revenue_adjustments, attribution_runs) never delete rows
  - Attribution credits reconcile: sum(credit_weight) + unattributed_credit = 1.0
"""

from __future__ import annotations

from alembic import op

revision = "m1e2a3s4u5r6"
down_revision = "9a1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade() -> None:

    # ── 1. Campaign touchpoint facts (Silver) ────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS silver_campaign_touchpoint_facts (
            touchpoint_id           UUID         NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               TEXT         NOT NULL,
            profile_id              TEXT,
            cluster_id              TEXT,
            anonymous_id            TEXT,
            session_id              TEXT,
            device_id               TEXT,
            account_id              TEXT,
            organization_id         TEXT,
            wallet_id               TEXT,
            agent_id                TEXT,
            campaign_id             TEXT,
            ad_group_id             TEXT,
            ad_set_id               TEXT,
            creative_id             TEXT,
            ad_id                   TEXT,
            placement_id            TEXT,
            keyword_id              TEXT,
            audience_id             TEXT,
            offer_id                TEXT,
            landing_page_id         TEXT,
            channel                 TEXT,
            source                  TEXT,
            medium                  TEXT,
            platform                TEXT,
            touchpoint_type         TEXT         NOT NULL DEFAULT 'pageview',
            interaction_type        TEXT,
            is_view_through         BOOLEAN      NOT NULL DEFAULT FALSE,
            is_click_through        BOOLEAN      NOT NULL DEFAULT FALSE,
            viewable                BOOLEAN,
            engaged                 BOOLEAN,
            dwell_ms                INTEGER,
            position                INTEGER,
            frequency               INTEGER,
            occurred_at             TIMESTAMPTZ  NOT NULL,
            received_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
            processed_at            TIMESTAMPTZ,
            source_event_id         TEXT,
            connector_record_id     TEXT,
            source_connector_id     TEXT,
            utm_source              TEXT,
            utm_medium              TEXT,
            utm_campaign            TEXT,
            utm_content             TEXT,
            utm_term                TEXT,
            click_id                TEXT,
            referrer                TEXT,
            landing_url             TEXT,
            identity_resolution_method TEXT,
            identity_confidence     NUMERIC(5,4),
            identity_version        TEXT,
            consent_snapshot_id     TEXT,
            privacy_class           TEXT         NOT NULL DEFAULT 'behavioral',
            provenance              JSONB        NOT NULL DEFAULT '{}'::jsonb,
            evidence_ids            JSONB        NOT NULL DEFAULT '[]'::jsonb,
            idempotency_key         TEXT         NOT NULL,
            schema_version          INTEGER      NOT NULL DEFAULT 1,
            created_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, touchpoint_id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS sctf_idempotency
            ON silver_campaign_touchpoint_facts (tenant_id, idempotency_key);
        CREATE INDEX IF NOT EXISTS sctf_campaign
            ON silver_campaign_touchpoint_facts (tenant_id, campaign_id, occurred_at DESC)
            WHERE campaign_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS sctf_profile
            ON silver_campaign_touchpoint_facts (tenant_id, profile_id, occurred_at DESC)
            WHERE profile_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS sctf_anonymous
            ON silver_campaign_touchpoint_facts (tenant_id, anonymous_id, occurred_at DESC)
            WHERE anonymous_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS sctf_source_event
            ON silver_campaign_touchpoint_facts (source_event_id)
            WHERE source_event_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS sctf_occurred
            ON silver_campaign_touchpoint_facts (tenant_id, occurred_at DESC);
    """)

    # ── 2. Canonical conversions ─────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS canonical_conversions (
            conversion_id           UUID         NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               TEXT         NOT NULL,
            conversion_type         TEXT         NOT NULL,
            conversion_name         TEXT,
            goal_id                 TEXT,
            profile_id              TEXT,
            cluster_id              TEXT,
            account_id              TEXT,
            organization_id         TEXT,
            wallet_id               TEXT,
            agent_id                TEXT,
            order_id                TEXT,
            payment_id              TEXT,
            subscription_id         TEXT,
            invoice_id              TEXT,
            opportunity_id          TEXT,
            transaction_hash        TEXT,
            external_conversion_id  TEXT,
            gross_value             NUMERIC(18,6),
            discount_value          NUMERIC(18,6) NOT NULL DEFAULT 0,
            tax_value               NUMERIC(18,6) NOT NULL DEFAULT 0,
            shipping_value          NUMERIC(18,6) NOT NULL DEFAULT 0,
            fee_value               NUMERIC(18,6) NOT NULL DEFAULT 0,
            refund_value            NUMERIC(18,6) NOT NULL DEFAULT 0,
            chargeback_value        NUMERIC(18,6) NOT NULL DEFAULT 0,
            contribution_value      NUMERIC(18,6),
            net_value               NUMERIC(18,6),
            currency                TEXT         NOT NULL DEFAULT 'USD',
            normalized_currency     TEXT         NOT NULL DEFAULT 'USD',
            exchange_rate           NUMERIC(18,8) NOT NULL DEFAULT 1.0,
            quantity                INTEGER      NOT NULL DEFAULT 1,
            product_ids             JSONB        NOT NULL DEFAULT '[]'::jsonb,
            line_items              JSONB        NOT NULL DEFAULT '[]'::jsonb,
            occurred_at             TIMESTAMPTZ  NOT NULL,
            observed_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
            confirmed_at            TIMESTAMPTZ,
            adjusted_at             TIMESTAMPTZ,
            reversed_at             TIMESTAMPTZ,
            conversion_status       TEXT         NOT NULL DEFAULT 'confirmed',
            conversion_source       TEXT,
            authority_rank          INTEGER      NOT NULL DEFAULT 0,
            deduplication_key       TEXT         NOT NULL,
            attribution_eligible    BOOLEAN      NOT NULL DEFAULT TRUE,
            consent_snapshot_id     TEXT,
            identity_version        TEXT,
            provenance              JSONB        NOT NULL DEFAULT '{}'::jsonb,
            evidence_ids            JSONB        NOT NULL DEFAULT '[]'::jsonb,
            source_connector_id     TEXT,
            source_event_id         TEXT,
            schema_version          INTEGER      NOT NULL DEFAULT 1,
            created_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, conversion_id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS cc_dedup_key
            ON canonical_conversions (tenant_id, deduplication_key);
        CREATE INDEX IF NOT EXISTS cc_profile
            ON canonical_conversions (tenant_id, profile_id, occurred_at DESC)
            WHERE profile_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS cc_order
            ON canonical_conversions (tenant_id, order_id)
            WHERE order_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS cc_occurred
            ON canonical_conversions (tenant_id, occurred_at DESC);
        CREATE INDEX IF NOT EXISTS cc_eligible
            ON canonical_conversions (tenant_id, attribution_eligible, occurred_at DESC)
            WHERE attribution_eligible = TRUE;
        CREATE INDEX IF NOT EXISTS cc_status
            ON canonical_conversions (tenant_id, conversion_status);
    """)

    # ── 3. Revenue adjustments (append-only) ─────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS revenue_adjustments (
            adjustment_id           UUID         NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               TEXT         NOT NULL,
            conversion_id           UUID         NOT NULL,
            adjustment_type         TEXT         NOT NULL,
            amount                  NUMERIC(18,6) NOT NULL,
            currency                TEXT         NOT NULL DEFAULT 'USD',
            normalized_amount       NUMERIC(18,6),
            occurred_at             TIMESTAMPTZ  NOT NULL,
            reason                  TEXT,
            source_event_id         TEXT,
            connector_record_id     TEXT,
            evidence_ids            JSONB        NOT NULL DEFAULT '[]'::jsonb,
            idempotency_key         TEXT         NOT NULL,
            schema_version          INTEGER      NOT NULL DEFAULT 1,
            created_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, adjustment_id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS ra_idempotency
            ON revenue_adjustments (tenant_id, idempotency_key);
        CREATE INDEX IF NOT EXISTS ra_conversion
            ON revenue_adjustments (tenant_id, conversion_id, occurred_at DESC);
    """)

    # ── 4. Actual spend records ───────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS spend_records (
            spend_record_id         UUID         NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               TEXT         NOT NULL,
            platform                TEXT,
            ad_account_id           TEXT,
            campaign_id             TEXT,
            ad_group_id             TEXT,
            ad_set_id               TEXT,
            creative_id             TEXT,
            ad_id                   TEXT,
            placement_id            TEXT,
            keyword_id              TEXT,
            period_start            TIMESTAMPTZ  NOT NULL,
            period_end              TIMESTAMPTZ  NOT NULL,
            source_timezone         TEXT         NOT NULL DEFAULT 'UTC',
            billing_currency        TEXT         NOT NULL DEFAULT 'USD',
            normalized_currency     TEXT         NOT NULL DEFAULT 'USD',
            exchange_rate           NUMERIC(18,8) NOT NULL DEFAULT 1.0,
            impressions             BIGINT       NOT NULL DEFAULT 0,
            reach                   BIGINT       NOT NULL DEFAULT 0,
            frequency               NUMERIC(10,4),
            clicks                  BIGINT       NOT NULL DEFAULT 0,
            engagements             BIGINT       NOT NULL DEFAULT 0,
            video_views             BIGINT       NOT NULL DEFAULT 0,
            viewable_impressions    BIGINT       NOT NULL DEFAULT 0,
            media_spend             NUMERIC(18,6) NOT NULL DEFAULT 0,
            platform_fees           NUMERIC(18,6) NOT NULL DEFAULT 0,
            agency_fees             NUMERIC(18,6) NOT NULL DEFAULT 0,
            creative_cost           NUMERIC(18,6) NOT NULL DEFAULT 0,
            affiliate_cost          NUMERIC(18,6) NOT NULL DEFAULT 0,
            other_cost              NUMERIC(18,6) NOT NULL DEFAULT 0,
            total_cost              NUMERIC(18,6) NOT NULL DEFAULT 0,
            source_record_id        TEXT,
            source_connector_id     TEXT,
            sync_run_id             TEXT,
            source_version          TEXT,
            provenance              JSONB        NOT NULL DEFAULT '{}'::jsonb,
            idempotency_key         TEXT         NOT NULL,
            schema_version          INTEGER      NOT NULL DEFAULT 1,
            created_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, spend_record_id)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS sr_idempotency
            ON spend_records (tenant_id, idempotency_key);
        CREATE INDEX IF NOT EXISTS sr_campaign
            ON spend_records (tenant_id, campaign_id, period_start DESC)
            WHERE campaign_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS sr_period
            ON spend_records (tenant_id, period_start DESC, period_end DESC);
        CREATE INDEX IF NOT EXISTS sr_platform
            ON spend_records (tenant_id, platform, period_start DESC)
            WHERE platform IS NOT NULL;
    """)

    # ── 5. Versioned journeys ────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS journey_versions (
            journey_version_id      UUID         NOT NULL DEFAULT gen_random_uuid(),
            journey_id              UUID         NOT NULL,
            tenant_id               TEXT         NOT NULL,
            profile_id              TEXT,
            cluster_id              TEXT,
            account_id              TEXT,
            organization_id         TEXT,
            wallet_id               TEXT,
            agent_id                TEXT,
            journey_type            TEXT         NOT NULL DEFAULT 'profile',
            journey_state           TEXT         NOT NULL DEFAULT 'open',
            started_at              TIMESTAMPTZ,
            ended_at                TIMESTAMPTZ,
            converted_at            TIMESTAMPTZ,
            entry_touchpoint_id     UUID,
            exit_touchpoint_id      UUID,
            conversion_ids          JSONB        NOT NULL DEFAULT '[]'::jsonb,
            event_ids               JSONB        NOT NULL DEFAULT '[]'::jsonb,
            touchpoint_ids          JSONB        NOT NULL DEFAULT '[]'::jsonb,
            session_ids             JSONB        NOT NULL DEFAULT '[]'::jsonb,
            device_ids              JSONB        NOT NULL DEFAULT '[]'::jsonb,
            campaign_ids            JSONB        NOT NULL DEFAULT '[]'::jsonb,
            channel_sequence        JSONB        NOT NULL DEFAULT '[]'::jsonb,
            previous_version_id     UUID,
            rebuild_reason          TEXT,
            identity_version        TEXT,
            data_watermark          TIMESTAMPTZ,
            compiler_version        TEXT         NOT NULL DEFAULT '1.0',
            computed_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
            is_current              BOOLEAN      NOT NULL DEFAULT TRUE,
            PRIMARY KEY (tenant_id, journey_version_id)
        );
        CREATE INDEX IF NOT EXISTS jv_journey
            ON journey_versions (tenant_id, journey_id, computed_at DESC);
        CREATE INDEX IF NOT EXISTS jv_profile
            ON journey_versions (tenant_id, profile_id, is_current)
            WHERE profile_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS jv_current
            ON journey_versions (tenant_id, journey_id)
            WHERE is_current = TRUE;
    """)

    # ── 6. Attribution model configurations ──────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS attribution_model_configs (
            model_config_id             UUID         NOT NULL DEFAULT gen_random_uuid(),
            tenant_id                   TEXT         NOT NULL,
            name                        TEXT         NOT NULL,
            model_type                  TEXT         NOT NULL,
            model_version               TEXT         NOT NULL DEFAULT '1.0',
            conversion_types            JSONB        NOT NULL DEFAULT '["all"]'::jsonb,
            click_lookback_window       INTEGER      NOT NULL DEFAULT 720,
            view_lookback_window        INTEGER      NOT NULL DEFAULT 168,
            engaged_view_threshold_ms   INTEGER      NOT NULL DEFAULT 1000,
            session_timeout_seconds     INTEGER      NOT NULL DEFAULT 1800,
            direct_traffic_policy       TEXT         NOT NULL DEFAULT 'include',
            organic_policy              TEXT         NOT NULL DEFAULT 'include',
            brand_search_policy         TEXT         NOT NULL DEFAULT 'include',
            cross_device_policy         TEXT         NOT NULL DEFAULT 'enabled',
            identity_confidence_min     NUMERIC(5,4) NOT NULL DEFAULT 0.5,
            fraud_policy                TEXT         NOT NULL DEFAULT 'exclude',
            internal_traffic_policy     TEXT         NOT NULL DEFAULT 'exclude',
            repeat_conversion_policy    TEXT         NOT NULL DEFAULT 'include_all',
            currency_policy             TEXT         NOT NULL DEFAULT 'normalize_usd',
            status                      TEXT         NOT NULL DEFAULT 'active',
            effective_from              TIMESTAMPTZ  NOT NULL DEFAULT now(),
            effective_until             TIMESTAMPTZ,
            created_by                  TEXT,
            approved_by                 TEXT,
            created_at                  TIMESTAMPTZ  NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, model_config_id)
        );
        CREATE INDEX IF NOT EXISTS amc_tenant_status
            ON attribution_model_configs (tenant_id, status);
        CREATE INDEX IF NOT EXISTS amc_model_type
            ON attribution_model_configs (tenant_id, model_type);
    """)

    # ── 7. Attribution runs (immutable) ──────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS attribution_runs (
            attribution_run_id          UUID         NOT NULL DEFAULT gen_random_uuid(),
            tenant_id                   TEXT         NOT NULL,
            conversion_id               UUID         NOT NULL,
            conversion_version          TEXT,
            journey_id                  UUID,
            journey_version_id          UUID,
            model_config_id             UUID,
            model_type                  TEXT         NOT NULL,
            model_version               TEXT         NOT NULL DEFAULT '1.0',
            code_version                TEXT,
            input_touchpoint_ids        JSONB        NOT NULL DEFAULT '[]'::jsonb,
            excluded_touchpoint_ids     JSONB        NOT NULL DEFAULT '[]'::jsonb,
            exclusion_reasons           JSONB        NOT NULL DEFAULT '{}'::jsonb,
            eligible_revenue            NUMERIC(18,6),
            credit_total                NUMERIC(12,8) NOT NULL DEFAULT 1.0,
            unattributed_credit         NUMERIC(12,8) NOT NULL DEFAULT 0.0,
            identity_confidence         NUMERIC(5,4),
            model_confidence            NUMERIC(5,4),
            data_watermark              TIMESTAMPTZ,
            currency                    TEXT         NOT NULL DEFAULT 'USD',
            status                      TEXT         NOT NULL DEFAULT 'pending',
            failure_reason              TEXT,
            is_active                   BOOLEAN      NOT NULL DEFAULT FALSE,
            started_at                  TIMESTAMPTZ,
            completed_at                TIMESTAMPTZ,
            created_at                  TIMESTAMPTZ  NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, attribution_run_id)
        );
        CREATE INDEX IF NOT EXISTS ar_conversion
            ON attribution_runs (tenant_id, conversion_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS ar_active
            ON attribution_runs (tenant_id, conversion_id)
            WHERE is_active = TRUE;
        CREATE INDEX IF NOT EXISTS ar_status
            ON attribution_runs (tenant_id, status);
    """)

    # ── 8. Attribution credits ────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS attribution_credits (
            credit_id               UUID         NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               TEXT         NOT NULL,
            attribution_run_id      UUID         NOT NULL,
            conversion_id           UUID         NOT NULL,
            touchpoint_id           UUID,
            campaign_id             TEXT,
            ad_group_id             TEXT,
            ad_set_id               TEXT,
            creative_id             TEXT,
            ad_id                   TEXT,
            placement_id            TEXT,
            keyword_id              TEXT,
            channel                 TEXT,
            source                  TEXT,
            credit_weight           NUMERIC(12,8) NOT NULL,
            attributed_conversion_count NUMERIC(12,8) NOT NULL DEFAULT 0,
            attributed_gross_revenue NUMERIC(18,6),
            attributed_net_revenue  NUMERIC(18,6),
            attributed_contribution_value NUMERIC(18,6),
            identity_confidence     NUMERIC(5,4),
            model_confidence        NUMERIC(5,4),
            explanation             TEXT,
            evidence_ids            JSONB        NOT NULL DEFAULT '[]'::jsonb,
            created_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, credit_id)
        );
        CREATE INDEX IF NOT EXISTS ac_run
            ON attribution_credits (tenant_id, attribution_run_id);
        CREATE INDEX IF NOT EXISTS ac_conversion
            ON attribution_credits (tenant_id, conversion_id);
        CREATE INDEX IF NOT EXISTS ac_campaign
            ON attribution_credits (tenant_id, campaign_id, created_at DESC)
            WHERE campaign_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS ac_touchpoint
            ON attribution_credits (tenant_id, touchpoint_id)
            WHERE touchpoint_id IS NOT NULL;
    """)

    # ── 9. Measurement connectors ─────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS measurement_connectors (
            connector_id            UUID         NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               TEXT         NOT NULL,
            connector_type          TEXT         NOT NULL,
            name                    TEXT,
            status                  TEXT         NOT NULL DEFAULT 'active',
            config                  JSONB        NOT NULL DEFAULT '{}'::jsonb,
            cursor_state            JSONB        NOT NULL DEFAULT '{}'::jsonb,
            last_sync_at            TIMESTAMPTZ,
            last_success_at         TIMESTAMPTZ,
            next_sync_at            TIMESTAMPTZ,
            health_status           TEXT         NOT NULL DEFAULT 'unknown',
            health_message          TEXT,
            sync_run_count          INTEGER      NOT NULL DEFAULT 0,
            error_count             INTEGER      NOT NULL DEFAULT 0,
            created_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, connector_id)
        );
        CREATE INDEX IF NOT EXISTS mc_tenant_status
            ON measurement_connectors (tenant_id, status);
        CREATE INDEX IF NOT EXISTS mc_type
            ON measurement_connectors (tenant_id, connector_type);
        CREATE INDEX IF NOT EXISTS mc_next_sync
            ON measurement_connectors (next_sync_at ASC)
            WHERE status = 'active' AND next_sync_at IS NOT NULL;
    """)


def downgrade() -> None:
    for table in [
        "attribution_credits",
        "attribution_runs",
        "attribution_model_configs",
        "journey_versions",
        "spend_records",
        "revenue_adjustments",
        "canonical_conversions",
        "silver_campaign_touchpoint_facts",
        "measurement_connectors",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
