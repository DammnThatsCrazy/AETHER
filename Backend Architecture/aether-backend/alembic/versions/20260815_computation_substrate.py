"""computation substrate: durable computed_results + runs + restatements

Creates the durable storage for the Computation Substrate:

- ``computed_results`` — one immutable row per canonical result. The only
  sanctioned mutation is *supersession*: an active row is stamped with
  ``superseded_by`` and a fresh row takes its place. A partial UNIQUE index
  guarantees at most one *active* (``superseded_by IS NULL``) result per
  ``(tenant_id, definition_id, definition_version, context_hash)``.
- ``computation_runs`` — the run that produced a result (definition + context +
  status + timings).
- ``computation_restatements`` — the audit trail linking a prior result to the
  result that superseded it, with a human ``reason``.

DDL parity: the DDL below is duplicated verbatim in
``services/computation/repositories.py`` (the alembic versions directory is not
importable and alembic is not a runtime dependency, so the repo owns its own copy
for runtime auto-creation). ``tests/computation/test_repo_ddl_parity.py`` asserts
the repo constants match the strings in this file. When changing table shape,
edit this migration first, then mirror it in the repository.

Revision ID: 20260815_computation_substrate
Revises: 20260814_customer_webhook_delivery_claims
Create Date: 2026-08-15
"""

from __future__ import annotations

from alembic import op

revision = "20260815_computation_substrate"
down_revision = "20260814_customer_webhook_delivery_claims"
branch_labels = None
depends_on = None

COMPUTED_RESULTS_DDL = """
CREATE TABLE IF NOT EXISTS computed_results (
    result_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    definition_id TEXT NOT NULL,
    definition_version TEXT NOT NULL,
    context_hash TEXT NOT NULL,
    run_id TEXT,
    status TEXT NOT NULL,
    value DOUBLE PRECISION,
    value_type TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT 'count',
    currency TEXT,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    superseded_by TEXT,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_computed_results_active
    ON computed_results (tenant_id, definition_id, definition_version, context_hash)
    WHERE superseded_by IS NULL;
CREATE INDEX IF NOT EXISTS ix_computed_results_tenant
    ON computed_results (tenant_id, definition_id);
"""

COMPUTATION_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS computation_runs (
    run_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    definition_id TEXT NOT NULL,
    definition_version TEXT NOT NULL,
    context_hash TEXT,
    status TEXT NOT NULL,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_computation_runs_tenant
    ON computation_runs (tenant_id, definition_id);
"""

COMPUTATION_RESTATEMENTS_DDL = """
CREATE TABLE IF NOT EXISTS computation_restatements (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    prior_result_id TEXT NOT NULL,
    new_result_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    restated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_computation_restatements_tenant
    ON computation_restatements (tenant_id, new_result_id);
"""


def upgrade() -> None:
    op.execute(COMPUTED_RESULTS_DDL)
    op.execute(COMPUTATION_RUNS_DDL)
    op.execute(COMPUTATION_RESTATEMENTS_DDL)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_computation_restatements_tenant")
    op.execute("DROP TABLE IF EXISTS computation_restatements")
    op.execute("DROP INDEX IF EXISTS ix_computation_runs_tenant")
    op.execute("DROP TABLE IF EXISTS computation_runs")
    op.execute("DROP INDEX IF EXISTS ix_computed_results_active")
    op.execute("DROP INDEX IF EXISTS ix_computed_results_tenant")
    op.execute("DROP TABLE IF EXISTS computed_results")
