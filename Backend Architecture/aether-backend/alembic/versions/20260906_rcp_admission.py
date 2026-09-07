"""Reconciled Control Plane — §16 integration admission records (Phase 3).

Phase 3 opens the admission half of the reconciliation loop: integrations are
*registered* through the §16 admission lifecycle (discover -> understand ->
classify -> reconcile_source_authority -> authorize -> simulate -> approve ->
compile -> activate -> observe) before the continuous lifecycle (monitor ->
drift -> reconcile -> change / review / suspend / revoke) takes over. The
single table below records that lifecycle:

* ``admission_records`` — one row per admitted/being-admitted integration: the
  durable §16 lifecycle fact for a (tenant, env, managed integration). The row
  carries the source facts it was registered from (``source_ref`` /
  ``integration_kind`` / ``source_origin``) and the §16 lifecycle position
  (``current_stage``, ``lifecycle_state``, ``active``). The unique index makes
  at most one admission per integration — the engine's ``get_or_create`` is the
  only way a row is born, and re-admission returns the existing row. Per CP-03
  ("discovery never equals authorization") the row is a *lifecycle fact* —
  ``current_stage='discover'`` and ``active=false`` until the full §16 walk has
  been driven; nothing about this table ever enables an integration.

The DDL is additive ``CREATE TABLE/INDEX IF NOT EXISTS`` only — nothing is
dropped or widened. Tenancy is enforced in the repository SQL (every row
carries tenant_id/environment_id so no cross-tenant read is possible).

The SQL below is string-identical to ``SCHEMA_SQL`` in
``services/managed_integrations/admission_repository.py`` (the repo executes it
to self-ensure the table under ``AETHER_ENV=local``).

Revision ID: 20260906_rcp_admission
Revises: 20260906_rcp_execution
Create Date: 2026-09-06

COORDINATOR SHARED-SURFACE DELTA (tuple-merge note): this migration's
down_revision is the Reconciled-Control-Phase-2 lane head
``20260906_rcp_execution``. When this branch is combined with sibling lanes
that each add a migration off the same base, a NEW tuple-merge revision must be
created with ``down_revision = (<this revision>, <sibling revision>, ...)``
exactly like ``20260906_merge_data_exchange_head`` /
``20260904_merge_communication360_head``.
"""

from __future__ import annotations

from alembic import op

revision = "20260906_rcp_admission"
down_revision = "20260906_rcp_execution"
branch_labels = None
depends_on = None

# Must stay string-identical to
# services/managed_integrations/admission_repository.py ``SCHEMA_SQL``.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS admission_records (
    admission_id TEXT PRIMARY KEY,
    managed_integration_ref TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    source_ref TEXT NOT NULL,
    integration_kind TEXT NOT NULL,
    source_origin TEXT NOT NULL,
    current_stage TEXT NOT NULL DEFAULT 'discover',
    lifecycle_state TEXT NOT NULL DEFAULT 'monitor',
    active BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_admission_integration
    ON admission_records (tenant_id, environment_id, managed_integration_ref);
"""


def upgrade() -> None:
    op.execute(SCHEMA_SQL)


def downgrade() -> None:
    # Best-effort: reverse the additive DDL so a downgrade leaves the Phase-2
    # schema exactly as it was.
    op.execute("DROP TABLE IF EXISTS admission_records")
