"""credential-turnkey: Alembic chain for every auto-created JSONB table + rail mirror.

The build-wave repos write through ``repositories.repos.BaseRepository``, which
auto-creates a JSONB table at first write (``_ensure_table``)::

    CREATE TABLE IF NOT EXISTS <t> (
        id TEXT PRIMARY KEY,
        data JSONB NOT NULL DEFAULT '{}'::jsonb,
        tenant_id TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    )
    CREATE INDEX IF NOT EXISTS idx_<t>_tenant ON <t> (tenant_id);

A clean-DB ``alembic upgrade head`` used to land with NONE of those tables, so
the first write raced schema creation and the runtime auto-create never ran in
a read-only replica / pre-provisioned migration path. This revision backfills
the migration chain with the same idempotent, additive DDL so a provisioned
deployment matches what the runtime creates.

Also carries the payment-rail durability mirror tables
(``LedgerDurabilitySeam.migration_ddl()``) verbatim, and repairs the
2026-06-13 reward-enablement clean-DB bug: ``20260613_reward_enablement``
created the ``reward_*`` tables with a columnar schema that has NO ``data``
JSONB column, while the reward repositories are ``BaseRepository``-backed and
read/write ``row["data"]`` — on a fresh DB those reads fail with "column data
does not exist". The ALTERs below add the column idempotently.

Everything is additive + idempotent (IF NOT EXISTS everywhere), and the
downgrade drops exactly what this revision created.

Revision ID: 20260901_credential_turnkey_tables
Revises: 20260830_app_version_registration
Create Date: 2026-08-09
"""

from __future__ import annotations

from alembic import op

revision = "20260901_credential_turnkey_tables"
down_revision = "20260830_app_version_registration"
branch_labels = None
depends_on = None


#: BaseRepository JSONB tables with NO existing migration DDL. Every one is a
#: live ``super().__init__("<name>")`` table verified against the migration
#: graph (single source: this revision). DDL mirrors ``BaseRepository``
#: ``_ensure_table`` exactly (id TEXT PK, data JSONB, tenant_id, timestamps,
#: tenant index) so a provisioned DB is identical to a runtime-created one.
_JSONB_TABLES = [
    # capability / readiness
    "capability_readiness",
    "tenant_launch_readiness",
    # billing / revops
    "tenant_contract_profiles",
    "tenant_entitlements",
    "usage_metering_events",
    "billable_usage_summaries",
    "invoice_previews",
    "revenue_leakage_signals",
    "value_created_events",
    "metering_evidence",
    # commerce
    "commerce_resources",
    "commerce_assets",
    "commerce_facilitators",
    "commerce_challenges",
    "commerce_policies",
    "commerce_approvals",
    "commerce_authorizations",
    "commerce_receipts",
    "commerce_settlements",
    "commerce_entitlements",
    "commerce_grants",
    "commerce_fulfillments",
    "commerce_treasuries",
    "commerce_budget_policies",
    "commerce_signer_refs",
    "commerce_metering",
    # rewards (durable outbox / budget / evidence)
    "reward_delivery_jobs",
    "reward_evidence_outbox",
    "reward_reservation_release_jobs",
    "reward_budget_ledger",
    "reward_budget_reservations",
    "reward_external_audit_evidence",
    # security governance (BaseRepository JSONB; no DDL existed in any prior
    # revision, so a clean DB raced schema creation on first write)
    "security_audit_events",
    "security_policy_decisions",
]

#: ``reward_*`` tables created by ``20260613_reward_enablement`` with a
#: columnar schema that LACKS the ``data`` JSONB column, while their
#: repositories are ``BaseRepository``-backed and read/write ``row["data"]``.
#: On a clean DB those paths fail (column "data" does not exist). These ALTERs
#: are idempotent + additive and repair the phase-0-flagged clean-DB bug.
#: ``tenant_reward_rail_configs`` / ``tenant_contract_registry`` are excluded:
#: the rail-config repo is columnar-designed and the contract-registry repo
#: implements direct SQL (documented there), so no ``data`` column is intended.
_REWARD_DATA_ALTER_TABLES = [
    "reward_campaigns",
    "reward_rules",
    "reward_eligibility_decisions",
    "reward_action_payloads",
    "reward_proofs",
    "reward_execution_receipts",
    "reward_audit_log",
]

