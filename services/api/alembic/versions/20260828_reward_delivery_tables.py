"""reward delivery / budget / audit-evidence / credit-ledger tables

Brings the reward tables that were runtime-`_ensure_table`-only under version
control:

* reward_delivery_jobs         — durable leased delivery outbox
                                 (idempotent per (tenant, action_id, rail));
* reward_budget_ledger         — per-campaign reward pool ledger;
* reward_budget_reservations   — durable reserve→commit→release rows;
* reward_external_audit_evidence — EVM mainnet audit-evidence store;
* reward_credit_ledger         — internal_credit double-entry entries
                                 (idempotent per idempotency_key);
* reward_credit_balances       — per-(tenant, recipient, currency) balances.

BaseRepository JSONB shape; purely additive (IF NOT EXISTS); reversible.

Revision ID: 20260828_reward_delivery_tables
Revises: 20260827_commerce_tables
Create Date: 2026-08-28
"""

from __future__ import annotations

from alembic import op

revision = "20260828_reward_delivery_tables"
down_revision = "20260827_commerce_tables"
branch_labels = None
depends_on = None

_TABLES = (
    "reward_delivery_jobs",
    "reward_budget_ledger",
    "reward_budget_reservations",
    "reward_external_audit_evidence",
    "reward_credit_ledger",
    "reward_credit_balances",
)

# {table: ([lookup exprs], optional unique expr)}
_INDEXES: dict[str, tuple[list[str], str | None]] = {
    "reward_delivery_jobs": (
        ["(data->>'state')", "(data->>'next_attempt_at')"],
        "(data->>'tenant_id'), (data->>'action_id'), (data->>'rail')",
    ),
    "reward_budget_ledger": ([], None),
    "reward_budget_reservations": (["(data->>'state')"], None),
    "reward_external_audit_evidence": (["(data->>'chain_id')", "(data->>'status')"], None),
    "reward_credit_ledger": (
        ["(data->>'recipient_id')", "(data->>'campaign_id')"],
        "(data->>'idempotency_key')",
    ),
    "reward_credit_balances": (
        [],
        "(data->>'tenant_id'), (data->>'recipient_id'), (data->>'currency')",
    ),
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
