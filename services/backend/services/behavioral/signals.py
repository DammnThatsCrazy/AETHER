"""
Behavioral Signal Registry — defines all derived signal types,
their source dependencies, and output contracts.
"""

from __future__ import annotations

from enum import Enum
from typing import Any



class SignalFamily(str, Enum):
    INTENT_RESIDUE = "intent_residue"
    WALLET_FRICTION = "wallet_friction"
    IDENTITY_DELTA = "identity_delta"
    PRE_POST_CONTINUITY = "pre_post_continuity"
    SEQUENCE_SCAR = "sequence_scar"
    SOURCE_SHADOW = "source_shadow"
    REWARD_NEAR_MISS = "reward_near_miss"
    SOCIAL_CHAIN_LAG = "social_chain_lag"
    CEX_DEX_TRANSITION = "cex_dex_transition"
    BEHAVIORAL_TWIN = "behavioral_twin"


# Signal definitions: what each signal needs, produces, and explains
SIGNAL_REGISTRY: dict[str, dict[str, Any]] = {
    "intent_residue": {
        "family": SignalFamily.INTENT_RESIDUE,
        "source_events": ["page", "track", "conversion", "wallet"],
        "required_joins": ["session_id", "user_id"],
        "outputs": ["intent_residue_score", "unfinished_flow_type", "last_high_intent_step",
                     "return_to_intent_probability", "residue_explanation"],
        "consumers": ["trust_score", "churn_prediction", "journey_prediction", "profile_360"],
    },
    "wallet_friction": {
        "family": SignalFamily.WALLET_FRICTION,
        "source_events": ["wallet", "error", "track"],
        "required_joins": ["session_id", "user_id", "wallet_address"],
        "outputs": ["wallet_connect_attempt_count", "wallet_connect_failure_loop",
                     "wallet_switch_before_connect", "connect_hesitation_ms",
                     "connect_friction_score", "connect_friction_explanation"],
        "consumers": ["trust_score", "bot_detection", "profile_360"],
    },
    "identity_delta": {
        "family": SignalFamily.IDENTITY_DELTA,
        "source_events": ["identify", "wallet"],
        "required_joins": ["user_id", "identity_cluster"],
        "outputs": ["identity_confidence_delta", "new_evidence_type",
                     "contradictory_evidence_type", "merge_stability_score",
                     "identity_delta_explanation"],
        "consumers": ["identity_resolution", "trust_score", "profile_360", "expectations"],
    },
    "pre_post_continuity": {
        "family": SignalFamily.PRE_POST_CONTINUITY,
        "source_events": ["page", "track", "identify", "wallet", "conversion"],
        "required_joins": ["session_id", "user_id", "anonymous_id"],
        "outputs": ["pre_post_identity_continuity", "pre_connect_intent_strength",
                     "connect_consistency_score", "behavior_to_wallet_match_confidence",
                     "continuity_explanation"],
        "consumers": ["trust_score", "intent_prediction", "attribution", "profile_360"],
    },
    "sequence_scar": {
        "family": SignalFamily.SEQUENCE_SCAR,
        "source_events": ["page", "track", "wallet", "error", "conversion"],
        "required_joins": ["session_id", "user_id"],
        "outputs": ["sequence_scar_type", "scar_recurrence_count",
                     "scar_resolution_rate", "scar_to_conversion_lag",
                     "sequence_scar_explanation"],
        "consumers": ["churn_prediction", "journey_prediction", "profile_360", "population"],
    },
    "source_shadow": {
        "family": SignalFamily.SOURCE_SHADOW,
        "source_events": ["*"],  # meta-signal about source health
        "required_joins": ["entity_id", "source"],
        "outputs": ["source_coverage_confidence", "behavior_absence_confidence",
                     "source_shadow_flag", "observation_gap_vs_behavior_gap",
                     "source_shadow_explanation"],
        "consumers": ["expectations", "trust_score", "anomaly_detection", "profile_360"],
    },
    "reward_near_miss": {
        "family": SignalFamily.REWARD_NEAR_MISS,
        "source_events": ["conversion", "track", "wallet"],
        "required_joins": ["user_id", "campaign_id"],
        "outputs": ["eligibility_gap_reason", "near_miss_window",
                     "recovery_probability", "next_best_action_for_eligibility",
                     "reward_near_miss_explanation"],
        "consumers": ["rewards", "churn_prediction", "profile_360"],
    },
    "social_chain_lag": {
        "family": SignalFamily.SOCIAL_CHAIN_LAG,
        "source_events": ["track"],
        "required_joins": ["user_id", "wallet_address"],
        "outputs": ["social_to_chain_lag_hours", "narrative_to_action_lag",
                     "governance_attention_to_vote_lag", "social_signal_followthrough_rate",
                     "lag_explanation"],
        "consumers": ["attribution", "trust_score", "profile_360"],
    },
    "cex_dex_transition": {
        "family": SignalFamily.CEX_DEX_TRANSITION,
        "source_events": ["wallet", "transaction"],
        "required_joins": ["user_id", "wallet_address"],
        "outputs": ["cex_to_dex_transition_score", "fiat_onramp_proximity",
                     "cross_venue_behavior_similarity", "venue_shift_alert",
                     "transition_explanation"],
        "consumers": ["trust_score", "anomaly_detection", "profile_360"],
    },
    "behavioral_twin": {
        "family": SignalFamily.BEHAVIORAL_TWIN,
        "source_events": ["page", "track", "wallet", "conversion"],
        "required_joins": ["user_id"],
        "outputs": ["twin_group_id", "divergence_outcome_type",
                     "divergence_point", "twin_similarity_score",
                     "divergence_explanation"],
        "consumers": ["churn_prediction", "intent_prediction", "population", "profile_360"],
    },
}
