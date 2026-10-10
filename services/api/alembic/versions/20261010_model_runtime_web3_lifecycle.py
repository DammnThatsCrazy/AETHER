"""Persist tenant model preferences/budget reservations and raw Web3 observations.

Revision ID: 20261010_model_runtime_web3_lifecycle
Revises: 20261005_merge_connector_runtime_and_sdk_identity_heads
Create Date: 2026-10-10
"""
from __future__ import annotations

from alembic import op

revision = "20261010_model_runtime_web3_lifecycle"
down_revision = "20261005_merge_connector_runtime_and_sdk_identity_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE IF NOT EXISTS model_runtime_tenant_preferences (
        id TEXT PRIMARY KEY, data JSONB NOT NULL DEFAULT '{}'::jsonb,
        tenant_id TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""")
    op.execute("CREATE INDEX IF NOT EXISTS idx_model_runtime_tenant_preferences_tenant ON model_runtime_tenant_preferences (tenant_id)")
    op.execute("""CREATE TABLE IF NOT EXISTS web3_observations (
        id TEXT PRIMARY KEY, data JSONB NOT NULL DEFAULT '{}'::jsonb,
        tenant_id TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""")
    op.execute("CREATE INDEX IF NOT EXISTS idx_web3_observations_tenant ON web3_observations (tenant_id)")

    op.execute("""CREATE TABLE IF NOT EXISTS model_runtime_token_reservations (
        tenant_id TEXT NOT NULL,
        request_id TEXT NOT NULL,
        period_start TIMESTAMPTZ NOT NULL,
        reserved_tokens BIGINT NOT NULL CHECK (reserved_tokens >= 0),
        status TEXT NOT NULL CHECK (status IN ('reserved', 'settled', 'released', 'expired')),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        PRIMARY KEY (tenant_id, request_id)
    )""")
    op.execute("""CREATE INDEX IF NOT EXISTS ix_model_runtime_token_reservations_period
        ON model_runtime_token_reservations (tenant_id, period_start, status)""")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS model_runtime_token_reservations")
    op.execute("DROP TABLE IF EXISTS web3_observations")
    op.execute("DROP TABLE IF EXISTS model_runtime_tenant_preferences")
