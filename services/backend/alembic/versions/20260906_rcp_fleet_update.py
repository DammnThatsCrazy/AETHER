"""Reconciled Control Plane — §29 fleet upgrade controller stores (Phase 4).

Phase 4 is the *progressive-delivery + fleet upgrade* half of the
reconciliation loop (§40 rings, §12.8 rollout engine, and the §29 fleet
upgrade controller that plans upgrades for managed integrations). The two
tables below are the controller's durable facts — policy first, plans second:

* ``fleet_update_policies`` — the §29/§28 tenant update-channel policy: one
  row per (tenant_ref, environment_id, channel) naming the channel and the
  §40 delivery-ring ceiling (``max_ring``, default ``100%``) the tenant
  operator set. The channel must be a §28 release channel (pinned /
  security_auto / patch_auto / compatible_auto / managed_stable) and the ring
  must be a §40 rollout ring — the unique index makes the
  one-policy-per-channel rule atomic. ``pinned`` is expressed by a policy
  whose channel allows no automatic class (the engine never invents a class
  set); ``managed_stable`` is a managed band, never uncontrolled ``latest``
  (§29) — that guard lives in the engine, not the schema.
* ``fleet_upgrade_plans`` — one row per §29 upgrade plan the controller
  composed for one managed integration: the candidate release (ref + §29
  release class), the §30 platform behavior that governs it, the eligibility
  verdict, the execution path (automatic / review / action), the human-readable
  eligibility reasons (every failed gate, or an ``"eligible"`` entry), the
  §40 ring ceiling when eligible (``planned_ring``), and ``rollout_ref`` which
  is filled only when the plan is handed to the §40 rollout engine.

Nothing here executes: plans are composed facts (the §34/§35 governed executor
path and the §40 rollout engine are separate). Tenancy is enforced in the
repository SQL — these rows carry tenant_ref/environment_id so no cross-tenant
read is possible (CP-08).

Both tables are ``CREATE TABLE/INDEX IF NOT EXISTS`` — nothing is dropped or
widened. The SQL below is string-identical to ``SCHEMA_SQL`` in
``services/managed_integrations/fleet_controller_repository.py`` (the repo
executes it to self-ensure the tables under ``AETHER_ENV=local``).

Revision ID: 20260906_rcp_fleet_update
Revises: 20260906_rcp_rollouts
Create Date: 2026-09-06

COORDINATOR SHARED-SURFACE DELTA (tuple-merge note): this migration's
down_revision is the sibling Phase-4 rollout-lane head
``20260906_rcp_rollouts`` (the §40 universal-ring + rollout-engine tables land
there first, in the concurrent rollout lane). When this branch is combined
with sibling lanes that each add a migration off the same base, a NEW
tuple-merge revision must be created with ``down_revision = (<this revision>,
<sibling revision>, ...)`` exactly like ``20260906_merge_data_exchange_head`` /
``20260904_merge_communication360_head``.
"""

from __future__ import annotations

from alembic import op

revision = "20260906_rcp_fleet_update"
down_revision = "20260906_rcp_rollouts"
branch_labels = None
depends_on = None

# Must stay string-identical to
# services/managed_integrations/fleet_controller_repository.py ``SCHEMA_SQL``.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS fleet_update_policies (
    policy_id TEXT PRIMARY KEY,
    tenant_ref TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    max_ring TEXT NOT NULL DEFAULT '100%',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_fleet_policy_scope
    ON fleet_update_policies (tenant_ref, environment_id, channel);

CREATE TABLE IF NOT EXISTS fleet_upgrade_plans (
    plan_id TEXT PRIMARY KEY,
    tenant_ref TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    managed_integration_ref TEXT NOT NULL,
    integration_kind TEXT NOT NULL,
    artifact_kind TEXT NOT NULL,
    candidate_ref TEXT NOT NULL,
    candidate_class TEXT NOT NULL,
    channel TEXT NOT NULL,
    behavior TEXT NOT NULL,
    eligible BOOLEAN NOT NULL DEFAULT false,
    execution_path TEXT NOT NULL,
    eligibility_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
    planned_ring TEXT,
    rollout_ref TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_fleet_plans_tenant
    ON fleet_upgrade_plans (tenant_ref, created_at);
"""


def upgrade() -> None:
    op.execute(SCHEMA_SQL)


def downgrade() -> None:
    # Best-effort: reverse the additive DDL in dependency-free order (plans
    # first — nothing references policies, but drop order stays child-first).
    op.execute("DROP TABLE IF EXISTS fleet_upgrade_plans")
    op.execute("DROP TABLE IF EXISTS fleet_update_policies")
