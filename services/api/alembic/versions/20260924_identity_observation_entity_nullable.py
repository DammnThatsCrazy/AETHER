"""Allow ``identity_signal_observations.canonical_entity_id`` to be NULL.

Revision ID: 20260924_identity_observation_entity_nullable
Revises: 20260914_graph_mutation_rights_ref
Create Date: 2026-09-24

The identity resolver writes an event's signal observations BEFORE it knows
which canonical entity the event resolves to (resolver step 4, "persist signal
observations"), then links them once resolution decides (step 8,
``IdentityResolutionRepository.set_observations_canonical_entity``).
``20260715_identity_merge_correctness`` documents exactly that: the column "is
backfilled at resolution time". ``20260612_identity_resolution_tables``
nevertheless declared it ``NOT NULL`` with no default, so on Postgres the
first observation insert of every event would violate the constraint.

The migration is the wrong side here: an unresolved observation genuinely has
no entity yet, and writing a placeholder id would fabricate an identity link
that ``get_observations_for_entity`` could match. The constraint is relaxed
instead; ``NULL`` means "not yet linked to a resolved entity".

ADDITIVE (relaxes a constraint; no data rewrite). The downgrade restores
``NOT NULL`` and fails loudly while unlinked rows exist, rather than inventing
entity ids for them.
"""

from __future__ import annotations

from alembic import op

revision = "20260924_identity_observation_entity_nullable"
down_revision = "20260914_graph_mutation_rights_ref"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE identity_signal_observations "
        "ALTER COLUMN canonical_entity_id DROP NOT NULL"
    )


def downgrade() -> None:
    # Fails (by design) if unlinked observations exist; they must be resolved
    # or removed explicitly before the old constraint can hold again.
    op.execute(
        "ALTER TABLE identity_signal_observations "
        "ALTER COLUMN canonical_entity_id SET NOT NULL"
    )
