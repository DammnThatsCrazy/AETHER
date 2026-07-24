"""Deferred attribution handoffs + Apple attribution postbacks.

Two additive tables for Phase 4 iOS traffic intelligence:

``deferred_attribution_handoffs`` — deterministic deferred-attribution
registry (services/traffic/deferred_attribution.py). Only the SHA-256 of the
handoff identifier is stored, unique per tenant; resolution is resolve-once
(consumed_at set atomically) and expiring. Unmatched installs stay
Direct / Unknown — there is no probabilistic path.

``apple_attribution_postbacks`` — campaign-level AdAttributionKit /
SKAdNetwork postback rows (services/attribution/apple_postbacks.py), stored
with proof_level 'platform_verified' and an honest signature_status
('unverified'/'missing' — never 'verified' without real verification).
Idempotent on (tenant_id, idempotency_key). Explicitly separate from
user-level deterministic evidence: no touchpoints are derived from these rows.

Additive + reversible; IF NOT EXISTS idioms throughout, matching
20260733_canonical_activity_surface.

Revision ID: 20260803_deferred_attribution
Revises: 20260802_source_link_proof
Create Date: 2026-07-23
"""

from __future__ import annotations

from alembic import op

revision = "20260803_deferred_attribution"
down_revision = "20260802_source_link_proof"
branch_labels = None
depends_on = None


DEFERRED_HANDOFFS_DDL = """
CREATE TABLE IF NOT EXISTS deferred_attribution_handoffs (
    handoff_id      UUID PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    identifier_hash TEXT NOT NULL,
    evidence        JSONB NOT NULL DEFAULT '{}'::jsonb,
    link_id         TEXT,
    environment     TEXT NOT NULL DEFAULT 'production',
    expires_at      TIMESTAMPTZ NOT NULL,
    consumed_at     TIMESTAMPTZ,
    created_by      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_deferred_handoff_identifier UNIQUE (tenant_id, identifier_hash)
);
"""

DEFERRED_HANDOFFS_PENDING_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS ix_deferred_handoffs_pending "
    "ON deferred_attribution_handoffs (tenant_id, expires_at) "
    "WHERE consumed_at IS NULL"
)

APPLE_POSTBACKS_DDL = """
CREATE TABLE IF NOT EXISTS apple_attribution_postbacks (
    apple_postback_id       UUID PRIMARY KEY,
    tenant_id               TEXT NOT NULL,
    idempotency_key         TEXT NOT NULL,
    reduced_payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
    coarse_conversion_value TEXT,
    fine_conversion_value   INTEGER,
    environment             TEXT NOT NULL DEFAULT 'production',
    signature_status        TEXT NOT NULL DEFAULT 'missing',
    proof_level             TEXT NOT NULL DEFAULT 'platform_verified',
    received_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_apple_postback_idempotency UNIQUE (tenant_id, idempotency_key)
);
"""

APPLE_POSTBACKS_RECEIVED_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS ix_apple_postbacks_received "
    "ON apple_attribution_postbacks (tenant_id, received_at)"
)


def upgrade() -> None:
    op.execute(DEFERRED_HANDOFFS_DDL)
    op.execute(DEFERRED_HANDOFFS_PENDING_INDEX_DDL)
    op.execute(APPLE_POSTBACKS_DDL)
    op.execute(APPLE_POSTBACKS_RECEIVED_INDEX_DDL)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_apple_postbacks_received")
    op.execute("DROP TABLE IF EXISTS apple_attribution_postbacks")
    op.execute("DROP INDEX IF EXISTS ix_deferred_handoffs_pending")
    op.execute("DROP TABLE IF EXISTS deferred_attribution_handoffs")
