"""Create the pattern discovery stores.

Revision ID: 20261114_pattern_discovery_stores
Revises: 20261107_merge_rcp_activation_lineage_heads
Create Date: 2026-11-14

Four tenant-scoped JSONB stores for intelligence/pattern_discovery:

* ``discovered_patterns`` — versioned pattern candidates. Indexed for the
  review queue (status, kind, priority), entity context lookups (GIN on the
  affected-entity keys) and the staleness sweep.
* ``pattern_feedback`` — append-only analyst verdicts (calibration source).
* ``pattern_discovery_baselines`` — one decayed aggregate baseline per tenant.
* ``pattern_discovery_runs`` — discovery run records.
"""

from __future__ import annotations

from alembic import op

revision = "20261114_pattern_discovery_stores"
down_revision = "20261107_merge_rcp_activation_lineage_heads"
branch_labels = None
depends_on = None

_TABLES = (
    "discovered_patterns",
    "pattern_feedback",
    "pattern_discovery_baselines",
    "pattern_discovery_runs",
)


def upgrade() -> None:
    for table in _TABLES:
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id TEXT PRIMARY KEY,
                data JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                tenant_id TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                CHECK (jsonb_typeof(data) = 'object'),
                CHECK (length(btrim(tenant_id)) > 0),
                CHECK (data->>'tenant_id' = tenant_id)
            )
            """
        )
        op.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_tenant ON {table} (tenant_id, created_at DESC)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_discovered_patterns_status "
        "ON discovered_patterns (tenant_id, (data->>'status'), (data->>'priority'))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_discovered_patterns_kind "
        "ON discovered_patterns (tenant_id, (data->>'kind'))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_discovered_patterns_entities "
        "ON discovered_patterns USING GIN ((data->'affected_entity_keys'))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pattern_feedback_kind "
        "ON pattern_feedback (tenant_id, (data->>'kind'))"
    )


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
