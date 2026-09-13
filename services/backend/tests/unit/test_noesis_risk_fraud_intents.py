"""Noesis Risk360/Fraud360 read-only intents (Phase 6B).

Covers the three new read-only intents — ``risk_assessment_explain``,
``fraud_hypothesis_summarize``, and ``risk_fraud_contradiction_lookup`` —
end to end: classifier mapping, read-only allowlisting, the risk_fraud
adapter over seeded Risk360/Fraud360 store rows, the disabled-plane
``service_disabled`` path, and honest absent-data envelopes. Noesis must never
mutate risk or fraud truth, so every assertion below is against stored reads.

Under test the Risk360/Fraud360 stores run on the in-memory BaseRepository
backend (``AETHER_ENV=local``), shared per table and reset per test.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]  # .../aether-backend
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from config.settings import RiskFraud360Config, settings as app_settings  # noqa: E402
from repositories.repos import AnalyticsRepository, reset_in_memory_stores  # noqa: E402
from services.fraud360.contracts import FraudHypothesis, FraudHypothesisState  # noqa: E402
from services.fraud360.store import FraudHypothesisRepository  # noqa: E402
from services.noesis.adapters.risk_fraud_adapter import RiskFraudNoesisAdapter  # noqa: E402
from services.noesis.models import (  # noqa: E402
    SUPPORTED_INTENTS,
    NoesisQueryRequest,
    QueryPlan,
)
from services.noesis.service import NoesisService, Scope  # noqa: E402
from services.operational_intelligence.models import EvidenceRef  # noqa: E402
from services.risk360.contracts import (  # noqa: E402
    ExposureAssessment,
    RiskAssessment,
    RiskComponent,
    RiskVector,
)
from services.risk360.store import RiskAssessmentRepository  # noqa: E402
from shared.auth.auth import Role, TenantContext  # noqa: E402
from shared.cache.cache import CacheClient  # noqa: E402
from shared.common.common import BadRequestError  # noqa: E402
from shared.contracts_models.epistemic import EpistemicStatus  # noqa: E402
from shared.graph.graph import GraphClient  # noqa: E402
from shared.measurement.value_states import ValueState  # noqa: E402

TENANT = "tenant-a"
NEW_INTENTS = frozenset({
    "risk_assessment_explain",
    "fraud_hypothesis_summarize",
    "risk_fraud_contradiction_lookup",
})


# ─── Fixtures / helpers ─────────────────────────────────────────────────


class _PermissiveFlags:
    noesis_enabled = True

    def is_tenant_allowed(self, tenant_id: str) -> bool:
        return True


@pytest.fixture(autouse=True)
def _reset_stores() -> None:
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


@pytest.fixture()
def tenant() -> TenantContext:
    return TenantContext(tenant_id=TENANT, role=Role.VIEWER, permissions=["read"])


@pytest.fixture()
def service() -> NoesisService:
    return NoesisService(
        graph=GraphClient(),
        analytics=AnalyticsRepository(CacheClient()),
        flags=_PermissiveFlags(),
    )


def _scope() -> Scope:
    return Scope(surface="aether", effective_tenant_id=TENANT, cross_tenant=False, debug_allowed=False)


def _request(message: str) -> NoesisQueryRequest:
    return NoesisQueryRequest(message=message, surface="aether")


def _component(dimension: str, state: ValueState, *, score: float | None = None) -> RiskComponent:
    claim = EpistemicStatus.OBSERVED if state is ValueState.OBSERVED else EpistemicStatus.DERIVED
    return RiskComponent(dimension=dimension, state=state, score=score, claim_state=claim)


def _assessment(
    assessment_id: str,
    *,
    subject_id: str = "ent_123",
    components: list[RiskComponent] | None = None,
    exposure: ExposureAssessment | None = None,
) -> RiskAssessment:
    components = components or [_component("economic", ValueState.OBSERVED, score=0.4)]
    return RiskAssessment(
        assessment_id=assessment_id,
        tenant_id=TENANT,
        subject_kind="entity",
        subject_id=subject_id,
        policy_id="policy_fraud_review",
        policy_version="3",
        dimensions=[c.dimension for c in components],
        vector=RiskVector(components=components),
        exposure=exposure,
        claim_state=EpistemicStatus.DERIVED,
        confidence=0.6,
        evidence_refs=[EvidenceRef(id=f"ev-{assessment_id}", type="transaction", source="risk360/test")],
    )


def _exposure() -> ExposureAssessment:
    return ExposureAssessment(
        tenant_id=TENANT,
        subject_kind="entity",
        subject_id="ent_123",
        exposed_asset_labels=["wallet"],
        claim_state=EpistemicStatus.DERIVED,
    )


async def _seed_assessment(assessment_id: str, **kwargs) -> None:
    assessment = _assessment(assessment_id, **kwargs)
    await RiskAssessmentRepository().upsert_scoped(
        TENANT, assessment_id, assessment.model_dump(mode="json")
    )


async def _seed_hypothesis(
    hypothesis_id: str,
    *,
    subject_id: str = "ent_123",
    state: FraudHypothesisState = FraudHypothesisState.MATERIAL,
    matched: list[str] | None = None,
    materiality: float | None = 0.6,
    contradictory_ids: list[str] | None = None,
    support_ids: list[str] | None = None,
) -> None:
    hypothesis = FraudHypothesis(
        hypothesis_id=hypothesis_id,
        tenant_id=TENANT,
        subject_kind="entity",
        subject_id=subject_id,
        state=state,
        claim_state=EpistemicStatus.DERIVED,
        confidence=0.7,
        matched_pattern_ids=matched or ["synthetic_identity"],
        materiality=materiality,
        evidence_refs=[
            EvidenceRef(id=i, type="transaction", source="fraud360/test")
            for i in (support_ids or ["ev_support"])
        ],
        contradictory_evidence_refs=[
            EvidenceRef(id=i, type="annotation", source="fraud360/test")
            for i in (contradictory_ids or [])
        ],
        risk_assessment_ids=["ra_linked"],
        network_ids=["net_1"],
        flow_trace_ids=["ft_1"],
        decision_ids=["dec_1"],
    )
    await FraudHypothesisRepository().create(TENANT, hypothesis)


def _enabled(monkeypatch: pytest.MonkeyPatch, *, risk: bool = True, fraud: bool = True) -> None:
    monkeypatch.setattr(
        app_settings,
        "risk_fraud_360",
        RiskFraud360Config(risk360_enabled=risk, fraud360_enabled=fraud),
    )


# ─── Classification ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_classifier_maps_three_phrasings_to_new_intents(service: NoesisService) -> None:
    cases = {
        "explain the risk assessment for entity ent_123": "risk_assessment_explain",
        "summarize the fraud hypothesis on entity ent_123": "fraud_hypothesis_summarize",
        "are the risk and fraud views contradictory for entity ent_123": "risk_fraud_contradiction_lookup",
    }
    for message, expected in cases.items():
        plan = service._classify(_request(message), _scope())
        assert plan.intent == expected, f"{message!r} → {plan.intent!r}"
        assert plan.target == "ent_123"
        assert plan.tenant_id == TENANT


@pytest.mark.asyncio
async def test_classifier_new_intents_beat_generic_risk_cluster(service: NoesisService) -> None:
    # "risk"/"fraud" tokens also trigger risk_cluster_lookup (0.76); the
    # specific read-only intents must win at higher confidence.
    plan = service._classify(
        _request("summarize the fraud hypothesis on entity ent_123"), _scope()
    )
    assert plan.intent == "fraud_hypothesis_summarize"
    assert plan.confidence >= 0.7


# ─── Read-only allowlisting ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_new_intents_are_read_only_allowlisted(service: NoesisService) -> None:
    assert NEW_INTENTS <= SUPPORTED_INTENTS
    for intent in NEW_INTENTS:
        # _assert_read_only passes for every new intent (they are allowlisted).
        service._assert_read_only(
            QueryPlan(intent=intent, tenant_id=TENANT, target="ent_123")  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_write_like_filter_still_rejected(service: NoesisService) -> None:
    plan = QueryPlan(
        intent="risk_assessment_explain",  # type: ignore[arg-type]
        tenant_id=TENANT,
        filters={"query": "delete ent_123"},
    )
    with pytest.raises(BadRequestError):
        service._assert_read_only(plan)


@pytest.mark.asyncio
async def test_write_like_utterance_rejected_before_dispatch(
    service: NoesisService, tenant: TenantContext
) -> None:
    response = await service.query(_request("delete the risk assessment"), tenant)
    assert response.intent == "rejected"
    assert response.error is not None
    assert response.error.code == "safety_rejection"


@pytest.mark.asyncio
async def test_registry_entries_for_new_intents() -> None:
    from services.noesis.capability_registry import CAPABILITY_REGISTRY, get_capability

    registry_intents = {cap.intent for cap in CAPABILITY_REGISTRY}
    assert NEW_INTENTS <= registry_intents
    assert get_capability("risk_fraud_contradiction_lookup") is not None
    assert get_capability("risk_fraud_contradiction_lookup").requires_target is True
    assert get_capability("risk_fraud_contradiction_lookup").surfaces == ["aether", "kyber"]


# ─── Dispatch envelope ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_returns_answer_envelope_for_seeded_assessment(
    monkeypatch: pytest.MonkeyPatch, service: NoesisService
) -> None:
    _enabled(monkeypatch)
    await _seed_assessment("ra-1", subject_id="ent_123")

    plan = QueryPlan(
        intent="risk_assessment_explain",  # type: ignore[arg-type]
        target="ent_123",
        tenant_id=TENANT,
        limit=10,
    )
    response = await service._dispatch(plan, _scope(), _request("explain risk assessment"))

    assert response.intent == "risk_assessment_explain"
    assert response.answer
    assert response.evidence.sufficient is True
    assert any(r.get("assessment_id") == "ra-1" for r in response.results)


# ─── Adapter correctness ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_risk_assessment_explain_summarizes_scored_dimensions() -> None:
    await _seed_assessment(
        "ra-1",
        components=[
            _component("economic", ValueState.OBSERVED, score=0.4),
            _component("behavioral", ValueState.ESTIMATED, score=0.7),
        ],
        exposure=_exposure(),
    )

    envelope = await RiskFraudNoesisAdapter().risk_assessment_explain(TENANT, "ent_123")

    assert envelope["sufficient"] is True
    assert envelope["sources"] == ["risk_assessments"]
    result = envelope["results"][0]
    assert result["assessment_id"] == "ra-1"
    dims = {c["dimension"]: c for c in result["components"]}
    assert dims["economic"]["state"] == "observed"
    assert dims["behavioral"]["state"] == "estimated"
    assert envelope["answer"].find("policy reference policy_fraud_review") != -1
    assert "2/2 dimension(s) scored" in envelope["answer"]


@pytest.mark.asyncio
async def test_fraud_hypothesis_summarize_names_matched_pattern() -> None:
    await _seed_hypothesis(
        "hyp-1",
        matched=["synthetic_identity"],
        contradictory_ids=["ev_contra"],
    )

    envelope = await RiskFraudNoesisAdapter().fraud_hypothesis_summarize(TENANT, "ent_123")

    assert envelope["sufficient"] is True
    assert envelope["sources"] == ["fraud_hypotheses"]
    result = envelope["results"][0]
    assert result["hypothesis_id"] == "hyp-1"
    # Pattern display name is resolved from the declarative FRAUD_PATTERNS registry.
    assert result["matched_patterns"] == ["Synthetic identity"]
    assert result["families"] == ["synthetic identity"]
    assert result["state"] == "material"
    assert result["materiality"] == 0.6
    assert result["contradictory_evidence_ids"] == ["ev_contra"]
    assert result["cross_refs"]["networks"] == 1
    assert result["cross_refs"]["decisions"] == 1
    assert "Synthetic identity" in envelope["answer"]


@pytest.mark.asyncio
async def test_contradiction_surface_reports_genuine_gap() -> None:
    # Material fraud hypothesis, but the subject's stored assessment has NO
    # scored "fraud" dimension (only economic) → a genuine, honestly-named gap.
    await _seed_assessment(
        "ra-1", components=[_component("economic", ValueState.OBSERVED, score=0.4)]
    )
    await _seed_hypothesis("hyp-1", state=FraudHypothesisState.MATERIAL)

    envelope = await RiskFraudNoesisAdapter().contradiction_surface(TENANT, "ent_123")

    assert envelope["sufficient"] is True
    items = {item["kind"] for item in envelope["results"]}
    assert "unsupported_fraud_claim" in items
    assert "never" not in envelope["answer"].lower()  # nothing fabricated
    assert all(item["subject"] == "entity:ent_123" for item in envelope["results"])


@pytest.mark.asyncio
async def test_contradiction_surface_reports_recorded_contradiction() -> None:
    await _seed_assessment(
        "ra-1",
        components=[_component("fraud", ValueState.OBSERVED, score=0.65)],
    )
    await _seed_hypothesis(
        "hyp-1",
        state=FraudHypothesisState.MATERIAL,
        contradictory_ids=["ev_contra"],
        support_ids=["ev_support"],
    )

    envelope = await RiskFraudNoesisAdapter().contradiction_surface(TENANT, "ent_123")

    kinds = {item["kind"] for item in envelope["results"]}
    assert "recorded_contradiction" in kinds
    item = next(i for i in envelope["results"] if i["kind"] == "recorded_contradiction")
    assert item["contradictory_evidence_ids"] == ["ev_contra"]


@pytest.mark.asyncio
async def test_contradiction_surface_none_is_honest_no_contradiction() -> None:
    # Fraud dimension IS scored for the subject and the material hypothesis
    # records no contradictory evidence → no contradiction, sufficient True.
    await _seed_assessment(
        "ra-1", components=[_component("fraud", ValueState.OBSERVED, score=0.65)]
    )
    await _seed_hypothesis("hyp-1", state=FraudHypothesisState.MATERIAL)

    envelope = await RiskFraudNoesisAdapter().contradiction_surface(TENANT, "ent_123")

    assert envelope["sufficient"] is True
    assert envelope["results"] == []
    assert "No contradictions or gaps surfaced" in envelope["answer"]


@pytest.mark.asyncio
async def test_contradiction_surface_requires_target() -> None:
    envelope = await RiskFraudNoesisAdapter().contradiction_surface(TENANT, None)
    assert envelope["sufficient"] is False
    assert envelope["results"] == []


# ─── Honest absent-data envelopes ───────────────────────────────────────


@pytest.mark.asyncio
async def test_absent_data_returns_sufficient_false() -> None:
    risk = await RiskFraudNoesisAdapter().risk_assessment_explain(TENANT, "ent_unknown")
    assert risk["sufficient"] is False
    assert risk["results"] == []
    assert "No stored Risk360 assessment" in risk["answer"]

    fraud = await RiskFraudNoesisAdapter().fraud_hypothesis_summarize(TENANT, "ent_unknown")
    assert fraud["sufficient"] is False
    assert fraud["results"] == []
    assert "No stored Fraud360 hypotheses" in fraud["answer"]

    contra = await RiskFraudNoesisAdapter().contradiction_surface(TENANT, "ent_unknown")
    assert contra["sufficient"] is False
    assert contra["results"] == []


# ─── Disabled-plane gating ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_risk_intent_disabled_when_risk_flag_off(
    monkeypatch: pytest.MonkeyPatch, service: NoesisService
) -> None:
    _enabled(monkeypatch, risk=False, fraud=True)

    response = await service._dispatch(
        QueryPlan(intent="risk_assessment_explain", target="ent_123", tenant_id=TENANT),  # type: ignore[arg-type]
        _scope(),
        _request("explain the risk assessment"),
    )
    assert response.error is not None
    assert response.error.code == "service_disabled"
    assert "Risk360 Intelligence" in response.answer


@pytest.mark.asyncio
async def test_fraud_intent_disabled_when_fraud_flag_off(
    monkeypatch: pytest.MonkeyPatch, service: NoesisService
) -> None:
    _enabled(monkeypatch, risk=True, fraud=False)

    response = await service._dispatch(
        QueryPlan(intent="fraud_hypothesis_summarize", target="ent_123", tenant_id=TENANT),  # type: ignore[arg-type]
        _scope(),
        _request("summarize the fraud hypothesis"),
    )
    assert response.error is not None
    assert response.error.code == "service_disabled"


@pytest.mark.asyncio
async def test_contradiction_intent_disabled_when_either_flag_off(
    monkeypatch: pytest.MonkeyPatch, service: NoesisService
) -> None:
    # fraud OFF (even with risk ON) gates the contradiction intent, which reads both planes.
    _enabled(monkeypatch, risk=True, fraud=False)

    response = await service._dispatch(
        QueryPlan(intent="risk_fraud_contradiction_lookup", target="ent_123", tenant_id=TENANT),  # type: ignore[arg-type]
        _scope(),
        _request("are the risk and fraud views contradictory?"),
    )
    assert response.error is not None
    assert response.error.code == "service_disabled"


@pytest.mark.asyncio
async def test_disabled_flag_default_off_is_service_disabled(
    monkeypatch: pytest.MonkeyPatch, service: NoesisService
) -> None:
    # Explicitly default OFF (mirrors the env-default of AETHER_RISK360_ENABLED /
    # AETHER_FRAUD360_ENABLED) — deterministic regardless of ambient process env.
    _enabled(monkeypatch, risk=False, fraud=False)

    response = await service._dispatch(
        QueryPlan(intent="risk_assessment_explain", target="ent_123", tenant_id=TENANT),  # type: ignore[arg-type]
        _scope(),
        _request("explain the risk assessment"),
    )
    assert response.error is not None
    assert response.error.code == "service_disabled"
