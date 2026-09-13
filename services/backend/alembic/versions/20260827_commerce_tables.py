"""x402 commerce tables — durable schema under version control

The x402 commerce collections (challenges, approvals, entitlements,
settlements, resources, policies, facilitators, assets, authorizations,
receipts, grants, fulfillments, treasuries, budget_policies) were previously
auto-created ad hoc by BaseRepository._ensure_table with no migration, no
uniqueness, and no storage policy. This brings all fourteen under version
control with the BaseRepository JSONB shape plus the uniqueness and lookup
indexes the flows depend on:

* receipts unique per (tenant, authorization_id) — no double-receipt;
* settlements unique per (tenant, receipt_id);
* authorizations unique per (tenant, payment_identifier) — idempotency;
* budget_policies unique per (tenant, subject_id) — one active cap per subject.

Purely additive (IF NOT EXISTS); fully reversible.

Revision ID: 20260827_commerce_tables
Revises: 20260826_purge_plaintext_reward_secrets
Create Date: 2026-08-27
"""

from __future__ import annotations

from alembic import op

revision = "20260827_commerce_tables"
down_revision = "20260826_purge_plaintext_reward_secrets"
branch_labels = None
depends_on = None

# Literal table list (kept a plain string tuple so the storage-policy coverage
# extractor, which statically reads *_TABLES assignments, discovers them).
_TABLES = (
    "commerce_challenges",
    "commerce_approvals",
    "commerce_entitlements",
    "commerce_settlements",
    "commerce_resources",
    "commerce_policies",
    "commerce_facilitators",
    "commerce_assets",
    "commerce_authorizations",
    "commerce_receipts",
    "commerce_grants",
    "commerce_fulfillments",
    "commerce_treasuries",
    "commerce_budget_policies",
    "x402_reconciliation_cursor",
)

# Per-table index metadata: {table: ([lookup exprs], optional unique expr)}.
_INDEXES: dict[str, tuple[list[str], str | None]] = {
    "commerce_challenges": (["(data->>'challenge_id')"], None),
    "commerce_approvals": (["(data->>'status')", "(data->>'challenge_id')"], None),
    "commerce_entitlements": (["(data->>'status')"], None),
    "commerce_settlements": (["(data->>'state')"], "(data->>'tenant_id'), (data->>'receipt_id')"),
    "commerce_resources": (["(data->>'resource_id')"], None),
    "commerce_policies": (["(data->>'challenge_id')"], None),
    "commerce_facilitators": (["(data->>'facilitator_id')"], None),
    "commerce_assets": (["(data->>'symbol')"], None),
    "commerce_authorizations": ([], "(data->>'tenant_id'), (data->>'payment_identifier')"),
    "commerce_receipts": (["(data->>'verified')"], "(data->>'tenant_id'), (data->>'authorization_id')"),
    "commerce_grants": (["(data->>'entitlement_id')"], None),
    "commerce_fulfillments": (["(data->>'status')"], None),
    "commerce_treasuries": ([], None),
    "commerce_budget_policies": (["(data->>'active')"], "(data->>'tenant_id'), (data->>'subject_id')"),
    "x402_reconciliation_cursor": ([], None),
}


def upgrade() -> None:
    for table in _TABLES:
        lookups, unique_expr = _INDEXES[table]
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id TEXT PRIMARY KEY,
                tenant_id TEXT,
                data JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant ON {table} (tenant_id);")
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_env ON {table} ((data->>'environment'));")
        for i, expr in enumerate(lookups):
            op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_lk{i} ON {table} ({expr});")
        if unique_expr:
            op.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{table} ON {table} ({unique_expr});"
            )
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated ON {table};")
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated ON {table};")
        op.execute(f"DROP TABLE IF EXISTS {table};")
