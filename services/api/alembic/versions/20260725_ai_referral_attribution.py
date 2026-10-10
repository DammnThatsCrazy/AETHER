"""AI and agent referral classification extensions for canonical attribution.

This migration extends the existing acquisition -> canonical touchpoint ->
journey -> attribution -> measurement path.  It deliberately does not create a
second touchpoint, campaign, attribution, or job subsystem.

The active source classification remains a projection on
``silver_campaign_touchpoint_facts``.  Historical classifier decisions are
preserved in ``touchpoint_source_classification_revisions`` and repair progress
is checkpointed in ``source_classification_repair_runs`` while execution stays
on the existing durable ``jobs`` platform.  Verified referral links store only
a token hash; plaintext referral tokens are never persisted.

Revision ID: 20260725_ai_referral_attribution
Revises: 20260724_ingestion_v2
Create Date: 2026-07-25
"""

from __future__ import annotations

from alembic import op

revision = "20260725_ai_referral_attribution"
down_revision = "20260724_ingestion_v2"
branch_labels = None
depends_on = None


VERIFIED_REFERRAL_LINKS_DDL = """
CREATE TABLE IF NOT EXISTS verified_referral_links (
    verified_referral_link_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    placement_id TEXT,
    agent_id TEXT,
    campaign_id TEXT,
    ai_provider TEXT,
    ai_product TEXT,
    referral_mediation_type TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    expires_at TIMESTAMPTZ,
    use_count BIGINT NOT NULL DEFAULT 0,
    first_used_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    created_by TEXT,
    revoked_by TEXT,
    revocation_reason TEXT,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT verified_referral_links_token_hash_uk UNIQUE (token_hash),
    CONSTRAINT verified_referral_links_tenant_link_uk
        UNIQUE (tenant_id, verified_referral_link_id)
);
"""


VERIFIED_REFERRAL_LINK_USES_DDL = """
CREATE TABLE IF NOT EXISTS verified_referral_link_uses (
    tenant_id TEXT NOT NULL,
    verified_referral_link_id UUID NOT NULL,
    source_event_id TEXT NOT NULL,
    first_used_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT verified_referral_link_uses_pk
        PRIMARY KEY (tenant_id, verified_referral_link_id, source_event_id),
    CONSTRAINT verified_referral_link_uses_link_fk
        FOREIGN KEY (tenant_id, verified_referral_link_id)
        REFERENCES verified_referral_links
            (tenant_id, verified_referral_link_id)
);
"""


JOBS_TENANT_REFERENCE_KEY_DDL = """
ALTER TABLE jobs
    ADD CONSTRAINT jobs_tenant_id_id_uk UNIQUE (tenant_id, id);
"""


SOURCE_CLASSIFICATION_REPAIR_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS source_classification_repair_runs (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    target_classifier_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    phase TEXT NOT NULL DEFAULT 'classify_touchpoints',
    filters JSONB NOT NULL DEFAULT '{}'::jsonb,
    cursor_occurred_at TIMESTAMPTZ,
    cursor_touchpoint_id UUID,
    counters JSONB NOT NULL DEFAULT '{}'::jsonb,
    errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT source_classification_repair_runs_job_uk UNIQUE (job_id),
    CONSTRAINT source_classification_repair_runs_job_fk
        FOREIGN KEY (tenant_id, job_id) REFERENCES jobs(tenant_id, id)
);
"""


TOUCHPOINT_CLASSIFICATION_COLUMNS_DDL = """
ALTER TABLE silver_campaign_touchpoint_facts
    ADD COLUMN IF NOT EXISTS source_class TEXT,
    ADD COLUMN IF NOT EXISTS referral_mediation_type TEXT,
    ADD COLUMN IF NOT EXISTS ai_provider TEXT,
    ADD COLUMN IF NOT EXISTS ai_product TEXT,
    ADD COLUMN IF NOT EXISTS actor_type TEXT,
    ADD COLUMN IF NOT EXISTS journey_role TEXT,
    ADD COLUMN IF NOT EXISTS evidence_confidence NUMERIC(5,4),
    ADD COLUMN IF NOT EXISTS verification_level TEXT,
    ADD COLUMN IF NOT EXISTS source_classifier_version TEXT,
    ADD COLUMN IF NOT EXISTS source_classified_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS normalized_referrer_domain TEXT,
    ADD COLUMN IF NOT EXISTS referrer_path_hash TEXT,
    ADD COLUMN IF NOT EXISTS source_classification_evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS source_classification_id UUID,
    ADD COLUMN IF NOT EXISTS attribution_eligible BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS verified_referral_link_id UUID;
