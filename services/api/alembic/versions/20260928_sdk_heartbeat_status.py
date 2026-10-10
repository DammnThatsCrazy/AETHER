"""Persist tenant/app-scoped SDK heartbeat status without subject identifiers."""

from alembic import op

revision = "20260928_sdk_heartbeat_status"
down_revision = "20260927_sdk_identify_idempotency"
branch_labels = None
depends_on = None

SDK_HEARTBEAT_STATUS_DDL = """
CREATE TABLE IF NOT EXISTS sdk_heartbeat_status (
    tenant_id TEXT NOT NULL,
    sdk_name TEXT NOT NULL,
    tenant_app_key TEXT NOT NULL,
    sdk_version TEXT NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    heartbeat_count BIGINT NOT NULL DEFAULT 1,
    PRIMARY KEY (tenant_id, sdk_name, tenant_app_key)
)
"""


def upgrade() -> None:
    op.execute(SDK_HEARTBEAT_STATUS_DDL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sdk_heartbeat_status")
