"""Offline evaluation of identity match scores against adjudicated pair outcomes.

The runtime score is ordinal evidence strength, not a probability. This module
reports adjudicated error counts and empirical same-identity rates by score
band. It does not fit a probability mapping, change resolver thresholds, or
enable production calibration.
"""

from __future__ import annotations

from datetime import datetime
import json
import math
import re
from pathlib import Path
from typing import Any

VALID_ACTIONS = frozenset({"merge", "no_merge", "review"})


def _validate_row(row: Any, *, line_number: int | None = None) -> dict[str, Any]:
    prefix = f"line {line_number}: " if line_number is not None else ""
    if not isinstance(row, dict):
        raise ValueError(f"{prefix}expected a JSON object")
    decision_id = row.get("decision_id")
    if not isinstance(decision_id, str) or not decision_id.strip():
        raise ValueError(f"{prefix}decision_id is required")
    if row.get("label_source") != "human_review":
        raise ValueError(f"{prefix}label_source must be 'human_review'")
    score = row.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ValueError(f"{prefix}score must be numeric")
    if not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError(f"{prefix}score must be finite and within [0, 1]")
    label = row.get("same_identity")
    if type(label) is not bool:
        raise ValueError(f"{prefix}same_identity must be a boolean")
    action = row.get("runtime_action")
    if action not in VALID_ACTIONS:
        raise ValueError(f"{prefix}runtime_action must be one of {sorted(VALID_ACTIONS)}")
    source_family = row.get("source_family")
    if not isinstance(source_family, str) or not source_family.strip() or len(source_family) > 64:
        raise ValueError(f"{prefix}source_family must be a non-empty source-family label")
    tenant_ref = row.get("tenant_ref")
    if not isinstance(tenant_ref, str) or not re.fullmatch(r"tenant:[A-Za-z0-9_-]{8,128}", tenant_ref):
        raise ValueError(f"{prefix}tenant_ref must be an opaque tenant: reference")
    adjudicator_ref = row.get("adjudicator_ref")
    if not isinstance(adjudicator_ref, str) or not re.fullmatch(r"reviewer:[A-Za-z0-9_-]{8,128}", adjudicator_ref):
        raise ValueError(f"{prefix}adjudicator_ref must be a pseudonymous reviewer: reference")
    adjudicated_at = row.get("adjudicated_at")
    if not isinstance(adjudicated_at, str):
        raise ValueError(f"{prefix}adjudicated_at must be an ISO timestamp")
    try:
        parsed_adjudicated_at = datetime.fromisoformat(adjudicated_at.replace("Z", "+00:00"))
    except ValueError:
        parsed_adjudicated_at = None
    if parsed_adjudicated_at is None or parsed_adjudicated_at.tzinfo is None:
        raise ValueError(f"{prefix}adjudicated_at must be a timezone-aware ISO timestamp")
    if row.get("independent_review") is not True:
        raise ValueError(f"{prefix}independent_review must be true")
    return {
        "decision_id": decision_id,
        "score": float(score),
        "same_identity": label,
        "runtime_action": action,
        "label_source": "human_review",
        "source_family": source_family,
        "tenant_ref": tenant_ref,
        "adjudicator_ref": adjudicator_ref,
        "adjudicated_at": adjudicated_at,
        "independent_review": True,
    }


def load_reviewed_pairs(path: str | Path) -> list[dict[str, Any]]:
    """Load reviewed pair decisions from JSONL and reject malformed/duplicate rows."""
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                raw_row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {line_number}: invalid JSON: {exc.msg}") from exc
            row = _validate_row(raw_row, line_number=line_number)
            if row["decision_id"] in seen_ids:
                raise ValueError(f"line {line_number}: duplicate decision_id {row['decision_id']!r}")
            seen_ids.add(row["decision_id"])
            rows.append(row)
    return rows


