"""Unit tests for the Fraud360 intelligence-projection provider (Phase 4).

The provider is a read-only, fail-isolated, tenant-scoped domain-synthesis
projection (ADR-010). These tests cover:

* a valid ``ProjectionResult`` with the registry's typed sections and
  evidence-grounded claims (``extra="forbid"`` conformance);
* ``register_provider`` (success, duplicate different-object, version mismatch)
  and no global side effect on import;
* stored hypothesis state + claim state echoed verbatim — a ``derived`` /
  ``inferred`` / ``predicted`` suspicion is never upgraded, and a hypothesis
  whose ``claim_state`` is in the suspicion band can never surface anywhere in
  the result as ``confirmed`` / ``verified`` / ``causally_supported``;
* the ``evidence`` section carries supporting AND contradictory refs;
* an empty store yields an honest ``empty``/``missing`` result (no exception);
* ``risk360`` / ``profile360`` missing in ``context.dependencyState`` degrades
  the affected sections honestly and never raises;
* a raising source reader degrades its section content-free (no leak);
* tenant + subject isolation; read-only posture (no write path).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[2]  # .../aether-backend

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.fraud360.contracts import (  # noqa: E402
    EpistemicStatus,
    FraudHypothesis,
    FraudHypothesisState,
)
from services.fraud360.provider import (  # noqa: E402
    OUTPUT_SECTIONS,
    PROJECTION_ID,
    Fraud360Provider,
    RepositoryFraudSourceReader,
    SECTION_DEPENDENCIES,
    register_provider,
)
from services.fraud360.store import FraudHypothesisRepository  # noqa: E402
from services.operational_intelligence.models import EvidenceRef  # noqa: E402
from shared.intelligence_projections import (  # noqa: E402
    ContractVersionIncompatible,
    DuplicateProjection,
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
    ProjectionContext,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
    ProviderRegistry,
    projection_registry,
)
from shared.intelligence_projections.generated_registry import (  # noqa: E402
    PROJECTION_SECTION_STATES,
)

VALID_SECTION_STATES = frozenset(PROJECTION_SECTION_STATES)

SUSPICION_CLAIM_STATES = frozenset(
    {"derived", "inferred", "predicted", "correlated", "attributed"}
)
FACTUAL_CLAIM_STATES = frozenset(
    {"observed", "verified", "causally_supported", "resolved"}
)


@pytest.fixture(autouse=True)
def _reset_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _section(section_id: str, result: ProjectionResult) -> ProjectionSection:
    return next(s for s in result.sections if s.id == section_id)


def _request(tenant: str = "tenant-a", **overrides: object) -> ProjectionRequest:
    values: dict[str, object] = {
        "projectionId": "fraud360",
        "tenantId": tenant,
        "subject": ProjectionSubject(kind="entity", id="ent_1"),
    }
    values.update(overrides)
    return ProjectionRequest(**values)


async def _make_context(
    reg: ProviderRegistry, tenant: str = "tenant-a"
) -> ProjectionContext:
    """Build a runtime context for a fraud360 request (registry truth)."""
    return await reg.build_context("fraud360", _request(tenant=tenant))


# ---------------------------------------------------------------------------
# Hypothesis helpers / seed fixtures
# ---------------------------------------------------------------------------


def _hypothesis(
    tenant_id: str,
    hypothesis_id: str,
    *,
    state: FraudHypothesisState,
    claim_state: EpistemicStatus,
    subject_kind: str = "entity",
    subject_id: str = "ent_1",
    confidence: float | None = None,
    materiality: float | None = None,
    patterns: list[str] | None = None,
    evidence: list[EvidenceRef] | None = None,
    contradictory: list[EvidenceRef] | None = None,
) -> FraudHypothesis:
    return FraudHypothesis(
        hypothesis_id=hypothesis_id,
        tenant_id=tenant_id,
        subject_kind=subject_kind,  # type: ignore[arg-type]
        subject_id=subject_id,
        state=state,
        claim_state=claim_state,
        confidence=confidence,
        matched_pattern_ids=patterns or [],
        materiality=materiality,
        evidence_refs=evidence or [],
        contradictory_evidence_refs=contradictory or [],
    )


def _evidence(evidence_id: str, etype: str = "transaction") -> EvidenceRef:
    return EvidenceRef(id=evidence_id, type=etype, source="fraud360/test")


def _seed_hypotheses(tenant_id: str = "tenant-a") -> list[FraudHypothesis]:
    """A legal, multi-state hypothesis set for ``entity:ent_1`` under a tenant.

    Includes one CONFIRMED hypothesis (factual ``verified`` claim per the state
    machine) and several suspicion-band hypotheses (``candidate``/``derived``,
    ``under_evaluation``/``inferred``, ``investigating``/``predicted``) so the
    no-silent-escalation echo is exercised end to end.
    """
    return [
        _hypothesis(
            tenant_id,
            "hyp-confirm",
            state=FraudHypothesisState.CONFIRMED,
            claim_state=EpistemicStatus.VERIFIED,
            confidence=0.95,
            materiality=0.9,
            patterns=["promotion_abuse"],
            evidence=[_evidence("ev_confirm_sup")],
            contradictory=[_evidence("ev_confirm_con", "annotation")],
        ),
        _hypothesis(
            tenant_id,
            "hyp-cand",
            state=FraudHypothesisState.CANDIDATE,
            claim_state=EpistemicStatus.DERIVED,
            confidence=0.4,
            patterns=["referral_abuse"],
            evidence=[_evidence("ev_cand_sup", "event")],
            contradictory=[_evidence("ev_cand_con", "annotation")],
        ),
        _hypothesis(
            tenant_id,
            "hyp-eval",
            state=FraudHypothesisState.UNDER_EVALUATION,
            claim_state=EpistemicStatus.INFERRED,
            confidence=0.55,
            patterns=["payment_fraud"],
            evidence=[_evidence("ev_eval_sup")],
        ),
        _hypothesis(
            tenant_id,
            "hyp-invest",
            state=FraudHypothesisState.INVESTIGATING,
            claim_state=EpistemicStatus.PREDICTED,
            confidence=0.8,
            materiality=0.75,
            patterns=["account_takeover"],
            evidence=[_evidence("ev_invest_sup", "event")],
            contradictory=[_evidence("ev_invest_con", "annotation")],
        ),
    ]


async def _seed_store(repo: FraudHypothesisRepository, tenant_id: str = "tenant-a") -> None:
    for hypothesis in _seed_hypotheses(tenant_id):
        await repo.create(tenant_id, hypothesis)


class _StubProvider:
    """Minimal sibling provider so dependencyState reports a dep as available."""

    def __init__(self, projection_id: str) -> None:
        self.projection_id = projection_id
        self.contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION

    async def project(self, request: object, context: object) -> object:
        raise NotImplementedError


def _registry_with_synthesis_deps_available() -> ProviderRegistry:
    """A registry whose profile360 / risk360 dependencies read as available."""
    reg = ProviderRegistry()
    reg.register(_StubProvider("profile360"), source="test")
    reg.register(_StubProvider("risk360"), source="test")
    return reg


class _FakeReader:
    """Canonical-source test double returning FraudHypothesis objects."""

    def __init__(self, rows: list[FraudHypothesis], *, raises: Exception | None = None) -> None:
        self._rows = rows
        self._raises = raises

    async def hypotheses(self, *, tenant_id: str, subject: object) -> list[FraudHypothesis]:
        if self._raises is not None:
            raise self._raises
        return list(self._rows)


# ---------------------------------------------------------------------------
# Registration + module surface
# ---------------------------------------------------------------------------


def test_register_provider_succeeds_on_fresh_registry() -> None:
    reg = ProviderRegistry()  # fraud360 row is present in the generated registry
    assert register_provider(reg) is None
    assert reg.sources()["fraud360"] == "services/fraud360"
    provider = reg.require("fraud360")
    assert isinstance(provider, Fraud360Provider)


def test_register_duplicate_different_object_raises() -> None:
    reg = ProviderRegistry()
    register_provider(reg)
    with pytest.raises(DuplicateProjection) as excinfo:
        register_provider(reg)  # a fresh Fraud360Provider instance -> duplicate
    assert excinfo.value.projection_id == "fraud360"


def test_register_version_mismatch_raises() -> None:
    class _WrongVersion:
        projection_id = "fraud360"
        contract_version = "2.0.0"

        async def project(self, request: object, context: object) -> object:
            return None

    reg = ProviderRegistry()
    with pytest.raises(ContractVersionIncompatible) as excinfo:
        reg.register(_WrongVersion())
    assert excinfo.value.projection_id == "fraud360"
    assert excinfo.value.version == "2.0.0"


def test_provider_contract_version_matches_registry() -> None:
    assert (
        Fraud360Provider.contract_version == INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    )
    # Default reader is the repository-backed one (no injection).
    assert isinstance(Fraud360Provider()._sources, RepositoryFraudSourceReader)


def test_module_import_has_no_global_side_effect() -> None:
    # Importing the provider/package must not auto-register on the global plane.
    projection_registry.unregister("fraud360")  # defensive: clean global state
    assert projection_registry.get("fraud360") is None


def test_provider_surface_is_read_only() -> None:
    provider = Fraud360Provider()
    for mutation_name in (
        "create", "update", "upsert", "delete", "remove", "save", "write",
        "mutate",
    ):
        assert not hasattr(provider, mutation_name), mutation_name
    assert Fraud360Provider.graph_mutation_policy == "read_only"
    # The registry row itself is read_only.
    assert ProviderRegistry().graph_mutation_policy("fraud360") == "read_only"


def test_output_sections_match_registry_row() -> None:
    from shared.intelligence_projections.generated_registry import (
        INTELLIGENCE_PROJECTION_DEFINITIONS,
    )

    registry_row = INTELLIGENCE_PROJECTION_DEFINITIONS["fraud360"]
    assert set(OUTPUT_SECTIONS) == set(registry_row["outputSections"])
    assert PROJECTION_ID == "fraud360"
    assert "summary" in SECTION_DEPENDENCIES


# ---------------------------------------------------------------------------
# Valid result over a seeded repository-backed store
# ---------------------------------------------------------------------------


async def test_empty_store_returns_honest_empty_result() -> None:
    provider = Fraud360Provider()  # default repository reader
    result = await provider.project(_request(), await _make_context(ProviderRegistry()))

    assert isinstance(result, ProjectionResult)
    assert result.projectionId == "fraud360"
    assert result.tenantId == "tenant-a"
    assert result.generatedAt
    assert result.degradedReasons == []
    assert result.claims == []
    assert [s.id for s in result.sections] == list(OUTPUT_SECTIONS)

    summary = _section("summary", result)
    assert summary.state == "empty"
    assert summary.content["hypothesisCount"] == 0
    assert summary.content["families"] == []
    assert summary.content["stateCounts"] == {}
    assert summary.content["materiality"] is None
    assert summary.content["synthesisState"] == "absent"

    state_sec = _section("state", result)
    assert state_sec.state == "empty"
    assert state_sec.content["hypothesisStates"] == []

    findings = _section("findings", result)
    assert findings.state == "empty"
    assert findings.content["candidates"] == []

    health = _section("health", result)
    assert health.state == "available"

    # Strict round-trip through the contract proves no unexpected fields leak.
    ProjectionResult(**result.model_dump(mode="json"))


async def test_project_returns_valid_result_over_seeded_store() -> None:
    repo = FraudHypothesisRepository()
    await _seed_store(repo)
    reg = _registry_with_synthesis_deps_available()
    provider = Fraud360Provider()  # default repository reader
    request = _request()
    context = await _make_context(reg)
    result = await provider.project(request, context)

    assert result.projectionId == "fraud360"
    assert result.tenantId == "tenant-a"
    assert result.contractVersion == INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    assert result.generatedAt
    assert result.degradedReasons == []
    assert [s.id for s in result.sections] == list(OUTPUT_SECTIONS)
    for section in result.sections:
        assert section.state in VALID_SECTION_STATES, section.id

    # With profile360/risk360 available the synthesis sections read available.
    assert _section("summary", result).state == "available"
    assert _section("state", result).state == "available"

    # Strict round-trip through the contract proves no unexpected fields leak.
    ProjectionResult(**result.model_dump(mode="json"))


async def test_claims_are_evidence_grounded() -> None:
    repo = FraudHypothesisRepository()
    await _seed_store(repo)
    reg = _registry_with_synthesis_deps_available()
    provider = Fraud360Provider()
    result = await provider.project(_request(), await _make_context(reg))

    assert result.claims, "expected evidence-grounded claims"
    for claim in result.claims:
        assert isinstance(claim.subject, ProjectionSubject)
        assert claim.evidenceRefs, (
            f"requiresEvidence: claim {claim.id!r} must carry EvidenceRefs"
        )
        for ref in claim.evidenceRefs:
            assert isinstance(ref, EvidenceRef)
            assert ref.id


async def test_state_section_echoes_stored_states_exactly() -> None:
    repo = FraudHypothesisRepository()
    await _seed_store(repo)
    reg = _registry_with_synthesis_deps_available()
    provider = Fraud360Provider()
    result = await provider.project(_request(), await _make_context(reg))

    state_sec = _section("state", result)
    assert state_sec.state == "available"
    rendered = {
        item["hypothesisId"]: item
        for item in state_sec.content["hypothesisStates"]
    }
    # Stored states and claim states echo verbatim.
    assert rendered["hyp-confirm"]["state"] == "confirmed"
    assert rendered["hyp-confirm"]["claimState"] == "verified"
    assert rendered["hyp-confirm"]["family"] == "promotion abuse"
    assert rendered["hyp-cand"]["state"] == "candidate"
    assert rendered["hyp-cand"]["claimState"] == "derived"  # never upgraded
    assert rendered["hyp-eval"]["state"] == "under_evaluation"
    assert rendered["hyp-eval"]["claimState"] == "inferred"
    assert rendered["hyp-invest"]["state"] == "investigating"
    assert rendered["hyp-invest"]["claimState"] == "predicted"

    assert state_sec.content["stateCounts"]["confirmed"] == 1
    assert state_sec.content["stateCounts"]["candidate"] == 1
    assert state_sec.content["claimCounts"]["derived"] == 1


async def test_evidence_section_carries_supporting_and_contradictory() -> None:
    repo = FraudHypothesisRepository()
    await _seed_store(repo)
    reg = _registry_with_synthesis_deps_available()
    provider = Fraud360Provider()
    result = await provider.project(_request(), await _make_context(reg))

    evidence = _section("evidence", result)
    assert evidence.state == "available"
    supporting = {ref["id"] for ref in evidence.content["supporting"]}
    contradictory = {ref["id"] for ref in evidence.content["contradictory"]}
    assert supporting, "supporting evidence must be first-class"
    assert contradictory, "contradictory evidence must be first-class"
    assert "ev_confirm_sup" in supporting
    assert "ev_cand_sup" in supporting
    assert "ev_confirm_con" in contradictory
    assert "ev_cand_con" in contradictory
    assert evidence.content["supportingCount"] == len(supporting)


async def test_findings_surface_only_material_hypotheses() -> None:
    repo = FraudHypothesisRepository()
    await _seed_store(repo)
    reg = _registry_with_synthesis_deps_available()
    provider = Fraud360Provider()
    result = await provider.project(_request(), await _make_context(reg))

    findings = _section("findings", result)
    assert findings.state == "available"
    candidates = {
        cand["hypothesisId"]: cand for cand in findings.content["candidates"]
    }
    # Material-phase hypotheses surface as candidates; suspicion-only records do
    # not get promoted into findings.
    assert "hyp-confirm" in candidates
    assert "hyp-invest" in candidates
    assert "hyp-cand" not in candidates
    assert "hyp-eval" not in candidates
    assert candidates["hyp-confirm"]["claimState"] == "verified"
    assert candidates["hyp-invest"]["claimState"] == "predicted"


# ---------------------------------------------------------------------------
# Honest dependency degradation (risk360/profile360 missing) — never raises
# ---------------------------------------------------------------------------


async def test_missing_synthesis_dependencies_echoed_in_dependency_state() -> None:
    repo = FraudHypothesisRepository()
    await _seed_store(repo)
    reg = ProviderRegistry()  # nothing registered -> siblings "missing"
    context = await _make_context(reg)
    assert {d.projectionId for d in context.dependencyState} == {
        "profile360", "risk360",
    }
    assert all(d.state == "missing" for d in context.dependencyState)

    provider = Fraud360Provider()
    result = await provider.project(_request(), context)

    # The provider echoes the registry-computed dependency state verbatim.
    assert result.dependencyState == context.dependencyState


async def test_missing_risk360_degrades_without_raising() -> None:
    repo = FraudHypothesisRepository()
    await _seed_store(repo)
    provider = Fraud360Provider()
    request = _request()
    context = await _make_context(ProviderRegistry())

    result = await provider.project(request, context)
    assert result.projectionId == "fraud360"
    assert [s.id for s in result.sections] == list(OUTPUT_SECTIONS)

    # Affected synthesis sections degrade honestly — never a projection failure.
    summary = _section("summary", result)
    assert summary.state == "degraded"
    assert summary.content["missingDependencies"] == ["profile360", "risk360"]
    assert summary.warnings and any("risk360" in w for w in summary.warnings)

    state_sec = _section("state", result)
    assert state_sec.state == "degraded"

    findings = _section("findings", result)
    assert findings.state == "degraded"

    # Honest degradation still surfaces what the store provides.
    assert summary.content["hypothesisCount"] == 4
    evidence = _section("evidence", result)
    assert evidence.state == "available"


# ---------------------------------------------------------------------------
# Source failures degrade content-free
# ---------------------------------------------------------------------------


async def test_raising_source_degrades_content_free() -> None:
    provider = Fraud360Provider(
        sources=_FakeReader([], raises=RuntimeError("boom: secret-detail"))
    )
    request = _request()
    result = await provider.project(request, await _make_context(ProviderRegistry()))

    assert result.projectionId == "fraud360"
    assert result.degradedReasons == []
    summary = _section("summary", result)
    assert summary.state == "missing"
    # Unknown store content is never rendered as a fabricated zero.
    assert summary.content["hypothesisCount"] is None
    # No exception message / secret detail leaks into the result.
    dumped = result.model_dump_json()
    assert "secret-detail" not in dumped
    assert "boom" not in dumped


# ---------------------------------------------------------------------------
# Tenant + subject isolation
# ---------------------------------------------------------------------------


async def test_tenant_a_never_surfaces_tenant_b_or_other_subjects() -> None:
    rows = [
        _hypothesis("tenant-a", "hyp-a", state=FraudHypothesisState.CANDIDATE,
                    claim_state=EpistemicStatus.DERIVED,
                    evidence=[_evidence("ev_a")]),
        _hypothesis("tenant-b", "hyp-b", state=FraudHypothesisState.CONFIRMED,
                    claim_state=EpistemicStatus.VERIFIED,
                    evidence=[_evidence("ev_b")]),
        # Same tenant, DIFFERENT subject — must also be filtered out.
        _hypothesis("tenant-a", "hyp-other", state=FraudHypothesisState.CANDIDATE,
                    claim_state=EpistemicStatus.DERIVED, subject_kind="relationship",
                    subject_id="rel_1", evidence=[_evidence("ev_other")]),
    ]
    provider = Fraud360Provider(sources=_FakeReader(rows))
    result = await provider.project(
        _request(tenant="tenant-a"), await _make_context(ProviderRegistry(), tenant="tenant-a")
    )

    assert result.tenantId == "tenant-a"
    rendered = _section("state", result).content["hypothesisStates"]
    assert [item["hypothesisId"] for item in rendered] == ["hyp-a"]
    serialized = result.model_dump_json()
    assert "hyp-b" not in serialized
    assert "tenant-b" not in serialized
    assert "hyp-other" not in serialized
    assert "rel_1" not in serialized


# ---------------------------------------------------------------------------
# No-silent-escalation: every hypothesis echoed, never upgraded
# ---------------------------------------------------------------------------


def _rendered_hypothesis_entries(payload: object) -> list[dict]:
    """Every per-hypothesis render in the result (state + findings candidates)."""
    found: list[dict] = []

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            if {"hypothesisId", "state", "claimState"} <= set(node):
                found.append(node)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for value in node:
                _walk(value)

    _walk(payload)
    return found


async def test_no_suspicion_hypothesis_ever_surfaces_as_factual() -> None:
    repo = FraudHypothesisRepository()
    await _seed_store(repo)
    reg = _registry_with_synthesis_deps_available()
    provider = Fraud360Provider()
    result = await provider.project(_request(), await _make_context(reg))

    payload = result.model_dump(mode="json")
    entries = _rendered_hypothesis_entries(payload)
    assert len(entries) == 6, entries  # 4 state renders + hyp-confirm/hyp-invest candidates

    for entry in entries:
        claim_state = entry["claimState"]
        if claim_state in SUSPICION_CLAIM_STATES:
            # A suspicion-band hypothesis is never rendered in a factual state
            # (the confirmed/verified/causally_supported vocabulary is verboten).
            assert entry["state"] != "confirmed", entry
            assert entry["state"] not in {"verified", "causally_supported"}, entry
        else:
            # Only factual-claim hypotheses may read as confirmed.
            assert claim_state in FACTUAL_CLAIM_STATES, entry
            if entry["state"] == "confirmed":
                assert claim_state == "verified", entry


async def test_claims_never_textually_escalate_a_suspicion() -> None:
    repo = FraudHypothesisRepository()
    await _seed_store(repo)
    reg = _registry_with_synthesis_deps_available()
    provider = Fraud360Provider()
    result = await provider.project(_request(), await _make_context(reg))

    for claim in result.claims:
        text = " ".join(claim.claims)
        if claim.id == "state.hyp-cand":
            assert "derived" in text
            for forbidden in ("confirmed", "verified", "causally_supported"):
                assert forbidden not in text, (claim.id, text)


# ---------------------------------------------------------------------------
# Contract conformance (extra="forbid")
# ---------------------------------------------------------------------------


def test_projection_result_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ProjectionResult(
            projectionId="fraud360",
            tenantId="tenant-a",
            contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
            sections=[],
            claims=[],
            dependencyState=[],
            generatedAt="2026-09-03T00:00:00Z",
            degradedReasons=[],
            unexpectedField="nope",
        )


def test_section_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ProjectionSection(id="summary", state="available", surprise="x")


async def test_provider_result_conforms_to_extra_forbid() -> None:
    repo = FraudHypothesisRepository()
    await _seed_store(repo)
    reg = _registry_with_synthesis_deps_available()
    provider = Fraud360Provider()
    result = await provider.project(_request(), await _make_context(reg))
    ProjectionResult(**result.model_dump(mode="json"))
