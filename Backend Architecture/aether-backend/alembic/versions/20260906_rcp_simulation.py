"""Reconciled Control Plane — simulation/shadow evidence records (Phase 3).

``simulation_runs`` records one §37 simulation/shadow or §20 digital-twin run:
a pure comparison between a *current path* (authoritative result) and a
*candidate path* (non-authoritative result) along the ten canonical §37 axes,
plus the run's unknowns/warnings and the single §12.7 result
(``pass`` | ``conditional`` | ``fail``).

Phase-3 boundary: these rows are evidence that later R1/R2 execution gates
consult — nothing in Phase 3 executes or applies a ChangeSet, and no shadow
result ever mutates canonical graph state (§37). ``changeset_ref`` is nullable
on purpose: digital-twin dry runs (§20) may legitimately precede the ChangeSet
they inform.

The ALTERs are additive ``CREATE TABLE/INDEX IF NOT EXISTS`` — nothing is
dropped or widened. Tenancy is carried on every row so no cross-tenant read is
possible (repository SQL always filters by tenant_id/environment_id).

The SQL below is string-identical to ``SCHEMA_SQL`` in
``services/managed_integrations/simulation_repository.py`` (the repo executes
it to self-ensure the table under ``AETHER_ENV=local``).

Revision ID: 20260906_rcp_simulation
Revises: 20260906_rcp_admission
Create Date: 2026-09-06

COORDINATOR SHARED-SURFACE DELTA (tuple-merge note): this migration's
down_revision is the Reconciled-Control-Phase-3 admission lane head
``20260906_rcp_admission`` (integration admission lands before the
simulation/shadow tables; the schema-mapping and source-authority lanes chain
after this revision). When this branch is combined with sibling lanes that
each add a migration off the same base, a NEW tuple-merge revision must be
created with ``down_revision = (<this revision>, <sibling revision>, ...)``
exactly like ``20260906_merge_data_exchange_head`` /
``20260904_merge_communication360_head``.
"""

from __future__ import annotations

from alembic import op

revision = "20260906_rcp_simulation"
down_revision = "20260906_rcp_admission"
branch_labels = None
depends_on = None

# Must stay string-identical to
# services/managed_integrations/simulation_repository.py ``SCHEMA_SQL``.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS simulation_runs (
    simulation_id TEXT PRIMARY KEY,
    changeset_ref TEXT,
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    simulation_mode TEXT NOT NULL DEFAULT 'digital_twin',   -- digital_twin | shadow (§37)
    input_snapshot_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    fixture_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    axis_results JSONB NOT NULL DEFAULT '{}'::jsonb,        -- axis -> pass|conditional|fail
    deltas JSONB NOT NULL DEFAULT '{}'::jsonb,              -- axis -> delta summary
    unknowns JSONB NOT NULL DEFAULT '[]'::jsonb,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    result TEXT NOT NULL,                                    -- pass|conditional|fail (§12.7)
    ran_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_simulation_runs_scope
    ON simulation_runs (tenant_id, environment_id, changeset_ref);
"""


def upgrade() -> None:
    op.execute(SCHEMA_SQL)


def downgrade() -> None:
    # Best-effort: reverse the additive DDL. simulation_runs is self-contained
    # (no ALTERs on earlier-phase tables), so a downgrade drops it and leaves
    # the Phase-2 schema exactly as it was.
    op.execute("DROP TABLE IF EXISTS simulation_runs")
