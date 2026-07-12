"""value semantics — durable price/valuation/rollup snapshots + valuation audit

Additive tables for the canonical value service (services/value): observed price
snapshots, per-value USD valuation snapshots, safe-rollup snapshots, a
source-valuation audit trail, and an unpriced/stale-asset audit. All amounts are
stored as TEXT (decimal strings) — never floats; NULL usd means unpriced (never
0). Tenant-scoped. Purely additive; no destructive changes.

Revision ID: 20260721_value_semantics
Revises: 20260720_silver_import_facts
Create Date: 2026-07-21
"""

from __future__ import annotations

from alembic import op

revision = "20260721_value_semantics"
down_revision = "20260720_silver_import_facts"
branch_labels = None
depends_on = None

_TABLES = {
    "value_price_snapshots": """
        CREATE TABLE IF NOT EXISTS value_price_snapshots (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            asset TEXT NOT NULL,
            usd_price TEXT,
            conversion_source TEXT,
            valuation_method TEXT,
            confidence TEXT,
            freshness TEXT,
            priced_at TIMESTAMPTZ,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    "value_valuation_snapshots": """
        CREATE TABLE IF NOT EXISTS value_valuation_snapshots (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            usd_value TEXT,
            valuation_method TEXT,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            recorded_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    "value_rollup_snapshots": """
        CREATE TABLE IF NOT EXISTS value_rollup_snapshots (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            metric TEXT,
            total_usd TEXT,
            rollup_status TEXT,
            unpriced_count INTEGER,
            excluded_count INTEGER,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            recorded_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    "value_source_valuation_audit": """
        CREATE TABLE IF NOT EXISTS value_source_valuation_audit (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            source TEXT,
            asset TEXT,
            usd_value TEXT,
            reason TEXT,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
    "value_unpriced_stale_audit": """
        CREATE TABLE IF NOT EXISTS value_unpriced_stale_audit (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            asset TEXT,
            exclusion_reason TEXT,
            data JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """,
}


def upgrade() -> None:
    for ddl in _TABLES.values():
        op.execute(ddl)
    for table in _TABLES:
        op.execute(f"CREATE INDEX IF NOT EXISTS ix_{table}_tenant ON {table} (tenant_id);")


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table};")
