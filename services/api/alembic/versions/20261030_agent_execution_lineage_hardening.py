"""Separate source vs canonical lineage identity on agent execution facts.

Revision ID: 20261030_agent_exec_lineage_hardening
Revises: 20261031_merge_agent_behavior_snapshots_heads
Create Date: 2026-10-30

High-Cardinality Agent Lineage work order, AO-3. Adds the columns that keep
the following pairs distinct on ``silver_agent_execution_facts``:

  * source run vs canonical run (a trace is not a run);
  * reported principal vs canonical principal (a claim is not a resolution);
  * agent definition vs agent instance;
  * parent vs root (agent entity and run).

Every ``canonical_*`` / ``*_entity_id`` resolution column starts NULL at
projection time and is only filled by canonical resolution. Source values are
never overwritten. Historical rows stay NULL (``control_mode`` is NULL, not
``UNKNOWN``, for rows projected before this revision: unknown is not asserted).

Also adds ``protocol`` / ``protocol_version``, which the projector already
emitted but no earlier revision created, so the generic Silver writer was
dropping them.
"""
from __future__ import annotations

from alembic import op

revision = "20261030_agent_exec_lineage_hardening"
down_revision = "20261031_merge_agent_behavior_snapshots_heads"
branch_labels = None
depends_on = None

_COLUMNS = (
    "canonical_run_id",
    "source_run_id",
    "root_run_id",
    "agent_definition_id",
    "agent_instance_id",
    "parent_agent_entity_id",
    "root_agent_entity_id",
    "reported_principal_ref",
    "reported_principal_namespace",
    "canonical_principal_entity_id",
    "principal_resolution_status",
    "initiator_entity_id",
    "executor_entity_id",
    "operator_entity_id",
    "beneficiary_entity_id",
    "control_mode",
    "authority_type",
    "authority_ref",
    "protocol",
    "protocol_version",
    "external_effect_ref",
    "execution_verification_state",
    "parent_span_id",
)


def upgrade() -> None:
    adds = ",\n            ".join(f"ADD COLUMN IF NOT EXISTS {name} TEXT" for name in _COLUMNS)
    op.execute(f"""
        ALTER TABLE silver_agent_execution_facts
            {adds},
            ADD COLUMN IF NOT EXISTS delegation_depth INTEGER
    """)
    # Tenant-scoped lookups used by lineage reconstruction and bulk principal
    # resolution. Partial so legacy rows and unreported values cost nothing.
    op.execute(
        "CREATE INDEX IF NOT EXISTS silver_agent_exec_root_run "
        "ON silver_agent_execution_facts (tenant_id, root_run_id, occurred_at) "
        "WHERE root_run_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS silver_agent_exec_instance "
        "ON silver_agent_execution_facts (tenant_id, agent_instance_id, occurred_at) "
        "WHERE agent_instance_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS silver_agent_exec_definition "
        "ON silver_agent_execution_facts (tenant_id, agent_definition_id, occurred_at) "
        "WHERE agent_definition_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS silver_agent_exec_principal_unresolved "
        "ON silver_agent_execution_facts "
        "(tenant_id, reported_principal_namespace, reported_principal_ref) "
        "WHERE reported_principal_ref IS NOT NULL "
        "AND canonical_principal_entity_id IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS silver_agent_exec_principal_canonical "
        "ON silver_agent_execution_facts (tenant_id, canonical_principal_entity_id, occurred_at) "
        "WHERE canonical_principal_entity_id IS NOT NULL"
    )


def downgrade() -> None:
    for index in (
        "silver_agent_exec_principal_canonical",
        "silver_agent_exec_principal_unresolved",
        "silver_agent_exec_definition",
        "silver_agent_exec_instance",
        "silver_agent_exec_root_run",
    ):
        op.execute(f"DROP INDEX IF EXISTS {index}")
    drops = ",\n            ".join(f"DROP COLUMN IF EXISTS {name}" for name in _COLUMNS)
    op.execute(f"""
        ALTER TABLE silver_agent_execution_facts
            {drops},
            DROP COLUMN IF EXISTS delegation_depth
    """)
