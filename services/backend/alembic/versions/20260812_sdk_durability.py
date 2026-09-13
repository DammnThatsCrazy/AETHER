"""durable SDK installation inventory and immutable remote configuration"""

from alembic import op

revision = "20260812_sdk_durability"
# Re-pointed onto main's migration head after merging origin/main: the turnkey
# settings/account chain (sdk_durability -> account_organization ->
# account_deletion_workflow -> customer_webhook_delivery_claims) originally
# branched from 20260811_demo_seed_core alongside main's activation/kyber chain,
# producing two heads. Stacking this chain after 20260815_kyber_missions
# linearizes to a single head. These tables are independent of the main chain's,
# so ordering is a no-op for the DDL itself.
down_revision = "20260815_kyber_missions"
branch_labels = None
depends_on = None

TABLES = ("sdk_installations", "sdk_manifest_versions", "sdk_manifest_states")


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id TEXT PRIMARY KEY,
                data JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                tenant_id TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        op.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_tenant ON {table} (tenant_id)")
    op.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_sdk_manifest_tenant_version
        ON sdk_manifest_versions (tenant_id, (data->>'manifest_version'))""")
    op.execute("""CREATE INDEX IF NOT EXISTS idx_sdk_installations_last_seen
        ON sdk_installations (tenant_id, (data->>'last_seen') DESC)""")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table}")
