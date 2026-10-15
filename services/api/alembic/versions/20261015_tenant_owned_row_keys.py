"""Tenant-owned row keys: backfill row tenants and key per-tenant records by tenant

``BaseRepository.insert``/``update`` now replace a row only when its
``tenant_id`` column matches the writing tenant, and graph vertex writes keep a
vertex's owner. The idempotent steps in ``repositories.tenant_row_keys`` bring
existing rows in line: empty tenant columns are backfilled from the row JSON,
seeded web3 registry rows become ``system`` rows, ``behavior_profiles``,
``journey_chains``, ``profiles``, ``behavioral_signals``, ``event_envelopes``
and x402 commerce rows are re-keyed ``{tenant}:{id}``, and ``chain:`` / card
catalog graph vertices become ``platform`` owned.

Run the same steps again after the rollout to pick up rows old pods wrote
mid-deploy: ``make tenant-row-keys`` (or ``python -m repositories.tenant_row_keys``
in the API image).

Downgrade is a no-op: deleted contaminated rows cannot be restored, and moving
re-keyed rows back could collide with rows written under the bare ids.

Revision ID: 20261015_tenant_owned_row_keys
Revises: 20261012_merge_source_access_heads
Create Date: 2026-10-15
"""

from __future__ import annotations

from alembic import op

from repositories.tenant_row_keys import apply

revision = "20261015_tenant_owned_row_keys"
down_revision = "20261012_merge_source_access_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    apply(op.execute)


def downgrade() -> None:
    """No-op: contaminated rows were deleted and re-keyed rows may collide with bare ids."""
