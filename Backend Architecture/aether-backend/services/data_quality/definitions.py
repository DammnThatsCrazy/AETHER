"""Static baselines and seed definitions for data-quality monitors.

These describe the *shape* of each intelligence-quality dimension and provide a
deterministic, healthy baseline so local/mock mode renders a populated dashboard
without external services. Live values are layered on top at read time (via the
``report_*`` adapters) or perturbed deterministically per tenant.

No external SLA, compliance, or certification is claimed here — these are
internal data-quality objectives only.
"""
from __future__ import annotations

import hashlib
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Per-dimension healthy baselines (the score is the dimension's normalized 0..1
# quality; the remaining keys are the tracked metrics surfaced on the routes).
# ─────────────────────────────────────────────────────────────────────────────

EVENT_QUALITY_BASELINE: dict[str, Any] = {
    "base_score": 0.96,
    "event_volume": 1_000_000,
    "invalid_event_count": 420,
    "schema_validation_failure_rate": 0.004,
    "missing_required_field_count": 130,
    "unknown_field_count": 58,
    "duplicate_event_count": 210,
    "late_arriving_event_count": 95,
    "out_of_order_event_count": 33,
    "sdk_version_distribution": {"web@8.9.0": 0.71, "ios@8.8.0": 0.18, "android@8.8.0": 0.11},
}

SCHEMA_STABILITY_BASELINE: dict[str, Any] = {
    "base_score": 0.97,
    "detected_changes": [],  # list of {change_type, field, detail}
    "change_type_counts": {
        "field_removed": 0,
        "field_added": 1,
        "field_type_changed": 0,
        "enum_value_changed": 0,
        "required_field_missing": 0,
        "timestamp_format_changed": 0,
        "identity_key_changed": 0,
        "payload_shape_changed": 0,
    },
    "tracked_schemas": 24,
}

IDENTITY_RESOLUTION_BASELINE: dict[str, Any] = {
    "base_score": 0.93,
    "merge_rate": 0.061,
    "split_rate": 0.012,
    "unresolved_entity_rate": 0.038,
    "duplicate_entity_rate": 0.021,
    "identity_confidence_distribution": {"high": 0.78, "medium": 0.17, "low": 0.05},
    "wallet_conflicts": 14,
    "email_conflicts": 22,
    "device_conflicts": 9,
    "account_conflicts": 6,
    "identity_graph_churn": 0.047,
    "manual_correction_rate": 0.008,
}

GRAPH_QUALITY_BASELINE: dict[str, Any] = {
    "base_score": 0.94,
    "vertex_creation_rate": 5200.0,
    "edge_creation_rate": 14300.0,
    "edge_deletion_rate": 410.0,
    "edge_type_distribution": {"interacted_with": 0.42, "owns": 0.21, "located_in": 0.19, "transacted": 0.18},
    "orphaned_vertices": 73,
    "dangling_edges": 12,
    "unexpected_relationship_spikes": 0,
    "missing_expected_edges": 41,
    "graph_density_drift": 0.018,
    "degree_distribution_drift": 0.024,
    "cluster_community_drift": 0.031,
}

PROFILE_QUALITY_BASELINE: dict[str, Any] = {
    "base_score": 0.92,
    "profile_freshness_seconds": 240.0,
    "missing_profile_field_rate": 0.052,
    "stale_computed_attribute_rate": 0.061,
    "source_coverage": 0.88,
    "relationship_coverage": 0.81,
    "profile_confidence": 0.9,
    "profile_update_latency_ms": 320.0,
    "contradiction_count": 7,
}

RECOMMENDATION_QUALITY_BASELINE: dict[str, Any] = {
    "base_score": 0.9,
    "generated": 4200,
    "viewed": 3100,
    "approved": 1850,
    "rejected": 410,
    "acted": 1620,
    "outcomes": 1380,
    "success_rate": 0.71,
    "failure_rate": 0.14,
    "neutral_rate": 0.15,
    "suppression_rate": 0.09,
    "average_confidence_delta": 0.04,
    "evidence_quality_score": 0.86,
    "freshness_penalty_average": 0.03,
    "governance_penalty_average": 0.02,
    "low_confidence_recommendation_rate": 0.11,
}

OUTCOME_FEEDBACK_BASELINE: dict[str, Any] = {
    "base_score": 0.91,
    "outcome_volume": 1380,
    "missing_outcome_value_count": 24,
    "average_outcome_delay_seconds": 5400.0,
    "outcome_label_distribution": {"success": 0.71, "failure": 0.14, "neutral": 0.15},
    "duplicate_outcome_count": 11,
    "value_outlier_count": 8,
    "confidence_delta_anomaly_count": 5,
    "outcome_recommendation_mismatch_attempts": 0,
}

PLAYBOOK_QUALITY_BASELINE: dict[str, Any] = {
    "base_score": 0.9,
    "trigger_rate": 0.34,
    "run_count": 640,
    "success_rate": 0.77,
    "stale_run_rate": 0.05,
    "incomplete_run_rate": 0.06,
    "observed_value_trend": 0.08,
    "average_confidence_delta": 0.03,
    "manual_override_rate": 0.04,
    "manual_rejection_rate": 0.03,
}

CONTAMINATION_BASELINE: dict[str, Any] = {
    "base_score": 0.99,
    "records_missing_tenant_id": 0,
    "tenant_id_mismatches": 0,
    "cross_tenant_identifiers": 0,
    "cross_tenant_graph_edges": 0,
    "shared_integration_config_leakage": 0,
    "audit_export_scope_mismatch": 0,
    "billing_scope_mismatch": 0,
}

# Maps the score field on IntelligenceQualityScore → (baseline, route key).
DIMENSION_BASELINES: dict[str, dict[str, Any]] = {
    "event_quality_score": EVENT_QUALITY_BASELINE,
    "schema_stability_score": SCHEMA_STABILITY_BASELINE,
    "identity_resolution_score": IDENTITY_RESOLUTION_BASELINE,
    "graph_quality_score": GRAPH_QUALITY_BASELINE,
    "profile_quality_score": PROFILE_QUALITY_BASELINE,
    "recommendation_quality_score": RECOMMENDATION_QUALITY_BASELINE,
    "outcome_feedback_quality_score": OUTCOME_FEEDBACK_BASELINE,
    "playbook_quality_score": PLAYBOOK_QUALITY_BASELINE,
}


# ─────────────────────────────────────────────────────────────────────────────
# Seed drift events — representative, non-escalating (historical signals). The
# contamination → audit escalation path is exercised at create()/detect() time,
# never on reseed, so it is not duplicated.
# ─────────────────────────────────────────────────────────────────────────────

SEED_DRIFT_EVENTS: list[dict[str, Any]] = [
    {
        "drift_event_id": "drift_seed_schema_web",
        "tenant_id": None,
        "drift_type": "schema_drift",
        "severity": "low",
        "source": "schema_drift_detector",
        "affected_resource_type": "event_schema",
        "affected_resource_id": "web@8.9.0",
        "reason": "Additive field 'utm_term' detected on web events (backward compatible).",
        "supporting_metrics": {"change_type": "field_added", "field": "utm_term"},
        "recommended_action": "No action required; additive change is backward compatible.",
        "status": "acknowledged",
    },
    {
        "drift_event_id": "drift_seed_reco_quality",
        "tenant_id": None,
        "drift_type": "recommendation_quality_drift",
        "severity": "medium",
        "source": "recommendation_quality_monitor",
        "affected_recommendation_family": "retention_play",
        "confidence_impact": -0.06,
        "reason": "Low-confidence recommendation rate rose above the watch threshold.",
        "supporting_metrics": {"low_confidence_recommendation_rate": 0.18, "threshold": 0.15},
        "recommended_action": "Review evidence quality and freshness penalties for the family.",
        "status": "open",
    },
    {
        "drift_event_id": "drift_seed_outcome_delay",
        "tenant_id": None,
        "drift_type": "outcome_feedback_drift",
        "severity": "low",
        "source": "outcome_feedback_monitor",
        "reason": "Average outcome delay increased modestly week over week.",
        "supporting_metrics": {"average_outcome_delay_seconds": 7200, "baseline": 5400},
        "recommended_action": "Monitor outcome capture latency; no escalation needed yet.",
        "status": "open",
    },
]


# Illustrative tenant set for the Kyber aggregate "tenants" view in local/mock
# mode. Routes may override via a ?tenant_ids= query param in deployment.
SAMPLE_TENANT_IDS: list[str] = ["tenant_alpha", "tenant_beta", "tenant_gamma"]


# ─────────────────────────────────────────────────────────────────────────────
# Deterministic per-tenant jitter so different tenants render distinct (but
# stable) scores in local/mock mode without random noise.
# ─────────────────────────────────────────────────────────────────────────────

def tenant_jitter(tenant_id: str | None, salt: str) -> float:
    """Return a stable value in [-0.05, 0.0] derived from tenant_id + salt."""
    if not tenant_id:
        return 0.0
    digest = hashlib.sha256(f"{tenant_id}:{salt}".encode("utf-8")).hexdigest()
    # 0..255 → 0.0..0.05 reduction
    return -(int(digest[:2], 16) / 255.0) * 0.05
