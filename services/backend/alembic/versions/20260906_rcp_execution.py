"""Reconciled Control Plane — durable execution records (Phase 2).

Phase 2 is the *execution half* of the reconciliation loop. The tables below
record what happened when a ChangeSet moves through the §34 executor — they are
append-only evidence + current-authority state, all keyed back to a ChangeSet
or a managed integration:

* ``change_set_events`` — append-only status-history for a ChangeSet (§34
  transitions: from_status -> to_status by which actor, when).
* ``change_evidence`` — one row per executed/attempted change (§32 step 22 /
  §12.13): before/after state refs, the §12.15 epistemic ``claim_type``, the
  confidence scale, approval/validation/rollback/contradictory refs.
* ``last_known_good`` — the durable LKG for a managed integration (§32 step 21 /
  §12.12), established *only after* verification passes. One row per
  (tenant, env, integration) — the unique index makes a later LKG replace an
  earlier one atomically.
* ``change_set_rollbacks`` — one row per ChangeSet rollback (§32 steps 20-21 /
  §12.11): the LKG ref it restores toward, the ordered rollback actions, the
  queue-recovery/replay policy, and its status.
* ``change_set_approvals`` — durable §21 role-gated approvals attached to a
  ChangeSet (R3/R4/R5/security-emergency plans need recorded approvals before
  they leave ``waiting_approval``). The evidence record identifies which
  authority was exercised.
* ``action_required`` — unresolved changes surfaced for action (§32 step 23 /
  §12.14), emitted by the executor/actuator that cannot resolve a change.
* Plus additive columns on ``change_sets`` for the §12.5 execution fields
  (``started_at``/``completed_at``/``before_state_refs``/``target_state_refs``/
  ``rollback_ref``).

The ALTERs are additive ``ADD COLUMN IF NOT EXISTS`` and every table is
``CREATE TABLE/INDEX IF NOT EXISTS`` — nothing is dropped or widened. Tenancy is
enforced in the repository SQL (this migration's tables carry tenant_id/
environment_id on every row so no cross-tenant read is possible).

The SQL below is string-identical to ``SCHEMA_SQL`` in
``services/managed_integrations/execution_records_repository.py`` (the repo
executes it to self-ensure the tables under ``AETHER_ENV=local``).

Revision ID: 20260906_rcp_execution
Revises: 20260906_rcp_change_sets
Create Date: 2026-09-06

COORDINATOR SHARED-SURFACE DELTA (tuple-merge note): this migration's
down_revision is the Reconciled-Control-Phase-1 lane head
``20260906_rcp_change_sets``. When this branch is combined with sibling lanes
that each add a migration off the same base, a NEW tuple-merge revision must be
created with ``down_revision = (<this revision>, <sibling revision>, ...)``
exactly like ``20260906_merge_data_exchange_head`` /
``20260904_merge_communication360_head``.
"""

from __future__ import annotations

from alembic import op

revision = "20260906_rcp_execution"
down_revision = "20260906_rcp_change_sets"
branch_labels = None
depends_on = None

# Must stay string-identical to
# services/managed_integrations/execution_records_repository.py ``SCHEMA_SQL``.
SCHEMA_SQL = """
ALTER TABLE change_sets ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
ALTER TABLE change_sets ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE change_sets ADD COLUMN IF NOT EXISTS before_state_refs JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE change_sets ADD COLUMN IF NOT EXISTS target_state_refs JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE change_sets ADD COLUMN IF NOT EXISTS rollback_ref TEXT;

CREATE TABLE IF NOT EXISTS change_set_events (
    event_id TEXT PRIMARY KEY,
    changeset_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_change_set_events_changeset
    ON change_set_events (changeset_id, occurred_at);

CREATE TABLE IF NOT EXISTS change_evidence (
    change_evidence_id TEXT PRIMARY KEY,
    changeset_ref TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    initiator TEXT NOT NULL,
    policy_ref TEXT,
    before_state_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    after_state_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    reason TEXT,
    claim_type TEXT NOT NULL,
    confidence TEXT NOT NULL,
    risk_ref TEXT,
    simulation_ref TEXT,
    rollout_ref TEXT,
    validation_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    approval_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    rollback_ref TEXT,
    tenant_action_required BOOLEAN NOT NULL DEFAULT false,
    evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    contradictory_evidence_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_change_evidence_changeset
    ON change_evidence (changeset_ref);

CREATE TABLE IF NOT EXISTS last_known_good (
    lkg_id TEXT PRIMARY KEY,
    managed_integration_ref TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    desired_state_ref TEXT,
    artifact_ref TEXT,
    runtime_config_ref TEXT,
    schema_ref TEXT,
    mapping_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    integration_contract_ref TEXT,
    policy_ref TEXT,
    provider_state_ref TEXT,
    verified_health_ref TEXT,
    established_at TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_last_known_good_integration
    ON last_known_good (tenant_id, environment_id, managed_integration_ref);

CREATE TABLE IF NOT EXISTS change_set_rollbacks (
    rollback_id TEXT PRIMARY KEY,
    changeset_ref TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    last_known_good_ref TEXT,
    rollback_actions JSONB NOT NULL DEFAULT '[]'::jsonb,
    queue_recovery_policy TEXT,
    replay_policy TEXT,
    validation_requirements JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_change_set_rollbacks_changeset
    ON change_set_rollbacks (changeset_ref);

CREATE TABLE IF NOT EXISTS change_set_approvals (
    approval_id TEXT PRIMARY KEY,
    changeset_ref TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    required_approval_ref TEXT NOT NULL,
    granted_role TEXT NOT NULL,
    granted_by_actor TEXT NOT NULL,
    decision TEXT NOT NULL DEFAULT 'approved',
    note TEXT,
    decided_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_change_set_approvals_changeset
    ON change_set_approvals (changeset_ref);

CREATE TABLE IF NOT EXISTS action_required (
    action_id TEXT PRIMARY KEY,
    tenant_ref TEXT NOT NULL,
    managed_integration_ref TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    reason TEXT NOT NULL,
    impact TEXT,
    deadline TIMESTAMPTZ,
    required_actor TEXT NOT NULL,
    required_action TEXT NOT NULL,
    continuity_state TEXT,
    data_loss_expected BOOLEAN NOT NULL DEFAULT false,
    resolution_ref TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_action_required_status
    ON action_required (status);
"""


def upgrade() -> None:
    op.execute(SCHEMA_SQL)


def downgrade() -> None:
    # Best-effort: reverse the additive DDL in dependency-free order. The
    # ALTERed columns on change_sets are dropped too so a downgrade leaves the
    # Phase-1 schema exactly as it was.
    op.execute("DROP TABLE IF EXISTS action_required")
    op.execute("DROP TABLE IF EXISTS change_set_approvals")
    op.execute("DROP TABLE IF EXISTS change_set_rollbacks")
    op.execute("DROP TABLE IF EXISTS last_known_good")
    op.execute("DROP TABLE IF EXISTS change_evidence")
    op.execute("DROP TABLE IF EXISTS change_set_events")
    op.execute("ALTER TABLE change_sets DROP COLUMN IF EXISTS started_at")
    op.execute("ALTER TABLE change_sets DROP COLUMN IF EXISTS completed_at")
    op.execute("ALTER TABLE change_sets DROP COLUMN IF EXISTS before_state_refs")
    op.execute("ALTER TABLE change_sets DROP COLUMN IF EXISTS target_state_refs")
    op.execute("ALTER TABLE change_sets DROP COLUMN IF EXISTS rollback_ref")
