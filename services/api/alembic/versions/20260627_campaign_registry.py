"""Campaign Intelligence — Canonical Campaign Registry & Resolution.

Revision ID: cr001a2b3c4d
Revises: ca001b2c3d4e
Create Date: 2026-06-27

Introduces the Campaign Registry domain:

  campaigns              — structured canonical campaign catalog; replaces the generic
                           JSONB auto-table previously used by CampaignRepository.
                           Every canonical Aether campaign_id is a UUID from this table.
  campaign_external_refs — durable one-to-many mapping from external platform campaign
                           identifiers to canonical Aether campaign UUIDs. Uniqueness
                           is enforced at (tenant_id, platform, external_account_id,
                           external_campaign_id) so the same external ID on different
                           accounts never collides.
  campaign_aliases       — deterministic acquisition evidence aliases (UTM, utm_id,
                           tracking codes, partner codes, landing tokens) used by the
                           resolver to map SDK/webhook evidence to canonical campaigns.
                           A partial unique index prevents duplicate active aliases
                           per type per tenant.
  campaign_resolution_reviews — durable Mapping Review queue for unresolved or
                           ambiguous campaign evidence. Identical evidence hashes
                           increment observed_count rather than creating new rows.

Extends existing fact tables with explicit resolution provenance:
  spend_records                       — external_campaign_id, external_account_id,
                                        campaign_resolution_status/method/version
  silver_campaign_touchpoint_facts    — same, plus campaign_resolution_confidence
  attribution_credits                 — external_campaign_id, campaign_resolution_method

Design invariants:
  - All rows are tenant-scoped; no row is reachable without a tenant predicate
  - External IDs are stored as TEXT verbatim (no lowercasing, no fuzzy mutation)
  - campaign_id in fact tables always references the canonical Aether UUID
  - Raw provider metadata is retained in raw_metadata JSONB; never discarded
  - ON CONFLICT clauses in application code handle concurrent upsert races
"""

from __future__ import annotations

from alembic import op

revision = "cr001a2b3c4d"
down_revision = "ca001b2c3d4e"
branch_labels = None
depends_on = None


