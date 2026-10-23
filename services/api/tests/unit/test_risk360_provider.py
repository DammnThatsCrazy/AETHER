"""Risk360 Phase-4 provider + read-only route tests.

The Risk360 provider is a read-only, fail-isolated, tenant-scoped projection
over canonical risk truth (ADR-010; Risk360/Fraud360 convergence program Phase
4). These tests cover:

* a valid ``ProjectionResult`` with the five typed sections, tenant-filtered,
  ``dependencyState`` echoed verbatim, and claims carrying reused canonical
  ``EvidenceRef``s;
* per-dimension honesty — a missing dimension is a typed non-value-bearing
  state (``missing_inputs`` / ``not_applicable``) and never a fabricated ``0``;
* an empty backing store degrades sections honestly (``missing`` / ``empty``),
  never raises, and still returns a valid result;
* a source reader that raises degrades its sections content-free (never a
  crash, never the exception text);
* ``dependencyState`` naming ``profile360`` / ``cluster360`` as missing degrades
  the affected section (never raises);
* tenant isolation — tenant A's assessment/evidence never surfaces in tenant B's
  projection;
* registration via ``register_provider`` (success, duplicate, version mismatch,
  unknown id) and no import-time side effect on the global plane registry;
* read-only posture — the provider exposes no mutation path.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[2]  # .../aether-backend

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from repositories.repos import _IN_MEMORY_STORES, reset_in_memory_stores  # noqa: E402
from graph.operational_intelligence.models import EvidenceRef as _OI_EvidenceRef  # noqa: E402
from intelligence.risk360 import router as _package_router  # noqa: E402  (re-export smoke)
from intelligence.risk360.contracts import (  # noqa: E402
    EntityRef,
    EpistemicStatus,
    EvidenceRef,
    ExposureAssessment,
    GraphSnapshotRef,
    MonetaryAmount,
    RiskAssessment,
    RiskComponent,
    RiskPoisoningEvidence,
    RiskPoisoningLifecycleEvent,
    RiskSignal,
    RiskVector,
    ValueState,
)
from intelligence.risk360.provider import (  # noqa: E402
    EXPLORE_CAPABILITY,
    OUTPUT_SECTIONS,
    PROJECTION_ID,
    READ_CAPABILITY,
    RepositoryRiskSourceReader,
    Risk360Provider,
    SECTION_DEPENDENCIES,
    build_projection_request,
    register_provider,
)
from intelligence.risk360.routes import SERVED_SUBJECT_KINDS, create_router  # noqa: E402
from services.social360.provider import (  # noqa: E402
    SocialGraphPathRead,
    SocialObservedPath,
)
from intelligence.risk360.store import (  # noqa: E402
    RiskAssessmentRepository,
    RiskPoisoningEvidenceRead,
    RiskPoisoningEvidenceRepository,
    RiskSignalRepository,
)
from shared.intelligence_projections import (  # noqa: E402
    ContractVersionIncompatible,
    DuplicateProjection,
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
    ProjectionContext,
    ProjectionNotFound,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSubject,
    ProviderRegistry,
)
from shared.intelligence_projections.generated_registry import (  # noqa: E402
    INTELLIGENCE_PROJECTION_DEFINITIONS,
    INTELLIGENCE_PROJECTION_IDS,
    PROJECTION_CAPABILITY_MAP,
    PROJECTION_SECTION_STATES,
)
from shared.intelligence_projections.registry import projection_registry  # noqa: E402

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"

VALID_SECTION_STATES = frozenset(PROJECTION_SECTION_STATES)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_stores() -> None:
    reset_in_memory_stores()


def _request(tenant: str = TENANT_A, **overrides: object) -> ProjectionRequest:
    values: dict[str, object] = {
        "projectionId": "risk360",
        "tenantId": tenant,
        "subject": ProjectionSubject(kind="entity", id="usr_1"),
    }
    values.update(overrides)
    return ProjectionRequest(**values)


async def _context(reg: ProviderRegistry, tenant: str = TENANT_A) -> ProjectionContext:
    """Build a runtime context for a risk360 request (registry truth)."""
    return await reg.build_context("risk360", _request(tenant=tenant))


def _evidence(ident: str) -> EvidenceRef:
    return EvidenceRef(
        id=ident,
        type="transaction",
        source="ledger",
        uri=f"store://ledger/{ident}",
    )


def _assessment(
    assessment_id: str = "a-1",
    tenant_id: str = TENANT_A,
    subject_id: str = "usr_1",
    *,
    assessed_at: datetime | None = None,
) -> RiskAssessment:
    """A rich assessment: one observed dimension + one not_applicable dimension."""
    return RiskAssessment(
        assessment_id=assessment_id,
        tenant_id=tenant_id,
        subject_kind="entity",
        subject_id=subject_id,
        subject_ref=EntityRef(kind="user", id=subject_id),
        policy_id="policy_payment_authorization",
        policy_version="3",
        dimensions=["economic", "payment"],
        vector=RiskVector(
            components=[
                RiskComponent(
                    dimension="economic",
                    state=ValueState.OBSERVED,
                    score=0.4,
                    claim_state=EpistemicStatus.OBSERVED,
                    confidence=0.8,
                    evidence_refs=[_evidence(f"ev-economic-{assessment_id}")],
                ),
                RiskComponent(
                    dimension="payment",
                    state=ValueState.NOT_APPLICABLE,
                    claim_state=EpistemicStatus.NOT_APPLICABLE,
                ),
            ]
        ),
        exposure=ExposureAssessment(
            tenant_id=tenant_id,
            subject_kind="entity",
            subject_id=subject_id,
            subject_ref=EntityRef(kind="user", id=subject_id),
            exposed_asset_labels=["wallet"],
            economic_value=MonetaryAmount(amount="120.00", currency="USD"),
        ),
        claim_state=EpistemicStatus.DERIVED,
        confidence=0.55,
        evidence_refs=[_evidence(f"ev-assessment-{assessment_id}")],
        snapshot=GraphSnapshotRef(graph_snapshot_id=f"gs-{assessment_id}"),
        run_id=f"run_{assessment_id}",
        assessed_at=assessed_at,
    )


def _empty_assessment(
    assessment_id: str = "a-empty",
    tenant_id: str = TENANT_A,
    subject_id: str = "usr_1",
) -> RiskAssessment:
    """An assessment that records zero dimensions — the honest-zero case."""
    return RiskAssessment(
        assessment_id=assessment_id,
        tenant_id=tenant_id,
        subject_kind="entity",
        subject_id=subject_id,
        vector=RiskVector(),
        assessed_at=datetime(2026, 9, 3, tzinfo=timezone.utc),
    )


def _signal(signal_id: str, tenant_id: str, *, subject_id: str = "usr_1") -> RiskSignal:
    return RiskSignal(
        signal_id=signal_id,
        tenant_id=tenant_id,
        subject_kind="entity",
        subject_id=subject_id,
        risk_dimension="payment",
        source="fraud.signals",
        detector_version="2.1.0",
        claim_state=EpistemicStatus.INFERRED,
        confidence=0.7,
        evidence_refs=[_evidence(f"ev-{signal_id}")],
        score=0.3,
        observed_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
    )


def _financial_risk_records(
    *, entity_id: str, index: int
) -> tuple[dict, dict]:
    """One exact economic RiskSignal and its policy-versioned assessment."""
    evidence = _evidence(f"financial-risk-evidence-{index}")
    observed_at = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    assessment = RiskAssessment(
        assessment_id=f"financial-assessment-{index}",
        tenant_id=TENANT_A,
        subject_kind="entity",
        subject_id=entity_id,
        policy_id="economic-risk-policy",
        policy_version="5",
        dimensions=["economic"],
        vector=RiskVector(
            components=[
                RiskComponent(
                    dimension="economic",
                    state=ValueState.OBSERVED,
                    score=0.42,
                    claim_state=EpistemicStatus.DERIVED,
                    confidence=0.8,
                    evidence_refs=[evidence],
                )
            ]
        ),
        claim_state=EpistemicStatus.DERIVED,
        evidence_refs=[evidence],
        assessed_at=datetime(2026, 10, 20, 12, 2, tzinfo=timezone.utc),
    )
    signal = RiskSignal(
        signal_id=f"financial-signal-{index}",
        tenant_id=TENANT_A,
        subject_kind="entity",
        subject_id=entity_id,
        risk_dimension="economic",
        claim_state=EpistemicStatus.INFERRED,
        confidence=0.7,
        evidence_refs=[evidence],
        source="economic.risk.detector",
        detector_version="3",
        observed_at=observed_at,
        score=0.35,
    )
    return assessment.model_dump(mode="json"), signal.model_dump(mode="json")


def _financial_flow_path(path_id: str = "path-financial-1") -> dict:
    """Fixture for two exact transfer-linked entities with trace timestamps."""
    transfer_id = "transfer-financial-1"
    transfer_at = "2026-10-20T12:01:00+00:00"
    return {
        "tenant_id": TENANT_A,
        "path_id": path_id,
        "trace_id": "trace-financial-1",
        "path_nodes": ["entity-financial-a", "entity-financial-b"],
        "hop_count": 1,
        "path_discovered_at": "2026-10-20T12:03:00+00:00",
        "trace_completed_at": "2026-10-20T12:04:00+00:00",
        "transfer_edges": [
            {
                "from_entity_id": "entity-financial-a",
                "to_entity_id": "entity-financial-b",
                "transfer_id": transfer_id,
                "asset_id": "asset-usd",
                "amount": "12.50",
                "occurred_at": transfer_at,
                "evidence_ref": {
                    "id": transfer_id,
                    "type": "transaction",
                    "source": "transfers",
                    "observedAt": transfer_at,
                    "uri": f"store://transfers/{transfer_id}",
                },
            }
        ],
        "linkage_reason": None,
    }


async def _seed(assessment: RiskAssessment | None, signals: list[RiskSignal] | None = None) -> None:
    assessment_repo = RiskAssessmentRepository()
    signal_repo = RiskSignalRepository()
    if assessment is not None:
        await assessment_repo.upsert_scoped(
            assessment.tenant_id,
            assessment.assessment_id,
            assessment.model_dump(mode="json"),
        )
    for signal in signals or []:
        await signal_repo.upsert_scoped(
            signal.tenant_id, signal.signal_id, signal.model_dump(mode="json")
        )


class _SiblingProvider:
    """A contract-compatible stub sibling so build_context marks it available."""

    def __init__(self, projection_id: str) -> None:
        self.projection_id = projection_id
        self.contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION

    async def project(self, request: object, context: object) -> object:
        raise NotImplementedError


def _available_registry() -> ProviderRegistry:
    """A registry whose risk360 siblings (profile360/cluster360/economic360) are
    all registered and available, so the provider's sections can lift."""
    reg = ProviderRegistry()
    for projection_id in ("profile360", "cluster360", "economic360"):
        reg.register(_SiblingProvider(projection_id))
    return reg


