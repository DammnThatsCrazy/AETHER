"""payment webhook endpoint — one active endpoint per (tenant, provider, environment)

Adds a partial-unique index over ``payment_webhook_endpoints`` so at most one
ACTIVE endpoint can exist for a given (tenant, provider, environment). The
registry's ``rotate`` already revokes the prior active endpoint in application
code before minting a new one; this index is the durable database backstop that
makes the invariant impossible to violate under a race or a partial write.

Partial-unique on ``state = 'active'`` only — any number of revoked endpoints may
coexist (they are retained for audit). Purely additive; fully reversible.

Revision ID: 20260816_payment_webhook_endpoint_active_unique
Revises: 20260814_customer_webhook_delivery_claims
Create Date: 2026-08-16
"""

from __future__ import annotations

from alembic import op

revision = "20260816_payment_webhook_endpoint_active_unique"
down_revision = "20260814_customer_webhook_delivery_claims"
branch_labels = None
depends_on = None

TABLE = "payment_webhook_endpoints"
INDEX = "ux_payment_webhook_endpoints_active"


def upgrade() -> None:
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX} ON {TABLE} "
        f"((data->>'tenant_id'), (data->>'provider'), (data->>'environment')) "
        f"WHERE data->>'state' = 'active';"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX};")
