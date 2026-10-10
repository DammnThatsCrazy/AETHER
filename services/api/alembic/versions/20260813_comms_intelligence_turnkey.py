"""communications intelligence — credential-turnkey spine

Revision ID: 20260813_comms_turnkey
Revises: 20260813_payment_webhook_endpoints
Create Date: 2026-08-13

Additive-only schema for the credential-turnkey communications reference
release. Three concerns, one revision (mirrors the 20260703_comms_intel
precedent of grouping the comms schema):

  * ``comms_sync_runs`` — durable per-run synchronization ledger (§12.4). Generic
    JSONB row shape so the repository inherits the in-memory local-mode fallback
    (BaseRepository), matching connector_cursors / webhook_inbox.
  * ``comms_provider_identities`` — provider→canonical identity bridge with a
    provisional/unresolved queue (§13). Same JSONB shape.
  * ``communication_suppressions`` — enforcement/consent state columns that
    separate provider-reported from Aether-enforced suppression (§16).

Safe to run online: only ``CREATE TABLE IF NOT EXISTS`` and additive
``ADD COLUMN IF NOT EXISTS``; no table rewrites. ``downgrade`` drops the new
tables and columns.
"""

from alembic import op

revision = "20260813_comms_turnkey"
down_revision = "20260813_payment_webhook_endpoints"
branch_labels = None
depends_on = None


# New nullable columns on communication_suppressions (§16 state separation).
_SUPPRESSION_COLUMNS = [
    ("provider_account_id", "TEXT"),
    ("canonical_entity_id", "TEXT"),
    ("canonical_profile_id", "TEXT"),
    ("consent_purpose", "TEXT"),
    ("processing_basis", "TEXT"),
    # provider_reported | aether_observed | aether_enforced | unknown
    ("provider_enforcement_state", "TEXT"),
    # enforced | pending | write_back_pending | write_back_failed | write_back_disabled
    ("aether_enforcement_state", "TEXT"),
    ("last_reconciled_at", "TIMESTAMPTZ"),
    ("evidence_reference", "TEXT"),
]


def upgrade() -> None:
    # ── Durable synchronization ledger (§12.4) ───────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS comms_sync_runs (
            id TEXT PRIMARY KEY,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            tenant_id TEXT,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_comms_sync_runs_tenant "
        "ON comms_sync_runs (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_comms_sync_runs_connector "
        "ON comms_sync_runs (tenant_id, (data->>'connector_instance_id'))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_comms_sync_runs_status "
        "ON comms_sync_runs ((data->>'status'))"
    )

    # ── Provider → canonical identity bridge (§13) ───────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS comms_provider_identities (
            id TEXT PRIMARY KEY,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            tenant_id TEXT,
            created_at TIMESTAMPTZ DEFAULT now(),
            updated_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_comms_provider_identities_tenant "
        "ON comms_provider_identities (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_comms_provider_identities_provider "
        "ON comms_provider_identities "
        "(tenant_id, (data->>'provider'), (data->>'provider_profile_id'))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_comms_provider_identities_status "
        "ON comms_provider_identities ((data->>'resolution_status'))"
    )

    # ── Suppression enforcement/consent state columns (§16) ──────────────────
    for col, sqltype in _SUPPRESSION_COLUMNS:
        op.execute(
            f"ALTER TABLE communication_suppressions "
            f"ADD COLUMN IF NOT EXISTS {col} {sqltype};"
        )


def downgrade() -> None:
    for col, _ in _SUPPRESSION_COLUMNS:
        op.execute(
            f"ALTER TABLE communication_suppressions DROP COLUMN IF EXISTS {col};"
        )
    op.execute("DROP TABLE IF EXISTS comms_provider_identities;")
    op.execute("DROP TABLE IF EXISTS comms_sync_runs;")