"""


TOUCHPOINT_CLASSIFICATION_REVISIONS_DDL = """
CREATE TABLE IF NOT EXISTS touchpoint_source_classification_revisions (
    classification_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    touchpoint_id UUID NOT NULL,
    classifier_version TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    prior_classification JSONB NOT NULL DEFAULT '{}'::jsonb,
    classification JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence NUMERIC(5,4),
    verification_level TEXT,
    reason TEXT NOT NULL,
    job_id TEXT,
    previous_classification_id UUID,
    superseded_by UUID,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    classified_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT tsc_revisions_tenant_classification_uk
        UNIQUE (tenant_id, classification_id),
    CONSTRAINT tsc_revisions_confidence_ck
        CHECK (
            confidence IS NULL
            OR (confidence >= 0 AND confidence <= 1)
        ),
    CONSTRAINT tsc_revisions_touchpoint_fk
        FOREIGN KEY (tenant_id, touchpoint_id)
        REFERENCES silver_campaign_touchpoint_facts (tenant_id, touchpoint_id),
    CONSTRAINT tsc_revisions_job_fk
        FOREIGN KEY (tenant_id, job_id) REFERENCES jobs(tenant_id, id),
    CONSTRAINT tsc_revisions_previous_classification_fk
        FOREIGN KEY (tenant_id, previous_classification_id)
        REFERENCES touchpoint_source_classification_revisions
            (tenant_id, classification_id),
    CONSTRAINT tsc_revisions_superseded_by_fk
        FOREIGN KEY (tenant_id, superseded_by)
        REFERENCES touchpoint_source_classification_revisions
            (tenant_id, classification_id)
);
"""


TOUCHPOINT_CLASSIFICATION_RELATIONSHIPS_DDL = """
ALTER TABLE silver_campaign_touchpoint_facts
    ADD CONSTRAINT sctf_source_classification_fk
        FOREIGN KEY (tenant_id, source_classification_id)
        REFERENCES touchpoint_source_classification_revisions
            (tenant_id, classification_id),
    ADD CONSTRAINT sctf_verified_referral_link_fk
        FOREIGN KEY (tenant_id, verified_referral_link_id)
        REFERENCES verified_referral_links (tenant_id, verified_referral_link_id);
"""


CANONICAL_ACTIVITY_COLUMNS_DDL = """
ALTER TABLE canonical_activity
    ADD COLUMN IF NOT EXISTS source_class TEXT,
    ADD COLUMN IF NOT EXISTS referral_mediation_type TEXT,
    ADD COLUMN IF NOT EXISTS ai_provider TEXT,
    ADD COLUMN IF NOT EXISTS ai_product TEXT,
    ADD COLUMN IF NOT EXISTS journey_role TEXT,
    ADD COLUMN IF NOT EXISTS evidence_confidence NUMERIC(5,4),
    ADD COLUMN IF NOT EXISTS verification_level TEXT,
    ADD COLUMN IF NOT EXISTS source_classifier_version TEXT,
    ADD COLUMN IF NOT EXISTS normalized_referrer_domain TEXT,
    ADD COLUMN IF NOT EXISTS source_classification_id UUID,
    ADD COLUMN IF NOT EXISTS attribution_eligible BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS verified_referral_link_id UUID;
"""


JOURNEY_STEP_COLUMNS_DDL = """
ALTER TABLE journey_steps
    ADD COLUMN IF NOT EXISTS source_class TEXT,
    ADD COLUMN IF NOT EXISTS referral_mediation_type TEXT,
    ADD COLUMN IF NOT EXISTS ai_provider TEXT,
    ADD COLUMN IF NOT EXISTS ai_product TEXT,
    ADD COLUMN IF NOT EXISTS journey_role TEXT,
    ADD COLUMN IF NOT EXISTS evidence_confidence NUMERIC(5,4),
    ADD COLUMN IF NOT EXISTS verification_level TEXT,
    ADD COLUMN IF NOT EXISTS source_classifier_version TEXT,
    ADD COLUMN IF NOT EXISTS normalized_referrer_domain TEXT,
    ADD COLUMN IF NOT EXISTS source_classification_id UUID,
    ADD COLUMN IF NOT EXISTS attribution_eligible BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS verified_referral_link_id UUID;
"""


JOURNEY_VERSION_COLUMNS_DDL = """
ALTER TABLE journey_versions
    ADD COLUMN IF NOT EXISTS excluded_source_noise_count INTEGER NOT NULL DEFAULT 0;
