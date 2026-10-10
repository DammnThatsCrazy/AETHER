"""Incrementality experiment system — experiments, assignments, exposures, outcomes.

Revision ID: i1n2c3r4e5m6
Revises: m1e2a3s4u5r6
Create Date: 2026-06-22

Creates four tables for the incrementality experiment framework:

  experiments           — experiment definitions (holdout, geo, campaign)
  experiment_assignments — deterministic treatment/control assignment per entity
  experiment_exposures  — exposure events (when an entity saw a treatment)
  experiment_outcomes   — outcome events linked to an experiment assignment

Design:
  - Holdout experiments: a percentage of traffic is withheld from a campaign
  - Geo holdouts: geographic regions serve as control markets
  - Pre/post analysis: compares metrics in pre vs. post period for holdout cells
  - Incremental lift = (converted_treatment_rate - converted_control_rate) / converted_control_rate
  - Incremental metrics are always labeled separately from attributed metrics
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "i1n2c3r4e5m6"
down_revision = "m1e2a3s4u5r6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Experiments ──────────────────────────────────────────────────────────
    op.create_table(
        "experiments",
        sa.Column("experiment_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("experiment_type", sa.Text, nullable=False),  # holdout|geo_holdout|pre_post|campaign_ab
        sa.Column("status", sa.Text, nullable=False, server_default="draft"),  # draft|running|paused|stopped|analyzing|complete
        sa.Column("hypothesis", sa.Text),
        sa.Column("holdout_pct", sa.Numeric(5, 4)),  # fraction of traffic in control (e.g. 0.1 = 10%)
        sa.Column("campaign_ids", JSONB, server_default="[]"),
        sa.Column("geo_regions", JSONB, server_default="[]"),  # for geo holdouts
        sa.Column("start_at", sa.DateTime(timezone=True)),
        sa.Column("end_at", sa.DateTime(timezone=True)),
        sa.Column("pre_period_start", sa.DateTime(timezone=True)),
        sa.Column("pre_period_end", sa.DateTime(timezone=True)),
        sa.Column("post_period_start", sa.DateTime(timezone=True)),
        sa.Column("post_period_end", sa.DateTime(timezone=True)),
        sa.Column("primary_metric", sa.Text, server_default="conversion_rate"),
        sa.Column("secondary_metrics", JSONB, server_default="[]"),
        sa.Column("minimum_detectable_effect", sa.Numeric(8, 6)),
        sa.Column("statistical_significance_threshold", sa.Numeric(5, 4), server_default="0.05"),
        sa.Column("created_by", sa.Text),
        sa.Column("approved_by", sa.Text),
        sa.Column("config", JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_experiments_tenant_id", "experiments", ["tenant_id"])
    op.create_index("ix_experiments_status", "experiments", ["tenant_id", "status"])

    # ── Experiment Assignments ───────────────────────────────────────────────
    op.create_table(
        "experiment_assignments",
        sa.Column("assignment_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("experiment_id", UUID(as_uuid=True), sa.ForeignKey("experiments.experiment_id"), nullable=False),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("entity_type", sa.Text, nullable=False),  # profile|cluster|account|geo_region
        sa.Column("entity_id", sa.Text, nullable=False),
        sa.Column("cell", sa.Text, nullable=False),  # treatment|control
        sa.Column("assignment_method", sa.Text, server_default="deterministic_hash"),
        sa.Column("hash_seed", sa.Text),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("experiment_id", "entity_id", name="uq_experiment_entity_assignment"),
    )
    op.create_index("ix_experiment_assignments_entity", "experiment_assignments", ["tenant_id", "entity_id"])
    op.create_index("ix_experiment_assignments_experiment", "experiment_assignments", ["experiment_id", "cell"])

    # ── Experiment Exposures ─────────────────────────────────────────────────
    op.create_table(
        "experiment_exposures",
        sa.Column("exposure_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("experiment_id", UUID(as_uuid=True), sa.ForeignKey("experiments.experiment_id"), nullable=False),
        sa.Column("assignment_id", UUID(as_uuid=True), sa.ForeignKey("experiment_assignments.assignment_id"), nullable=False),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("entity_id", sa.Text, nullable=False),
        sa.Column("cell", sa.Text, nullable=False),
        sa.Column("exposure_type", sa.Text, nullable=False),  # ad_impression|campaign_touch|geo_market
        sa.Column("touchpoint_id", UUID(as_uuid=True)),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.Text, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_experiment_exposures_experiment_entity", "experiment_exposures", ["experiment_id", "entity_id"])

    # ── Experiment Outcomes ──────────────────────────────────────────────────
    op.create_table(
        "experiment_outcomes",
        sa.Column("outcome_id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("experiment_id", UUID(as_uuid=True), sa.ForeignKey("experiments.experiment_id"), nullable=False),
        sa.Column("assignment_id", UUID(as_uuid=True), sa.ForeignKey("experiment_assignments.assignment_id"), nullable=False),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("entity_id", sa.Text, nullable=False),
        sa.Column("cell", sa.Text, nullable=False),
        sa.Column("conversion_id", UUID(as_uuid=True)),
        sa.Column("outcome_type", sa.Text, nullable=False),  # purchase|lead|signup|trial|...
        sa.Column("gross_value", sa.Numeric(18, 6)),
        sa.Column("net_value", sa.Numeric(18, 6)),
        sa.Column("currency", sa.Text, server_default="USD"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_incremental", sa.Boolean),  # NULL = unknown, true/false = analyzed
        sa.Column("idempotency_key", sa.Text, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_experiment_outcomes_experiment_cell", "experiment_outcomes", ["experiment_id", "cell"])
    op.create_index("ix_experiment_outcomes_entity", "experiment_outcomes", ["tenant_id", "entity_id"])


def downgrade() -> None:
    op.drop_table("experiment_outcomes")
    op.drop_table("experiment_exposures")
    op.drop_table("experiment_assignments")
    op.drop_table("experiments")
