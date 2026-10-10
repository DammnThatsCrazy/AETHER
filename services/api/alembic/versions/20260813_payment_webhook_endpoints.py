"""payment webhook endpoint registry — server-side tenant resolution

Additive JSONB table backing the durable webhook endpoint registry. A public
provider webhook URL carries a high-entropy, non-sequential ``endpoint_id`` that
resolves server-side to exactly one (tenant, provider, environment) — replacing
the untrusted ``X-Aether-Tenant-ID`` header. The endpoint id is not, on its own,
authentication: the provider signature is still verified. Endpoints are revocable
and rotatable.

Follows the BaseRepository shape (id TEXT PK, data JSONB, tenant_id, created_at,
updated_at). Purely additive; fully reversible.

Revision ID: 20260813_payment_webhook_endpoints
Revises: 20260812_provider_credential_versions
Create Date: 2026-08-13
"""

from __future__ import annotations

from alembic import op

revision = "20260813_payment_webhook_endpoints"
down_revision = "20260812_provider_credential_versions"
branch_labels = None
depends_on = None

_TABLES = ("payment_webhook_endpoints",)
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
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_provider ON {TABLE} "
        f"((data->>'tenant_id'), (data->>'provider'), (data->>'environment'), (data->>'state'));"
    )
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_{TABLE}_state ON {TABLE} ((data->>'state'));")
    op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_updated ON {TABLE};")
    op.execute(
        f"CREATE TRIGGER trg_{TABLE}_updated BEFORE UPDATE ON {TABLE} "
        f"FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS trg_{TABLE}_updated ON {TABLE};")
    op.execute(f"DROP TABLE IF EXISTS {TABLE};")
