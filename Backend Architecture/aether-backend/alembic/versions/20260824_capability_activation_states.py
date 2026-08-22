"""capability activation states — persisted canonical lifecycle

Additive JSONB table backing the capability lifecycle authority
(services/capabilities/lifecycle.py). Rows are append-only STATE VERSIONS for
the coordinate (tenant_id, provider, environment, capability): exactly one
non-superseded row per coordinate (partial unique index), full promotion /
demotion / suspension history preserved, every row recording actor, reason,
evidence references, and the credential version the state is bound to.

Follows the BaseRepository shape (id TEXT PK, data JSONB, tenant_id,
created_at, updated_at) and the 20260812 provider_credential_versions
partial-unique pattern. Purely additive; fully reversible.

Revision ID: 20260824_capability_activation_states
Revises: 20260823_connector_webhook_endpoints
Create Date: 2026-08-24
"""

from __future__ import annotations

from alembic import op

revision = "20260824_capability_activation_states"
down_revision = "20260823_connector_webhook_endpoints"
branch_labels = None
depends_on = None

_TABLES = ("capability_activation_states",)
TABLE = _TABLES[0]


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            id TEXT PRIMARY KEY,
            tenant_id TEXT,
            data JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_tenant ON {TABLE} (tenant_id);")
    # One CURRENT (non-superseded) state per coordinate.
    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_{TABLE}_current
        ON {TABLE} (
            (data->>'tenant_id'), (data->>'provider'),
            (data->>'environment'), (data->>'capability')
        )
        WHERE (data->>'superseded') = 'false';
        """
    )
    # Linear history: one row per coordinate + state_version.
    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_{TABLE}_version
        ON {TABLE} (
            (data->>'tenant_id'), (data->>'provider'),
            (data->>'environment'), (data->>'capability'),
            (data->>'state_version')
        );
        """
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_state ON {TABLE} "
        f"((data->>'readiness_state')) WHERE (data->>'superseded') = 'false';"
    )
    op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_updated ON {TABLE};")
    op.execute(
        f"CREATE TRIGGER trg_{TABLE}_updated BEFORE UPDATE ON {TABLE} "
        f"FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_updated ON {TABLE};")
    op.execute(f"DROP TABLE IF EXISTS {TABLE};")
