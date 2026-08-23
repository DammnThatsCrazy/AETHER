"""credential-turnkey: Alembic backfill for every auto-created JSONB table.

Re-cut of the credential-turnkey table backfill onto current main.

Background: ``BaseRepository`` (``repositories/repos.py``) auto-creates a JSONB
table at first write (``_ensure_table``)::

    CREATE TABLE IF NOT EXISTS <t> (
        id TEXT PRIMARY KEY,
        data JSONB NOT NULL DEFAULT '{}'::jsonb,
        tenant_id TEXT,
        created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_<t>_tenant ON <t> (tenant_id);

A clean-DB ``alembic upgrade head`` used to land with NONE of those tables, so
the first write raced schema creation and the runtime auto-create never ran in
a read-only replica / pre-provisioned migration path. This revision backfills
the migration chain with the same idempotent, additive DDL so a provisioned
deployment matches what the runtime creates.

This is the *re-cut* of the original ``20260901_credential_turnkey_tables``
(which was cut against ``20260830_app_version_registration`` BEFORE main merged
the commerce / reward-delivery migrations). The old revision forked main's
migration head and re-created tables main now owns. This revision rebases onto
main's current single head and creates ONLY tables / columns that no main
migration and no ported-source DDL creates.

Created here (new to alembic, all BaseRepository-shaped):

* readiness / billing-revops / security / metering-evidence JSONB tables whose
  owning repositories predate any migration and previously relied on runtime
  auto-create;
* ``commerce_signer_refs`` / ``commerce_metering`` / ``reward_evidence_outbox``
  / ``stablecoin_reconciliation_results`` — tables referenced by the ported
  credential-turnkey source (``x402/signer_repos.py``,
  ``commerce/metering.py``, ``rewards/receipt_evidence.py``,
  ``stablecoins/price_persistence.py``) with no DDL anywhere.

NOT re-created (main already owns them):

* the fourteen ``commerce_*`` tables + ``x402_reconciliation_cursor``
  (``20260827_commerce_tables``);
* ``reward_delivery_jobs`` / ``reward_budget_ledger`` /
  ``reward_budget_reservations`` / ``reward_external_audit_evidence`` /
  ``reward_credit_ledger`` / ``reward_credit_balances``
  (``20260828_reward_delivery_tables``).

Dropped from the original revision (no live consumer on this tree):

* ``payment_rail_receipts`` / ``payment_rail_reconciliation_records`` /
  ``payment_rail_provider_accounts`` — their DDL owner
  ``services/integrations/providers/payment_rails/durability.py`` was dropped
  from the port, and no code references the mirror tables;
* ``capability_readiness`` — its owning repository
  (``services/capabilities/readiness_repo.py``) is not ported; the string only
  survives as a resource-type / service name;
* ``reward_reservation_release_jobs`` — its owning module
  (``services/rewards/reservation_release.py``) is not ported; no code
  reference on this tree.

Also repairs the 2026-06-13 reward clean-DB bug: ``20260613_reward_enablement``
created the ``reward_*`` tables with a columnar schema that has NO ``data``
JSONB column, while the reward repositories (``services/rewards/repositories.py``)
are ``BaseRepository``-backed and read/write ``row["data"]`` — on a fresh DB
those reads fail with "column data does not exist". The ALTERs below add the
column idempotently, AND drop NOT NULL from the columnar columns the JSONB
repositories never write (``reward_campaigns.name``,
``reward_eligibility_decisions.eligible/decision``,
``reward_proofs.wallet_address/nonce/expiry/expires_at``, ...): ``BaseRepository``
inserts supply only ``id``/``data``/``tenant_id``/``created_at``/``updated_at``,
so those NOT NULL-without-default columns would otherwise abort every reward
insert on a clean DB even after ``data`` is added.

Everything is additive + idempotent (IF NOT EXISTS everywhere), and the
downgrade drops exactly what this revision created.

Revision ID: 20260901_credential_turnkey_tables
Revises: 20260831_merge_app_version_head
Create Date: 2026-08-23
"""

from __future__ import annotations

from alembic import op

revision = "20260901_credential_turnkey_tables"
down_revision = "20260831_merge_app_version_head"
branch_labels = None
depends_on = None


