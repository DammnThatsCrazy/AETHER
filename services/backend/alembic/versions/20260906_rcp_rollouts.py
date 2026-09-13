"""Reconciled Control Plane — §40 universal progressive delivery records (Phase 4).

Phase 4 is the *delivery-records* layer of the control plane: one ``rollouts``
row per §40 universal progressive-delivery rollout of a managed artifact kind
(``ROLLOUT_ARTIFACT_KINDS``: runtime_config, sdk_compatible_projection,
connector_release, mapping_revision, schema_projection, classifier_version,
endpoint_migration, operational_policy) over the canonical §40 ring sequence —
``olympus_internal -> test_tenants -> 1% -> 5% -> 20% -> 50% -> 100%``. Exact
order is law: a rollout advances one ring at a time and never skips a stage.
``olympus_internal`` is stage zero (the operator/console surface, not tenant
traffic); ``test_tenants`` is non-production tenant traffic.

Columns carry the §12.8 RolloutContract fields plus the coordinator-approved
operational columns:

* ``rollout_id`` / ``changeset_ref`` / ``artifact_kind`` / ``strategy`` —
  §12.8 identity (artifact_kind is a §40 ``ROLLOUT_ARTIFACT_KINDS`` member).
* ``cohorts`` — cohort ids are §40 ring values (a cohort string ``"1%"`` means
  the 1% cohort).
* ``current_stage`` + ``percentage`` — the current ring and its
  ``ring_percentage`` (percentages always track the stage).
* ``health_gates`` — ``[{axis, operator, threshold}]`` §12.9 HealthContract
  gate configuration the rollout engine evaluates on §12.9 snapshots.
* ``advance_conditions`` / ``pause_conditions`` / ``rollback_conditions`` —
  policy/approval tokens (strings) consulted by the engine.
* ``paused_reason`` — coordinator-approved operational column: §12.9 auto-pause
  must be durable; NULL = not paused.
* ``end_state`` — coordinator-approved terminal column; vocab
  ``{'completed', 'rolled_back'}`` enforced at update; NULL = in flight.
* ``tenant_id`` / ``environment_id`` — tenancy carried on every row (CP-11),
  always in the repository WHERE clauses.
* ``started_at`` / ``last_transition_at`` / ``completed_at`` / ``created_at`` —
  the rollout timeline.

The engine records delivery facts only — nothing here applies changes or
grants approvals, and rings above 0% deliver to real tenants only under tenant
update policy + approvals (the §41+ review gate governs turning rings on for
real traffic).

The DDL below is additive-only: one ``CREATE TABLE/INDEX IF NOT EXISTS`` and
nothing is dropped or widened. The SQL is string-identical to ``SCHEMA_SQL`` in
``services/managed_integrations/rollout_repository.py`` (the repo executes it
to self-ensure the table under ``AETHER_ENV=local``).

Revision ID: 20260906_rcp_rollouts
Revises: 20260906_rcp_source_authority
Create Date: 2026-09-06

COORDINATOR SHARED-SURFACE DELTA (tuple-merge note): this migration's
down_revision is the Phase-3 source-authority lane head
``20260906_rcp_source_authority`` (source-authority lands after the Phase-3
admission + simulation + schema-mapping lanes). When this branch is combined
with sibling lanes that each add a migration off the same base, a NEW
tuple-merge revision must be created with ``down_revision = (<this revision>,
<sibling revision>, ...)`` exactly like ``20260906_merge_data_exchange_head`` /
``20260904_merge_communication360_head``.
"""

from __future__ import annotations

from alembic import op

revision = "20260906_rcp_rollouts"
down_revision = "20260906_rcp_source_authority"
branch_labels = None
depends_on = None

# Must stay string-identical to
# services/managed_integrations/rollout_repository.py ``SCHEMA_SQL``.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS rollouts (
    rollout_id TEXT PRIMARY KEY,
    changeset_ref TEXT,
    artifact_kind TEXT NOT NULL,
    strategy TEXT NOT NULL DEFAULT 'canary',
    cohorts JSONB NOT NULL DEFAULT '[]'::jsonb,   -- cohort ids are rollout ring values (a cohort string "1%" means the 1% cohort)
    current_stage TEXT NOT NULL DEFAULT 'olympus_internal',
    percentage REAL NOT NULL DEFAULT 0.0,
    health_gates JSONB NOT NULL DEFAULT '[]'::jsonb,   -- [{axis, operator, threshold}] §12.9 gate config
    advance_conditions JSONB NOT NULL DEFAULT '[]'::jsonb,   -- policy/approval tokens (strings)
    pause_conditions JSONB NOT NULL DEFAULT '[]'::jsonb,
    rollback_conditions JSONB NOT NULL DEFAULT '[]'::jsonb,
    paused_reason TEXT NULL,   -- coordinator-approved operational column: §12.9 auto-pause must be durable; NULL = not paused
    end_state TEXT NULL,       -- coordinator-approved terminal column; vocab {'completed','rolled_back'} enforced at update; NULL = in flight
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    started_at TIMESTAMPTZ,
    last_transition_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_rollouts_scope
    ON rollouts (tenant_id, environment_id, artifact_kind, created_at);
"""


def upgrade() -> None:
    op.execute(SCHEMA_SQL)


def downgrade() -> None:
    # Best-effort: reverse the additive DDL so a downgrade leaves the Phase-3
    # schema exactly as it was.
    op.execute("DROP TABLE IF EXISTS rollouts")