#: Payment-rail durability mirror tables — DDL copied VERBATIM from
#: ``services/integrations/providers/payment_rails/durability.py``
#: ``LedgerDurabilitySeam.migration_ddl()`` (authoritative source of truth).
_PAYMENT_RAIL_RECEIPTS_DDL = """
CREATE TABLE IF NOT EXISTS payment_rail_receipts (
    tenant_id           TEXT    NOT NULL,
    receipt_id          TEXT    NOT NULL PRIMARY KEY,
    provider            TEXT    NOT NULL,
    current_stage       TEXT    NOT NULL DEFAULT 'received',
    verification_state  TEXT,
    rejection_reason    TEXT,
    funding_session_id  TEXT,
    endpoint_id         TEXT,
    environment         TEXT,
    source              TEXT,
    processing_attempts INTEGER NOT NULL DEFAULT 0,
    repair_attempts     INTEGER NOT NULL DEFAULT 0,
    received_at         TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ,
    record_json         JSONB   NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_payment_rail_receipts_tenant_updated
    ON payment_rail_receipts (tenant_id, updated_at DESC);
"""

_PAYMENT_RAIL_RECONCILIATION_DDL = """
CREATE TABLE IF NOT EXISTS payment_rail_reconciliation_records (
    tenant_id          TEXT   NOT NULL,
    funding_session_id TEXT   NOT NULL,
    provider           TEXT   NOT NULL,
    state              TEXT   NOT NULL,
    last_source        TEXT,
    first_observed_at  TIMESTAMPTZ,
    last_checked_at    TIMESTAMPTZ,
    resolved_at        TIMESTAMPTZ,
    updated_at         TIMESTAMPTZ,
    record_json        JSONB  NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (tenant_id, funding_session_id)
);
CREATE INDEX IF NOT EXISTS idx_payment_rail_recon_tenant_state
    ON payment_rail_reconciliation_records (tenant_id, state);
"""

_PAYMENT_RAIL_PROVIDER_ACCOUNTS_DDL = """
CREATE TABLE IF NOT EXISTS payment_rail_provider_accounts (
    tenant_id            TEXT    NOT NULL,
    provider             TEXT    NOT NULL,
    status               TEXT    NOT NULL DEFAULT 'not_configured',
    provider_poll_health TEXT,
    webhook_configured   BOOLEAN NOT NULL DEFAULT FALSE,
    polling_configured   BOOLEAN NOT NULL DEFAULT FALSE,
    environment          TEXT,
    last_poll_at         TIMESTAMPTZ,
    updated_at           TIMESTAMPTZ,
    record_json          JSONB   NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (tenant_id, provider)
);
"""


def _jsonb_table_ddl(table: str) -> str:
    """The exact DDL BaseRepository._ensure_table issues (minus runtime pool)."""
    return (
        "CREATE TABLE IF NOT EXISTS " + table + " (\n"
        "    id TEXT PRIMARY KEY,\n"
        "    data JSONB NOT NULL DEFAULT '{}'::jsonb,\n"
        "    tenant_id TEXT,\n"
        "    created_at TIMESTAMPTZ DEFAULT NOW(),\n"
        "    updated_at TIMESTAMPTZ DEFAULT NOW()\n"
        ");\n"
        "CREATE INDEX IF NOT EXISTS idx_" + table + "_tenant ON " + table + " (tenant_id);"
    )


def upgrade() -> None:
    for table in _JSONB_TABLES:
        op.execute(_jsonb_table_ddl(table))

    # Payment-rail durability mirror tables (verbatim from migration_ddl()).
    op.execute(_PAYMENT_RAIL_RECEIPTS_DDL)
    op.execute(_PAYMENT_RAIL_RECONCILIATION_DDL)
    op.execute(_PAYMENT_RAIL_PROVIDER_ACCOUNTS_DDL)

    # Repair the 2026-06-13 reward clean-DB bug: add the missing data JSONB
    # column to the columnar reward_* tables whose BaseRepository repos read
    # row["data"].
    for table in _REWARD_DATA_ALTER_TABLES:
        op.execute(
            "ALTER TABLE " + table
            + " ADD COLUMN IF NOT EXISTS data JSONB NOT NULL DEFAULT '{}'::jsonb"
        )


def downgrade() -> None:
    # Undo the reward data-column repair (idempotent).
    for table in _REWARD_DATA_ALTER_TABLES:
        op.execute("ALTER TABLE " + table + " DROP COLUMN IF EXISTS data")

    # Drop the mirror + JSONB tables created above (reverse order).
    op.execute("DROP TABLE IF EXISTS payment_rail_provider_accounts")
    op.execute("DROP TABLE IF EXISTS payment_rail_reconciliation_records")
    op.execute("DROP TABLE IF EXISTS payment_rail_receipts")
    for table in reversed(_JSONB_TABLES):
        op.execute("DROP TABLE IF EXISTS " + table)
