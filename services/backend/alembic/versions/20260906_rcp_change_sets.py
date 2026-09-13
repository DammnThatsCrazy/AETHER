"""Reconciled Control Plane — ChangeSet plan table (Phase 1).

One additive table backs the Phase-1 planning half of the reconciliation
loop:

* ``change_sets`` — candidate change transactions generated from actionable
  drift (§32 step 12). A row carries the tenant/env scope, the §35 guard
  revisions + idempotency key (``desired_revision``, ``observed_revision``,
  ``reconcile_sequence``, ``idempotency_key``), the typed ``changes``,
  the §32-13 ``blast_radius``, the §39 ``risk`` assessment, and the §34
  ``status``. Phase 1 rows reach at most ``planned`` (or terminal
  ``superseded``/``cancelled``): nothing here is ever executed — the actuator
  engine is a later phase and illegal transitions fail closed.

No foreign key links ``change_sets`` to ``managed_integrations``/``reconcile_runs``
on purpose: a plan's ``integration_scope`` is a JSONB list of managed-integration
refs (a future mapping change may reach many integrations), and the planner must
be able to produce a candidate from an evidence-backed run regardless of whether
a registration row exists. Tenancy scoping is enforced in the repository SQL,
not by the schema.

The SQL below is string-identical to ``SCHEMA_SQL`` in
``services/managed_integrations/change_sets_repository.py`` (the repo executes
it to self-ensure the table under ``AETHER_ENV=local``). Pure additive ``CREATE
TABLE IF NOT EXISTS``/``CREATE INDEX IF NOT EXISTS`` — nothing is dropped or
widened.

Revision ID: 20260906_rcp_change_sets
Revises: 20260906_rcp_managed_integrations
Create Date: 2026-09-06

COORDINATOR SHARED-SURFACE DELTA (tuple-merge note): this migration's
down_revision is the Reconciled-Control-Phase-0 lane head
``20260906_rcp_managed_integrations``. When this branch is combined with
sibling lanes that each add a migration off the same base, a NEW tuple-merge
revision must be created with ``down_revision = (<this revision>, <sibling
revision>, ...)`` exactly like
``20260906_merge_data_exchange_head``/``20260904_merge_communication360_head``.
"""

from __future__ import annotations

from alembic import op

revision = "20260906_rcp_change_sets"
down_revision = "20260906_rcp_managed_integrations"
branch_labels = None
depends_on = None

# Must stay string-identical to
# services/managed_integrations/change_sets_repository.py ``SCHEMA_SQL``.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS change_sets (
    changeset_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    integration_scope JSONB NOT NULL DEFAULT '[]'::jsonb,
    desired_revision TEXT NOT NULL,
    observed_revision TEXT NOT NULL,
    reconcile_sequence TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    changes JSONB NOT NULL DEFAULT '[]'::jsonb,
    reason TEXT,
    initiator TEXT NOT NULL,
    policy_ref TEXT,
    risk JSONB NOT NULL DEFAULT '{}'::jsonb,
    blast_radius JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    superseded_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_change_sets_tenant_env_status
    ON change_sets (tenant_id, environment_id, status);
CREATE INDEX IF NOT EXISTS ix_change_sets_idempotency
    ON change_sets (tenant_id, idempotency_key);
"""


def upgrade() -> None:
    op.execute(SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS change_sets")
