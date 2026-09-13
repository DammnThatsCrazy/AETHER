"""Reconciled Control Plane — managed-integration durable tables (Phase 0).

Two additive tables back the Phase-0 operator read surface:

* ``managed_integrations`` — durable registration facts for every managed
  integration (SDK, connector, provider-runtime connection, webhook, import,
  feed) that the reconciler converges toward an authorized desired state. Rows
  record the tenant scope, the kind/source identity, the release channel the
  tenant opted into, and the last reconcile stamp. Health/lifecycle values are
  opaque strings sourced from the observing authority — never inferred.
* ``reconcile_runs`` — evidence rows for one desired-vs-observed classification
  (result + drift JSON). The JSONB ``drift_summary`` holds DRAFT change
  summaries only; Phase 0 never applies a ChangeSet (CP-08 boundary).

No foreign key links ``reconcile_runs`` to ``managed_integrations`` on purpose:
the reconciler must be able to record an evidence-backed ``unknown``/``missing``
run for an integration that has never been registered — a durable registration
row is itself a fact Phase 0 does not auto-create. Tenancy scoping is enforced
in the repository SQL, not by the schema.

The SQL below is string-identical to ``SCHEMA_SQL`` in
``services/managed_integrations/repository.py`` (the repo executes it to
self-ensure tables under ``AETHER_ENV=local``, mirroring the data-exchange
plane). Pure additive ``CREATE TABLE IF NOT EXISTS``/``CREATE INDEX IF NOT
EXISTS`` — nothing is dropped or widened.

Revision ID: 20260906_rcp_managed_integrations
Revises: 20260906_wsd_silver_exact_money
Create Date: 2026-09-06

COORDINATOR SHARED-SURFACE DELTA (tuple-merge note): this migration's
down_revision is the single lane head ``20260906_wsd_silver_exact_money``.
When this branch is combined with sibling lanes that each add a migration off
that head, a NEW tuple-merge revision must be created with ``down_revision =
(<this revision>, <sibling revision>, ...)`` exactly like
``20260906_merge_data_exchange_head``/``20260904_merge_communication360_head``.
"""

from __future__ import annotations

from alembic import op

revision = "20260906_rcp_managed_integrations"
down_revision = "20260906_wsd_silver_exact_money"
branch_labels = None
depends_on = None

# Must stay string-identical to
# services/managed_integrations/repository.py ``SCHEMA_SQL``.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS managed_integrations (
    managed_integration_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    integration_kind TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    provider_ref TEXT,
    source_origin TEXT NOT NULL,
    source_owner TEXT NOT NULL,
    release_channel TEXT NOT NULL DEFAULT 'managed_stable',
    health_state TEXT NOT NULL DEFAULT 'unknown',
    lifecycle_state TEXT NOT NULL DEFAULT 'unknown',
    schema_fingerprint TEXT,
    desired_state_ref TEXT,
    observed_state_ref TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_reconcile_at TIMESTAMPTZ,
    last_reconcile_result TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_managed_integrations_tenant_env_kind
    ON managed_integrations (tenant_id, environment_id, integration_kind);
CREATE TABLE IF NOT EXISTS reconcile_runs (
    reconcile_id TEXT PRIMARY KEY,
    managed_integration_id TEXT NOT NULL,
    desired_state_ref TEXT,
    observed_state_ref TEXT,
    desired_revision TEXT NOT NULL,
    observed_revision TEXT,
    freshness_ok BOOLEAN NOT NULL,
    result TEXT NOT NULL,
    note TEXT,
    drift_summary JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_reconcile_runs_integration_created
    ON reconcile_runs (managed_integration_id, created_at);
"""


def upgrade() -> None:
    op.execute(SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS reconcile_runs")
    op.execute("DROP TABLE IF EXISTS managed_integrations")