"""


ATTRIBUTION_CREDIT_COLUMNS_DDL = """
ALTER TABLE attribution_credits
    ADD COLUMN IF NOT EXISTS source_class TEXT,
    ADD COLUMN IF NOT EXISTS referral_mediation_type TEXT,
    ADD COLUMN IF NOT EXISTS ai_provider TEXT,
    ADD COLUMN IF NOT EXISTS ai_product TEXT,
    ADD COLUMN IF NOT EXISTS actor_type TEXT,
    ADD COLUMN IF NOT EXISTS journey_role TEXT,
    ADD COLUMN IF NOT EXISTS evidence_confidence NUMERIC(5,4),
    ADD COLUMN IF NOT EXISTS verification_level TEXT,
    ADD COLUMN IF NOT EXISTS source_classifier_version TEXT,
    ADD COLUMN IF NOT EXISTS normalized_referrer_domain TEXT,
    ADD COLUMN IF NOT EXISTS source_classification_id UUID,
    ADD COLUMN IF NOT EXISTS attribution_eligible BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS verified_referral_link_id UUID;
"""


ATTRIBUTION_RUN_COLUMNS_DDL = """
ALTER TABLE attribution_runs
    ADD COLUMN IF NOT EXISTS trigger_reason TEXT,
    ADD COLUMN IF NOT EXISTS source_classifier_version TEXT,
    ADD COLUMN IF NOT EXISTS model_config_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS prior_attribution_run_id UUID;

ALTER TABLE attribution_runs
    ADD CONSTRAINT attribution_runs_prior_run_fk
        FOREIGN KEY (tenant_id, prior_attribution_run_id)
        REFERENCES attribution_runs (tenant_id, attribution_run_id);
"""


DEDUPLICATE_ACTIVE_ATTRIBUTION_RUNS_DDL = """
WITH ranked_active_runs AS (
    SELECT
        tenant_id,
        attribution_run_id,
        ROW_NUMBER() OVER (
            PARTITION BY tenant_id, conversion_id
            ORDER BY
                created_at DESC,
                completed_at DESC NULLS LAST,
                attribution_run_id DESC
        ) AS active_rank
    FROM attribution_runs
    WHERE is_active IS TRUE
)
UPDATE attribution_runs AS attribution_run
SET is_active = FALSE
FROM ranked_active_runs AS ranked
WHERE ranked.active_rank > 1
  AND attribution_run.tenant_id = ranked.tenant_id
  AND attribution_run.attribution_run_id = ranked.attribution_run_id;
"""


DEDUPLICATE_CURRENT_JOURNEY_VERSIONS_DDL = """
WITH ranked_current_versions AS (
    SELECT
        tenant_id,
        journey_version_id,
        ROW_NUMBER() OVER (
            PARTITION BY tenant_id, journey_id
            ORDER BY computed_at DESC, journey_version_id DESC
        ) AS current_rank
    FROM journey_versions
    WHERE is_current IS TRUE
)
UPDATE journey_versions AS journey
SET is_current = FALSE
FROM ranked_current_versions AS ranked
WHERE ranked.current_rank > 1
  AND journey.tenant_id = ranked.tenant_id
  AND journey.journey_version_id = ranked.journey_version_id;
