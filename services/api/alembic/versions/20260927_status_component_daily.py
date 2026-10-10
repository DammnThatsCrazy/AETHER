"""Public status history — per-component daily health-sample rollups.

Revision ID: 20260927_status_component_daily
Revises: 20260925_conversion_exchange_rate_nullable
Create Date: 2026-09-27

``status_component_daily`` backs the unauthenticated ``GET /v1/status/history``
feed that draws the public status page's 90-day uptime bars. One row per
(UTC day, component) holds additive sample counts (``ok`` / ``degraded`` /
``down`` / ``unknown``) folded in by live API processes from their own
``/v1/health`` verdict (services/api/ingestion/gateway/status_history.py). The table is
platform-global aggregate availability: no tenant id, hostname or error text.

ADDITIVE ``CREATE TABLE IF NOT EXISTS`` only — nothing existing is touched.

The SQL below is string-identical to ``SCHEMA_SQL`` in
``services/api/ingestion/gateway/status_history_repository.py`` (the repository executes it
to self-ensure the table under ``AETHER_ENV=local``); a unit test pins parity.
"""

from __future__ import annotations

from alembic import op

revision = "20260927_status_component_daily"
down_revision = "20260925_conversion_exchange_rate_nullable"
branch_labels = None
depends_on = None

# Must stay string-identical to
# services/api/ingestion/gateway/status_history_repository.py ``SCHEMA_SQL``.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS status_component_daily (
    day DATE NOT NULL,
    component TEXT NOT NULL,
    ok_samples INTEGER NOT NULL DEFAULT 0 CHECK (ok_samples >= 0),
    degraded_samples INTEGER NOT NULL DEFAULT 0 CHECK (degraded_samples >= 0),
    down_samples INTEGER NOT NULL DEFAULT 0 CHECK (down_samples >= 0),
    unknown_samples INTEGER NOT NULL DEFAULT 0 CHECK (unknown_samples >= 0),
    first_sample_at TIMESTAMPTZ NOT NULL,
    last_sample_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (day, component)
);
"""


def upgrade() -> None:
    op.execute(SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS status_component_daily")
