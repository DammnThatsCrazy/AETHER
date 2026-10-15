"""measurement integrity plane: immutable measurement_results + restatements

Creates the durable, append-only storage for the Measurement Integrity Plane:

- ``measurement_results`` — one immutable row per computed metric result. The
  ONLY sanctioned mutation is *supersession*: an active row is stamped with
  ``superseded_by`` and a fresh row takes its place. A partial UNIQUE index
  guarantees at most one *active* (``superseded_by IS NULL``) result per
  ``(tenant_id, metric_name, metric_version, context_hash)``.
- ``measurement_restatements`` — the audit trail linking a prior result to the
  result that superseded it, with a human ``reason``.

DDL parity: the DDL below is duplicated verbatim in
``repositories/measurement_results_repo.py`` (the alembic versions directory is
not an importable package and alembic is not a runtime backend dependency, so
the repo owns its own copy for runtime auto-creation). Both blocks bundle the
CREATE TABLE with its indexes; ``tests/unit/test_measurement_results_repo.py``
asserts the repo constants match the strings in this file. When changing table
shape, edit this migration first, then mirror it in the repository.

Revision ID: 20260716_measurement_integrity
Revises: 20260715_identity_merge_correctness
Create Date: 2026-07-16
"""

from __future__ import annotations

from alembic import op

revision = "20260716_measurement_integrity"
down_revision = "20260715_identity_merge_correctness"
branch_labels = None
depends_on = None

MEASUREMENT_RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS measurement_results (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_version TEXT NOT NULL,
    context_hash TEXT NOT NULL,
    value DOUBLE PRECISION,
    value_state TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT 'count',
    lineage JSONB NOT NULL DEFAULT '{}'::jsonb,
    sufficiency JSONB NOT NULL DEFAULT '{}'::jsonb,
    uncertainty JSONB,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    superseded_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_measurement_results_active
    ON measurement_results (tenant_id, metric_name, metric_version, context_hash)
    WHERE superseded_by IS NULL;
CREATE INDEX IF NOT EXISTS ix_measurement_results_tenant
    ON measurement_results (tenant_id, metric_name);
"""

MEASUREMENT_RESTATEMENTS_DDL = """
CREATE TABLE IF NOT EXISTS measurement_restatements (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    prior_result_id TEXT NOT NULL,
    new_result_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    restated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_measurement_restatements_tenant
    ON measurement_restatements (tenant_id, new_result_id);
"""


def upgrade() -> None:
    op.execute(MEASUREMENT_RESULTS_DDL)
    op.execute(MEASUREMENT_RESTATEMENTS_DDL)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_measurement_restatements_tenant")
    op.execute("DROP TABLE IF EXISTS measurement_restatements")
    op.execute("DROP INDEX IF EXISTS ix_measurement_results_tenant")
    op.execute("DROP INDEX IF EXISTS ux_measurement_results_active")
    op.execute("DROP TABLE IF EXISTS measurement_results")
