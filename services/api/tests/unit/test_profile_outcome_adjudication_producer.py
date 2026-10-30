import pytest

from graph.operational_intelligence.models import EntityRef
from journeys.measurement.outcome import truth_recorder
from intelligence.model_governance.evaluations import PROFILE_LABEL_CONTRACT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome_type,label_contract,expected_claim",
    [
        ("churn_observed", PROFILE_LABEL_CONTRACT, "observed"),
        ("retention_observed", PROFILE_LABEL_CONTRACT, "observed"),
        ("churn_observed", "profile-outcome-labels.v1", "derived"),
        ("goal_achieved", PROFILE_LABEL_CONTRACT, "derived"),
    ],
)
async def test_silver_outcome_adjudication_contract_is_closed(
    monkeypatch, outcome_type, label_contract, expected_claim,
):
    captured = []
    monkeypatch.setattr(truth_recorder, "outcome_truth_store_enabled", lambda: True)

    async def capture(record, *args, **kwargs):
        captured.append(record)
        return record

    monkeypatch.setattr(truth_recorder, "persist_outcome_truth", capture)
    result = await truth_recorder.record_from_silver_outcome(
        tenant_id="tenant-a",
        row={
            "outcome_type": outcome_type,
            "prediction_id": "prediction-1",
            "prediction_label_contract_version": label_contract,
            "occurred_at": "2026-10-29T12:00:00Z",
        },
        event_id="event-1",
        subject=EntityRef(kind="user", id="user-1"),
    )

    assert result is captured[0]
    assert result.claim_type == expected_claim
    assert result.prediction_id == "prediction-1"
    assert result.prediction_label_contract_version == label_contract
    assert result.evidence_refs[0].id == "event-1"
