"""Tenant-scoped prediction-market observations.

Revision ID: 20261023_prediction_market_observations
Revises: 20261022_journey_handoffs
Create Date: 2026-10-23

Each row is one immutable venue observation. The primary key includes a hash of
the normalized content, so resubmitting identical content is idempotent while a
changed quote is a new row. ``received_at`` is server-assigned and is the as-of
axis; a venue-reported resolution is stored as reported and is never treated as
settlement.
"""

from alembic import op

revision = "20261023_prediction_market_observations"
down_revision = "20261022_journey_handoffs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS prediction_market_observations (
            tenant_id TEXT NOT NULL,
            venue TEXT NOT NULL,
            market_ref TEXT NOT NULL,
            observation_sha256 TEXT NOT NULL,
            status TEXT NOT NULL,
            received_at TIMESTAMPTZ NOT NULL,
            data JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, venue, market_ref, observation_sha256),
            CHECK (venue IN ('polymarket','kalshi')),
            CHECK (status IN ('open','closed','resolved','unknown')),
            CHECK (length(btrim(tenant_id)) > 0 AND length(btrim(market_ref)) > 0),
            CHECK (length(observation_sha256) = 64),
            CHECK (jsonb_typeof(data) = 'object')
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS prediction_market_observations_asof "
        "ON prediction_market_observations "
        "(tenant_id, venue, market_ref, received_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS prediction_market_observations_asof")
    op.execute("DROP TABLE IF EXISTS prediction_market_observations")
