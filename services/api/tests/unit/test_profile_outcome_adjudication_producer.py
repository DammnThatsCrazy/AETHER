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
    from identity.profile import prediction_authority
    monkeypatch.setattr(prediction_authority, "verify_prediction_policy_evidence", _allow_policy)

    async def capture(record, *args, **kwargs):
        captured.append(record)
        return record

    monkeypatch.setattr(truth_recorder, "persist_outcome_truth", capture)
    from identity.profile.prediction_authority import ProfilePredictionOutputRepository

    async def exact_prediction(self, tenant_id, prediction_id):
        return {
            "prediction_id": prediction_id, "idempotency_key": "key-1", "tenant_id": tenant_id,
            "entity_id": "user-1", "model_id": "churn_prediction", "artifact_version": "v1",
            "artifact_checksum_sha256": "a" * 64, "artifact_approval_state": "promoted",
            "feature_schema_hash": "schema-v1", "feature_digest": "b" * 16,
            "state_schema_version": "profile_future_state.v1", "policy_decision_id": "policy-1",
            "policy_version": "policy-v1", "actor_id": "actor-1",
            "generated_at": "2026-10-29T10:00:00Z", "valid_from": "2026-10-29T10:00:00Z",
            "valid_until": "2026-10-30T13:00:00Z",
            "states": [{"state": "churned", "probability": 0.7, "rank": 1}],
            "evidence_refs": [
                {"id": "churn_prediction@v1:" + "a" * 64, "type": "model_output", "source": "model_artifact_registry"},
                {"id": "policy-1", "type": "annotation", "source": "consent_policy_decisions"},
                {"id": "input-event", "type": "event", "source": "analytics_events"},
            ],
        }

    monkeypatch.setattr(ProfilePredictionOutputRepository, "get_prediction", exact_prediction)
    result = await truth_recorder.record_from_silver_outcome(
        tenant_id="tenant-a",
        row={
            "tenant_id": "tenant-a", "user_id": "user-1",
            "outcome_type": outcome_type,
            "source_event_type": outcome_type, "source_event_id": "event-1",
            "prediction_id": "prediction-1",
            "prediction_label_contract_version": label_contract,
            "occurred_at": "2026-10-29T12:00:00Z",
        },
        event_id="event-1",
        subject=EntityRef(kind="user", id="user-1"),
        policy_version=truth_recorder.PROFILE_OUTCOME_ADJUDICATION_POLICY_VERSION,
    )

    assert result is captured[0]
    assert result.claim_type == expected_claim
    assert result.prediction_id == "prediction-1"
    assert result.prediction_label_contract_version == label_contract
    assert result.evidence_refs[0].id == "event-1"


async def _allow_policy(_prediction):
    return True


@pytest.mark.asyncio
async def test_production_silver_worker_records_server_adjudicated_profile_outcome(monkeypatch):
    """Exercise Silver projection -> ingestion recorder -> durable truth recorder."""
    from ingestion.ingestion import workers
    from ingestion.silver.projectors.outcome_projector import OutcomeProjector
    from identity.profile.prediction_authority import ProfilePredictionOutputRepository

    captured = []
    monkeypatch.setattr(truth_recorder, "outcome_truth_store_enabled", lambda: True)
    from identity.profile import prediction_authority
    monkeypatch.setattr(prediction_authority, "verify_prediction_policy_evidence", _allow_policy)

    async def capture(record, *args, **kwargs):
        captured.append(record)
        return record

    async def exact_prediction(self, tenant_id, prediction_id):
        return {
            "prediction_id": prediction_id, "idempotency_key": "key-1", "tenant_id": tenant_id,
            "entity_id": "user-1", "model_id": "churn_prediction", "artifact_version": "v1",
            "artifact_checksum_sha256": "a" * 64, "artifact_approval_state": "promoted",
            "feature_schema_hash": "schema-v1", "feature_digest": "b" * 16,
            "state_schema_version": "profile_future_state.v1", "policy_decision_id": "policy-1",
            "policy_version": "consent-policy-v4", "actor_id": "actor-1",
            "generated_at": "2026-10-29T10:00:00Z", "valid_from": "2026-10-29T10:00:00Z",
            "valid_until": "2026-10-30T13:00:00Z",
            "states": [{"state": "churned", "probability": 0.7, "rank": 1}],
            "evidence_refs": [
                {"id": "churn_prediction@v1:" + "a" * 64, "type": "model_output", "source": "model_artifact_registry"},
                {"id": "policy-1", "type": "annotation", "source": "consent_policy_decisions"},
                {"id": "input-event", "type": "event", "source": "analytics_events"},
            ],
        }

    monkeypatch.setattr(truth_recorder, "persist_outcome_truth", capture)
    monkeypatch.setattr(ProfilePredictionOutputRepository, "get_prediction", exact_prediction)

    projected = OutcomeProjector().project({
        "type": "churn_observed",
        "messageId": "event-1",
        "userId": "user-1",
        "timestamp": "2026-10-29T12:00:00Z",
        "context": {"tenantId": "tenant-a"},
        "properties": {
            "predictionId": "prediction-1",
            "predictionLabelContractVersion": PROFILE_LABEL_CONTRACT,
            "adjudicationPolicyState": "allowed",  # untrusted input is not projected
        },
    })
    assert projected is not None
    await workers._record_outcome_truth(
        "tenant-a", {"event_id": "event-1"}, [projected],
    )

    assert len(captured) == 1
    assert captured[0].claim_type == "observed"
    assert captured[0].policy_version == truth_recorder.PROFILE_OUTCOME_ADJUDICATION_POLICY_VERSION
    assert captured[0].prediction_id == "prediction-1"