#: BaseRepository JSONB tables with NO existing migration DDL and at least one
#: live repository / raw-SQL consumer on this tree. Every one is a
#: ``super().__init__("<name>")`` table (or raw-SQL ``FROM`` target) verified
#: against the main migration graph (single source: this revision). DDL mirrors
#: ``BaseRepository._ensure_table`` exactly (id TEXT PK, data JSONB, tenant_id,
#: timestamps, tenant index) so a provisioned DB is identical to a
#: runtime-created one.
_JSONB_TABLES = [
    # readiness / tenant launch
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
    # commerce (signer refs + metering are NOT in 20260827_commerce_tables)
    "commerce_signer_refs",
    "commerce_metering",
    # rewards durable evidence outbox (not in 20260828_reward_delivery_tables)
    "reward_evidence_outbox",
    # security governance
    "security_audit_events",
    "security_policy_decisions",
    # stablecoin reconciliation results (port of price_persistence.py)
    "stablecoin_reconciliation_results",
]

#: ``reward_*`` tables created by ``20260613_reward_enablement`` with a
#: columnar schema that LACKS the ``data`` JSONB column, while their
#: repositories (``services/rewards/repositories.py``) are
#: ``BaseRepository``-backed and read/write ``row["data"]``. On a clean DB
#: those paths fail (column "data" does not exist). These ALTERs are idempotent
#: + additive and repair the phase-0-flagged clean-DB bug.
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

#: Columns the ``20260613_reward_enablement`` columnar schema declared
#: ``NOT NULL`` with NO server default (e.g. ``reward_campaigns.name``,
#: ``reward_eligibility_decisions.eligible/decision``,
#: ``reward_proofs.wallet_address/nonce/expiry/expires_at``), while
#: ``BaseRepository.insert`` supplies only ``id``, ``data``, ``tenant_id``,
#: ``created_at``, ``updated_at`` (JSONB-shaped — see
#: ``repositories/repos.py::BaseRepository.insert``). On a clean DB the JSONB
#: reward repositories therefore STILL fail to insert after ``data`` is added:
#: every NOT NULL column without a default that the JSONB write never names
#: aborts the INSERT. The reward repositories read/write exclusively through
#: the ``data`` JSONB column (they never SELECT or set these columnar columns),
#: so ``DROP NOT NULL`` leaves them nullable — honestly NULL, never a
#: fabricated default that would disagree with the JSONB payload — while
#: keeping the 2026-06-13 schema (indexes, FKs, triggers) intact for any
#: legacy consumer.
_REWARD_NULLABLE_COLUMNS: dict[str, list[str]] = {
    "reward_campaigns": ["name"],
    "reward_rules": ["campaign_id", "name"],
    "reward_eligibility_decisions": ["eligible", "decision"],
    "reward_action_payloads": ["rail", "execution_mode"],
    "reward_proofs": ["wallet_address", "nonce", "expiry", "expires_at"],
    "reward_execution_receipts": ["rail", "execution_mode"],
    "reward_audit_log": ["action"],
}


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

    # Repair the 2026-06-13 reward clean-DB bug: add the missing data JSONB
    # column to the columnar reward_* tables whose BaseRepository repos read
    # row["data"].
    for table in _REWARD_DATA_ALTER_TABLES:
        op.execute(
            "ALTER TABLE " + table
            + " ADD COLUMN IF NOT EXISTS data JSONB NOT NULL DEFAULT '{}'::jsonb"
        )

    # Same clean-DB bug, second half: the columnar reward schema declared
    # several columns NOT NULL with no default, so a BaseRepository insert
    # (which writes only id/data/tenant_id/created_at/updated_at) STILL fails
    # after ``data`` is added. DROP NOT NULL makes those columns nullable so a
    # JSONB insert succeeds (see _REWARD_NULLABLE_COLUMNS for the rationale).
    for table, columns in _REWARD_NULLABLE_COLUMNS.items():
        for column in columns:
            op.execute(
                "ALTER TABLE " + table
                + " ALTER COLUMN " + column + " DROP NOT NULL"
            )


def downgrade() -> None:
    # Undo the reward data-column repair (idempotent). The DROP NOT NULL on
    # _REWARD_NULLABLE_COLUMNS is intentionally NOT reverted: those are
    # pre-existing 2026-06-13 tables, and restoring NOT NULL would fail once the
    # JSONB repos have written rows with NULL in the legacy columnar columns
    # (which is exactly the state this revision makes possible).
    for table in _REWARD_DATA_ALTER_TABLES:
        op.execute("ALTER TABLE " + table + " DROP COLUMN IF EXISTS data")

    # Drop the JSONB tables created above (reverse order).
    for table in reversed(_JSONB_TABLES):
        op.execute("DROP INDEX IF EXISTS idx_" + table + "_tenant")
        op.execute("DROP TABLE IF EXISTS " + table)
