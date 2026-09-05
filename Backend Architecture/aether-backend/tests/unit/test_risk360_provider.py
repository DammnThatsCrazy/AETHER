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
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[2]  # .../aether-backend

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.operational_intelligence.models import EvidenceRef as _OI_EvidenceRef  # noqa: E402
from services.risk360 import router as _package_router  # noqa: E402  (re-export smoke)
from services.risk360.contracts import (  # noqa: E402
    EntityRef,
    EpistemicStatus,
    EvidenceRef,
    ExposureAssessment,
    GraphSnapshotRef,
    MonetaryAmount,
    RiskAssessment,
    RiskComponent,
    RiskSignal,
    RiskVector,
    ValueState,
)
from services.risk360.provider import (  # noqa: E402
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
from services.risk360.routes import SERVED_SUBJECT_KINDS, create_router  # noqa: E402
from services.risk360.store import (  # noqa: E402
    RiskAssessmentRepository,
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
        raise_assessment: bool = False,
        raise_signals: bool = False,
    ) -> None:
        self._assessment = assessment
        self._signals = list(signals or [])
        self._raise_assessment = raise_assessment
        self._raise_signals = raise_signals

    async def latest_assessment(self, *, tenant_id: str, subject: object) -> dict | None:
        if self._raise_assessment:
            raise RuntimeError("boom: secret-detail")
        return self._assessment

    async def signals(self, *, tenant_id: str, subject: object) -> list[dict]:
        if self._raise_signals:
            raise RuntimeError("boom: secret-detail")
        return list(self._signals)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_register_provider_succeeds_on_fresh_registry() -> None:
    reg = ProviderRegistry()
    assert register_provider(reg) is None
    assert reg.sources() == {"risk360": "services/risk360"}
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
        "profile360", "cluster360", "economic360",
    }
    assert all(d.state == "available" for d in result.dependencyState)


@pytest.mark.asyncio
async def test_section_states_are_typed_section_state_vocabulary() -> None:
    await _seed(_assessment(), [_signal("sig-1", TENANT_A)])
    provider = Risk360Provider()
    result = await provider.project(
        _request(), await _context(_available_registry())
    )
    for section in result.sections:
        assert section.state in VALID_SECTION_STATES, section.id
    # The states actually chosen are the honest subset the provider is allowed.
    assert {s.state for s in result.sections} <= {
        "available", "degraded", "empty", "missing",
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
        assert claim.evidenceRefs, (
            f"requiresEvidence: claim {claim.id!r} must carry EvidenceRefs"
        )
        for ref in claim.evidenceRefs:
            assert isinstance(ref, _OI_EvidenceRef)
            assert ref.id
    ids = {claim.id for claim in result.claims}
    assert "risk360.assessment.a-1" in ids
    assert "risk360.dimension.economic" in ids
    assert "risk360.health.fraud.signals" in ids


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
        "profile360", "cluster360", "economic360",
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
    assert by_dep == {"cluster360": "available", "economic360": "available", "profile360": "missing"}

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
    assert by_dep == {"cluster360": "missing", "economic360": "available", "profile360": "available"}

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
        "create", "insert", "upsert", "write", "update",
        "delete", "remove", "mutate", "put", "post",
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


def test_route_router_exposes_the_read_only_surface() -> None:
    from services.risk360.routes import router

    assert router.prefix == "/v1/risk360"
    # Only GET routes exist (no write path).
    for route in router.routes:
        assert set(route.methods or {}) <= {"GET"}, route.path
    paths = {getattr(r, "path", "") for r in router.routes}
    assert "/v1/risk360/{subject_kind}/{subject_id}" in paths
    assert "/v1/risk360/health" in paths
    assert _package_router is router
    assert create_router() is not None