@pytest.mark.asyncio
async def test_caller_adjudication_assertion_cannot_override_server_policy(monkeypatch):
    captured = []
    monkeypatch.setattr(truth_recorder, "outcome_truth_store_enabled", lambda: True)

    async def capture(record, *args, **kwargs):
        captured.append(record)
        return record

    async def deny_policy(_prediction):
        return False

    from identity.profile import prediction_authority
    monkeypatch.setattr(prediction_authority, "verify_prediction_policy_evidence", deny_policy)
    monkeypatch.setattr(truth_recorder, "persist_outcome_truth", capture)
    from identity.profile.prediction_authority import ProfilePredictionOutputRepository

    async def exact_prediction(self, tenant_id, prediction_id):
        return {
            "prediction_id": prediction_id, "idempotency_key": "key-1", "tenant_id": tenant_id,
            "entity_id": "user-1", "model_id": "churn_prediction", "artifact_version": "v1",
            "artifact_checksum_sha256": "a" * 64, "artifact_approval_state": "promoted",
            "feature_schema_hash": "schema-v1", "feature_digest": "b" * 16,
            "state_schema_version": "profile_future_state.v1", "policy_decision_id": "policy-1",
            "policy_version": "consent-policy-v4", "actor_id": "actor-1",
            "generated_at": "2026-10-29T10:00:00Z", "valid_from": "2026-10-29T10:00:00Z",
            "valid_until": "2026-10-30T13:00:00Z",
            "states": [{"state": "churned", "probability": 0.7, "rank": 1}],
            "evidence_refs": [
                {"id": "churn_prediction@v1:" + "a" * 64, "type": "model_output", "source": "model_artifact_registry"},
                {"id": "policy-1", "type": "annotation", "source": "consent_policy_decisions"},
                {"id": "input-event", "type": "event", "source": "analytics_events"},
            ],
        }

    monkeypatch.setattr(ProfilePredictionOutputRepository, "get_prediction", exact_prediction)
    await truth_recorder.record_from_silver_outcome(
        tenant_id="tenant-a",
        row={
            "tenant_id": "tenant-a", "user_id": "user-1", "outcome_type": "churn_observed",
            "source_event_type": "churn_observed", "source_event_id": "event-1",
            "prediction_id": "prediction-1", "prediction_label_contract_version": PROFILE_LABEL_CONTRACT,
            "occurred_at": "2026-10-29T12:00:00Z", "adjudication_policy_state": "allowed",
        },
        event_id="event-1",
        subject=EntityRef(kind="user", id="user-1"),
        policy_version=truth_recorder.PROFILE_OUTCOME_ADJUDICATION_POLICY_VERSION,
    )

    assert len(captured) == 1
    assert captured[0].claim_type == "derived"