def upgrade() -> None:

    # ── 1. campaigns ─────────────────────────────────────────────────────────
    # Structured canonical registry for all campaigns known to Aether.
    # origin distinguishes:
    #   external  — imported from a connected ad platform
    #   custom    — manually registered by the tenant
    #   discovered — inferred from UTM evidence without a connected source
    op.execute("""
        CREATE TABLE IF NOT EXISTS campaigns (
            campaign_id             UUID        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               TEXT        NOT NULL,
            name                    TEXT        NOT NULL,
            status                  TEXT        NOT NULL DEFAULT 'active',
            channel                 TEXT,
            start_at                TIMESTAMPTZ,
            end_at                  TIMESTAMPTZ,
            budget_usd              NUMERIC(18,6),
            origin                  TEXT        NOT NULL DEFAULT 'custom',
            primary_platform        TEXT,
            source_connector_id     TEXT,
            sync_status             TEXT        NOT NULL DEFAULT 'not_synced',
            provider_status         TEXT,
            first_seen_at           TIMESTAMPTZ,
            last_seen_at            TIMESTAMPTZ,
            archived_at             TIMESTAMPTZ,
            display_name_override   TEXT,
            properties              JSONB       NOT NULL DEFAULT '{}'::jsonb,
            schema_version          INTEGER     NOT NULL DEFAULT 1,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT campaigns_pk PRIMARY KEY (campaign_id)
        );

        CREATE UNIQUE INDEX IF NOT EXISTS campaigns_tenant_campaign_idx
            ON campaigns (tenant_id, campaign_id);

        CREATE INDEX IF NOT EXISTS campaigns_tenant_status_idx
            ON campaigns (tenant_id, status)
            WHERE archived_at IS NULL;

        CREATE INDEX IF NOT EXISTS campaigns_tenant_platform_idx
            ON campaigns (tenant_id, primary_platform)
            WHERE primary_platform IS NOT NULL;

        CREATE INDEX IF NOT EXISTS campaigns_tenant_origin_idx
            ON campaigns (tenant_id, origin);
    """)

    # ── 2. campaign_external_refs ─────────────────────────────────────────────
    # One canonical campaign may have multiple external references
    # (e.g. the same campaign running across multiple ad accounts on the same platform,
    # or the same real-world campaign across Google and Meta).
    # The uniqueness constraint is at the account + campaign level so the same
    # external_campaign_id on a different account is treated as distinct.
    op.execute("""
        CREATE TABLE IF NOT EXISTS campaign_external_refs (
            external_ref_id         UUID        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               TEXT        NOT NULL,
            campaign_id             UUID        NOT NULL,
            platform                TEXT        NOT NULL,
            external_account_id     TEXT        NOT NULL,
            external_campaign_id    TEXT        NOT NULL,
            external_campaign_name  TEXT,
            external_status         TEXT,
            source_connector_id     TEXT,
            first_seen_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_seen_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            raw_metadata            JSONB       NOT NULL DEFAULT '{}'::jsonb,
            schema_version          INTEGER     NOT NULL DEFAULT 1,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT campaign_external_refs_pk PRIMARY KEY (external_ref_id),
            CONSTRAINT cer_tenant_platform_account_campaign_uk
                UNIQUE (tenant_id, platform, external_account_id, external_campaign_id),
            CONSTRAINT cer_campaign_fk
                FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id)
        );

        CREATE INDEX IF NOT EXISTS cer_campaign_idx
            ON campaign_external_refs (tenant_id, campaign_id);

        CREATE INDEX IF NOT EXISTS cer_platform_account_idx
            ON campaign_external_refs (tenant_id, platform, external_account_id);

        CREATE INDEX IF NOT EXISTS cer_last_seen_idx
            ON campaign_external_refs (tenant_id, last_seen_at DESC);
    """)

    # ── 3. campaign_aliases ───────────────────────────────────────────────────
    # Acquisition evidence aliases used by the resolver.
    # Supported alias_type values:
    #   utm_id, canonical_token, external_campaign_id, utm_campaign,
    #   external_campaign_name, landing_token, custom_tracking_code,
    #   partner_code, affiliate_code, qr_code
    #
    # The partial unique index enforces that two active (valid_until IS NULL)
    # aliases of the same type cannot share the same normalized value within
    # a tenant. When an alias expires, valid_until is set and a new one may
    # be registered for the same normalized value.
    op.execute("""
        CREATE TABLE IF NOT EXISTS campaign_aliases (
            alias_id                UUID        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               TEXT        NOT NULL,
            campaign_id             UUID        NOT NULL,
            alias_type              TEXT        NOT NULL,
            alias_value             TEXT        NOT NULL,
            alias_value_normalized  TEXT        NOT NULL,
            platform                TEXT,
            external_account_id     TEXT,
            source                  TEXT,
            medium                  TEXT,
            valid_from              TIMESTAMPTZ,
            valid_until             TIMESTAMPTZ,
            source_connector_id     TEXT,
            created_by              TEXT        NOT NULL DEFAULT 'system',
            provenance              JSONB       NOT NULL DEFAULT '{}'::jsonb,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT campaign_aliases_pk PRIMARY KEY (alias_id),
            CONSTRAINT ca_campaign_fk
                FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id)
        );

        -- One active alias of a given type per normalized value per tenant.
        -- Expired aliases (valid_until IS NOT NULL) are excluded so history
        -- is preserved without blocking new registrations.
        CREATE UNIQUE INDEX IF NOT EXISTS ca_active_alias_type_value_idx
            ON campaign_aliases (tenant_id, alias_type, alias_value_normalized)
            WHERE valid_until IS NULL;

        CREATE INDEX IF NOT EXISTS ca_campaign_idx
            ON campaign_aliases (tenant_id, campaign_id);

        CREATE INDEX IF NOT EXISTS ca_type_value_idx
            ON campaign_aliases (tenant_id, alias_type, alias_value_normalized);
    """)

    # ── 4. campaign_resolution_reviews ────────────────────────────────────────
    # Durable queue for unresolved or ambiguous campaign evidence.
    # evidence_hash is a stable SHA-256 over (tenant_id, normalized evidence fields)
    # so identical unresolved evidence from repeated events increments observed_count
    # on the same open row instead of creating a new review item.
    op.execute("""
        CREATE TABLE IF NOT EXISTS campaign_resolution_reviews (
            review_id               UUID        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               TEXT        NOT NULL,
            status                  TEXT        NOT NULL DEFAULT 'open',
            evidence                JSONB       NOT NULL,
            evidence_hash           TEXT        NOT NULL,
            candidate_campaign_ids  JSONB       NOT NULL DEFAULT '[]'::jsonb,
            observed_count          INTEGER     NOT NULL DEFAULT 1,
            affected_touchpoints    INTEGER     NOT NULL DEFAULT 0,
            first_seen_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_seen_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            resolved_campaign_id    UUID,
            resolved_by             TEXT,
            resolved_at             TIMESTAMPTZ,
            resolution_note         TEXT,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT campaign_resolution_reviews_pk PRIMARY KEY (review_id),
            CONSTRAINT crr_tenant_hash_status_uk
                UNIQUE (tenant_id, evidence_hash, status),
            CONSTRAINT crr_resolved_campaign_fk
                FOREIGN KEY (resolved_campaign_id) REFERENCES campaigns(campaign_id)
        );

        CREATE INDEX IF NOT EXISTS crr_tenant_status_idx
            ON campaign_resolution_reviews (tenant_id, status, first_seen_at DESC);

        CREATE INDEX IF NOT EXISTS crr_tenant_hash_idx
            ON campaign_resolution_reviews (tenant_id, evidence_hash);
    """)

    # ── 5. Extend spend_records ───────────────────────────────────────────────
    # Preserve original provider campaign identity alongside the canonical UUID.
    # campaign_resolution_status values: resolved, unresolved, ambiguous,
    #   not_applicable (connector writes with explicit canonical UUID)
    op.execute("""
        ALTER TABLE spend_records
            ADD COLUMN IF NOT EXISTS external_campaign_id        TEXT,
            ADD COLUMN IF NOT EXISTS external_account_id         TEXT,
            ADD COLUMN IF NOT EXISTS campaign_resolution_status  TEXT DEFAULT 'not_applicable',
            ADD COLUMN IF NOT EXISTS campaign_resolution_method  TEXT,
            ADD COLUMN IF NOT EXISTS campaign_resolution_version TEXT;

        CREATE INDEX IF NOT EXISTS sr_external_campaign_idx
            ON spend_records (tenant_id, external_campaign_id)
            WHERE external_campaign_id IS NOT NULL;
    """)

    # ── 6. Extend silver_campaign_touchpoint_facts ────────────────────────────
    op.execute("""
        ALTER TABLE silver_campaign_touchpoint_facts
            ADD COLUMN IF NOT EXISTS external_campaign_id           TEXT,
            ADD COLUMN IF NOT EXISTS external_account_id            TEXT,
            ADD COLUMN IF NOT EXISTS campaign_resolution_status     TEXT DEFAULT 'not_applicable',
            ADD COLUMN IF NOT EXISTS campaign_resolution_method     TEXT,
            ADD COLUMN IF NOT EXISTS campaign_resolution_confidence NUMERIC(5,4),
            ADD COLUMN IF NOT EXISTS campaign_resolution_version    TEXT;

        CREATE INDEX IF NOT EXISTS sctf_external_campaign_idx
            ON silver_campaign_touchpoint_facts (tenant_id, external_campaign_id)
            WHERE external_campaign_id IS NOT NULL;

        CREATE INDEX IF NOT EXISTS sctf_resolution_status_idx
            ON silver_campaign_touchpoint_facts (tenant_id, campaign_resolution_status)
            WHERE campaign_resolution_status IN ('unresolved', 'ambiguous');
    """)

    # ── 7. Extend attribution_credits ─────────────────────────────────────────
    op.execute("""
        ALTER TABLE attribution_credits
            ADD COLUMN IF NOT EXISTS external_campaign_id       TEXT,
            ADD COLUMN IF NOT EXISTS campaign_resolution_method TEXT;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE attribution_credits DROP COLUMN IF EXISTS campaign_resolution_method;")
    op.execute("ALTER TABLE attribution_credits DROP COLUMN IF EXISTS external_campaign_id;")

    op.execute("DROP INDEX IF EXISTS sctf_resolution_status_idx;")
    op.execute("DROP INDEX IF EXISTS sctf_external_campaign_idx;")
    op.execute("ALTER TABLE silver_campaign_touchpoint_facts DROP COLUMN IF EXISTS campaign_resolution_version;")
    op.execute("ALTER TABLE silver_campaign_touchpoint_facts DROP COLUMN IF EXISTS campaign_resolution_confidence;")
    op.execute("ALTER TABLE silver_campaign_touchpoint_facts DROP COLUMN IF EXISTS campaign_resolution_method;")
    op.execute("ALTER TABLE silver_campaign_touchpoint_facts DROP COLUMN IF EXISTS campaign_resolution_status;")
    op.execute("ALTER TABLE silver_campaign_touchpoint_facts DROP COLUMN IF EXISTS external_account_id;")
    op.execute("ALTER TABLE silver_campaign_touchpoint_facts DROP COLUMN IF EXISTS external_campaign_id;")

    op.execute("DROP INDEX IF EXISTS sr_external_campaign_idx;")
    op.execute("ALTER TABLE spend_records DROP COLUMN IF EXISTS campaign_resolution_version;")
    op.execute("ALTER TABLE spend_records DROP COLUMN IF EXISTS campaign_resolution_method;")
    op.execute("ALTER TABLE spend_records DROP COLUMN IF EXISTS campaign_resolution_status;")
    op.execute("ALTER TABLE spend_records DROP COLUMN IF EXISTS external_account_id;")
    op.execute("ALTER TABLE spend_records DROP COLUMN IF EXISTS external_campaign_id;")

    op.execute("DROP TABLE IF EXISTS campaign_resolution_reviews CASCADE;")
    op.execute("DROP TABLE IF EXISTS campaign_aliases CASCADE;")
    op.execute("DROP TABLE IF EXISTS campaign_external_refs CASCADE;")
    op.execute("DROP TABLE IF EXISTS campaigns CASCADE;")
