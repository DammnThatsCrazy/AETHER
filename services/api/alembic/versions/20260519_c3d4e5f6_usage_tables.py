"""Usage tables — tenant quota tracking and provider call metrics.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-19
"""

from __future__ import annotations

from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # tenant_usage: Redis quota counters flushed periodically by QuotaFlusher
    op.execute("""
        CREATE TABLE IF NOT EXISTS tenant_usage (
            id                 BIGSERIAL   PRIMARY KEY,
            tenant_id          VARCHAR(64) NOT NULL,
            billing_period     VARCHAR(7)  NOT NULL,
            plan_tier          VARCHAR(4),
            total_requests     BIGINT      NOT NULL DEFAULT 0,
            overage_requests   BIGINT      NOT NULL DEFAULT 0,
            overage_by_service JSONB       NOT NULL DEFAULT '{}',
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (tenant_id, billing_period)
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_tenant_usage_period ON tenant_usage (billing_period);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tenant_usage_tenant ON tenant_usage (tenant_id);")

    # provider_usage: per-tenant per-provider call metrics flushed by UsageMeter
    op.execute("""
        CREATE TABLE IF NOT EXISTS provider_usage (
            id                   SERIAL       PRIMARY KEY,
            tenant_id            TEXT         NOT NULL,
            category             TEXT         NOT NULL,
            provider_name        TEXT         NOT NULL,
            total_requests       INT          NOT NULL DEFAULT 0,
            successful_requests  INT          NOT NULL DEFAULT 0,
            failed_requests      INT          NOT NULL DEFAULT 0,
            total_latency_ms     DOUBLE PRECISION NOT NULL DEFAULT 0,
            method_breakdown     JSONB        NOT NULL DEFAULT '{}',
            period_start         DOUBLE PRECISION,
            flushed_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_provider_usage_tenant   ON provider_usage (tenant_id);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_provider_usage_category ON provider_usage (tenant_id, category);")
    op.execute("CREATE INDEX IF NOT EXISTS idx_provider_usage_flushed  ON provider_usage (flushed_at DESC);")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS provider_usage;")
    op.execute("DROP TABLE IF EXISTS tenant_usage;")
