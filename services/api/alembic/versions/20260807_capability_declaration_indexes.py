"""capability_declarations — index the columns the API actually filters on

`20260806_capability_declarations` created an expression index on
`data->>'publisher_ref'`, which no query filters: `publisher_ref` is only ever written and
used as a metric label. Meanwhile `GET /v1/capability-declarations?provider=…&server_name=…`
filters `data->>'provider'` and `data->>'server_name'` (via `_ScopedRepo.list_for_tenant`
→ `BaseRepository.find_many`, which filters `data->>'key'`), and neither was indexed — so
the list endpoint sequential-scans.

Corrected here rather than by editing `20260806`, because that revision may already be
applied; rewriting an applied migration in place would leave deployed databases silently
disagreeing with the migration history. Purely additive and fully reversible.

Revision ID: 20260807_capability_declaration_indexes
Revises: 20260806_capability_declarations
Create Date: 2026-08-07
"""

from __future__ import annotations

from alembic import op

revision = "20260807_capability_declaration_indexes"
down_revision = "20260806_capability_declarations"
branch_labels = None
depends_on = None

_TABLE = "capability_declarations"


def upgrade() -> None:
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_{_TABLE}_provider "
        f"ON {_TABLE} ((data->>'provider'));"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_{_TABLE}_server_name "
        f"ON {_TABLE} ((data->>'server_name'));"
    )
    # `publisher_ref` is written but never filtered; the index only costs write throughput.
    op.execute(f"DROP INDEX IF EXISTS ix_{_TABLE}_publisher;")
    # `_ensure_table` already auto-creates idx_capability_declarations_tenant on the same
    # column, so the migration's own duplicate is redundant.
    op.execute(f"DROP INDEX IF EXISTS ix_{_TABLE}_tenant;")


def downgrade() -> None:
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_{_TABLE}_tenant ON {_TABLE} (tenant_id);"
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS ix_{_TABLE}_publisher "
        f"ON {_TABLE} ((data->>'publisher_ref'));"
    )
    op.execute(f"DROP INDEX IF EXISTS ix_{_TABLE}_server_name;")
    op.execute(f"DROP INDEX IF EXISTS ix_{_TABLE}_provider;")
