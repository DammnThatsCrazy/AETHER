"""Reconciled Control Plane — durable production activation authority.

Revision ID: 20261029_rcp_activation_authority
Revises: 20261024_merge_360_surface_authorities
Create Date: 2026-10-29

Adds two additive tables:

* ``rcp_control_plane_activation_states`` — the durable operational activation
  authority (shadow -> detect -> plan -> R0 -> R1 -> R2 -> fully_managed, plus
  emergency_frozen), scoped globally or per tenant/environment/region.
* ``rcp_control_plane_activation_transitions`` — append-only evidence for every
  governed advance/freeze/resume attempt.

Environment variables are hard kill switches over the effective state; they are
not stored here and cannot grant activation. The SQL below is string-identical to
``SCHEMA_SQL`` in
``services/api/connectors/managed_integrations/activation_repository.py``
(parity-checked by repo-doctor). Pure additive ``CREATE TABLE IF NOT EXISTS`` /
``CREATE INDEX IF NOT EXISTS`` — nothing is dropped or widened.
"""

from __future__ import annotations

from alembic import op

revision = "20261029_rcp_activation_authority"
down_revision = "20261024_merge_360_surface_authorities"
branch_labels = None
depends_on = None

# Must stay string-identical to
# services/api/connectors/managed_integrations/activation_repository.py ``SCHEMA_SQL``.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS rcp_control_plane_activation_states (
    activation_id TEXT PRIMARY KEY,
    scope_kind TEXT NOT NULL,
    tenant_id TEXT,
    environment_id TEXT,
    region TEXT NOT NULL DEFAULT 'global',
    state TEXT NOT NULL DEFAULT 'shadow',
    previous_state TEXT,
    frozen_from_state TEXT,
    revision BIGINT NOT NULL DEFAULT 0,
    readiness_ref TEXT,
    readiness_ready BOOLEAN NOT NULL DEFAULT false,
    reason TEXT,
    updated_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (scope_kind IN ('global', 'tenant_environment')),
    CHECK (state IN ('shadow', 'detect', 'plan', 'r0', 'r1', 'r2',
                     'fully_managed', 'emergency_frozen')),
    CHECK (frozen_from_state IS NULL OR frozen_from_state IN
           ('shadow', 'detect', 'plan', 'r0', 'r1', 'r2', 'fully_managed'))
);
CREATE INDEX IF NOT EXISTS ix_rcp_activation_scope
    ON rcp_control_plane_activation_states
       (scope_kind, region, tenant_id, environment_id);
CREATE TABLE IF NOT EXISTS rcp_control_plane_activation_transitions (
    transition_id TEXT PRIMARY KEY,
    activation_id TEXT NOT NULL,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    transition TEXT NOT NULL,
    readiness_ref TEXT,
    readiness_ready BOOLEAN NOT NULL DEFAULT false,
    reason TEXT,
    actor TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (transition IN ('advance', 'freeze', 'resume'))
);
CREATE INDEX IF NOT EXISTS ix_rcp_activation_transition_history
    ON rcp_control_plane_activation_transitions (activation_id, created_at);
"""


def upgrade() -> None:
    op.execute(SCHEMA_SQL)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rcp_control_plane_activation_transitions")
    op.execute("DROP TABLE IF EXISTS rcp_control_plane_activation_states")
