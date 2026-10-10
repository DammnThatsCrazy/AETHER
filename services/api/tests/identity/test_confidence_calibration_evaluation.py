import json

import pytest

from identity.identity import confidence as confidence_module
from identity.identity.calibration_evaluation import evaluate_calibration, load_reviewed_pairs


def _row(decision_id: str, score: float, same: bool, action: str) -> dict:
    group = sum(ord(char) for char in decision_id) % 3
    return {
        "decision_id": decision_id,
        "score": score,
        "same_identity": same,
        "runtime_action": action,
        "label_source": "human_review",
        "source_family": "commerce" if group < 2 else "sdk",
        "tenant_ref": f"tenant:opaque-{group}",
        "adjudicator_ref": f"reviewer:opaque-{group}",
        "adjudicated_at": "2026-10-02T12:00:00Z",
        "independent_review": True,
    }


def test_evaluation_counts_false_merges_and_false_non_merges_and_stays_non_calibrated():
    # Adjudicated examples include both risky directions and a human-review action.
    rows = [
        _row("email-match-merged-correctly", 0.99, True, "merge"),
        _row("shared-device-merged-incorrectly", 0.91, False, "merge"),
        _row("same-user-rejected", 0.25, True, "no_merge"),
        _row("different-users-rejected", 0.12, False, "no_merge"),
        _row("ambiguous-in-review", 0.74, True, "review"),
    ]
    report = evaluate_calibration(rows, bins=2, minimum_labels=5)

    assert report["status"] == "insufficient_band_support"
    assert report["production_calibrated"] is False
    assert report["runtime_policy_changed"] is False
    assert report["resolver_thresholds_changed"] is False
    assert report["score_kind"] == "identity_match_score"
    assert report["score_semantics"] == "ordinal_evidence_strength_not_probability"
    assert report["decision_errors"]["false_merge_count"] == 1
    assert report["decision_errors"]["merge_action_count"] == 2
    assert report["decision_errors"]["false_merge_rate_among_merge_actions"] == pytest.approx(0.5)
    assert report["decision_errors"]["false_non_merge_count"] == 1
    assert report["decision_errors"]["known_same_identity_count"] == 3
    assert report["decision_errors"]["false_non_merge_rate_among_known_matches"] == pytest.approx(1 / 3)
    assert report["decision_errors"]["review_action_count"] == 1
    assert len(report["reliability_by_score_band"]) == 2
    high = report["reliability_by_score_band"][1]
    assert high["label_count"] == 3
    assert high["observed_same_identity_rate"] == pytest.approx(2 / 3)
    assert "probabilities" in report["interpretation"]
    assert "brier_score" not in report
    assert "log_loss" not in report


def test_evaluation_requires_total_and_per_band_sample_class_and_interval_thresholds():
    rows = []
    for index in range(20):
        rows.append(_row(f"low-{index}", 0.1 + (index % 2) * 0.1, index % 2 == 0, "review"))
        rows.append(_row(f"high-{index}", 0.8 + (index % 2) * 0.1, index % 2 == 0, "review"))
    report = evaluate_calibration(
        rows,
        bins=2,
        minimum_labels=40,
        minimum_per_band=20,
        minimum_each_class_per_band=10,
        maximum_interval_half_width=0.25,
        minimum_tenants=1,
    )

    assert report["status"] == "evaluation_evidence_sufficient_for_policy_review"
    assert report["evidence_sufficient_for_policy_review"] is True
    assert all(band["adequate_support"] for band in report["reliability_by_score_band"])
    assert all(band["observed_rate_95pct_wilson_interval"] for band in report["reliability_by_score_band"])
    assert report["production_calibrated"] is False
    assert report["resolver_thresholds_changed"] is False


def test_small_sample_and_missing_score_band_are_not_sufficient():
    rows = [_row("a", 0.9, True, "merge")]
    report = evaluate_calibration(rows, bins=2, minimum_labels=2)
    assert report["status"] == "insufficient_labels"
    assert report["production_calibrated"] is False

    rows = [
        _row("upper-pos", 0.9, True, "merge"),
        _row("upper-neg", 0.8, False, "merge"),
    ]
    report = evaluate_calibration(
        rows,
        bins=2,
        minimum_labels=2,
        minimum_per_band=1,
        minimum_each_class_per_band=1,
        maximum_interval_half_width=0.49,
        minimum_tenants=1,
        minimum_source_families=1,
    )
    assert report["status"] == "insufficient_band_support"
    assert report["evidence_sufficient_for_policy_review"] is False
    assert report["reliability_by_score_band"][0]["adequate_support"] is False


def test_evaluation_never_enables_the_runtime_calibrated_flag():
    assert confidence_module.CALIBRATED is False
    report = evaluate_calibration(
        [_row("review-1", 0.8, True, "merge"), _row("review-2", 0.2, False, "no_merge")],
        bins=2,
        minimum_labels=1,
        minimum_per_band=1,
        minimum_each_class_per_band=1,
        maximum_interval_half_width=0.49,
        minimum_tenants=1,
        minimum_source_families=1,
    )
    assert report["production_calibrated"] is False
    assert report["runtime_policy_changed"] is False
    assert report["resolver_thresholds_changed"] is False
    assert confidence_module.CALIBRATED is False


@pytest.mark.parametrize(
    "rows, message",
    [
        ([_row("dup", 0.2, False, "no_merge"), _row("dup", 0.8, True, "merge")], "duplicate decision_id"),
        ([{**_row("x", 0.3, True, "merge"), "label_source": "auto"}], "label_source"),
        ([{**_row("x", 0.3, True, "merge"), "same_identity": "true"}], "boolean"),
        ([{**_row("x", 1.1, True, "merge")}], r"within \[0, 1\]"),
        ([{**_row("x", 0.3, True, "merge"), "runtime_action": "maybe"}], "runtime_action"),
        ([{**_row("x", 0.3, True, "merge"), "independent_review": False}], "independent_review"),
        ([{**_row("x", 0.3, True, "merge"), "tenant_ref": "tenant-raw"}], "opaque tenant"),
    ],
)
def test_loader_rejects_ambiguous_or_invalid_labels(tmp_path, rows, message):
    path = tmp_path / "labels.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_reviewed_pairs(path)


def test_loader_rejects_malformed_json_and_evaluator_rejects_bad_thresholds(tmp_path):
    path = tmp_path / "labels.jsonl"
    path.write_text('{"decision_id":\n', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        load_reviewed_pairs(path)
    with pytest.raises(ValueError, match="half_width"):
        evaluate_calibration([_row("x", 0.5, True, "review")], maximum_interval_half_width=0.5)


def test_provenance_coverage_gates_policy_review_even_with_enough_labels():
    rows = [_row("a", 0.2, True, "review"), _row("b", 0.8, False, "review")]
    report = evaluate_calibration(
        rows,
        bins=2,
        minimum_labels=2,
        minimum_per_band=1,
        minimum_each_class_per_band=1,
        maximum_interval_half_width=0.49,
        minimum_tenants=3,
        minimum_source_families=1,
    )
    assert report["status"] == "insufficient_provenance"
    assert report["evidence_sufficient_for_policy_review"] is False
