"""Fail-closed authority and provider behavior for Profile360 predictions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from shared.intelligence_projections.contracts import ProjectionRequest, ProjectionSubject
from shared.intelligence_projections.registry import ProviderRegistry
from identity.profile.prediction_authority import (
    PredictionAuthorityEvidence,
    ProfilePredictionOutput,
    ProfilePredictionOutputRepository,
    ProfilePredictionWrite,
    record_eligible_profile_prediction,
)
from identity.profile.profile360_provider import (
    PredictionOutputRead,
    PredictionOutcomeRead,
    Profile360Provider,
    RepositoryProfile360Source,
)
from graph.operational_intelligence.models import EntityRef, EvidenceRef
from shared.backend_interpretation.primitives import OutcomeTruthRecord


TENANT = "tenant_profile_prediction"
ENTITY = "human-profile-1"
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _output(
    *,
    tenant_id: str = TENANT,
    entity_id: str = ENTITY,
    prediction_id: str = "ppout_test1",
    generated_at: datetime = NOW,
    valid_from: datetime = NOW - timedelta(minutes=1),
    valid_until: datetime = NOW + timedelta(hours=1),
) -> ProfilePredictionOutput:
    return ProfilePredictionOutput(
        prediction_id=prediction_id,
        idempotency_key=f"key-{prediction_id}",
        tenant_id=tenant_id,
        entity_id=entity_id,
        model_id="churn_prediction",
        artifact_version="v-production-2",
        artifact_checksum_sha256="a" * 64,
        artifact_approval_state="promoted",
        feature_schema_hash="schema-hash-v1",
        feature_digest="0123456789abcdef",
        state_schema_version="profile_future_state.v1",
        policy_decision_id="cpd-1",
        policy_version="consent-v2",
        actor_id="actor-1",
        generated_at=generated_at,
        valid_from=valid_from,
        valid_until=valid_until,
        states=[{"state": "at_risk", "probability": 0.73, "rank": 1}],
        evidence_refs=[
            PredictionAuthorityEvidence(
                id="event-1",
                type="event",
                source="analytics_events",
                observed_at=NOW - timedelta(minutes=2),
            ),
            PredictionAuthorityEvidence(
                id=f"churn_prediction@v-production-2:{'a' * 64}",
                type="model_output",
                source="model_artifact_registry",
            ),
            PredictionAuthorityEvidence(
                id="cpd-1",
                type="annotation",
                source="consent_policy_decisions",
            ),
        ],
    )


class _MemoryPredictionRepository(ProfilePredictionOutputRepository):
    async def _pool(self):
        return None


class _PredictionSource:
    def __init__(
        self,
        read: PredictionOutputRead,
        outcome_read: PredictionOutcomeRead | None = None,
    ) -> None:
        self.read = read
        self.outcome_read = outcome_read or PredictionOutcomeRead([], True, True)

    async def prediction_outputs(self, tenant_id, subject, *, as_of, limit):
        assert tenant_id == TENANT
        assert subject.kind == "entity" and subject.id == ENTITY
        assert as_of.tzinfo is not None
        assert 1 <= limit <= 100
        return self.read

    async def reported_outcomes_for_prediction(
        self, tenant_id, prediction_id, label_contract_version, *, limit
    ):
        assert tenant_id == TENANT
        assert prediction_id == "ppout_test1"
        assert label_contract_version == "profile-outcome-labels.v1"
        assert 1 <= limit <= 50
        return self.outcome_read


class _WriterRepository:
    def __init__(self) -> None:
        self.output = None

    async def record(self, output):
        self.output = output
        return True


@pytest.mark.asyncio
async def test_prediction_writer_skips_scores_without_explicit_future_state():
    result = await record_eligible_profile_prediction(
        tenant_id=TENANT,
        requested_subject_id=ENTITY,
        actor_id="actor-1",
        model_id="churn_prediction",
        feature_digest="0123456789abcdef",
        feature_schema_hash="schema-hash-v1",
        policy_decision_id="cpd-1",
        policy_version="consent-v2",
        policy_allowed=True,
        model_result={"churn_probability": 0.95, "artifact_version": "v-production-2"},
        artifact_resolver=lambda *_: SimpleNamespace(feature_schema_hash="schema-hash-v1"),
    )

    assert result == ProfilePredictionWrite(
        output=None,
        stored=False,
        reason="model_did_not_supply_likely_next_states",
    )


@pytest.mark.asyncio
async def test_prediction_writer_records_only_exact_policy_artifact_and_event_evidence(monkeypatch):
    import governance.policy.repositories
    import repositories.repos

    class _Entities:
        async def find_many(self, *, filters, limit):
            assert filters == {"tenant_id": TENANT, "entity_id": ENTITY}
            assert limit == 2
            return [{"tenant_id": TENANT, "entity_id": ENTITY, "entity_type": "human"}]

    class _Policy:
        async def find_by_id(self, decision_id):
            assert decision_id == "cpd-1"
            return {
                "policy_decision_id": "cpd-1",
                "tenant_id": TENANT,
                "actor_id": "actor-1",
                "subject_ref": ENTITY,
                "resource_type": "ml_model",
                "resource_id": "churn_prediction",
                "action": "serve_inference",
                "consent_policy_version": "consent-v2",
                "allowed": True,
                "created_at": NOW.isoformat(),
            }

    class _Analytics:
        def __init__(self, cache):
            assert cache == "cache"

        async def query_events(self, tenant_id, query, *, limit):
            assert tenant_id == TENANT
            assert query == {"canonical_entity_id": ENTITY}
            assert limit == 1001
            return [
                {
                    "tenant_id": TENANT,
                    "canonical_entity_id": ENTITY,
                    "event_id": "event-1",
                    "event_type": "observed_activity",
                    "occurred_at": (NOW - timedelta(minutes=2)).isoformat(),
                }
            ]

    monkeypatch.setattr(repositories.repos, "EntityRepository", lambda: _Entities())
    monkeypatch.setattr(
        governance.policy.repositories,
        "ConsentPolicyDecisionRepository",
        lambda: _Policy(),
    )
    monkeypatch.setattr(repositories.repos, "AnalyticsRepository", _Analytics)
    repository = _WriterRepository()

    result = await record_eligible_profile_prediction(
        tenant_id=TENANT,
        requested_subject_id=ENTITY,
        actor_id="actor-1",
        model_id="churn_prediction",
        feature_digest="0123456789abcdef",
        feature_schema_hash="schema-hash-v1",
        policy_decision_id="cpd-1",
        policy_version="consent-v2",
        policy_allowed=True,
        model_result={
            "artifact_version": "v-production-2",
            "artifact_checksum_sha256": "a" * 64,
            "state_schema_version": "profile_future_state.v1",
            "likely_next_states": [{"state": "at_risk", "probability": 0.73, "rank": 1}],
            "valid_from": (NOW - timedelta(minutes=1)).isoformat(),
            "valid_until": (NOW + timedelta(hours=1)).isoformat(),
            "evidence_refs": [
                {"type": "event", "source": "analytics_events", "id": "event-1"}
            ],
        },
        cache="cache",
        repository=repository,
        artifact_resolver=lambda model, version: SimpleNamespace(
            model_id=model,
            artifact_version=version,
            feature_schema_hash="schema-hash-v1",
            checksum_sha256="a" * 64,
            created_at=NOW.isoformat(),
        ),
    )

    assert result.stored is True
    assert result.output is repository.output
    assert result.output.entity_id == ENTITY
    assert result.output.policy_decision_id == "cpd-1"
    assert {ref.id for ref in result.output.evidence_refs} >= {
        "event-1",
        "cpd-1",
        "churn_prediction@v-production-2:" + "a" * 64,
    }

    mismatched_actor = await record_eligible_profile_prediction(
        tenant_id=TENANT,
        requested_subject_id=ENTITY,
        actor_id="different-actor",
        model_id="churn_prediction",
        feature_digest="0123456789abcdef",
        feature_schema_hash="schema-hash-v1",
        policy_decision_id="cpd-1",
        policy_version="consent-v2",
        policy_allowed=True,
        model_result={
            "artifact_version": "v-production-2",
            "artifact_checksum_sha256": "a" * 64,
            "state_schema_version": "profile_future_state.v1",
            "likely_next_states": [{"state": "at_risk", "probability": 0.73, "rank": 1}],
            "valid_from": (NOW - timedelta(minutes=1)).isoformat(),
            "valid_until": (NOW + timedelta(hours=1)).isoformat(),
            "evidence_refs": [
                {"type": "event", "source": "analytics_events", "id": "event-1"}
            ],
        },
        cache="cache",
        repository=repository,
        artifact_resolver=lambda model, version: SimpleNamespace(
            model_id=model,
            artifact_version=version,
            feature_schema_hash="schema-hash-v1",
            checksum_sha256="a" * 64,
            created_at=NOW.isoformat(),
        ),
    )
    assert mismatched_actor.stored is False
    assert mismatched_actor.reason == "prediction_policy_decision_scope_or_version_invalid"


@pytest.mark.asyncio
async def test_prediction_repository_bounds_exact_subject_and_validity_reads():
    repo = _MemoryPredictionRepository()
    await repo.record(_output())
    await repo.record(_output(prediction_id="ppout_other_tenant", tenant_id="other"))
    await repo.record(_output(prediction_id="ppout_other_entity", entity_id="other-entity"))
    await repo.record(
        _output(
            prediction_id="ppout_expired",
            generated_at=NOW - timedelta(minutes=90),
            valid_from=NOW - timedelta(hours=2),
            valid_until=NOW - timedelta(hours=1),
        )
    )

    rows, truncated = await repo.read_valid_for_subject(
        TENANT, ENTITY, as_of=NOW, limit=1000
    )

    assert [row["prediction_id"] for row in rows] == ["ppout_test1"]
    assert truncated is False


@pytest.mark.asyncio
async def test_profile360_likely_next_states_is_unknown_without_approved_rows():
    request = ProjectionRequest(
        projectionId="profile360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="entity", id=ENTITY),
        temporalMode="as_of",
        asOf=NOW.isoformat(),
        includeSections=["likely_next_states"],
    )
    provider = Profile360Provider(
        source=_PredictionSource(
            PredictionOutputRead([], available=True, scope_known=True)
        )
    )
    context = await ProviderRegistry().build_context("profile360", request)

    result = await provider.project(request, context)

    section = result.sections[0]
    assert section.id == "likely_next_states"
    assert section.state == "unknown"
    assert section.content["reasonCode"] == "no_fresh_approved_prediction_valid_at_anchor"
    assert not result.claims


@pytest.mark.asyncio
@pytest.mark.parametrize("scope_change", [
    {"tenant_id": "tenant-other"},
    {"entity_id": "entity-other"},
])
async def test_profile360_reader_rejects_prediction_outside_exact_subject_scope(
    monkeypatch, scope_change
):
    import identity.profile.prediction_authority as authority

    async def unexpected_policy_check(_output):
        pytest.fail("out-of-scope prediction must be rejected before governance reads")

    def unexpected_artifact_lookup(_model, _version):
        pytest.fail("out-of-scope prediction must be rejected before artifact lookup")

    monkeypatch.setattr(authority, "verify_prediction_policy_evidence", unexpected_policy_check)
    monkeypatch.setattr(authority, "approved_production_artifact", unexpected_artifact_lookup)
    raw = _output(**scope_change).model_dump(mode="python")
    request = ProjectionRequest(
        projectionId="profile360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="entity", id=ENTITY),
        temporalMode="as_of",
        asOf=NOW.isoformat(),
        includeSections=["likely_next_states"],
    )
    provider = Profile360Provider(
        source=_PredictionSource(
            PredictionOutputRead([raw], available=True, scope_known=True)
        )
    )
    context = await ProviderRegistry().build_context("profile360", request)

    result = await provider.project(request, context)

    section = result.sections[0]
    assert section.state == "degraded"
    assert section.content["items"] == []
    assert section.content["reasonCode"] == "profile_prediction_records_invalid"
    assert not result.claims


@pytest.mark.asyncio
@pytest.mark.parametrize("metric,expected", [
    (0.12, "reported"), (None, "unknown"), (True, "unknown"),
    (float("nan"), "unknown"), (1.2, "unknown"), (10**400, "unknown"),
])
async def test_profile360_projects_only_valid_prediction_with_predicted_epistemics(monkeypatch, metric, expected):
    import identity.profile.prediction_authority as authority

    async def allowed_policy(_output):
        return True

    monkeypatch.setattr(authority, "verify_prediction_policy_evidence", allowed_policy)

    monkeypatch.setattr(
        authority,
        "approved_production_artifact",
        lambda model, version: SimpleNamespace(
            model_id=model,
            artifact_version=version,
            checksum_sha256="a" * 64,
            promotion_state="promoted",
            disabled=False,
            synthetic_data=False,
            threshold_passed=True,
            production_allowed=True,
            metrics={"calibration_error": metric},
        ),
    )
    output = _output()
    request = ProjectionRequest(
        projectionId="profile360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="entity", id=ENTITY),
        temporalMode="as_of",
        asOf=NOW.isoformat(),
        includeSections=["likely_next_states"],
    )
    provider = Profile360Provider(
        source=_PredictionSource(
            PredictionOutputRead(
                [output.model_dump(mode="python")],
                available=True,
                scope_known=True,
            )
        )
    )
    context = await ProviderRegistry().build_context("profile360", request)

    result = await provider.project(request, context)

    section = result.sections[0]
    assert section.id == "likely_next_states"
    assert section.state == "available"
    assert section.content["items"][0]["states"][0]["state"] == "at_risk"
    governance = section.content["items"][0]["modelGovernance"]
    assert governance["calibrationMetric"]["state"] == expected
    assert governance["modelCalibrationVerified"] is False
    assert "observedOutcome" not in section.content["items"][0]
    if expected == "reported":
        assert governance["calibrationMetric"]["value"] == 0.12
        assert governance["calibrationMetric"]["datasetAndEvaluationScope"] == "unknown"
        assert governance["calibrationMetric"]["predictionApplicability"] == "unknown"
    assert result.claims[0].claimState.value == "predicted"
    assert result.claims[0].domainSlotIds == ["likely_next_states"]
    assert "these are predictions, not observed states" in result.claims[0].claims[0]


def _reported_outcome(
    *,
    tenant_id: str = TENANT,
    subject_id: str = ENTITY,
    subject_kind: str = "user",
    prediction_id: str = "ppout_test1",
    label_version: str = "profile-outcome-labels.v1",
    observed_at: datetime = NOW,
    outcome_id: str = "outcome-1",
) -> OutcomeTruthRecord:
    return OutcomeTruthRecord(
        outcome_id=outcome_id,
        tenant_id=tenant_id,
        definition_ref="goal_achieved",
        subject=EntityRef(kind=subject_kind, id=subject_id),
        state="final",
        achieved_at=observed_at.isoformat(),
        observed_at=observed_at.isoformat(),
        prediction_id=prediction_id,
        prediction_label_contract_version=label_version,
        evidence_refs=[EvidenceRef(id="event-outcome-1", type="event", source="silver_outcome_facts")],
    )


@pytest.mark.asyncio
async def test_profile360_reports_only_exact_versioned_outcome_association(monkeypatch):
    import identity.profile.prediction_authority as authority

    async def allowed_policy(_output):
        return True

    monkeypatch.setattr(authority, "verify_prediction_policy_evidence", allowed_policy)
    monkeypatch.setattr(
        authority,
        "approved_production_artifact",
        lambda model, version: SimpleNamespace(
            model_id=model, artifact_version=version, checksum_sha256="a" * 64,
            promotion_state="promoted", disabled=False, synthetic_data=False,
            threshold_passed=True, production_allowed=True, metrics={},
        ),
    )
    prediction = _output()
    exact = _reported_outcome()
    request = ProjectionRequest(
        projectionId="profile360", tenantId=TENANT,
        subject=ProjectionSubject(kind="entity", id=ENTITY),
        temporalMode="as_of", asOf=NOW.isoformat(),
        includeSections=["likely_next_states"],
    )
    provider = Profile360Provider(source=_PredictionSource(
        PredictionOutputRead([prediction.model_dump(mode="python")], True, True),
        PredictionOutcomeRead([exact], True, True),
    ))
    result = await provider.project(request, await ProviderRegistry().build_context("profile360", request))

    item = result.sections[0].content["items"][0]
    associations = item["reportedOutcomeAssociations"]
    assert [fact["outcomeId"] for fact in associations["facts"]] == ["outcome-1"], associations
    assert associations["facts"][0]["evidenceRefs"][0]["id"] == "event-outcome-1"
    assert associations["complete"] is True
    assert associations["reasonCode"] is None
    assert "correctness" in associations["interpretation"]
    assert item["epistemicStatus"] == "predicted"
    assert all("correct" not in " ".join(claim.claims).lower() for claim in result.claims)


@pytest.mark.asyncio
@pytest.mark.parametrize("read,expected_reason", [
    (PredictionOutcomeRead([_reported_outcome(observed_at=NOW + timedelta(seconds=1))], True, True), "profile_outcome_truth_records_invalid"),
    (PredictionOutcomeRead([_reported_outcome(label_version="profile-outcome-labels.v2")], True, True), "profile_outcome_truth_records_invalid"),
    (PredictionOutcomeRead([_reported_outcome(tenant_id="tenant-other")], True, True), "profile_outcome_truth_records_invalid"),
    (PredictionOutcomeRead([_reported_outcome(subject_kind="session")], True, True), "profile_outcome_truth_records_invalid"),
    (PredictionOutcomeRead([], True, True, invalid_records=True), "profile_outcome_truth_records_invalid"),
    (PredictionOutcomeRead([_reported_outcome(), _reported_outcome(outcome_id="outcome-duplicate")], True, True), "profile_outcome_truth_ambiguous"),
    (PredictionOutcomeRead([_reported_outcome()], True, True, truncated=True), "profile_outcome_truth_read_truncated"),
])
async def test_profile360_suppresses_future_ambiguous_or_truncated_outcomes(monkeypatch, read, expected_reason):
    import identity.profile.prediction_authority as authority

    async def allowed_policy(_output):
        return True

    monkeypatch.setattr(authority, "verify_prediction_policy_evidence", allowed_policy)
    monkeypatch.setattr(
        authority,
        "approved_production_artifact",
        lambda model, version: SimpleNamespace(
            model_id=model, artifact_version=version, checksum_sha256="a" * 64,
            promotion_state="promoted", disabled=False, synthetic_data=False,
            threshold_passed=True, production_allowed=True, metrics={},
        ),
    )
    request = ProjectionRequest(
        projectionId="profile360", tenantId=TENANT,
        subject=ProjectionSubject(kind="entity", id=ENTITY),
        temporalMode="as_of", asOf=NOW.isoformat(),
        includeSections=["likely_next_states"],
    )
    provider = Profile360Provider(source=_PredictionSource(
        PredictionOutputRead([_output().model_dump(mode="python")], True, True), read,
    ))
    result = await provider.project(request, await ProviderRegistry().build_context("profile360", request))

    associations = result.sections[0].content["items"][0]["reportedOutcomeAssociations"]
    assert associations["facts"] == []
    assert associations["complete"] is False
    assert associations["reasonCode"] == expected_reason


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "artifact",
    [
        None,
        RuntimeError("artifact policy unavailable"),
        SimpleNamespace(
            model_id="churn_prediction",
            artifact_version="v-production-2",
            checksum_sha256="b" * 64,
            promotion_state="promoted",
            disabled=False,
            synthetic_data=False,
            threshold_passed=True,
            production_allowed=True,
        ),
    ],
)
async def test_profile360_suppresses_predictions_without_current_exact_artifact(
    monkeypatch, artifact
):
    import identity.profile.prediction_authority as authority

    async def allowed_policy(_output):
        return True

    monkeypatch.setattr(authority, "verify_prediction_policy_evidence", allowed_policy)

    calls = []

    def resolve(model, version):
        calls.append((model, version))
        if isinstance(artifact, Exception):
            raise artifact
        return artifact

    monkeypatch.setattr(authority, "approved_production_artifact", resolve)
    request = ProjectionRequest(
        projectionId="profile360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="entity", id=ENTITY),
        temporalMode="as_of",
        asOf=NOW.isoformat(),
        includeSections=["likely_next_states"],
    )
    provider = Profile360Provider(
        source=_PredictionSource(
            PredictionOutputRead(
                [_output().model_dump(mode="python")],
                available=True,
                scope_known=True,
            )
        )
    )
    context = await ProviderRegistry().build_context("profile360", request)

    result = await provider.project(request, context)

    section = result.sections[0]
    assert calls == [("churn_prediction", "v-production-2")]
    assert section.state == "degraded"
    assert section.content["items"] == []
    assert section.content["reasonCode"] == "profile_prediction_records_invalid"
    assert not result.claims


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    {}, {"tenant_id": "other"}, {"subject_ref": "other"},
    {"resource_id": "other"}, {"allowed": False}, {"actor_id": "other"},
    {"created_at": (NOW + timedelta(seconds=1)).isoformat()},
])
async def test_prediction_policy_evidence_requires_exact_inference_decision(monkeypatch, mutation):
    import governance.policy.repositories as policy_repositories
    from identity.profile.prediction_authority import verify_prediction_policy_evidence

    decision = {
        "policy_decision_id": "cpd-1", "tenant_id": TENANT, "actor_id": "actor-1",
        "subject_ref": ENTITY, "resource_type": "ml_model", "resource_id": "churn_prediction",
        "action": "serve_inference", "consent_policy_version": "consent-v2", "allowed": True,
        "created_at": NOW.isoformat(), **mutation,
    }

    class Policies:
        async def find_by_id(self, decision_id):
            assert decision_id == "cpd-1"
            return decision

    monkeypatch.setattr(policy_repositories, "ConsentPolicyDecisionRepository", Policies)
    assert await verify_prediction_policy_evidence(_output()) is (not bool(mutation))


@pytest.mark.asyncio
async def test_prediction_reader_suppresses_missing_policy_evidence(monkeypatch):
    import identity.profile.prediction_authority as authority

    async def unavailable_policy(_output):
        return False

    monkeypatch.setattr(authority, "verify_prediction_policy_evidence", unavailable_policy)
    request = ProjectionRequest(
        projectionId="profile360", tenantId=TENANT,
        subject=ProjectionSubject(kind="entity", id=ENTITY), temporalMode="as_of",
        asOf=NOW.isoformat(), includeSections=["likely_next_states"],
    )
    provider = Profile360Provider(source=_PredictionSource(
        PredictionOutputRead([_output().model_dump(mode="python")], available=True, scope_known=True)
    ))
    context = await ProviderRegistry().build_context("profile360", request)
    result = await provider.project(request, context)
    assert result.sections[0].state == "degraded"
    assert result.sections[0].content["items"] == []
    assert not result.claims


@pytest.mark.asyncio
@pytest.mark.parametrize("binding", ["exact", "foreign", "ambiguous", "wrong_entity"])
async def test_session_prediction_policy_requires_exact_current_identity(monkeypatch, binding):
    import governance.policy.repositories as policy_repositories
    import identity.identity.repository as identity_repository
    from identity.profile.prediction_authority import verify_prediction_policy_evidence

    payload = _output().model_dump(mode="python")
    payload["model_id"] = "intent_prediction"
    payload["evidence_refs"][1]["id"] = f"intent_prediction@v-production-2:{'a' * 64}"
    payload["evidence_refs"].append({
        "id": "identity-1", "type": "entity", "source": "identity_source_identities"
    })
    output = ProfilePredictionOutput.model_validate(payload)
    decision = {
        "policy_decision_id": "cpd-1", "tenant_id": TENANT, "actor_id": "actor-1",
        "subject_ref": "session-1", "resource_type": "ml_model", "resource_id": "intent_prediction",
        "action": "serve_inference", "consent_policy_version": "consent-v2", "allowed": True,
        "created_at": NOW.isoformat(),
    }
    row = {"id": "identity-1", "tenant_id": TENANT, "session_id": "session-1",
           "status": "resolved", "canonical_entity_id": ENTITY}
    if binding == "foreign":
        row["tenant_id"] = "other"
    if binding == "wrong_entity":
        row["canonical_entity_id"] = "other"

    class Policies:
        async def find_by_id(self, _decision_id):
            return decision

    class Identities:
        async def find_many(self, *, filters, limit):
            assert filters == {"tenant_id": TENANT, "session_id": "session-1", "status": "resolved"}
            assert limit == 2
            return [row, row] if binding == "ambiguous" else [row]

    monkeypatch.setattr(policy_repositories, "ConsentPolicyDecisionRepository", Policies)
    monkeypatch.setattr(identity_repository, "IdentityResolutionRepository", lambda: SimpleNamespace(
        _source_identities=Identities()
    ))
    assert await verify_prediction_policy_evidence(output) is (binding == "exact")


@pytest.mark.asyncio
async def test_repository_profile_source_uses_exact_tenant_and_entity(monkeypatch):
    import identity.profile.prediction_authority

    class _Repository:
        async def read_valid_for_subject(self, tenant_id, entity_id, *, as_of, limit):
            assert tenant_id == TENANT
            assert entity_id == ENTITY
            assert as_of == NOW
            assert limit == 1
            return [], False

    monkeypatch.setattr(
        identity.profile.prediction_authority,
        "ProfilePredictionOutputRepository",
        lambda: _Repository(),
    )

    read = await RepositoryProfile360Source().prediction_outputs(
        TENANT,
        ProjectionSubject(kind="entity", id=ENTITY),
        as_of=NOW,
        limit=1,
    )

    assert read.available is True
    assert read.scope_known is True
    assert read.rows == []