"""


INDEXES = [
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_journey_versions_current "
    "ON journey_versions (tenant_id, journey_id) WHERE is_current IS TRUE",
    "CREATE INDEX IF NOT EXISTS ix_verified_referral_links_tenant_status_expiry "
    "ON verified_referral_links (tenant_id, status, expires_at)",
    "CREATE INDEX IF NOT EXISTS ix_verified_referral_links_tenant_provider_product "
    "ON verified_referral_links (tenant_id, ai_provider, ai_product) "
    "WHERE ai_provider IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_verified_referral_links_tenant_mediation "
    "ON verified_referral_links (tenant_id, referral_mediation_type) "
    "WHERE referral_mediation_type IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_source_classification_repair_runs_tenant_status "
    "ON source_classification_repair_runs (tenant_id, status, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_source_classification_repair_runs_tenant_version "
    "ON source_classification_repair_runs (tenant_id, target_classifier_version, created_at DESC)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_tsc_revisions_current "
    "ON touchpoint_source_classification_revisions (tenant_id, touchpoint_id) "
    "WHERE is_current IS TRUE",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_tsc_revisions_replay "
    "ON touchpoint_source_classification_revisions "
    "(tenant_id, touchpoint_id, classifier_version, input_hash)",
    "CREATE INDEX IF NOT EXISTS ix_tsc_revisions_tenant_provider "
    "ON touchpoint_source_classification_revisions "
    "(tenant_id, (classification ->> 'ai_provider'), classified_at DESC) "
    "WHERE (classification ->> 'ai_provider') IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_tsc_revisions_tenant_mediation "
    "ON touchpoint_source_classification_revisions "
    "(tenant_id, (classification ->> 'referral_mediation_type'), classified_at DESC) "
    "WHERE (classification ->> 'referral_mediation_type') IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_tsc_revisions_tenant_version "
    "ON touchpoint_source_classification_revisions "
    "(tenant_id, classifier_version, classified_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_sctf_ai_provider_occurred "
    "ON silver_campaign_touchpoint_facts (tenant_id, ai_provider, occurred_at DESC) "
    "WHERE ai_provider IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_sctf_referral_mediation_occurred "
    "ON silver_campaign_touchpoint_facts "
    "(tenant_id, referral_mediation_type, occurred_at DESC) "
    "WHERE referral_mediation_type IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_sctf_source_classifier_version "
    "ON silver_campaign_touchpoint_facts "
    "(tenant_id, source_classifier_version, occurred_at DESC) "
    "WHERE source_classifier_version IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_sctf_verified_referral_link "
    "ON silver_campaign_touchpoint_facts (tenant_id, verified_referral_link_id) "
    "WHERE verified_referral_link_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_sctf_source_classification "
    "ON silver_campaign_touchpoint_facts (tenant_id, source_classification_id) "
    "WHERE source_classification_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_canonical_activity_ai_provider "
    "ON canonical_activity (tenant_id, ai_provider, occurred_at DESC) "
    "WHERE ai_provider IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_canonical_activity_referral_mediation "
    "ON canonical_activity (tenant_id, referral_mediation_type, occurred_at DESC) "
    "WHERE referral_mediation_type IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_canonical_activity_classifier_version "
    "ON canonical_activity (tenant_id, source_classifier_version, occurred_at DESC) "
    "WHERE source_classifier_version IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_journey_steps_ai_provider "
    "ON journey_steps (tenant_id, ai_provider, occurred_at DESC) "
    "WHERE ai_provider IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_journey_steps_referral_mediation "
    "ON journey_steps (tenant_id, referral_mediation_type, occurred_at DESC) "
    "WHERE referral_mediation_type IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_attribution_credits_ai_provider "
    "ON attribution_credits (tenant_id, ai_provider, created_at DESC) "
    "WHERE ai_provider IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_attribution_credits_referral_mediation "
    "ON attribution_credits (tenant_id, referral_mediation_type, created_at DESC) "
    "WHERE referral_mediation_type IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_attribution_runs_classifier_version "
    "ON attribution_runs (tenant_id, source_classifier_version, created_at DESC) "
    "WHERE source_classifier_version IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_attribution_runs_prior_run "
    "ON attribution_runs (tenant_id, prior_attribution_run_id) "
    "WHERE prior_attribution_run_id IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_attribution_runs_active_conversion "
    "ON attribution_runs (tenant_id, conversion_id) WHERE is_active IS TRUE",
]


def upgrade() -> None:
    # Provider/product describe referral mediation and remain independent of the
    # existing canonical campaign registry. campaign_id is only an optional link.
    op.execute(VERIFIED_REFERRAL_LINKS_DDL)
    op.execute(VERIFIED_REFERRAL_LINK_USES_DDL)
    op.execute(JOBS_TENANT_REFERENCE_KEY_DDL)
    op.execute(SOURCE_CLASSIFICATION_REPAIR_RUNS_DDL)
    op.execute(TOUCHPOINT_CLASSIFICATION_COLUMNS_DDL)
    op.execute(TOUCHPOINT_CLASSIFICATION_REVISIONS_DDL)
    op.execute(TOUCHPOINT_CLASSIFICATION_RELATIONSHIPS_DDL)
    op.execute(CANONICAL_ACTIVITY_COLUMNS_DDL)
    op.execute(JOURNEY_STEP_COLUMNS_DDL)
    op.execute(JOURNEY_VERSION_COLUMNS_DDL)
    op.execute(ATTRIBUTION_CREDIT_COLUMNS_DDL)
    op.execute(ATTRIBUTION_RUN_COLUMNS_DDL)

    # A partial unique index cannot be created while historical duplicate active
    # rows exist. Retain the newest run per tenant/conversion, then enforce the
    # invariant for every future recomputation.
    op.execute(DEDUPLICATE_ACTIVE_ATTRIBUTION_RUNS_DDL)
    op.execute(DEDUPLICATE_CURRENT_JOURNEY_VERSIONS_DDL)
    for index_ddl in INDEXES:
        op.execute(index_ddl)


_INDEX_NAMES = [
    "ux_journey_versions_current",
    "ux_attribution_runs_active_conversion",
    "ix_attribution_runs_prior_run",
    "ix_attribution_runs_classifier_version",
    "ix_attribution_credits_referral_mediation",
    "ix_attribution_credits_ai_provider",
    "ix_journey_steps_referral_mediation",
    "ix_journey_steps_ai_provider",
    "ix_canonical_activity_classifier_version",
    "ix_canonical_activity_referral_mediation",
    "ix_canonical_activity_ai_provider",
    "ix_sctf_source_classification",
    "ix_sctf_verified_referral_link",
    "ix_sctf_source_classifier_version",
    "ix_sctf_referral_mediation_occurred",
    "ix_sctf_ai_provider_occurred",
    "ix_tsc_revisions_tenant_version",
    "ix_tsc_revisions_tenant_mediation",
    "ix_tsc_revisions_tenant_provider",
    "ux_tsc_revisions_replay",
    "ux_tsc_revisions_current",
    "ix_source_classification_repair_runs_tenant_version",
    "ix_source_classification_repair_runs_tenant_status",
    "ix_verified_referral_links_tenant_mediation",
    "ix_verified_referral_links_tenant_provider_product",
    "ix_verified_referral_links_tenant_status_expiry",
]


def _drop_columns(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")


def downgrade() -> None:
    for index_name in _INDEX_NAMES:
        op.execute(f"DROP INDEX IF EXISTS {index_name}")

    op.execute(
        "ALTER TABLE attribution_runs "
        "DROP CONSTRAINT IF EXISTS attribution_runs_prior_run_fk"
    )
    op.execute(
        "ALTER TABLE silver_campaign_touchpoint_facts "
        "DROP CONSTRAINT IF EXISTS sctf_source_classification_fk, "
        "DROP CONSTRAINT IF EXISTS sctf_verified_referral_link_fk"
    )

    # Drop history/checkpoint/link tables only after removing references from the
    # canonical touchpoint projection. No CASCADE is used, so unexpected external
    # dependencies fail loudly rather than being destroyed.
    op.execute("DROP TABLE IF EXISTS touchpoint_source_classification_revisions")
    op.execute("DROP TABLE IF EXISTS source_classification_repair_runs")
    op.execute("DROP TABLE IF EXISTS verified_referral_link_uses")
    op.execute("DROP TABLE IF EXISTS verified_referral_links")
    op.execute("ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_tenant_id_id_uk")

    _drop_columns(
        "attribution_runs",
        (
            "prior_attribution_run_id",
            "model_config_snapshot",
            "source_classifier_version",
            "trigger_reason",
        ),
    )
    _drop_columns(
        "attribution_credits",
        (
            "verified_referral_link_id",
            "attribution_eligible",
            "source_classification_id",
            "normalized_referrer_domain",
            "source_classifier_version",
            "verification_level",
            "evidence_confidence",
            "journey_role",
            "actor_type",
            "ai_product",
            "ai_provider",
            "referral_mediation_type",
            "source_class",
        ),
    )
    _drop_columns("journey_versions", ("excluded_source_noise_count",))

    classification_dimensions = (
        "verified_referral_link_id",
        "attribution_eligible",
        "source_classification_id",
        "normalized_referrer_domain",
        "source_classifier_version",
        "verification_level",
        "evidence_confidence",
        "journey_role",
        "ai_product",
        "ai_provider",
        "referral_mediation_type",
        "source_class",
    )
    _drop_columns("journey_steps", classification_dimensions)
    _drop_columns("canonical_activity", classification_dimensions)
    _drop_columns(
        "silver_campaign_touchpoint_facts",
        (
            "verified_referral_link_id",
            "attribution_eligible",
            "source_classification_id",
            "source_classification_evidence",
            "referrer_path_hash",
            "normalized_referrer_domain",
            "source_classified_at",
            "source_classifier_version",
            "verification_level",
            "evidence_confidence",
            "journey_role",
            "actor_type",
            "ai_product",
            "ai_provider",
            "referral_mediation_type",
            "source_class",
        ),
    )
