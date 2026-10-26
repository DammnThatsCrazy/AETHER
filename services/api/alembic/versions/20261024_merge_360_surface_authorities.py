"""Merge the independently authored 360 backend authority migrations."""

from __future__ import annotations

revision = "20261024_merge_360_surface_authorities"
down_revision = (
    "20261024_campaign_population_link_authority",
    "20261024_commerce_flow_facts",
    "20261024_episode_journey_authority_records",
    "20261024_geo_temporal_timezone_authority",
    "20261024_profile_prediction_output_authority",
    "20261024_risk_intervention_records",
    "20261024_social_relationship_evidence_authority",
    "20261024_support_case_context_authorities",
    "20261024_workflow_memory_metadata_authorities",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
