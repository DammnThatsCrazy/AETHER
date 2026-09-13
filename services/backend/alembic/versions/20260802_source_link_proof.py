"""Verified source-link placement model, immutable redirect uses, and handoffs.

Extends the existing verified referral-link ledger (20260725) with the
canonical placement vocabulary (source / medium / channel_family /
economic_class / source_class), a link-owned redirect destination, activation
window, environment binding, and use budget.  Redirect traffic is recorded as
immutable rows in ``verified_referral_link_uses`` (now keyed by ``use_id`` so
uses without a Bronze event exist), and one-time human handoff tokens minted by
``GET /v1/r/{token}`` are stored hash-only in ``source_link_handoffs``.

Plaintext tokens are never persisted: both link tokens and handoff tokens are
stored exclusively as SHA-256 digests.

Additive + reversible.

Revision ID: 20260802_source_link_proof
Revises: 20260801_canonical_traffic
Create Date: 2026-07-23
"""

from __future__ import annotations

from alembic import op

revision = "20260802_source_link_proof"
down_revision = "20260801_canonical_traffic"
branch_labels = None
depends_on = None


VERIFIED_REFERRAL_LINKS_PLACEMENT_COLUMNS_DDL = """
ALTER TABLE verified_referral_links
    ADD COLUMN IF NOT EXISTS source TEXT,
    ADD COLUMN IF NOT EXISTS medium TEXT,
    ADD COLUMN IF NOT EXISTS channel_family TEXT,
    ADD COLUMN IF NOT EXISTS economic_class TEXT,
    ADD COLUMN IF NOT EXISTS source_class TEXT,
    ADD COLUMN IF NOT EXISTS destination_url TEXT,
    ADD COLUMN IF NOT EXISTS valid_from TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS environment TEXT,
    ADD COLUMN IF NOT EXISTS max_uses BIGINT,
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
"""


# Redirect uses have no Bronze source_event_id, so the ledger moves from the
# (tenant, link, event) natural key to a surrogate use_id primary key while the
# event-dedup invariant is preserved by a partial unique index.
VERIFIED_REFERRAL_LINK_USES_REDIRECT_COLUMNS_DDL = """
ALTER TABLE verified_referral_link_uses
    ADD COLUMN IF NOT EXISTS use_id UUID NOT NULL DEFAULT gen_random_uuid(),
    ADD COLUMN IF NOT EXISTS placement_id TEXT,
    ADD COLUMN IF NOT EXISTS ua_class TEXT,
    ADD COLUMN IF NOT EXISTS is_machine BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS verification_result TEXT,
    ADD COLUMN IF NOT EXISTS environment TEXT,
    ADD COLUMN IF NOT EXISTS handoff_minted BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS correlated_at TIMESTAMPTZ;
"""


VERIFIED_REFERRAL_LINK_USES_REKEY_DDL = """
ALTER TABLE verified_referral_link_uses
    DROP CONSTRAINT IF EXISTS verified_referral_link_uses_pk;
ALTER TABLE verified_referral_link_uses
    ALTER COLUMN source_event_id DROP NOT NULL;
ALTER TABLE verified_referral_link_uses
    ADD CONSTRAINT verified_referral_link_uses_use_pk PRIMARY KEY (use_id);
"""


SOURCE_LINK_HANDOFFS_DDL = """
CREATE TABLE IF NOT EXISTS source_link_handoffs (
    handoff_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id TEXT NOT NULL,
    handoff_hash TEXT NOT NULL,
    link_id UUID NOT NULL,
    link_use_id UUID NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    consumed_source_event_id TEXT,
    replay_count BIGINT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    environment TEXT,

    CONSTRAINT source_link_handoffs_hash_uk UNIQUE (handoff_hash),
    CONSTRAINT source_link_handoffs_link_fk
        FOREIGN KEY (tenant_id, link_id)
        REFERENCES verified_referral_links (tenant_id, verified_referral_link_id),
    CONSTRAINT source_link_handoffs_use_fk
        FOREIGN KEY (link_use_id)
        REFERENCES verified_referral_link_uses (use_id)
);
"""


INDEXES = [
    # Preserves the Bronze event-replay dedup contract used by
    # VerifiedReferralLinkRepository.resolve_token_hash.
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_verified_referral_link_uses_event "
    "ON verified_referral_link_uses "
    "(tenant_id, verified_referral_link_id, source_event_id) "
    "WHERE source_event_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_verified_referral_link_uses_tenant_link_time "
    "ON verified_referral_link_uses "
    "(tenant_id, verified_referral_link_id, first_used_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_source_link_handoffs_tenant_expiry "
    "ON source_link_handoffs (tenant_id, expires_at)",
    "CREATE INDEX IF NOT EXISTS ix_source_link_handoffs_link "
    "ON source_link_handoffs (tenant_id, link_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_verified_referral_links_environment "
    "ON verified_referral_links (tenant_id, environment) "
    "WHERE environment IS NOT NULL",
]


def upgrade() -> None:
    op.execute(VERIFIED_REFERRAL_LINKS_PLACEMENT_COLUMNS_DDL)
    op.execute(VERIFIED_REFERRAL_LINK_USES_REDIRECT_COLUMNS_DDL)
    op.execute(VERIFIED_REFERRAL_LINK_USES_REKEY_DDL)
    op.execute(SOURCE_LINK_HANDOFFS_DDL)
    for index_ddl in INDEXES:
        op.execute(index_ddl)


_INDEX_NAMES = [
    "ix_verified_referral_links_environment",
    "ix_source_link_handoffs_link",
    "ix_source_link_handoffs_tenant_expiry",
    "ix_verified_referral_link_uses_tenant_link_time",
    "ux_verified_referral_link_uses_event",
]


def _drop_columns(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS source_link_handoffs")
    for index_name in _INDEX_NAMES:
        op.execute(f"DROP INDEX IF EXISTS {index_name}")

    # Restore the original natural-key ledger. Rows without a source_event_id
    # (redirect uses) cannot exist under the old key and are dropped with it.
    op.execute(
        "DELETE FROM verified_referral_link_uses WHERE source_event_id IS NULL"
    )
    op.execute(
        "ALTER TABLE verified_referral_link_uses "
        "DROP CONSTRAINT IF EXISTS verified_referral_link_uses_use_pk"
    )
    op.execute(
        "ALTER TABLE verified_referral_link_uses "
        "ALTER COLUMN source_event_id SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE verified_referral_link_uses "
        "ADD CONSTRAINT verified_referral_link_uses_pk "
        "PRIMARY KEY (tenant_id, verified_referral_link_id, source_event_id)"
    )
    _drop_columns(
        "verified_referral_link_uses",
        (
            "correlated_at",
            "handoff_minted",
            "environment",
            "verification_result",
            "is_machine",
            "ua_class",
            "placement_id",
            "use_id",
        ),
    )
    _drop_columns(
        "verified_referral_links",
        (
            "metadata",
            "max_uses",
            "environment",
            "valid_from",
            "destination_url",
            "source_class",
            "economic_class",
            "channel_family",
            "medium",
            "source",
        ),
    )
