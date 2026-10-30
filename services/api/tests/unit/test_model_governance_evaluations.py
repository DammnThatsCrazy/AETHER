from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from intelligence.model_governance.evaluations import (
    ModelEvaluationRepository,
    PROFILE_LABEL_CONTRACT,
    evaluate_profile_artifact,
)


async def allow_policy(_output):
    return True


def promoted_artifact(model_id, version):
    return SimpleNamespace(
        model_id=model_id, artifact_version=version, checksum_sha256="a" * 64,
        promotion_state="promoted", disabled=False, synthetic_data=False,
        threshold_passed=True, production_allowed=True,
    )


class Predictions:
    async def list_for_artifact(self, tenant_id, model_id, artifact_version, start, end, *, limit):
        def output(prediction_id, row_tenant):
            return {
                "prediction_id": prediction_id, "idempotency_key": prediction_id,
                "tenant_id": row_tenant, "entity_id": "e-1", "model_id": model_id,
                "artifact_version": artifact_version, "artifact_checksum_sha256": "a" * 64,
                "artifact_approval_state": "promoted", "feature_schema_hash": "schema-v1",
                "feature_digest": "b" * 16, "state_schema_version": "profile_future_state.v1",
                "policy_decision_id": "policy-1", "policy_version": "policy-v1",
                "actor_id": "actor-1", "generated_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
                "valid_from": datetime(2026, 1, 2, tzinfo=timezone.utc),
                "valid_until": datetime(2026, 1, 10, tzinfo=timezone.utc),
                "states": [
                    {"state": "churned", "probability": 0.8, "rank": 1},
                    {"state": "active", "probability": 0.2, "rank": 2},
                ],
                "evidence_refs": [
                    {"id": "model-a@artifact-1:" + "a" * 64, "type": "model_output", "source": "model_artifact_registry"},
                    {"id": "policy-1", "type": "annotation", "source": "consent_policy_decisions"},
                    {"id": "event-1", "type": "event", "source": "analytics_events"},
                ],
            }
        return [
            output("p-1", tenant_id),
            # Foreign-tenant lookalike is rejected by exact row validation.
            output("p-foreign", "tenant-other"),
        ], False


class Outcomes:
    async def list_for_profile_adjudication(self, tenant_id, version, start, end):
        return [
            {"tenant_id": tenant_id, "prediction_id": "p-1",
             "prediction_label_contract_version": version, "user_id": "e-1",
             "source_event_id": "event-1", "source_event_type": "churn_observed", "fact_id": "fact-1",
             "occurred_at": "2026-01-03T00:00:00Z", "outcome_type": "churn_observed"},
            # Arbitrary legacy labels are not retroactively adjudicated.
            {"tenant_id": tenant_id, "prediction_id": "p-1",
             "prediction_label_contract_version": "profile-outcome-labels.v1",
             "user_id": "e-1", "source_event_id": "event-legacy",
             "source_event_type": "goal_achieved", "fact_id": "fact-legacy",
             "occurred_at": "2026-01-03T00:00:00Z", "outcome_type": "goal_achieved"},
        ]


class Evaluations:
    def __init__(self):
        self.rows = []

    async def insert(self, row):
        self.rows.append(row)
        return True


@pytest.mark.asyncio
async def test_profile_evaluation_uses_only_exact_contract_scoped_final_outcomes(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    persisted = ModelEvaluationRepository()
    result = await evaluate_profile_artifact(
        "tenant-a", "model-a", "artifact-1",
        window_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        window_end=datetime(2026, 2, 1, tzinfo=timezone.utc),
        split="evaluation", actor_id="admin-a", predictions=Predictions(),
        outcomes=Outcomes(), evaluations=persisted,
        policy_verifier=allow_policy,
        artifact_resolver=promoted_artifact,
    )

    assert result["state"] == "evaluated"
    assert result["sample_count"] == 1
    assert result["metrics"]["top_state_accuracy"] == 1.0
    assert result["metrics"]["expected_calibration_error"] == pytest.approx(0.2)
    assert result["split"] == "evaluation"
    assert result["method"].startswith(PROFILE_LABEL_CONTRACT)
    read_back = await persisted.latest_for_artifact(
        "tenant-a", "profile360", "model-a", "artifact-1", "a" * 64
    )
    assert read_back["evaluation_id"] == result["evaluation_id"]
    assert read_back["dataset_manifest_sha256"] == result["dataset_manifest_sha256"]
    assert read_back["metrics"]["expected_calibration_error"] == pytest.approx(0.2)
    detail = await persisted.get_evaluation("tenant-a", result["evaluation_id"])
    assert detail["sample_count"] == 1
    assert detail["sample_refs"][0]["outcomeFactId"] == "fact-1"
    assert await persisted.get_evaluation("tenant-other", result["evaluation_id"]) is None


@pytest.mark.asyncio
async def test_profile_evaluation_stays_unknown_without_adjudicated_evidence():
    class NoLabels(Outcomes):
        async def list_for_profile_adjudication(self, tenant_id, version, start, end):
            return []

    result = await evaluate_profile_artifact(
        "tenant-a", "model-a", "artifact-1",
        window_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        window_end=datetime(2026, 2, 1, tzinfo=timezone.utc),
        split="evaluation", actor_id="admin-a", predictions=Predictions(),
        outcomes=NoLabels(), evaluations=Evaluations(),
        policy_verifier=allow_policy,
        artifact_resolver=promoted_artifact,
    )
    assert result["state"] == "unknown"
    assert result["sample_count"] == 0
    assert result["metrics"] == {}
    assert result["reason"] == "no_exact_adjudicated_evaluation_samples"


@pytest.mark.asyncio
async def test_profile_evaluation_excludes_prediction_without_exact_allowed_policy_evidence():
    async def denied_policy(_output):
        return False

    result = await evaluate_profile_artifact(
        "tenant-a", "model-a", "artifact-1",
        window_start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        window_end=datetime(2026, 2, 1, tzinfo=timezone.utc),
        split="evaluation", actor_id="admin-a", predictions=Predictions(),
        outcomes=Outcomes(), evaluations=Evaluations(),
        policy_verifier=denied_policy, artifact_resolver=promoted_artifact,
    )
    assert result["state"] == "unknown"
    assert result["sample_count"] == 0
    assert result["metrics"] == {}