def _wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% Wilson interval for an observed binary outcome rate."""
    if total == 0:
        return None
    rate = successes / total
    z2 = z * z
    denominator = 1 + z2 / total
    center = (rate + z2 / (2 * total)) / denominator
    margin = z * math.sqrt(rate * (1 - rate) / total + z2 / (4 * total * total)) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def evaluate_calibration(
    rows: list[dict[str, Any]],
    *,
    bins: int = 10,
    minimum_labels: int = 500,
    minimum_per_band: int = 30,
    minimum_each_class_per_band: int = 10,
    maximum_interval_half_width: float = 0.15,
    minimum_tenants: int = 3,
    minimum_source_families: int = 2,
) -> dict[str, Any]:
    """Report decision errors and empirical rates, with explicit evidence gates.

    ``score`` is retained as an ordinal match-strength value. Its distance from
    an empirical rate is labeled a descriptive gap only, never probability
    calibration error. The gates here only indicate whether the evaluation set
    has enough evidence for a separate policy review; they cannot switch a
    runtime calibrated flag or authorize threshold tuning.
    """
    if bins < 2:
        raise ValueError("bins must be at least 2")
    if minimum_labels < 1 or minimum_per_band < 1 or minimum_each_class_per_band < 1:
        raise ValueError("label and band sample thresholds must be positive")
    if minimum_tenants < 1 or minimum_source_families < 1:
        raise ValueError("tenant and source coverage thresholds must be positive")
    if not 0 < maximum_interval_half_width < 0.5:
        raise ValueError("maximum_interval_half_width must be between 0 and 0.5")
    if not rows:
        raise ValueError("at least one human-reviewed pair is required")

    validated: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw_row in rows:
        row = _validate_row(raw_row)
        if row["decision_id"] in seen_ids:
            raise ValueError(f"duplicate decision_id {row['decision_id']!r}")
        seen_ids.add(row["decision_id"])
        validated.append(row)

    false_merges = [r for r in validated if r["runtime_action"] == "merge" and not r["same_identity"]]
    false_non_merges = [r for r in validated if r["runtime_action"] == "no_merge" and r["same_identity"]]
    merge_actions = [r for r in validated if r["runtime_action"] == "merge"]
    actual_matches = [r for r in validated if r["same_identity"]]
    no_merge_actions = [r for r in validated if r["runtime_action"] == "no_merge"]

    reliability_bands: list[dict[str, Any]] = []
    bands_with_adequate_support = 0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        members = [
            row for row in validated
            if lower <= row["score"] < upper or (index == bins - 1 and row["score"] == 1.0)
        ]
        positives = sum(row["same_identity"] for row in members)
        negatives = len(members) - positives
        interval = _wilson_interval(positives, len(members))
        half_width = (interval[1] - interval[0]) / 2 if interval else None
        supported = (
            len(members) >= minimum_per_band
            and positives >= minimum_each_class_per_band
            and negatives >= minimum_each_class_per_band
            and half_width is not None
            and half_width <= maximum_interval_half_width
        )
        bands_with_adequate_support += int(supported)
        empirical_rate = positives / len(members) if members else None
        mean_score = sum(row["score"] for row in members) / len(members) if members else None
        reliability_bands.append({
            "lower_bound": lower,
            "upper_bound": upper,
            "label_count": len(members),
            "same_identity_count": positives,
            "different_identity_count": negatives,
            "mean_match_score": mean_score,
            "observed_same_identity_rate": empirical_rate,
            "observed_rate_95pct_wilson_interval": list(interval) if interval else None,
            "descriptive_score_to_rate_gap": (
                abs(mean_score - empirical_rate)
                if mean_score is not None and empirical_rate is not None
                else None
            ),
            "adequate_support": supported,
        })

    enough_total = len(validated) >= minimum_labels
    all_bands_supported = bands_with_adequate_support == bins
    tenant_coverage = sorted({row["tenant_ref"] for row in validated})
    source_coverage = sorted({row["source_family"] for row in validated})
    reviewer_coverage = sorted({row["adjudicator_ref"] for row in validated})
    provenance_sufficient = (
        len(tenant_coverage) >= minimum_tenants
        and len(source_coverage) >= minimum_source_families
        and all(row["independent_review"] for row in validated)
    )
    evaluation_status = (
        "insufficient_labels" if not enough_total
        else "insufficient_provenance" if not provenance_sufficient
        else "insufficient_band_support" if not all_bands_supported
        else "evaluation_evidence_sufficient_for_policy_review"
    )
    false_merge_interval = _wilson_interval(len(false_merges), len(merge_actions))
    false_non_merge_interval = _wilson_interval(len(false_non_merges), len(actual_matches))

    return {
        "schema_version": "identity-confidence-calibration-evaluation.v2",
        "score_kind": "identity_match_score",
        "score_semantics": "ordinal_evidence_strength_not_probability",
        "production_calibrated": False,
        "runtime_policy_changed": False,
        "resolver_thresholds_changed": False,
        "status": evaluation_status,
        "evidence_sufficient_for_policy_review": enough_total and provenance_sufficient and all_bands_supported,
        "provenance_sufficient_for_policy_review": provenance_sufficient,
        "label_count": len(validated),
        "positive_label_count": len(actual_matches),
        "negative_label_count": len(validated) - len(actual_matches),
        "thresholds": {
            "minimum_total_labels": minimum_labels,
            "minimum_labels_per_score_band": minimum_per_band,
            "minimum_positive_and_negative_labels_per_band": minimum_each_class_per_band,
            "maximum_95pct_interval_half_width_per_band": maximum_interval_half_width,
            "required_supported_bands": bins,
            "minimum_tenant_coverage": minimum_tenants,
            "minimum_source_family_coverage": minimum_source_families,
        },
        "sample_coverage": {
            "tenant_refs": tenant_coverage,
            "source_families": source_coverage,
            "reviewer_refs": reviewer_coverage,
            "independent_review_count": sum(row["independent_review"] for row in validated),
        },
        "decision_errors": {
            "false_merge_count": len(false_merges),
            "merge_action_count": len(merge_actions),
            "false_merge_rate_among_merge_actions": len(false_merges) / len(merge_actions) if merge_actions else None,
            "false_merge_rate_95pct_wilson_interval": list(false_merge_interval) if false_merge_interval else None,
            "false_non_merge_count": len(false_non_merges),
            "known_same_identity_count": len(actual_matches),
            "false_non_merge_rate_among_known_matches": len(false_non_merges) / len(actual_matches) if actual_matches else None,
            "false_non_merge_rate_95pct_wilson_interval": list(false_non_merge_interval) if false_non_merge_interval else None,
            "explicit_no_merge_action_count": len(no_merge_actions),
            "review_action_count": sum(row["runtime_action"] == "review" for row in validated),
        },
        "reliability_by_score_band": reliability_bands,
        "interpretation": (
            "Observed same-identity rates describe this reviewed sample only. "
            "Match scores are not probabilities; descriptive score-to-rate gaps "
            "are not calibration errors and must not be used to tune runtime policy."
        ),
        "promotion_requirements": [
            "labels are independently adjudicated and cover the intended tenant, source, and time mix",
            "all score bands meet the configured sample, class-balance, and interval-width gates",
            "a tenant/source/time-stratified holdout meets an explicitly approved false-merge and false-non-merge budget",
            "a separately reviewed policy change explicitly enables calibration; this report never does so",
        ],
    }
