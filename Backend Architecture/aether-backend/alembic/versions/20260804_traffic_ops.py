"""Traffic-intelligence ops: shadow divergences + tenant traffic config.

Two additive tables for the traffic-intelligence follow-up work:

``source_classification_shadow_divergences`` — observational legacy-vs-canonical
source_class divergence facts (services/traffic/shadow.py). Written only in
shadow mode; never mutates customer-visible touchpoints or attribution.
Idempotent on (tenant_id, source_event_id, classifier_version) via a hashed
idempotency_key so a replayed event never double-counts a divergence.

``tenant_traffic_config`` — one JSONB config row per tenant (services/traffic/
config.py): source-link domains, destination allowlist, vanity URLs, placement
taxonomy, custom source aliases, custom search/social domain extensions,
interaction-tracking / URL-sanitization / direct-traffic policy, attribution
expiration, and historical-repair controls. Controlled extension only — values
are validated against the canonical registry at the API boundary.

Additive + reversible; IF NOT EXISTS idioms throughout, matching
20260803_deferred_attribution.

Revision ID: 20260804_traffic_ops
Revises: 20260803_deferred_attribution
Create Date: 2026-07-24
"""

from __future__ import annotations

from alembic import op

revision = "20260804_traffic_ops"
down_revision = "20260803_deferred_attribution"
branch_labels = None
depends_on = None


SHADOW_DIVERGENCES_DDL = """
CREATE TABLE IF NOT EXISTS source_classification_shadow_divergences (
    id                       BIGSERIAL PRIMARY KEY,
    tenant_id                TEXT NOT NULL,
    source_event_id          TEXT NOT NULL,
    touchpoint_id            UUID,
    legacy_source_class      TEXT NOT NULL,
    canonical_source_class   TEXT NOT NULL,
    diverged                 BOOLEAN NOT NULL DEFAULT FALSE,
    classifier_version       TEXT NOT NULL,
    observed_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    idempotency_key          TEXT NOT NULL,
    CONSTRAINT uq_shadow_divergence_idempotency UNIQUE (idempotency_key)
);
"""

SHADOW_DIVERGENCES_TENANT_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS ix_shadow_divergences_tenant_time "
    "ON source_classification_shadow_divergences (tenant_id, observed_at)"
)

SHADOW_DIVERGENCES_DIVERGED_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS ix_shadow_divergences_tenant_diverged "
    "ON source_classification_shadow_divergences (tenant_id, diverged)"
)

TENANT_TRAFFIC_CONFIG_DDL = """
CREATE TABLE IF NOT EXISTS tenant_traffic_config (
    tenant_id    TEXT PRIMARY KEY,
    config       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def upgrade() -> None:
    op.execute(SHADOW_DIVERGENCES_DDL)
    op.execute(SHADOW_DIVERGENCES_TENANT_INDEX_DDL)
    op.execute(SHADOW_DIVERGENCES_DIVERGED_INDEX_DDL)
    op.execute(TENANT_TRAFFIC_CONFIG_DDL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tenant_traffic_config")
    op.execute("DROP INDEX IF EXISTS ix_shadow_divergences_tenant_diverged")
    op.execute("DROP INDEX IF EXISTS ix_shadow_divergences_tenant_time")
    op.execute("DROP TABLE IF EXISTS source_classification_shadow_divergences")