class _FakeReader:
    """Protocol-shaped test double returning dicts directly (deterministic)."""

    def __init__(
        self,
        assessment: dict | None = None,
        signals: list[dict] | None = None,
        *,
        assessments_by_subject: dict[tuple[str, str], dict] | None = None,
        signals_by_subject: dict[tuple[str, str], list[dict]] | None = None,
        raise_assessment: bool = False,
        raise_signals: bool = False,
        source_provenance: list[dict] | None = None,
        source_provenance_truncated: bool = False,
        raise_source_provenance: bool = False,
        poisoning_evidence: list[object] | None = None,
        poisoning_evidence_complete: bool = True,
        poisoning_evidence_reason: str | None = None,
        raise_poisoning_evidence: bool = False,
        financial_flow_path: dict | None = None,
        agent_policy_flags: list[dict] | None = None,
        raise_agent_policy_flags: bool = False,
        assessment_history_rows: list[dict] | None = None,
        assessment_history_complete: bool = True,
        raise_assessment_history: bool = False,
    ) -> None:
        self._assessment = assessment
        self._signals = list(signals or [])
        self._assessments_by_subject = assessments_by_subject
        self._signals_by_subject = signals_by_subject
        self._raise_assessment = raise_assessment
        self._raise_signals = raise_signals
        self._source_provenance = list(source_provenance or [])
        self._source_provenance_truncated = source_provenance_truncated
        self._raise_source_provenance = raise_source_provenance
        self.source_provenance_calls = 0
        self._poisoning_evidence = list(poisoning_evidence or [])
        self._poisoning_evidence_complete = poisoning_evidence_complete
        self._poisoning_evidence_reason = poisoning_evidence_reason
        self._raise_poisoning_evidence = raise_poisoning_evidence
        self.poisoning_evidence_calls = 0
        self.poisoning_evidence_as_of: datetime | None = None
        self._financial_flow_path = financial_flow_path
        self._agent_policy_flags = list(agent_policy_flags or [])
        self._raise_agent_policy_flags = raise_agent_policy_flags
        self.agent_policy_flag_calls: list[tuple[str, str]] = []
        self._assessment_history_rows = list(assessment_history_rows or [])
        self._assessment_history_complete = assessment_history_complete
        self._raise_assessment_history = raise_assessment_history
        self.assessment_history_calls: list[tuple[str, str, datetime | None]] = []

    async def latest_assessment(self, *, tenant_id: str, subject: object) -> dict | None:
        if self._raise_assessment:
            raise RuntimeError("boom: secret-detail")
        if self._assessments_by_subject is not None:
            return self._assessments_by_subject.get((subject.kind, subject.id))
        return self._assessment

    async def assessment_history(
        self,
        *,
        tenant_id: str,
        subject: ProjectionSubject,
        as_of: datetime | None,
    ) -> tuple[list[dict], bool]:
        self.assessment_history_calls.append((tenant_id, subject.id, as_of))
        if self._raise_assessment_history:
            raise RuntimeError("boom: secret-detail")
        return list(self._assessment_history_rows), self._assessment_history_complete

    async def signals(self, *, tenant_id: str, subject: object) -> list[dict]:
        if self._raise_signals:
            raise RuntimeError("boom: secret-detail")
        if self._signals_by_subject is not None:
            return list(self._signals_by_subject.get((subject.kind, subject.id), []))
        return list(self._signals)

    async def agent_policy_flag_observations(
        self, *, tenant_id: str, agent_id: str
    ) -> list[dict]:
        self.agent_policy_flag_calls.append((tenant_id, agent_id))
        if self._raise_agent_policy_flags:
            raise RuntimeError("boom: secret-detail")
        return list(self._agent_policy_flags)

    async def source_provenance_observations(
        self, *, tenant_id: str, source_id: str
    ) -> tuple[list[dict], bool]:
        self.source_provenance_calls += 1
        if self._raise_source_provenance:
            raise RuntimeError("boom: secret-detail")
        return list(self._source_provenance), self._source_provenance_truncated

    async def poisoning_evidence(
        self,
        *,
        tenant_id: str,
        subject: ProjectionSubject,
        as_of: datetime | None,
    ) -> RiskPoisoningEvidenceRead:
        self.poisoning_evidence_calls += 1
        self.poisoning_evidence_as_of = as_of
        if self._raise_poisoning_evidence:
            raise RuntimeError("boom: secret-detail")
        return RiskPoisoningEvidenceRead(
            records=list(self._poisoning_evidence),  # type: ignore[arg-type]
            complete=self._poisoning_evidence_complete,
            reason=(
                self._poisoning_evidence_reason
                or (
                    "poisoning_evidence_scan_truncated"
                    if not self._poisoning_evidence_complete
                    else None
                )
            ),
        )

    async def financial_flow_path(self, *, tenant_id: str, path_id: str) -> dict | None:
        return self._financial_flow_path


class _FakeSocialGraphPathReader:
    def __init__(self, result: SocialGraphPathRead) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    async def read_paths(self, tenant_id: str, start_entity_id: str) -> SocialGraphPathRead:
        self.calls.append((tenant_id, start_entity_id))
        return self.result


async def _allow_social_analytics_consent(
    tenant_id: str,
    subject_id: str | None,
    anonymous_id: str | None,
    purpose: str,
) -> tuple[bool, str | None]:
    assert tenant_id == TENANT_A
    assert anonymous_id is None
    assert purpose == "analytics"
    return subject_id is not None, None


async def _deny_social_analytics_consent(
    tenant_id: str,
    subject_id: str | None,
    anonymous_id: str | None,
    purpose: str,
) -> tuple[bool, str | None]:
    del tenant_id, subject_id, anonymous_id, purpose
    return False, "consent_unknown"


def _observed_social_path(
    *, tenant_id: str = TENANT_A, start_id: str = "usr_1", suffix: str = ""
) -> SocialObservedPath:
    entity_ids = (start_id, f"entity-b{suffix}", f"entity-c{suffix}")
    observed_times = ("2026-10-20T10:00:00+00:00", "2026-10-20T10:01:00+00:00")
    graph_edges = []
    edge_evidence_refs = []
    for index, (from_id, to_id) in enumerate(zip(entity_ids, entity_ids[1:])):
        relationship_id = f"follow:{from_id}:{to_id}"
        fact_id = f"observation-{index + 1}{suffix}"
        graph_edges.append(
            {
                "edge_type": "FOLLOWS_SOCIAL",
                "from_vertex_id": from_id,
                "to_vertex_id": to_id,
                "properties": {
                    "tenant_id": tenant_id,
                    "relationship_predicate": "FOLLOWS",
                    "idempotency_key": relationship_id,
                    "evidence_refs": [fact_id],
                    "valid_from": "2026-10-20T09:00:00Z",
                    "observed_at": observed_times[index],
                },
            }
        )
        edge_evidence_refs.append(
            (
                _OI_EvidenceRef(
                    id=relationship_id,
                    type="relationship",
                    source="entity_graph",
                    observedAt="2026-10-20T09:00:00Z",
                ),
                _OI_EvidenceRef(
                    id=fact_id,
                    type="event",
                    source="relationship_facts",
                    observedAt=observed_times[index],
                ),
            )
        )
    return SocialObservedPath(
        entity_ids=entity_ids,
        edge_evidence_refs=tuple(edge_evidence_refs),
        graph_edges=tuple(graph_edges),
        edge_observed_at=observed_times,
    )


def _bronze_source_row(
    *,
    row_id: str,
    event_id: str,
    tenant_id: str,
    source_id: str,
    source_trust: str | None = "partner_api",
) -> dict:
    """One Bronze observation with exact source and ingress provenance links."""
    return {
        "id": row_id,
        "tenant_id": tenant_id,
        "event_id": event_id,
        "event_timestamp": "2026-10-19T12:00:00Z",
        "received_at": "2026-10-19T12:00:02Z",
        "payload": {
            "observation_envelope": {
                "observation": {
                    "observation_id": event_id,
                    "occurred_at": "2026-10-19T12:00:00Z",
                },
                "tenancy": {"tenant_id": tenant_id},
                "rights": {"source_id": source_id},
                "provenance": {
                    "source_trust": source_trust,
                    "credential_class": "partner_api",
                    "signature_status": "verified",
                    "adapter": "shopify_adapter",
                    "adapter_version": "2",
                },
                "payload": {"private": "must-not-render"},
            }
        },
    }


def _source_provenance_claim_row(
    *,
    event_id: str = "source-event-1",
    tenant_id: str = TENANT_A,
    source_id: str = "provider:crm",
    source_trust: str | None = "partner_api",
) -> dict:
    return {
        "tenant_id": tenant_id,
        "source_id": source_id,
        "observation_id": event_id,
        "source_trust": source_trust,
        "credential_class": "partner_api",
        "signature_status": "verified",
        "adapter": "crm_adapter",
        "adapter_version": "4",
        "observed_at": "2026-10-19T12:00:00Z",
        "evidence_ref": {
            "id": event_id,
            "type": "event",
            "source": "bronze_sdk_events",
            "observedAt": "2026-10-19T12:00:00Z",
            "uri": f"store://bronze_sdk_events/bronze-{event_id}",
        },
    }


