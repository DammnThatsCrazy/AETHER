"""Add durable tenant connector writer routes and append-only transitions.

Revision ID: 20261002_tenant_connector_routes
Revises: 20260927_status_component_daily
Create Date: 2026-10-02

The route key scopes writer authority by tenant, environment, managed
integration, provider capability, account, stream, and fact family. Every
transition advances ``writer_generation`` and ``revision`` and records an audit
receipt. There is no data backfill or automatic traffic switch: existing
connectors remain on their current paths until a governed route is created.

``SCHEMA_SQL`` is identical to the self-ensure DDL in
``services/provider_runtime/tenant_route_repository.py``. The new tables may be
dropped on downgrade only after operators have moved all routed tenants back
to legacy paths; downgrade cannot restore traffic decisions from audit rows.
"""

from __future__ import annotations

from alembic import op

revision = "20261002_tenant_connector_routes"
down_revision = "20260927_status_component_daily"
branch_labels = None
depends_on = None

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tenant_connector_routes (
    route_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    managed_integration_id TEXT NOT NULL,
    provider_identity TEXT NOT NULL,
    account_id TEXT NOT NULL DEFAULT '',
    stream_id TEXT NOT NULL,
    fact_family TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('legacy_only', 'shadow', 'new_primary', 'legacy_disabled')),
    legacy_connection_ref TEXT NOT NULL,
    native_connection_ref TEXT,
    shadow_namespace TEXT,
    writer_generation BIGINT NOT NULL CHECK (writer_generation > 0),
    revision BIGINT NOT NULL CHECK (revision > 0),
    evidence_bundle_ref TEXT,
    rollback_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_tenant_connector_route_scope
    ON tenant_connector_routes (tenant_id, environment_id, managed_integration_id, provider_identity, account_id, stream_id, fact_family);
CREATE TABLE IF NOT EXISTS tenant_connector_route_transitions (
    transition_id TEXT PRIMARY KEY,
    route_id TEXT NOT NULL REFERENCES tenant_connector_routes(route_id) ON DELETE RESTRICT,
    tenant_id TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    previous_mode TEXT,
    next_mode TEXT NOT NULL,
    previous_generation BIGINT,
    next_generation BIGINT NOT NULL,
    revision BIGINT NOT NULL,
    actor_ref TEXT NOT NULL,
    decision_ref TEXT NOT NULL,
    evidence_bundle_ref TEXT,
    reason TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_tenant_connector_route_transition_revision
    ON tenant_connector_route_transitions (route_id, revision);
CREATE INDEX IF NOT EXISTS ix_tenant_connector_route_transitions_scope
    ON tenant_connector_route_transitions (tenant_id, environment_id, route_id, occurred_at);
"""


def upgrade() -> None:
    op.execute(SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tenant_connector_route_transitions")
    op.execute("DROP TABLE IF EXISTS tenant_connector_routes")
