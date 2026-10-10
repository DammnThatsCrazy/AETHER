"""Add ``graph_mutation_ledger.rights_decision_ref``.

Revision ID: 20260914_graph_mutation_rights_ref
Revises: 20260911_plan_tier_greek
Create Date: 2026-09-14

Rights propagation (blueprint §11): "Graph mutation ``MutationIntent`` /
``MutationRecord`` gain a rights ref". ``MutationIntent.rights_decision_ref``
and the typed ``MutationRecord`` now carry the durable ``rdec_...`` identity of
the ``RightsDecision`` governing a write, so the ledger must persist it too —
otherwise a replayed/audited mutation loses the rights ancestry the fact
payload only annotates.

ADDITIVE: the column is nullable with no default and no backfill, so every
existing ledger row keeps the exact shape it had (``NULL`` = "no rights gate
ran for this write" — the pre-propagation meaning). ``20260729_graph_mutation_
ledger`` is deliberately NOT edited in place; the repository's runtime DDL
mirrors this migration through ``GRAPH_MUTATION_LEDGER_RIGHTS_REF_DDL``
(parity-tested by ``tests/unit/graph_gateway/test_ledger_ddl_parity.py``).
"""

from __future__ import annotations

from alembic import op

revision = "20260914_graph_mutation_rights_ref"
down_revision = "20260911_plan_tier_greek"
branch_labels = None
depends_on = None

# Mirrored VERBATIM in repositories/graph_mutation_ledger.py (parity-tested).
GRAPH_MUTATION_LEDGER_RIGHTS_REF_DDL = """
ALTER TABLE graph_mutation_ledger
    ADD COLUMN IF NOT EXISTS rights_decision_ref TEXT
"""


def upgrade() -> None:
    op.execute(GRAPH_MUTATION_LEDGER_RIGHTS_REF_DDL)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE graph_mutation_ledger DROP COLUMN IF EXISTS rights_decision_ref"
    )