def _poisoning_evidence_record(
    *,
    evidence_id: str = "poison-1",
    tenant_id: str = TENANT_A,
    source_id: str = "provider:crm",
    subject_kind: str = "source",
    subject_id: str = "provider:crm",
    status: str = "open",
    recorded_at: datetime | None = None,
    lifecycle_events: list[RiskPoisoningLifecycleEvent] | None = None,
    superseded_by_evidence_id: str | None = None,
) -> RiskPoisoningEvidence:
    seen = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    return RiskPoisoningEvidence(
        evidence_id=evidence_id,
        tenant_id=tenant_id,
        source_id=source_id,
        subject_kind=subject_kind,
        subject_id=subject_id,
        poisoning_type="communication_injection",
        signal_strength=0.76,
        confidence="high",
        claim_state=EpistemicStatus.INFERRED,
        detector_id="comm-injection-detector",
        detector_version="3.1.0",
        source_record_id="message-record-17",
        evidence_refs=[
            EvidenceRef(
                id="message-evidence-17",
                type="event",
                source="message-security",
                uri="store://message-security/evidence-17",
            )
        ],
        first_seen_at=seen,
        last_seen_at=seen,
        recorded_at=recorded_at or seen,
        status=status,  # type: ignore[arg-type]
        superseded_by_evidence_id=superseded_by_evidence_id,
        lifecycle_events=list(lifecycle_events or []),
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_register_provider_succeeds_on_fresh_registry() -> None:
    reg = ProviderRegistry()
    assert register_provider(reg) is None
    assert reg.sources() == {"risk360": "services/api/intelligence/risk360"}
    provider = reg.require("risk360")
    assert isinstance(provider, Risk360Provider)


def test_register_duplicate_different_object_raises() -> None:
    reg = ProviderRegistry()
    register_provider(reg)
    with pytest.raises(DuplicateProjection) as excinfo:
        register_provider(reg)
    assert excinfo.value.projection_id == "risk360"


def test_register_version_mismatch_raises() -> None:
    class _WrongVersion:
        projection_id = "risk360"
        contract_version = "2.0.0"

        async def project(self, request: object, context: object) -> object:
            return None

    reg = ProviderRegistry()
    with pytest.raises(ContractVersionIncompatible):
        reg.register(_WrongVersion())


def test_register_unknown_id_raises() -> None:
    class _UnknownId:
        projection_id = "no_such_projection"
        contract_version = "1.0.0"

        async def project(self, request: object, context: object) -> object:
            return None

    reg = ProviderRegistry()
    with pytest.raises(ProjectionNotFound) as excinfo:
        reg.register(_UnknownId())
    assert excinfo.value.projection_id == "no_such_projection"


def test_provider_contract_version_matches_registry() -> None:
    assert Risk360Provider.contract_version == INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    # The default reader is the repository-backed one (no injection).
    assert isinstance(Risk360Provider()._sources, RepositoryRiskSourceReader)


@pytest.mark.asyncio
async def test_repository_source_provenance_reads_exact_tenant_and_source_with_bound() -> None:
    store = _IN_MEMORY_STORES.setdefault("bronze_sdk_events", {})
    store["source-row"] = _bronze_source_row(
        row_id="bronze-source-row",
        event_id="source-event-1",
        tenant_id=TENANT_A,
        source_id="provider:crm",
    )
    store["other-source-row"] = _bronze_source_row(
        row_id="bronze-other-source-row",
        event_id="source-event-2",
        tenant_id=TENANT_A,
        source_id="provider:other",
    )
    store["other-tenant-row"] = _bronze_source_row(
        row_id="bronze-other-tenant-row",
        event_id="source-event-3",
        tenant_id=TENANT_B,
        source_id="provider:crm",
    )

    observations, truncated = await RepositoryRiskSourceReader().source_provenance_observations(
        tenant_id=TENANT_A,
        source_id="provider:crm",
    )

    assert truncated is False
    assert len(observations) == 1
    row = observations[0]
    assert row["tenant_id"] == TENANT_A
    assert row["source_id"] == "provider:crm"
    assert row["source_trust"] == "partner_api"
    assert row["evidence_ref"]["id"] == "source-event-1"
    assert row["evidence_ref"]["uri"] == "store://bronze_sdk_events/bronze-source-row"
    assert "private" not in str(row)


@pytest.mark.asyncio
async def test_repository_source_provenance_reports_bounded_partial_scan() -> None:
    store = _IN_MEMORY_STORES.setdefault("bronze_sdk_events", {})
    for index in range(101):
        store[f"source-row-{index}"] = _bronze_source_row(
            row_id=f"bronze-source-row-{index}",
            event_id=f"source-event-{index}",
            tenant_id=TENANT_A,
            source_id="provider:crm",
        )

    observations, truncated = await RepositoryRiskSourceReader().source_provenance_observations(
        tenant_id=TENANT_A,
        source_id="provider:crm",
    )

    assert len(observations) == 100
    assert truncated is True


@pytest.mark.asyncio
async def test_repository_agent_policy_flags_reads_exact_tenant_and_agent() -> None:
    from repositories.agentic_observability_repos import AgentRiskSignalRepository

    repository = AgentRiskSignalRepository()
    await repository.insert(
        "agent-risk-a-1",
        {
            "signal_id": "agent-risk-a-1",
            "tenant_id": TENANT_A,
            "agent_id": "agent-a",
            "risk_level": "high",
            "reason_codes": ["review"],
            "policy_flags": ["rate_limit_review"],
            "detected_at": "2026-10-20T12:00:00+00:00",
        },
    )
    await repository.insert(
        "agent-risk-other-agent",
        {
            "signal_id": "agent-risk-other-agent",
            "tenant_id": TENANT_A,
            "agent_id": "agent-b",
            "policy_flags": ["must-not-leak"],
        },
    )
    await repository.insert(
        "agent-risk-other-tenant",
        {
            "signal_id": "agent-risk-other-tenant",
            "tenant_id": TENANT_B,
            "agent_id": "agent-a",
            "policy_flags": ["must-not-leak"],
        },
    )

    rows = await RepositoryRiskSourceReader().agent_policy_flag_observations(
        tenant_id=TENANT_A,
        agent_id="agent-a",
    )

    assert [row["signal_id"] for row in rows] == ["agent-risk-a-1"]
    assert rows[0]["tenant_id"] == TENANT_A
    assert rows[0]["agent_id"] == "agent-a"
    assert "must-not-leak" not in str(rows)


@pytest.mark.asyncio
async def test_repository_financial_path_rejoins_one_exact_tenant_transfer_per_hop() -> None:
    from repositories.repos import (
        FlowTracePathRepository,
        FlowTraceRepository,
        TransferRepository,
    )

    await FlowTraceRepository().create(
        {
            "id": "trace-financial-1",
            "tenant_id": TENANT_A,
            "status": "complete",
            "completed_at": "2026-10-20T12:04:00+00:00",
        }
    )
    await FlowTracePathRepository().create(
        {
            "id": "path-financial-1",
            "tenant_id": TENANT_A,
            "trace_id": "trace-financial-1",
            "path_nodes": ["entity-financial-a", "entity-financial-b"],
            "hop_count": 1,
            "discovered_at": "2026-10-20T12:03:00+00:00",
        }
    )
    await TransferRepository().record_transfer(
        transfer_id="transfer-financial-1",
        tenant_id=TENANT_A,
        from_entity_id="entity-financial-a",
        to_entity_id="entity-financial-b",
        asset_id="asset-usd",
        amount="12.50",
    )

    read = await RepositoryRiskSourceReader().financial_flow_path(
        tenant_id=TENANT_A,
        path_id="path-financial-1",
    )

    assert read is not None
    assert read["path_nodes"] == ["entity-financial-a", "entity-financial-b"]
    assert len(read["transfer_edges"]) == 1
    assert read["transfer_edges"][0]["evidence_ref"]["id"] == "transfer-financial-1"
    assert read["transfer_edges"][0]["evidence_ref"]["source"] == "transfers"
    assert read["linkage_reason"] is None


@pytest.mark.asyncio
async def test_repository_financial_path_rejects_lossy_or_cross_tenant_paths() -> None:
    from repositories.repos import FlowTracePathRepository, FlowTraceRepository
    from intelligence.risk360.provider import RiskSourceReadIncomplete

    await FlowTraceRepository().create(
        {
            "id": "trace-financial-b",
            "tenant_id": TENANT_A,
            "status": "complete",
            "completed_at": "2026-10-20T12:04:00+00:00",
        }
    )
    await FlowTracePathRepository().create(
        {
            "id": "path-financial-lossy",
            "tenant_id": TENANT_A,
            "trace_id": "trace-financial-b",
            "path_nodes": ["entity-financial-a", "entity-financial-b"],
            "hop_count": 3,
            "discovered_at": "2026-10-20T12:03:00+00:00",
        }
    )

    read = await RepositoryRiskSourceReader().financial_flow_path(
        tenant_id=TENANT_A,
        path_id="path-financial-lossy",
    )

    assert read is not None
    assert read["path_nodes"] == []
    assert read["linkage_reason"] == "financial_flow_path_sequence_not_exact"

    await FlowTraceRepository().create(
        {
            "id": "trace-financial-cross-tenant",
            "tenant_id": TENANT_B,
            "status": "complete",
            "completed_at": "2026-10-20T12:04:00+00:00",
        }
    )
    await FlowTracePathRepository().create(
        {
            "id": "path-financial-cross-tenant",
            "tenant_id": TENANT_A,
            "trace_id": "trace-financial-cross-tenant",
            "path_nodes": ["entity-financial-a", "entity-financial-b"],
            "hop_count": 1,
            "discovered_at": "2026-10-20T12:03:00+00:00",
        }
    )
    with pytest.raises(RiskSourceReadIncomplete):
        await RepositoryRiskSourceReader().financial_flow_path(
            tenant_id=TENANT_A,
            path_id="path-financial-cross-tenant",
        )


@pytest.mark.asyncio
async def test_source_trust_projects_only_ingress_classification_and_marks_other_slots_unknown() -> (
    None
):
    source_id = "provider:crm"
    reader = _FakeReader(source_provenance=[_source_provenance_claim_row(source_id=source_id)])
    request = _request(subject=ProjectionSubject(kind="source", id=source_id))
    result = await Risk360Provider(sources=reader).project(
        request,
        await _context(_available_registry()),
    )

    health = next(section for section in result.sections if section.id == "health")
    source_summary = health.content["sourceProvenance"]
    assert source_summary["state"] == "partial"
    assert source_summary["semantics"] == "gateway_stamped_ingress_classification_only"
    assert source_summary["reliabilityEvaluation"] == "unknown"
    assert source_summary["observations"][0]["sourceTrustClassification"] == "partner_api"
    assert "must-not-render" not in result.model_dump_json()

    findings = next(section for section in result.sections if section.id == "findings")
    coverage = findings.content["requiredSlotCoverage"]
    assert coverage["source_trust"]["state"] == "partial"
    for slot_id in (
        "poisoning_evidence",
        "propagation_paths",
        "financial_contagion",
        "social_contagion",
    ):
        assert coverage[slot_id]["state"] == "unknown"
        assert coverage[slot_id]["reason"]

    source_claims = [
        claim for claim in result.claims if claim.kind == "source_ingress_trust_classification"
    ]
    assert len(source_claims) == 1
    assert source_claims[0].claimState == EpistemicStatus.OBSERVED
    assert source_claims[0].evidenceRefs[0].id == "source-event-1"
    assert source_claims[0].domainSlotIds == ["source_trust", "evidence_trace"]


@pytest.mark.asyncio
async def test_risk_policy_flags_are_partial_exact_agent_reports_with_evidence() -> None:
    signal = {
        "signal_id": "agent-risk-1",
        "tenant_id": TENANT_A,
        "agent_id": "agent-1",
        "policy_flags": ["rate_limit_review", "human_review_required"],
        "detected_at": "2026-10-20T12:00:00+00:00",
        "policy_version": "must-not-be-trusted-from-observation",
    }
    reader = _FakeReader(agent_policy_flags=[signal])
    request = _request(subject=ProjectionSubject(kind="agent", id="agent-1"))
    result = await Risk360Provider(sources=reader).project(
        request,
        await _context(_available_registry()),
    )

    findings = next(section for section in result.sections if section.id == "findings")
    policy_flags = findings.content["policyFlags"]
    assert policy_flags["state"] == "partial"
    assert policy_flags["reason"] == "agent_observed_flags_lack_model_governance_policy_version"
    assert policy_flags["semantics"] == "exact_agent_risk_signal_reports_only"
    assert policy_flags["policyEvaluation"] == "not_attested"
    assert policy_flags["policyVersion"] is None
    assert policy_flags["observations"] == [
        {
            "signalId": "agent-risk-1",
            "agentId": "agent-1",
            "policyFlags": ["rate_limit_review", "human_review_required"],
            "detectedAt": "2026-10-20T12:00:00+00:00",
            "evidenceRefs": [
                {
                    "id": "agent-risk-1",
                    "type": "event",
                    "source": "obs_agent_risk_signals",
                    "observedAt": "2026-10-20T12:00:00+00:00",
                    "confidence": None,
                    "uri": "store://obs_agent_risk_signals/agent-risk-1",
                }
            ],
        }
    ]
    assert findings.content["requiredSlotCoverage"]["policy_flags"] == {
        "state": "partial",
        "reason": "agent_observed_flags_lack_model_governance_policy_version",
    }

    claim = next(claim for claim in result.claims if claim.kind == "agent_policy_flags_reported")
    assert claim.claimState == EpistemicStatus.OBSERVED
    assert claim.domainSlotIds == ["policy_flags", "evidence_trace"]
    assert claim.evidenceRefs[0].id == "agent-risk-1"
    evidence = next(section for section in result.sections if section.id == "evidence")
    assert any(
        row["id"] == "agent-risk-1" and row["source"] == "obs_agent_risk_signals"
        for row in evidence.content["evidence"]
    )
    assert reader.agent_policy_flag_calls == [(TENANT_A, "agent-1")]


@pytest.mark.asyncio
async def test_assessment_run_history_is_exact_partial_audit_evidence() -> None:
    as_of = datetime(2026, 10, 21, tzinfo=timezone.utc)
    run = {
        "tenant_id": TENANT_A,
        "subject_kind": "entity",
        "subject_id": "usr_1",
        "run_id": "run_risk_2",
        "assessment_id": "assessment_risk_2",
        "definition_id": "risk360.standard",
        "definition_version": "1",
        "context_hash": "a" * 64,
        "status": "completed",
        "started_at": "2026-10-20T12:00:00+00:00",
        "completed_at": "2026-10-20T12:00:01+00:00",
        "supersedes_run_id": "run_risk_1",
        "claim_state": "derived",
        "dimensions": ["payment"],
    }
    reader = _FakeReader(
        assessment=_assessment().model_dump(mode="json"),
        assessment_history_rows=[run],
    )
    request = _request(temporalMode="as_of", asOf=as_of.isoformat())
    registry = _available_registry()
    result = await Risk360Provider(sources=reader).project(
        request,
        await registry.build_context("risk360", request),
    )

    findings = next(section for section in result.sections if section.id == "findings")
    history = findings.content["auditHistory"]
    assert history["state"] == "partial"
    assert history["assessmentRuns"][0]["runId"] == "run_risk_2"
    assert history["assessmentRuns"][0]["supersedesRunId"] == "run_risk_1"
    assert history["interventions"] == {
        "state": "unknown",
        "reason": "risk_intervention_authority_unavailable",
    }
    assert findings.content["requiredSlotCoverage"]["audit_history"]["state"] == "partial"
    assert reader.assessment_history_calls == [(TENANT_A, "usr_1", as_of)]
    evidence = next(section for section in result.sections if section.id == "evidence")
    assert any(
        item["id"] == "run_risk_2" and item["source"] == "computation_runs"
        for item in evidence.content["evidence"]
    )


@pytest.mark.asyncio
async def test_assessment_run_history_rejects_cross_subject_rows() -> None:
    reader = _FakeReader(
        assessment_history_rows=[
            {
                "tenant_id": TENANT_A,
                "subject_kind": "entity",
                "subject_id": "different-entity",
                "run_id": "run_wrong_subject",
                "assessment_id": "assessment_wrong_subject",
                "definition_id": "risk360.standard",
                "started_at": "2026-10-20T12:00:00+00:00",
                "dimensions": [],
            }
        ]
    )
    result = await Risk360Provider(sources=reader).project(
        _request(),
        await _context(_available_registry()),
    )

    findings = next(section for section in result.sections if section.id == "findings")
    assert findings.content["auditHistory"]["state"] == "degraded"
    assert findings.content["auditHistory"]["assessmentRuns"] == []
    assert findings.content["requiredSlotCoverage"]["audit_history"] == {
        "state": "degraded",
        "reason": "risk_assessment_history_exact_binding_mismatch",
    }


@pytest.mark.asyncio
async def test_risk_policy_flags_suppress_unscoped_and_historical_reads() -> None:
    rows = [
        {
            "signal_id": "cross-tenant",
            "tenant_id": TENANT_B,
            "agent_id": "agent-1",
            "policy_flags": ["must-not-leak"],
        }
    ]
    reader = _FakeReader(agent_policy_flags=rows)
    entity_result = await Risk360Provider(sources=reader).project(
        _request(),
        await _context(_available_registry()),
    )
    entity_findings = next(
        section for section in entity_result.sections if section.id == "findings"
    )
    assert entity_findings.content["policyFlags"]["state"] == "unknown"
    assert entity_findings.content["policyFlags"]["reason"] == "exact_agent_subject_required"
    assert reader.agent_policy_flag_calls == []

    historical = _request(
        subject=ProjectionSubject(kind="agent", id="agent-1"),
        asOf="2026-10-19T00:00:00+00:00",
        temporalMode="as_of",
    )
    historical_result = await Risk360Provider(sources=reader).project(
        historical,
        await _context(_available_registry()),
    )
    historical_findings = next(
        section for section in historical_result.sections if section.id == "findings"
    )
    assert historical_findings.content["policyFlags"]["state"] == "unknown"
    assert historical_findings.content["policyFlags"]["reason"] == (
        "agent_policy_flag_bitemporal_history_unavailable"
    )
    assert historical_findings.content["policyFlags"]["observations"] == []
    assert reader.agent_policy_flag_calls == []

    agent_request = _request(subject=ProjectionSubject(kind="agent", id="agent-1"))
    leaky_result = await Risk360Provider(sources=reader).project(
        agent_request,
        await _context(_available_registry()),
    )
    leaky_findings = next(section for section in leaky_result.sections if section.id == "findings")
    assert leaky_findings.content["policyFlags"]["state"] == "degraded"
    assert leaky_findings.content["policyFlags"]["reason"] == (
        "agent_policy_flag_record_invalid_or_scope_incomplete"
    )
    assert leaky_findings.content["policyFlags"]["observations"] == []
    assert "must-not-leak" not in leaky_result.model_dump_json()
    assert reader.agent_policy_flag_calls == [(TENANT_A, "agent-1")]

    failing_result = await Risk360Provider(
        sources=_FakeReader(raise_agent_policy_flags=True)
    ).project(agent_request, await _context(_available_registry()))
    failing_findings = next(
        section for section in failing_result.sections if section.id == "findings"
    )
    assert failing_findings.content["policyFlags"]["state"] == "degraded"
    assert failing_findings.content["policyFlags"]["reason"] == "agent_policy_flag_read_incomplete"
    assert "secret-detail" not in failing_result.model_dump_json()


@pytest.mark.asyncio
async def test_poisoning_evidence_projects_exact_detector_record_without_escalating_claim() -> None:
    source_id = "provider:crm"
    record = _poisoning_evidence_record(source_id=source_id, subject_id=source_id)
    result = await Risk360Provider(
        sources=_FakeReader(poisoning_evidence=[record])
    ).project(
        _request(subject=ProjectionSubject(kind="source", id=source_id)),
        await _context(_available_registry()),
    )

    findings = next(section for section in result.sections if section.id == "findings")
    payload = findings.content["poisoningEvidence"]
    assert payload["state"] == "partial"
    assert payload["records"][0]["sourceId"] == source_id
    assert payload["records"][0]["subject"] == {"kind": "source", "id": source_id}
    assert payload["records"][0]["detectorVersion"] == "3.1.0"
    assert payload["records"][0]["evidenceRefs"][0]["id"] == "message-evidence-17"
    assert payload["coverage"] == {
        "completeEvidenceScan": True,
        "detectorCoverage": "unattested",
        "negativeFindingInference": "prohibited",
    }
    assert payload["freshness"]["threshold"] == "unconfigured"
    assert payload["policy"] == {
        "scope": "tenant_read_gated",
        "projection": "metadata_only",
        "rawPayload": "excluded",
    }
    assert findings.content["requiredSlotCoverage"]["poisoning_evidence"] == {
        "state": "partial",
        "reason": "poisoning_detector_coverage_not_attested",
    }
    assert findings.content["requiredSlotCoverage"]["source_trust"] == {
        "state": "degraded",
        "reason": "open_poisoning_evidence_requires_source_review",
    }
    claim = next(
        claim for claim in result.claims if claim.kind == "source_poisoning_detector_evidence"
    )
    assert claim.id == "risk360.poisoning.poison-1.v1"
    assert claim.claimState is EpistemicStatus.INFERRED
    assert claim.confidence is None
    assert claim.domainSlotIds == ["poisoning_evidence", "evidence_trace", "source_trust"]
    assert "does not by itself verify" in claim.claims[0]
    serialized = result.model_dump_json()
    assert "suspected_payload_hash" not in serialized
    assert "payload_hash" not in serialized


@pytest.mark.asyncio
async def test_poisoning_evidence_rejects_tenant_and_source_subject_mismatches() -> None:
    source_id = "provider:crm"
    wrong_tenant = _poisoning_evidence_record(
        source_id=source_id,
        subject_id=source_id,
        tenant_id=TENANT_B,
    )
    wrong_source = _poisoning_evidence_record(
        evidence_id="poison-2",
        source_id="provider:other",
        subject_id=source_id,
    )
    for record in (wrong_tenant, wrong_source):
        result = await Risk360Provider(
            sources=_FakeReader(poisoning_evidence=[record])
        ).project(
            _request(subject=ProjectionSubject(kind="source", id=source_id)),
            await _context(_available_registry()),
        )
        findings = next(section for section in result.sections if section.id == "findings")
        coverage = findings.content["requiredSlotCoverage"]["poisoning_evidence"]
        assert coverage["state"] == "degraded"
        assert not findings.content["poisoningEvidence"]["records"]
        assert not [
            claim for claim in result.claims if claim.kind == "source_poisoning_detector_evidence"
        ]


@pytest.mark.asyncio
async def test_empty_and_incomplete_poisoning_reads_have_honest_states() -> None:
    empty = await Risk360Provider(sources=_FakeReader()).project(
        _request(), await _context(_available_registry())
    )
    empty_findings = next(section for section in empty.sections if section.id == "findings")
    assert empty_findings.content["poisoningEvidence"]["state"] == "unknown"
    assert empty_findings.content["poisoningEvidence"]["coverage"]["completeEvidenceScan"] is True
    assert empty_findings.content["requiredSlotCoverage"]["poisoning_evidence"] == {
        "state": "unknown",
        "reason": "poisoning_detector_coverage_not_attested",
    }

    partial = await Risk360Provider(
        sources=_FakeReader(
            poisoning_evidence=[_poisoning_evidence_record(subject_kind="entity", subject_id="usr_1")],
            poisoning_evidence_complete=False,
        )
    ).project(_request(), await _context(_available_registry()))
    partial_findings = next(section for section in partial.sections if section.id == "findings")
    assert partial_findings.content["poisoningEvidence"]["state"] == "degraded"
    assert partial_findings.content["requiredSlotCoverage"]["poisoning_evidence"]["state"] == "degraded"
    assert next(section for section in partial.sections if section.id == "health").state == "degraded"


@pytest.mark.asyncio
async def test_poisoning_read_reason_degrades_even_when_authority_marks_it_complete() -> None:
    result = await Risk360Provider(
        sources=_FakeReader(
            poisoning_evidence_complete=True,
            poisoning_evidence_reason="poisoning_evidence_partial_authority_read",
        )
    ).project(_request(), await _context(_available_registry()))

    findings = next(section for section in result.sections if section.id == "findings")
    assert findings.content["poisoningEvidence"]["state"] == "degraded"
    assert findings.content["requiredSlotCoverage"]["poisoning_evidence"] == {
        "state": "degraded",
        "reason": "poisoning_evidence_partial_authority_read",
    }
    assert next(section for section in result.sections if section.id == "health").state == "degraded"


@pytest.mark.asyncio
async def test_poisoning_evidence_reconstructs_point_in_time_lifecycle() -> None:
    recorded_at = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    acknowledged_at = recorded_at + timedelta(seconds=30)
    superseded_at = recorded_at + timedelta(minutes=2)
    events = [
        RiskPoisoningLifecycleEvent(
            event_id="life-1",
            from_status="open",
            to_status="acknowledged",
            occurred_at=acknowledged_at,
            actor_id="operator-1",
            reason="review started",
        ),
        RiskPoisoningLifecycleEvent(
            event_id="life-2",
            from_status="acknowledged",
            to_status="superseded",
            occurred_at=superseded_at,
            actor_id="detector-release-2",
            reason="new detector result",
        ),
    ]
    record = _poisoning_evidence_record(
        status="superseded",
        recorded_at=recorded_at,
        lifecycle_events=events,
        superseded_by_evidence_id="poison-2",
    )
    reader = _FakeReader(poisoning_evidence=[record])
    anchor = acknowledged_at + timedelta(seconds=1)
    result = await Risk360Provider(sources=reader).project(
        _request(
            subject=ProjectionSubject(kind="source", id="provider:crm"),
            asOf=anchor.isoformat(),
            temporalMode="as_of",
        ),
        await _context(_available_registry()),
    )
    assert reader.poisoning_evidence_as_of == anchor
    findings = next(section for section in result.sections if section.id == "findings")
    historical = findings.content["poisoningEvidence"]["records"][0]
    assert historical["status"] == "acknowledged"
    assert historical["supersededByEvidenceId"] is None
    assert [event["eventId"] for event in historical["lifecycle"]] == ["life-1"]


@pytest.mark.asyncio
async def test_repository_reader_joins_canonical_poisoning_authority() -> None:
    source_id = "provider:crm"
    await RiskPoisoningEvidenceRepository().create(
        _poisoning_evidence_record(source_id=source_id, subject_id=source_id)
    )
    result = await Risk360Provider().project(
        _request(subject=ProjectionSubject(kind="source", id=source_id)),
        await _context(_available_registry()),
    )
    findings = next(section for section in result.sections if section.id == "findings")
    assert findings.content["poisoningEvidence"]["records"][0]["evidenceId"] == "poison-1"


@pytest.mark.asyncio
async def test_as_of_source_trust_stays_unknown_without_bitemporal_bronze_reader() -> None:
    source_id = "provider:crm"
    reader = _FakeReader(source_provenance=[_source_provenance_claim_row(source_id=source_id)])
    request = _request(
        subject=ProjectionSubject(kind="source", id=source_id),
        asOf="2026-10-18T12:00:00Z",
        temporalMode="as_of",
    )
    result = await Risk360Provider(sources=reader).project(
        request,
        await _context(_available_registry()),
    )

    health = next(section for section in result.sections if section.id == "health")
    source_summary = health.content["sourceProvenance"]
    assert source_summary["state"] == "unknown"
    assert source_summary["reason"] == "source_provenance_bitemporal_history_unavailable"
    assert source_summary["observations"] == []
    assert reader.source_provenance_calls == 0
    assert not [
        claim for claim in result.claims if claim.kind == "source_ingress_trust_classification"
    ]

    findings = next(section for section in result.sections if section.id == "findings")
    coverage = findings.content["requiredSlotCoverage"]["source_trust"]
    assert coverage == {
        "state": "unknown",
        "reason": "source_provenance_bitemporal_history_unavailable",
    }


@pytest.mark.asyncio
async def test_financial_contagion_emits_only_exact_partial_value_risk_link() -> None:
    assessment_a, signal_a = _financial_risk_records(entity_id="entity-financial-a", index=1)
    assessment_b, signal_b = _financial_risk_records(entity_id="entity-financial-b", index=2)
    reader = _FakeReader(
        assessments_by_subject={
            ("entity", "entity-financial-a"): assessment_a,
            ("entity", "entity-financial-b"): assessment_b,
        },
        signals_by_subject={
            ("entity", "entity-financial-a"): [signal_a],
            ("entity", "entity-financial-b"): [signal_b],
        },
        financial_flow_path=_financial_flow_path(),
    )
    request = _request(
        subject=ProjectionSubject(kind="contagion_path", id="path-financial-1")
    )

    result = await Risk360Provider(sources=reader).project(
        request, await _context(_available_registry())
    )

    findings = next(section for section in result.sections if section.id == "findings")
    coverage = findings.content["requiredSlotCoverage"]
    assert coverage["financial_contagion"] == {
        "state": "partial",
        "reason": "financial_value_risk_link_observed_contagion_attribution_unavailable",
    }
    assert coverage["social_contagion"]["state"] == "unknown"
    assert coverage["propagation_paths"]["state"] == "unknown"

    claim = next(claim for claim in result.claims if claim.kind == "financial_flow_risk_link")
    assert claim.claimState == EpistemicStatus.DERIVED
    assert claim.domainSlotIds == ["financial_contagion", "evidence_trace"]
    assert {ref.id for ref in claim.evidenceRefs} == {
        "transfer-financial-1",
        "financial-risk-evidence-1",
        "financial-risk-evidence-2",
    }
    assert "economic-risk-policy v5" in claim.claims[0]
    assert "does not establish contagion, causal transmission" in claim.claims[0]
    assert "freshness against an SLA" in claim.claims[0]

    evidence = next(section for section in result.sections if section.id == "evidence")
    assert evidence.content["count"] == 3
    assert {row["source"] for row in evidence.content["evidence"]} == {
        "transfers",
        "ledger",
    }


@pytest.mark.asyncio
async def test_risk_propagation_paths_expose_observed_graph_only_not_social_contagion() -> None:
    path = _observed_social_path()
    reader = _FakeSocialGraphPathReader(
        SocialGraphPathRead(TENANT_A, "usr_1", paths=(path,))
    )
    result = await Risk360Provider(
        sources=_FakeReader(),  # type: ignore[arg-type]
        social_graph_path_reader=reader,
        consent_reader=_allow_social_analytics_consent,
    ).project(_request(), await _context(_available_registry()))

    findings = next(section for section in result.sections if section.id == "findings")
    coverage = findings.content["requiredSlotCoverage"]
    assert coverage["propagation_paths"] == {
        "state": "partial",
        "reason": "observed_social_graph_paths_do_not_establish_causal_risk_propagation",
    }
    assert coverage["social_contagion"] == {
        "state": "unknown",
        "reason": "social_contagion_causal_evidence_authority_unavailable",
    }
    projected = findings.content["propagationPaths"]
    assert projected["state"] == "partial"
    assert projected["freshness"] == "unknown"
    assert projected["causalRiskPropagationEstablished"] is False
    assert projected["paths"][0]["entityPath"] == ["usr_1", "entity-b", "entity-c"]
    assert projected["paths"][0]["timeOrderState"] == "ordered"
    assert projected["paths"][0]["semantics"] == {
        "observedDirectedGraphEdges": True,
        "riskPropagationEstablished": False,
        "socialContagionEstablished": False,
        "causalityEstablished": False,
    }

    path_claims = [claim for claim in result.claims if claim.kind == "risk_social_graph_path_observation"]
    assert len(path_claims) == 1
    assert path_claims[0].claimState == EpistemicStatus.OBSERVED
    assert path_claims[0].domainSlotIds == ["propagation_paths", "evidence_trace"]
    assert {ref.id for ref in path_claims[0].evidenceRefs} == {
        "follow:usr_1:entity-b",
        "observation-1",
        "follow:entity-b:entity-c",
        "observation-2",
    }
    evidence = next(section for section in result.sections if section.id == "evidence")
    assert {row["id"] for row in evidence.content["evidence"]} >= {
        "follow:usr_1:entity-b",
        "observation-1",
        "follow:entity-b:entity-c",
        "observation-2",
    }
    assert reader.calls == [(TENANT_A, "usr_1")]


@pytest.mark.asyncio
async def test_risk_social_paths_fail_closed_on_tenant_mismatch_and_future_observation() -> None:
    mismatched_reader = _FakeSocialGraphPathReader(
        SocialGraphPathRead("tenant-other", "usr_1", paths=(_observed_social_path(),))
    )
    mismatched = await Risk360Provider(
        sources=_FakeReader(),  # type: ignore[arg-type]
        social_graph_path_reader=mismatched_reader,
        consent_reader=_allow_social_analytics_consent,
    ).project(_request(), await _context(_available_registry()))
    mismatch_coverage = next(
        section for section in mismatched.sections if section.id == "findings"
    ).content["requiredSlotCoverage"]["propagation_paths"]
    assert mismatch_coverage == {
        "state": "degraded",
        "reason": "canonical_social_path_scope_mismatch",
    }
    assert not any(claim.kind == "risk_social_graph_path_observation" for claim in mismatched.claims)

    future_path = _observed_social_path()
    future_edges = [dict(edge) for edge in future_path.graph_edges]
    future_edges[0]["properties"] = {
        **future_edges[0]["properties"],
        "observed_at": "2026-10-24T10:00:00+00:00",
    }
    future_path = SocialObservedPath(
        entity_ids=future_path.entity_ids,
        edge_evidence_refs=future_path.edge_evidence_refs,
        graph_edges=tuple(future_edges),
        edge_observed_at=future_path.edge_observed_at,
    )
    future_reader = _FakeSocialGraphPathReader(
        SocialGraphPathRead(TENANT_A, "usr_1", paths=(future_path,))
    )
    future_result = await Risk360Provider(
        sources=_FakeReader(),  # type: ignore[arg-type]
        social_graph_path_reader=future_reader,
        consent_reader=_allow_social_analytics_consent,
    ).project(_request(), await _context(_available_registry()))
    future_coverage = next(
        section for section in future_result.sections if section.id == "findings"
    ).content["requiredSlotCoverage"]["propagation_paths"]
    assert future_coverage == {
        "state": "degraded",
        "reason": "canonical_social_path_evidence_incomplete",
    }
    assert not any(
        claim.kind == "risk_social_graph_path_observation" for claim in future_result.claims
    )


@pytest.mark.asyncio
async def test_risk_social_paths_reject_cross_tenant_edges_and_unjoined_fact_refs() -> None:
    valid_path = _observed_social_path()
    cases = []
    cross_tenant_edges = [dict(edge) for edge in valid_path.graph_edges]
    cross_tenant_edges[0]["properties"] = {
        **cross_tenant_edges[0]["properties"],
        "tenant_id": TENANT_B,
    }
    cases.append(
        SocialObservedPath(
            entity_ids=valid_path.entity_ids,
            edge_evidence_refs=valid_path.edge_evidence_refs,
            graph_edges=tuple(cross_tenant_edges),
            edge_observed_at=valid_path.edge_observed_at,
        )
    )
    unjoined_fact_edges = [dict(edge) for edge in valid_path.graph_edges]
    unjoined_fact_edges[0]["properties"] = {
        **unjoined_fact_edges[0]["properties"],
        "evidence_refs": ["unjoined-observation"],
    }
    cases.append(
        SocialObservedPath(
            entity_ids=valid_path.entity_ids,
            edge_evidence_refs=valid_path.edge_evidence_refs,
            graph_edges=tuple(unjoined_fact_edges),
            edge_observed_at=valid_path.edge_observed_at,
        )
    )

    for invalid_path in cases:
        reader = _FakeSocialGraphPathReader(
            SocialGraphPathRead(TENANT_A, "usr_1", paths=(invalid_path,))
        )
        result = await Risk360Provider(
            sources=_FakeReader(),  # type: ignore[arg-type]
            social_graph_path_reader=reader,
            consent_reader=_allow_social_analytics_consent,
        ).project(_request(), await _context(_available_registry()))
        coverage = next(
            section for section in result.sections if section.id == "findings"
        ).content["requiredSlotCoverage"]["propagation_paths"]
        assert coverage == {
            "state": "degraded",
            "reason": "canonical_social_path_evidence_incomplete",
        }
        assert not any(
            claim.kind == "risk_social_graph_path_observation" for claim in result.claims
        )


@pytest.mark.asyncio
async def test_risk_social_path_read_suppresses_temporal_and_unconsented_requests() -> None:
    path_reader = _FakeSocialGraphPathReader(
        SocialGraphPathRead(TENANT_A, "usr_1", paths=(_observed_social_path(),))
    )
    temporal = await Risk360Provider(
        sources=_FakeReader(),  # type: ignore[arg-type]
        social_graph_path_reader=path_reader,
        consent_reader=_allow_social_analytics_consent,
    ).project(
        _request(asOf="2026-10-20T12:00:00Z"),
        await _context(_available_registry()),
    )
    temporal_coverage = next(
        section for section in temporal.sections if section.id == "findings"
    ).content["requiredSlotCoverage"]["propagation_paths"]
    assert temporal_coverage == {
        "state": "unknown",
        "reason": "social_graph_path_bitemporal_history_unavailable",
    }
    assert path_reader.calls == []

    denied_reader = _FakeSocialGraphPathReader(
        SocialGraphPathRead(TENANT_A, "usr_1", paths=(_observed_social_path(),))
    )
    denied = await Risk360Provider(
        sources=_FakeReader(),  # type: ignore[arg-type]
        social_graph_path_reader=denied_reader,
        consent_reader=_deny_social_analytics_consent,
    ).project(_request(), await _context(_available_registry()))
    denied_coverage = next(
        section for section in denied.sections if section.id == "findings"
    ).content["requiredSlotCoverage"]["propagation_paths"]
    assert denied_coverage == {
        "state": "unknown",
        "reason": "social_path_subject_consent_restricted",
    }
    assert denied_reader.calls == []
    assert not any(claim.kind == "risk_social_graph_path_observation" for claim in denied.claims)


@pytest.mark.asyncio
async def test_risk_social_path_local_cap_marks_completeness_unknown() -> None:
    paths = tuple(_observed_social_path(suffix=f"-{index}") for index in range(51))
    reader = _FakeSocialGraphPathReader(
        SocialGraphPathRead(TENANT_A, "usr_1", paths=paths)
    )
    result = await Risk360Provider(
        sources=_FakeReader(),  # type: ignore[arg-type]
        social_graph_path_reader=reader,
        consent_reader=_allow_social_analytics_consent,
    ).project(_request(), await _context(_available_registry()))

    propagation = next(
        section for section in result.sections if section.id == "findings"
    ).content["propagationPaths"]
    assert propagation["state"] == "degraded"
    assert propagation["reason"] == "canonical_social_path_evidence_incomplete"
    assert propagation["completeness"] == "unknown"
    assert propagation["reasonCodes"] == ["canonical_social_path_result_capped"]
    assert len(propagation["paths"]) == 50


@pytest.mark.asyncio
async def test_financial_contagion_degrades_when_transfer_evidence_timestamp_disagrees() -> None:
    path = _financial_flow_path()
    path["transfer_edges"][0]["evidence_ref"]["observedAt"] = "2026-10-20T12:02:00+00:00"
    request = _request(
        subject=ProjectionSubject(kind="contagion_path", id="path-financial-1")
    )

    result = await Risk360Provider(sources=_FakeReader(financial_flow_path=path)).project(
        request, await _context(_available_registry())
    )

    findings = next(section for section in result.sections if section.id == "findings")
    assert findings.content["requiredSlotCoverage"]["financial_contagion"] == {
        "state": "degraded",
        "reason": "financial_transfer_evidence_scope_incomplete",
    }
    assert not [claim for claim in result.claims if claim.kind == "financial_flow_risk_link"]


@pytest.mark.asyncio
async def test_financial_contagion_degrades_when_path_transfers_are_not_chronological() -> None:
    path = _financial_flow_path()
    path["path_nodes"] = ["entity-a", "entity-b", "entity-c"]
    path["hop_count"] = 2
    path["transfer_edges"] = [
        {
            "from_entity_id": "entity-a",
            "to_entity_id": "entity-b",
            "transfer_id": "transfer-first-edge",
            "asset_id": "asset-usd",
            "amount": "12.50",
            "occurred_at": "2026-10-20T12:02:00+00:00",
            "evidence_ref": {
                "id": "transfer-first-edge",
                "type": "transaction",
                "source": "transfers",
                "observedAt": "2026-10-20T12:02:00+00:00",
                "uri": "store://transfers/transfer-first-edge",
            },
        },
        {
            "from_entity_id": "entity-b",
            "to_entity_id": "entity-c",
            "transfer_id": "transfer-second-edge",
            "asset_id": "asset-usd",
            "amount": "8.00",
            "occurred_at": "2026-10-20T12:01:00+00:00",
            "evidence_ref": {
                "id": "transfer-second-edge",
                "type": "transaction",
                "source": "transfers",
                "observedAt": "2026-10-20T12:01:00+00:00",
                "uri": "store://transfers/transfer-second-edge",
            },
        },
    ]
    request = _request(
        subject=ProjectionSubject(kind="contagion_path", id="path-financial-1")
    )

    result = await Risk360Provider(sources=_FakeReader(financial_flow_path=path)).project(
        request, await _context(_available_registry())
    )

    findings = next(section for section in result.sections if section.id == "findings")
    assert findings.content["requiredSlotCoverage"]["financial_contagion"] == {
        "state": "degraded",
        "reason": "financial_transfer_temporal_order_inconsistent",
    }
    assert not [claim for claim in result.claims if claim.kind == "financial_flow_risk_link"]


@pytest.mark.asyncio
async def test_financial_contagion_stays_unknown_for_historical_path_request() -> None:
    reader = _FakeReader(
        financial_flow_path=_financial_flow_path(),
        raise_assessment=True,
        raise_signals=True,
    )
    request = _request(
        subject=ProjectionSubject(kind="contagion_path", id="path-financial-1"),
        asOf="2026-10-19T00:00:00Z",
        temporalMode="as_of",
    )

    result = await Risk360Provider(sources=reader).project(
        request, await _context(_available_registry())
    )

    findings = next(section for section in result.sections if section.id == "findings")
    assert findings.content["requiredSlotCoverage"]["financial_contagion"] == {
        "state": "unknown",
        "reason": "financial_flow_risk_bitemporal_history_unavailable",
    }
    assert not [claim for claim in result.claims if claim.kind == "financial_flow_risk_link"]
    assert next(section for section in result.sections if section.id == "summary").state == "missing"


@pytest.mark.asyncio
async def test_financial_contagion_stays_unknown_without_risk_on_every_path_entity() -> None:
    assessment_a, signal_a = _financial_risk_records(entity_id="entity-financial-a", index=1)
    reader = _FakeReader(
        assessments_by_subject={("entity", "entity-financial-a"): assessment_a},
        signals_by_subject={("entity", "entity-financial-a"): [signal_a]},
        financial_flow_path=_financial_flow_path(),
    )
    request = _request(
        subject=ProjectionSubject(kind="contagion_path", id="path-financial-1")
    )

    result = await Risk360Provider(sources=reader).project(
        request, await _context(_available_registry())
    )

    findings = next(section for section in result.sections if section.id == "findings")
    assert findings.content["requiredSlotCoverage"]["financial_contagion"] == {
        "state": "unknown",
        "reason": "financial_risk_assessment_missing_for_path_entity",
    }
    assert not [claim for claim in result.claims if claim.kind == "financial_flow_risk_link"]


@pytest.mark.asyncio
async def test_source_provenance_scope_mismatch_degrades_without_leaking_rows() -> None:
    request = _request(subject=ProjectionSubject(kind="source", id="provider:crm"))
    leaked = _source_provenance_claim_row(tenant_id=TENANT_B)
    result = await Risk360Provider(sources=_FakeReader(source_provenance=[leaked])).project(
        request, await _context(_available_registry())
    )

    health = next(section for section in result.sections if section.id == "health")
    assert health.content["sourceProvenance"]["state"] == "degraded"
    assert health.content["sourceProvenance"]["observations"] == []
    assert "source-event-1" not in result.model_dump_json()
    coverage = next(section for section in result.sections if section.id == "findings").content[
        "requiredSlotCoverage"
    ]
    assert coverage["source_trust"]["state"] == "degraded"


def test_importing_the_package_does_not_auto_register_globally() -> None:
    # The plane's global registry stays clean: wiring is the caller's job
    # (register_provider is explicit), so importing the slice — including its
    # module-level ``router`` bound to the global registry — has NO side effect.
    assert projection_registry.get("risk360") is None
    # The router re-export exists and is bound to the plane's global registry.
    assert _package_router is not None


def test_surface_constants_align_with_registry_row() -> None:
    definition = INTELLIGENCE_PROJECTION_DEFINITIONS["risk360"]
    # The section set is exactly the registry row's outputSections.
    assert set(OUTPUT_SECTIONS) == set(definition["outputSections"])
    assert PROJECTION_ID == "risk360"
    assert set(SERVED_SUBJECT_KINDS) == set(definition["subjectKinds"])
    assert READ_CAPABILITY in PROJECTION_CAPABILITY_MAP["risk360"]
    assert EXPLORE_CAPABILITY in PROJECTION_CAPABILITY_MAP["risk360"]
    # Dependency map keys are sections we emit; values are registered projections.
    assert set(SECTION_DEPENDENCIES) <= set(OUTPUT_SECTIONS)
    assert set(SECTION_DEPENDENCIES.values()) <= set(INTELLIGENCE_PROJECTION_IDS)


# ---------------------------------------------------------------------------
# Valid seeded result: five typed sections + evidence-grounded claims
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_project_returns_valid_result_from_repositories() -> None:
    await _seed(_assessment(), [_signal("sig-1", TENANT_A)])
    reg = _available_registry()
    context = await _context(reg)

    provider = Risk360Provider()  # default repository-backed reader
    result = await provider.project(_request(), context)

    assert isinstance(result, ProjectionResult)
    assert result.projectionId == "risk360"
    assert result.tenantId == TENANT_A
    assert result.contractVersion == INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    assert result.generatedAt  # ISO-8601 UTC
    assert result.degradedReasons == []
    assert [s.id for s in result.sections] == list(OUTPUT_SECTIONS)
    assert OUTPUT_SECTIONS == ("summary", "state", "evidence", "findings", "health")
    # dependencyState is echoed verbatim from the registry-computed context.
    assert result.dependencyState == context.dependencyState
    assert {d.projectionId for d in result.dependencyState} == {
        "profile360",
        "cluster360",
        "economic360",
    }
    assert all(d.state == "available" for d in result.dependencyState)


@pytest.mark.asyncio
async def test_section_states_are_typed_section_state_vocabulary() -> None:
    await _seed(_assessment(), [_signal("sig-1", TENANT_A)])
    provider = Risk360Provider()
    result = await provider.project(_request(), await _context(_available_registry()))
    for section in result.sections:
        assert section.state in VALID_SECTION_STATES, section.id
    # The states actually chosen are the honest subset the provider is allowed.
    assert {s.state for s in result.sections} <= {
        "available",
        "degraded",
        "empty",
        "missing",
    }


@pytest.mark.asyncio
async def test_summary_render_is_canonical_and_never_invents_a_score() -> None:
    await _seed(_assessment(), [_signal("sig-1", TENANT_A)])
    provider = Risk360Provider()
    result = await provider.project(_request(), await _context(_available_registry()))

    summary = next(s for s in result.sections if s.id == "summary")
    assert summary.state == "available"
    content = summary.content
    assert content["tenantId"] == TENANT_A
    assert content["assessment"]["assessmentId"] == "a-1"
    assert content["assessment"]["scoredDimensions"] == ["economic"]
    # Only the data-supported observed dimension has a score anywhere here.
    assert "riskScore" not in content
    assert "trafficLight" not in content
    assert content["exposure"]["economicValue"]["amount"] == "120.00"


@pytest.mark.asyncio
async def test_state_section_honors_per_dimension_honesty() -> None:
    await _seed(_assessment(), [_signal("sig-1", TENANT_A)])
    provider = Risk360Provider()
    result = await provider.project(_request(), await _context(_available_registry()))

    state = next(s for s in result.sections if s.id == "state")
    assert state.state == "available"
    rows = {row["dimension"]: row for row in state.content["dimensionStates"]}
    assert "economic" in rows
    assert rows["economic"]["state"] == "observed"
    assert rows["economic"]["score"] == 0.4
    # Explicitly not_applicable dimension — honest typed absence, no score.
    assert rows["payment"]["state"] == "not_applicable"
    assert rows["payment"]["score"] is None
    # A never-observed dimension is typed missing_inputs with NO fabricated 0.
    assert rows["authentication"]["state"] == "missing_inputs"
    assert rows["authentication"]["score"] is None
    # No dimension outside a value-bearing state may carry a score.
    for row in rows.values():
        if row["state"] not in ("observed", "estimated"):
            assert row["score"] is None, row
    # No invented traffic-light badge in the section content.
    assert "badge" not in state.content


@pytest.mark.asyncio
async def test_claims_are_evidence_grounded_and_canonical() -> None:
    await _seed(_assessment(), [_signal("sig-1", TENANT_A)])
    provider = Risk360Provider()
    result = await provider.project(_request(), await _context(_available_registry()))

    assert result.claims, "expected evidence-grounded claims"
    for claim in result.claims:
        assert isinstance(claim.subject, ProjectionSubject)
        assert claim.evidenceRefs, f"requiresEvidence: claim {claim.id!r} must carry EvidenceRefs"
        for ref in claim.evidenceRefs:
            assert isinstance(ref, _OI_EvidenceRef)
            assert ref.id
    ids = {claim.id for claim in result.claims}
    assert "risk360.assessment.a-1" in ids
    assert "risk360.dimension.economic" in ids
    assert "risk360.health.fraud.signals" in ids
    by_id = {claim.id: claim for claim in result.claims}
    assert by_id["risk360.assessment.a-1"].claimState == EpistemicStatus.DERIVED
    assert by_id["risk360.dimension.economic"].claimState == EpistemicStatus.OBSERVED
    # The canonical fact that a source emitted a persisted signal is observed;
    # the signal's interpretation retains its own inferred claim state.
    assert by_id["risk360.health.fraud.signals"].claimState == EpistemicStatus.OBSERVED
    assert by_id["risk360.signal.sig-1"].claimState == EpistemicStatus.INFERRED


@pytest.mark.asyncio
async def test_evidence_section_lists_the_canonical_refs() -> None:
    await _seed(_assessment(), [_signal("sig-1", TENANT_A)])
    provider = Risk360Provider()
    result = await provider.project(_request(), await _context(_available_registry()))

    evidence = next(s for s in result.sections if s.id == "evidence")
    assert evidence.state == "available"
    ref_ids = {e["id"] for e in evidence.content["evidence"]}
    assert "ev-assessment-a-1" in ref_ids
    assert "ev-economic-a-1" in ref_ids
    assert "ev-sig-1" in ref_ids


@pytest.mark.asyncio
async def test_freshness_reports_timestamp_coverage_without_fresh_stale_claims() -> None:
    assessed_at = datetime(2026, 10, 18, 10, 0, tzinfo=timezone.utc)
    observed_at = datetime(2026, 10, 18, 9, 30, tzinfo=timezone.utc)
    timestamped = _signal("sig-timestamped", TENANT_A)
    timestamped.observed_at = observed_at
    untimestamped_row = _signal("sig-untimestamped", TENANT_A).model_dump(mode="json")
    untimestamped_row["observed_at"] = None
    provider = Risk360Provider(
        sources=_FakeReader(
            assessment=_assessment(assessed_at=assessed_at).model_dump(mode="json"),
            signals=[timestamped.model_dump(mode="json"), untimestamped_row],
        )  # type: ignore[arg-type]
    )

    result = await provider.project(_request(), await _context(_available_registry()))

    health = next(section for section in result.sections if section.id == "health")
    freshness = health.content["freshness"]
    assert freshness["assessment"] == {
        "state": "known",
        "assessmentId": "a-1",
        "assessedAt": assessed_at.isoformat(),
    }
    assert freshness["signals"] == {
        "state": "unknown",
        "signalCount": 2,
        "timestampedSignalCount": 1,
        "untimestampedSignalCount": 1,
        "latestObservedAt": observed_at.isoformat(),
    }
    assert "fresh" not in str(freshness).lower()
    assert "stale" not in str(freshness).lower()


@pytest.mark.asyncio
async def test_request_tenant_cannot_override_runtime_tenant_scope() -> None:
    class _NeverRead:
        async def latest_assessment(self, *, tenant_id: str, subject: object) -> dict | None:
            raise AssertionError("canonical read must not run across tenant scope")

        async def signals(self, *, tenant_id: str, subject: object) -> list[dict]:
            raise AssertionError("canonical read must not run across tenant scope")

    context = await _context(_available_registry(), tenant=TENANT_A)
    result = await Risk360Provider(sources=_NeverRead()).project(_request(tenant=TENANT_B), context)

    by_id = {section.id: section for section in result.sections}
    assert by_id["summary"].state == "degraded"
    assert by_id["state"].state == "degraded"
    assert by_id["evidence"].state == "degraded"
    assert by_id["findings"].state == "degraded"
    assert by_id["health"].state == "degraded"
    assert by_id["health"].content["freshness"]["assessment"]["state"] == "degraded"
    assert by_id["health"].content["freshness"]["signals"]["state"] == "degraded"
    assert result.claims == []


@pytest.mark.asyncio
async def test_assessment_with_zero_recorded_components_is_honest_empty() -> None:
    await _seed(_empty_assessment("a-empty", TENANT_A))
    provider = Risk360Provider()
    result = await provider.project(_request(), await _context(_available_registry()))

    summary = next(s for s in result.sections if s.id == "summary")
    assert summary.state == "empty"
    state = next(s for s in result.sections if s.id == "state")
    assert state.state == "empty"
    # Every dimension is typed as an honest absence, none fabricated a score.
    rows = {row["dimension"]: row for row in state.content["dimensionStates"]}
    assert rows["identity"]["score"] is None


# ---------------------------------------------------------------------------
# Empty backing store -> honest missing/empty, never raising
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_store_returns_honest_states_without_raising() -> None:
    provider = Risk360Provider()
    context = await _context(ProviderRegistry())  # nothing registered, deps missing
    result = await provider.project(_request(), context)

    assert isinstance(result, ProjectionResult)
    assert result.projectionId == "risk360"
    assert [s.id for s in result.sections] == list(OUTPUT_SECTIONS)
    by_id = {s.id: s for s in result.sections}
    assert by_id["summary"].state == "missing"
    assert by_id["state"].state == "missing"
    assert by_id["evidence"].state == "empty"
    assert by_id["findings"].state == "missing"
    assert by_id["health"].state == "missing"
    assert result.claims == []


# ---------------------------------------------------------------------------
# A raising source degrades its section content-free (never a crash)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_raising_assessment_reader_degrades_content_free() -> None:
    provider = Risk360Provider(
        sources=_FakeReader(raise_assessment=True)  # type: ignore[arg-type]
    )
    result = await provider.project(_request(), await _context(_available_registry()))

    assert result.projectionId == "risk360"
    assert result.degradedReasons == []
    by_id = {s.id: s for s in result.sections}
    assert by_id["summary"].state == "degraded"
    assert by_id["state"].state == "degraded"
    assert by_id["findings"].state == "degraded"
    # No exception message / secret detail leaks into the result.
    serialized = result.model_dump_json()
    assert "secret-detail" not in serialized
    assert "boom" not in serialized
    assert "RuntimeError" not in serialized


@pytest.mark.asyncio
async def test_raising_signals_reader_degrades_health_only() -> None:
    assessment = _assessment()
    provider = Risk360Provider(
        sources=_FakeReader(  # type: ignore[arg-type]
            assessment=assessment.model_dump(mode="json"),
            raise_signals=True,
        )
    )
    result = await provider.project(_request(), await _context(_available_registry()))

    by_id = {s.id: s for s in result.sections}
    assert by_id["health"].state == "degraded"
    # The assessment-backed sections still render normally.
    assert by_id["summary"].state == "available"
    assert by_id["state"].state == "available"
    assert "secret-detail" not in result.model_dump_json()
    assert "boom" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_repository_read_failure_is_not_misreported_as_missing() -> None:
    class FailingAssessmentRepository:
        async def list_by_subject(self, *args, **kwargs):
            raise RuntimeError("secret database diagnostic")

    reader = RepositoryRiskSourceReader()
    reader._assessments = FailingAssessmentRepository()
    result = await Risk360Provider(sources=reader).project(
        _request(), await _context(_available_registry())
    )

    by_id = {section.id: section for section in result.sections}
    assert by_id["summary"].state == "degraded"
    assert by_id["state"].state == "degraded"
    assert by_id["findings"].state == "degraded"
    assert "secret database diagnostic" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_repository_assessment_scan_over_bound_is_degraded() -> None:
    class OverLimitAssessmentRepository:
        async def list_by_subject(self, tenant_id, subject_kind, subject_id, *, limit):
            assert limit == 51
            return [
                _assessment(f"assessment-{index}").model_dump(mode="json") for index in range(51)
            ]

    reader = RepositoryRiskSourceReader()
    reader._assessments = OverLimitAssessmentRepository()
    result = await Risk360Provider(sources=reader).project(
        _request(), await _context(_available_registry())
    )

    by_id = {section.id: section for section in result.sections}
    assert by_id["summary"].state == "degraded"
    assert by_id["state"].state == "degraded"
    assert by_id["findings"].state == "degraded"
    assert by_id["findings"].content["assessmentId"] is None


@pytest.mark.asyncio
async def test_signal_scope_mismatch_and_truncation_degrade_health() -> None:
    assessment = _assessment()
    mismatched = _signal("wrong-tenant", "tenant-other").model_dump(mode="json")
    mismatch_result = await Risk360Provider(
        sources=_FakeReader(assessment=assessment.model_dump(mode="json"), signals=[mismatched])  # type: ignore[arg-type]
    ).project(_request(), await _context(_available_registry()))
    assert next(s for s in mismatch_result.sections if s.id == "health").state == "degraded"

    too_many = [
        _signal(f"signal-{index}", TENANT_A).model_dump(mode="json") for index in range(101)
    ]
    truncated_result = await Risk360Provider(
        sources=_FakeReader(assessment=assessment.model_dump(mode="json"), signals=too_many)  # type: ignore[arg-type]
    ).project(_request(), await _context(_available_registry()))
    health = next(s for s in truncated_result.sections if s.id == "health")
    assert health.state == "degraded"
    assert health.content["signalSources"] == {}


@pytest.mark.asyncio
async def test_agent_signal_context_preserves_observation_and_inferred_risk_state() -> None:
    agent_id = "agent-risk-context"
    observed_at = datetime(2026, 10, 18, 12, 30, tzinfo=timezone.utc)
    ref = EvidenceRef(
        id="ev-agent-risk-context",
        type="relationship",
        source="aether.fraud.detector.delegation",
        observedAt=observed_at.isoformat(),
        uri="aether://fraud-networks/network-agent/evidence?signal=agentic_delegation_abuse",
    )
    assessment = RiskAssessment(
        assessment_id="ras-agent-risk-context",
        tenant_id=TENANT_A,
        subject_kind="agent",
        subject_id=agent_id,
        dimensions=["agentic"],
        vector=RiskVector(
            components=[
                RiskComponent(
                    dimension="agentic",
                    state=ValueState.INSUFFICIENT_DATA,
                    claim_state=EpistemicStatus.UNKNOWN,
                    evidence_refs=[ref],
                )
            ]
        ),
        claim_state=EpistemicStatus.DERIVED,
        evidence_refs=[ref],
        assessed_at=observed_at,
    )
    signal = RiskSignal(
        signal_id="sig-agent-risk-context",
        tenant_id=TENANT_A,
        subject_kind="agent",
        subject_id=agent_id,
        risk_dimension="agentic",
        claim_state=EpistemicStatus.INFERRED,
        confidence=0.78,
        evidence_refs=[ref],
        source="aether.fraud.detector.delegation",
        observed_at=observed_at,
        score=None,
    )
    request = _request(subject=ProjectionSubject(kind="agent", id=agent_id))
    provider = Risk360Provider(
        sources=_FakeReader(
            assessment=assessment.model_dump(mode="json"),
            signals=[signal.model_dump(mode="json")],
        )  # type: ignore[arg-type]
    )

    result = await provider.project(request, await _context(_available_registry()))

    health = next(section for section in result.sections if section.id == "health")
    assert health.state == "available"
    context = health.content["signalContext"]
    assert len(context) == 1
    assert context[0]["signalId"] == signal.signal_id
    assert context[0]["dimension"] == "agentic"
    assert context[0]["claimState"] == EpistemicStatus.INFERRED.value
    assert context[0]["observedAt"] == observed_at.isoformat()
    assert context[0]["score"] is None
    assert context[0]["evidenceRefs"] == [ref.model_dump(mode="json")]

    claims = {claim.id: claim for claim in result.claims}
    assessment_claim = claims[f"risk360.assessment.{assessment.assessment_id}"]
    assert assessment_claim.evidenceRefs == [ref]
    assert assessment_claim.domainSlotIds == [
        "risk_assessment_state",
        "risk_evidence_and_limitations",
        "risk_summary",
        "evidence_trace",
    ]
    signal_claim = claims[f"risk360.signal.{signal.signal_id}"]
    assert signal_claim.claimState == EpistemicStatus.INFERRED
    assert signal_claim.evidenceRefs == [ref]
    assert signal_claim.domainSlotIds == [
        "risk_evidence_and_limitations",
        "evidence_trace",
        "risk_summary",
        "agent_amplification",
    ]
    assert "risk_signals" not in signal_claim.domainSlotIds
    assert (
        claims["risk360.health.aether.fraud.detector.delegation"].claimState
        == EpistemicStatus.OBSERVED
    )
    assert claims["risk360.health.aether.fraud.detector.delegation"].domainSlotIds == [
        "risk_assessment_state",
        "risk_evidence_and_limitations",
        "risk_summary",
        "evidence_trace",
    ]
    findings = next(section for section in result.sections if section.id == "findings")
    assert findings.content["requiredSlotCoverage"]["agent_amplification"]["state"] == "available"
    assert findings.content["requiredSlotCoverage"]["propagation_paths"]["state"] == "unknown"
    state = next(section for section in result.sections if section.id == "state")
    agentic = next(row for row in state.content["dimensionStates"] if row["dimension"] == "agentic")
    assert agentic["state"] == ValueState.INSUFFICIENT_DATA.value
    assert agentic["score"] is None


@pytest.mark.asyncio
async def test_reader_marks_same_tenant_rows_for_a_different_subject_degraded() -> None:
    # Same ID but another kind is not the requested Agent assessment; the
    # signal has the right kind but another ID. Neither can leak via a reader
    # implementation that ignores its subject arguments, and the incomplete
    # exact-subject read must not be mistaken for an ordinary missing result.
    assessment = _assessment("wrong-kind", TENANT_A, subject_id="usr_1")
    other_agent_signal = RiskSignal(
        signal_id="sig-other-agent",
        tenant_id=TENANT_A,
        subject_kind="agent",
        subject_id="agent-other",
        risk_dimension="agentic",
        claim_state=EpistemicStatus.INFERRED,
        evidence_refs=[_evidence("ev-other-agent")],
        source="fraud.agentic",
    )
    request = _request(subject=ProjectionSubject(kind="agent", id="usr_1"))
    provider = Risk360Provider(
        sources=_FakeReader(
            assessment=assessment.model_dump(mode="json"),
            signals=[other_agent_signal.model_dump(mode="json")],
        )  # type: ignore[arg-type]
    )

    result = await provider.project(request, await _context(_available_registry()))

    by_id = {section.id: section for section in result.sections}
    assert by_id["summary"].state == "degraded"
    assert by_id["state"].state == "degraded"
    assert by_id["evidence"].state == "degraded"
    assert by_id["findings"].state == "degraded"
    assert by_id["health"].state == "degraded"
    assert result.claims == []
    assert "wrong-kind" not in result.model_dump_json()
    assert "other-agent" not in result.model_dump_json()


@pytest.mark.asyncio
async def test_result_never_raises_projection_error_from_backing_source() -> None:
    provider = Risk360Provider(
        sources=_FakeReader(raise_assessment=True, raise_signals=True)  # type: ignore[arg-type]
    )
    result = await provider.project(_request(), await _context(ProviderRegistry()))
    assert isinstance(result, ProjectionResult)
    assert len(result.sections) == 5


# ---------------------------------------------------------------------------
# Missing in_flight dependencies -> recorded + degraded, never raising
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_dependencies_recorded_and_echoed_in_dependency_state() -> None:
    await _seed(_assessment())
    reg = ProviderRegistry()  # nothing registered -> all siblings "missing"
    context = await _context(reg)
    assert {d.projectionId for d in context.dependencyState} == {
        "profile360",
        "cluster360",
        "economic360",
    }
    assert all(d.state == "missing" for d in context.dependencyState)

    provider = Risk360Provider()
    result = await provider.project(_request(), context)
    # Echoed verbatim from the registry-computed dependency state.
    assert result.dependencyState == context.dependencyState
    by_id = {s.id: s for s in result.sections}
    assert by_id["summary"].state == "degraded"
    assert by_id["state"].state == "degraded"


@pytest.mark.asyncio
async def test_profile360_missing_degrades_summary_only() -> None:
    await _seed(_assessment())
    reg = ProviderRegistry()
    reg.register(_SiblingProvider("cluster360"))
    reg.register(_SiblingProvider("economic360"))
    # profile360 intentionally NOT registered -> summary's dependency is missing.
    context = await _context(reg)
    by_dep = {d.projectionId: d.state for d in context.dependencyState}
    assert by_dep == {
        "cluster360": "available",
        "economic360": "available",
        "profile360": "missing",
    }

    provider = Risk360Provider()
    result = await provider.project(_request(), context)
    by_id = {s.id: s for s in result.sections}
    assert by_id["summary"].state == "degraded"
    assert any("profile360" in w for w in (by_id["summary"].warnings or []))
    # The unaffected assessment-backed sections render normally.
    assert by_id["state"].state == "available"


@pytest.mark.asyncio
async def test_cluster360_missing_degrades_state_only() -> None:
    await _seed(_assessment())
    reg = ProviderRegistry()
    reg.register(_SiblingProvider("profile360"))
    reg.register(_SiblingProvider("economic360"))
    # cluster360 intentionally NOT registered -> state's dependency is missing.
    context = await _context(reg)
    by_dep = {d.projectionId: d.state for d in context.dependencyState}
    assert by_dep == {
        "cluster360": "missing",
        "economic360": "available",
        "profile360": "available",
    }

    provider = Risk360Provider()
    result = await provider.project(_request(), context)
    by_id = {s.id: s for s in result.sections}
    assert by_id["state"].state == "degraded"
    assert any("cluster360" in w for w in (by_id["state"].warnings or []))
    assert by_id["summary"].state == "available"


# ---------------------------------------------------------------------------
# Tenant isolation — tenant A never surfaces tenant B
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_a_never_surfaces_tenant_b_risk() -> None:
    a = _assessment("a-1", TENANT_A, subject_id="usr_1")
    b = _assessment("b-9", TENANT_B, subject_id="usr_1")
    await _seed(a)
    await _seed(b)
    provider = Risk360Provider()

    result_a = await provider.project(
        _request(tenant=TENANT_A), await _context(_available_registry(), tenant=TENANT_A)
    )
    assert result_a.tenantId == TENANT_A
    serialized_a = result_a.model_dump_json()
    assert "a-1" in serialized_a
    assert "tenant-b" not in serialized_a
    assert "b-9" not in serialized_a

    result_b = await provider.project(
        _request(tenant=TENANT_B), await _context(_available_registry(), tenant=TENANT_B)
    )
    assert result_b.tenantId == TENANT_B
    serialized_b = result_b.model_dump_json()
    assert "b-9" in serialized_b
    assert "tenant-a" not in serialized_b
    assert "a-1" not in serialized_b


# ---------------------------------------------------------------------------
# extra="forbid" conformance + read-only posture
# ---------------------------------------------------------------------------


def test_projection_result_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ProjectionResult(
            projectionId="risk360",
            tenantId="tenant-a",
            contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
            sections=[],
            claims=[],
            dependencyState=[],
            generatedAt="2026-09-03T00:00:00Z",
            degradedReasons=[],
            unexpectedField="nope",
        )


@pytest.mark.asyncio
async def test_provider_result_conforms_to_extra_forbid() -> None:
    await _seed(_assessment())
    provider = Risk360Provider()
    result = await provider.project(_request(), await _context(_available_registry()))
    # Round-trip through the strict contract proves no unexpected fields leak.
    dumped = result.model_dump(mode="json")
    ProjectionResult(**dumped)


def test_provider_surface_exposes_no_mutation_method() -> None:
    write_verbs = (
        "create",
        "insert",
        "upsert",
        "write",
        "update",
        "delete",
        "remove",
        "mutate",
        "put",
        "post",
    )
    for cls in (Risk360Provider, RepositoryRiskSourceReader):
        for name in dir(cls):
            if name.startswith("_"):
                continue
            assert not name.lower().startswith(write_verbs), (cls.__name__, name)


@pytest.mark.asyncio
async def test_project_is_read_only_and_does_not_mutate_stores() -> None:
    assessment = _assessment()
    await _seed(assessment, [_signal("sig-1", TENANT_A)])
    provider = Risk360Provider()
    request = _request()
    context = await _context(_available_registry())

    result_1 = await provider.project(request, context)
    result_2 = await provider.project(request, context)

    # Projecting is deterministic — sections and claims are byte-identical
    # across runs (generatedAt is the only difference).
    assert result_1.sections == result_2.sections
    assert result_1.claims == result_2.claims

    # No row was created, changed, or deleted by projecting.
    assessment_repo = RiskAssessmentRepository()
    signal_repo = RiskSignalRepository()
    assert (await assessment_repo.get_scoped(TENANT_A, "a-1"))["assessment_id"] == "a-1"
    assert await assessment_repo.list_scoped(TENANT_A) == [assessment.model_dump(mode="json")]
    signals = await signal_repo.list_scoped(TENANT_A)
    assert [s["signal_id"] for s in signals] == ["sig-1"]
    assert await assessment_repo.list_scoped(TENANT_B) == []


# ---------------------------------------------------------------------------
# build_projection_request helper + route plumbing are importable and honest
# ---------------------------------------------------------------------------


def test_build_projection_request_is_strict() -> None:
    request = build_projection_request(
        projection_id="risk360",
        tenant_id=TENANT_A,
        subject=ProjectionSubject(kind="relationship", id="rel-1"),
    )
    assert isinstance(request, ProjectionRequest)
    assert request.projectionId == "risk360"
    assert request.tenantId == TENANT_A
    assert request.subject.kind == "relationship"

    source_request = build_projection_request(
        projection_id="risk360",
        tenant_id=TENANT_A,
        subject=ProjectionSubject(kind="source", id="provider:crm"),
    )
    assert source_request.subject.kind == "source"


def test_route_router_exposes_the_read_only_surface() -> None:
    from intelligence.risk360.routes import router

    assert router.prefix == "/v1/risk360"
    # Only GET routes exist (no write path).
    for route in router.routes:
        assert set(route.methods or {}) <= {"GET"}, route.path
    paths = {getattr(r, "path", "") for r in router.routes}
    assert "/v1/risk360/{subject_kind}/{subject_id}" in paths
    assert "/v1/risk360/health" in paths
    assert _package_router is router
    assert create_router() is not None
