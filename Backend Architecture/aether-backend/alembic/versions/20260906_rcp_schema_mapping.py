"""Reconciled Control Plane — durable schema-mapping stores (Phase 3).

Phase 3 is the *schema/mapping drift-automation* half of the reconciliation
loop (§25 real schema fingerprinting, §8.1 mapping candidates, §38
auto-promotion gates). The tables below record what the automation decided —
they are evidence stores, not actuators:

* ``mapping_candidates`` — one row per §8.1 semantic-mapping candidate
  (candidate_id, source_ref/source_path, canonical_target, the §8.1
  mapping_method, the confidence, rationale, sensitivity_class,
  transform_ref, and the review_state). Candidates are epistemic proposals,
  never truth (§18). Tenancy is enforced in the repository SQL — this
  migration's rows carry tenant_id/environment_id so no cross-tenant read is
  possible.
* ``schema_mapping_runs`` — one row per §38 evaluation run: the
  observed/desired schema fingerprints that were compared (§25), the diff
  summary, the candidate_ids considered, the per-gate bool verdicts
  (``gate_results``, gate -> bool), the fail-closed ``promoted`` verdict, and
  the ``action_required_ref`` when the run did not promote.

Both tables are ``CREATE TABLE/INDEX IF NOT EXISTS`` — nothing is dropped or
widened. ``promoted`` defaults false: automatic promotion requires every §38
gate to hold, and a missing verdict is a failed gate (fail closed), never a
silent pass.

The SQL below is string-identical to ``SCHEMA_SQL`` in
``services/managed_integrations/schema_mapping_repository.py`` (the repo
executes it to self-ensure the tables under ``AETHER_ENV=local``).

Revision ID: 20260906_rcp_schema_mapping
Revises: 20260906_rcp_simulation
Create Date: 2026-09-06

COORDINATOR SHARED-SURFACE DELTA (tuple-merge note): this migration's
down_revision is the Phase-3 simulation-lane head
``20260906_rcp_simulation`` (dry-run + digital-twin tables land there first).
When this branch is combined with sibling lanes that each add a migration off
the same base, a NEW tuple-merge revision must be created with
``down_revision = (<this revision>, <sibling revision>, ...)`` exactly like
``20260906_merge_data_exchange_head`` /
``20260904_merge_communication360_head``.
"""

from __future__ import annotations

from alembic import op

revision = "20260906_rcp_schema_mapping"
down_revision = "20260906_rcp_simulation"
branch_labels = None
depends_on = None

# Must stay string-identical to
# services/managed_integrations/schema_mapping_repository.py ``SCHEMA_SQL``.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS mapping_candidates (
    candidate_id TEXT PRIMARY KEY,
    source_ref TEXT NOT NULL,
    source_path TEXT NOT NULL,
    canonical_target TEXT NOT NULL,
    mapping_method TEXT NOT NULL,
    confidence REAL NOT NULL,
    rationale TEXT,
    sensitivity_class TEXT,
    transform_ref TEXT,
    review_state TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_mapping_candidates_review
    ON mapping_candidates (tenant_id, environment_id, review_state);

CREATE TABLE IF NOT EXISTS schema_mapping_runs (
    run_id TEXT PRIMARY KEY,
    managed_integration_ref TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    observed_schema_fingerprint TEXT,
    desired_schema_fingerprint TEXT,
    diff_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    candidate_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    gate_results JSONB NOT NULL DEFAULT '{}'::jsonb,
    promoted BOOLEAN NOT NULL DEFAULT false,
    action_required_ref TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_schema_mapping_runs_integration
    ON schema_mapping_runs (tenant_id, environment_id, managed_integration_ref, created_at);
"""


def upgrade() -> None:
    op.execute(SCHEMA_SQL)


def downgrade() -> None:
    # Best-effort: reverse the additive DDL in dependency-free order (the
    # indexes drop with their tables). The Phase-3 base revision remains.
    op.execute("DROP TABLE IF EXISTS schema_mapping_runs")
    op.execute("DROP TABLE IF EXISTS mapping_candidates")
