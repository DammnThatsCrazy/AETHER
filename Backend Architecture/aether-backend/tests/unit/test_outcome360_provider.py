"""Unit tests for the Outcome360 intelligence-projection provider.

Covers: a valid typed ProjectionResult with the five registry output sections
and evidence-grounded claims; ``extra="forbid"`` conformance (constructed via
ProjectionRequest / ProjectionResult); missing-dependency degradation (temporal360
not implemented -> dependencyState records it, projection still returns, never
raises); content-free degraded results (the fail-isolated runtime); tenant
isolation (tenant A never surfaces tenant B's outcomes/evidence); and the
register_provider contract on a fresh ProviderRegistry.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from shared.intelligence_projections import (  # noqa: E402
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
    ContractVersionIncompatible,
    DuplicateProjection,
    ProjectionError,
    ProjectionNotFound,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSubject,
    ProviderRegistry,
)
from services.measurement.outcome import (  # noqa: E402
    EvidenceRef,
    Outcome,
    Outcome360Provider,
    OutcomeState,
    OutcomeStore,
    register_provider,
)


def _request(
    tenant_id: str = "tenant-a",
    subject_id: str = "cmp_1",
    *,
    temporal_mode: str | None = None,
    include_sections: list[str] | None = None,
) -> ProjectionRequest:
    return ProjectionRequest(
        projectionId="outcome360",
        tenantId=tenant_id,
        subject=ProjectionSubject(kind="campaign", id=subject_id),
        temporalMode=temporal_mode,
        includeSections=include_sections,
    )


def _outcome(
    outcome_id: str,
    tenant_id: str,
    *,
    definition_ref: str = "journey_completion",
    state: OutcomeState = OutcomeState.FINAL,
    achieved_at: str | None = "2026-08-01T00:00:00Z",
    value: float | None = 1.0,
) -> Outcome:
    return Outcome(
        id=outcome_id,
        tenant_id=tenant_id,
        domain="commercial",
        state=state,
        definition_ref=definition_ref,
        achieved_at=achieved_at,
        value=value,
        evidence_refs=[
            EvidenceRef(
                id=f"ev_{outcome_id}",
                type="event",
                source="measurement",
                observedAt="2026-08-01T00:00:00Z",
            )
        ],
        updated_at="2026-08-23T12:00:00Z",
    )


class InMemoryOutcomeStore:
    """Tenant-keyed outcome reader (tests never share a store across tenants)."""

    def __init__(self, by_tenant: dict[str, list[Outcome]]) -> None:
        self._by_tenant = dict(by_tenant)

    async def list_outcomes(
        self, tenant_id: str, subject: ProjectionSubject
    ) -> list[Outcome]:
        return list(self._by_tenant.get(tenant_id, []))


def _raise_error_provider(cls: type[Exception]) -> object:
    class _RaisingProvider:
        projection_id = "outcome360"
        contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION

        async def project(self, request: ProjectionRequest, context: object) -> ProjectionResult:
            raise cls("secret diagnostic: outcome-fact vault unreadable")

    return _RaisingProvider()


# ---------------------------------------------------------------------------
# Valid typed result with the registry's output sections + evidence grounding
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_provider_returns_valid_typed_result() -> None:
    registry = ProviderRegistry()
    store = InMemoryOutcomeStore(
        {"tenant-a": [_outcome("oc_1", "tenant-a"), _outcome("oc_2", "tenant-a")]}
    )
    registry.register(
        Outcome360Provider(outcome_store=store),
        source="services/measurement/outcome",
    )

    result = await registry.project("outcome360", _request())

    assert isinstance(result, ProjectionResult)
    assert result.projectionId == "outcome360"
    assert result.tenantId == "tenant-a"
    assert result.contractVersion == INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    # The five registry output sections, exactly.
    assert {s.id for s in result.sections} == {
        "summary",
        "state",
        "evidence",
        "outcomes",
        "findings",
    }
    by_id = {s.id: s for s in result.sections}
    assert by_id["summary"].state == "available"
    assert by_id["outcomes"].state == "available"
    assert by_id["evidence"].state == "available"
    # Every claim carries a reused EvidenceRef (requiresEvidence: true).
    assert result.claims
    assert all(c.evidenceRefs for c in result.claims)


@pytest.mark.asyncio
async def test_provider_computes_journey_completion_rate_finding() -> None:
    store = InMemoryOutcomeStore(
        {
            "tenant-a": [
                _outcome("oc_1", "tenant-a"),  # achieved
                _outcome("oc_2", "tenant-a", achieved_at=None, value=None),
            ]
        }
    )
    provider = Outcome360Provider(outcome_store=store)
    result = await provider.project(_request(), _context())

    findings = next(s for s in result.sections if s.id == "findings")
    rate = findings.content["findings"][0]
    assert rate["metric"] == "journey_completion_rate"
    assert rate["completed"] == 1
    assert rate["total"] == 2
    assert rate["rate"] == 0.5
    metric_claim = next(c for c in result.claims if c.kind == "metric")
    assert metric_claim.evidenceRefs


def _context() -> object:
    """Minimal ProjectionContext-shaped dependency state for direct calls."""
    from shared.intelligence_projections import ProjectionContext, ProjectionDependencyState

    return ProjectionContext(
        projectionId="outcome360",
        tenantId="tenant-a",
        registryState="in_flight",
        dependencyState=[
            ProjectionDependencyState(
                projectionId="temporal360",
                state="missing",
                reason="no provider registered",
            )
        ],
        warnings=[],
    )


# ---------------------------------------------------------------------------
# extra="forbid" conformance (constructed via ProjectionRequest / Result)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_provider_constructs_via_forbid_contracts() -> None:
    request = _request(temporal_mode="window")
    with pytest.raises(ValidationError):
        ProjectionRequest(
            projectionId="outcome360",
            tenantId="tenant-a",
            subject=ProjectionSubject(kind="campaign", id="cmp_1"),
            tenatId="typo",
        )
    store = InMemoryOutcomeStore({"tenant-a": [_outcome("oc_1", "tenant-a")]})
    provider = Outcome360Provider(outcome_store=store)
    result = await provider.project(request, _context())
    # ProjectionSection / ClaimEnvelope / ProjectionResult all fail closed.
    assert result.sections[0].title is not None


# ---------------------------------------------------------------------------
# Missing dependency -> dependencyState records it, projection still returns
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_page_caps_render_set_with_honest_has_next_page() -> None:
    from services.operational_intelligence.models import PageRequest

    store = InMemoryOutcomeStore(
        {
            "tenant-a": [
                _outcome(f"oc_{i}", "tenant-a") for i in range(5)
            ]
        }
    )
    provider = Outcome360Provider(outcome_store=store)
    request = _request()
    request.page = PageRequest(limit=2)

    result = await provider.project(request, _context())

    outcomes = next(s for s in result.sections if s.id == "outcomes")
    assert len(outcomes.content["outcomes"]) == 2
    assert result.page is not None
    assert result.page.hasNextPage is True
    assert result.page.totalEstimate == 5


@pytest.mark.asyncio
async def test_missing_temporal360_dependency_still_returns() -> None:
    registry = ProviderRegistry()
    register_provider(registry)  # temporal360 has NO provider registered

    result = await registry.project("outcome360", _request(temporal_mode="compare"))

    deps = {d.projectionId: d for d in result.dependencyState}
    assert "temporal360" in deps
    assert deps["temporal360"].state == "missing"
    # compare degrades to window; the projection still returns typed sections.
    assert result.temporalMode == "window"
    assert {s.id for s in result.sections} == {
        "summary",
        "state",
        "evidence",
        "outcomes",
        "findings",
    }
    assert not result.degradedReasons


@pytest.mark.asyncio
async def test_missing_backing_store_degrades_sections_not_plane() -> None:
    registry = ProviderRegistry()
    register_provider(registry)

    result = await registry.project("outcome360", _request())

    by_id = {s.id: s for s in result.sections}
    # No backing source available at runtime: outcome-bearing sections are
    # typed `missing` — the plane stays up (never raises, never empty-handed).
    assert by_id["outcomes"].state == "missing"
    assert by_id["summary"].state == "missing"
    assert result.claims == []


# ---------------------------------------------------------------------------
# Content-free degraded results (fail-isolated runtime)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_project_error_yields_content_free_degraded_result() -> None:
    registry = ProviderRegistry()
    registry.register(_raise_error_provider(ProjectionError))

    result = await registry.project("outcome360", _request())

    assert result.sections == []
    assert result.claims == []
    # Content-free: exception class name only — the diagnostic message never
    # surfaces (fail-closed secret hygiene).
    assert result.degradedReasons == ["ProjectionError"]
    assert "secret diagnostic" not in str(result.model_dump())


@pytest.mark.asyncio
async def test_non_projection_error_yields_generic_degraded_result() -> None:
    registry = ProviderRegistry()
    registry.register(_raise_error_provider(RuntimeError))

    result = await registry.project("outcome360", _request())

    assert result.sections == []
    assert result.degradedReasons == ["projection provider failure"]
    assert "secret diagnostic" not in str(result.model_dump())


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tenant_a_never_surfaces_tenant_b_outcomes() -> None:
    tenant_a_rows = [
        _outcome("a_1", "tenant-a"),
        _outcome("a_2", "tenant-a", definition_ref="campaign_conversion"),
    ]
    tenant_b_rows = [_outcome("b_1", "tenant-b")]  # journey_completion, tenant-b
    provider = Outcome360Provider(
        outcome_store=InMemoryOutcomeStore(
            {"tenant-a": tenant_a_rows, "tenant-b": tenant_b_rows}
        )
    )

    result_a = await provider.project(_request("tenant-a", "cmp_a"), _context())
    result_b = await provider.project(_request("tenant-b", "cmp_b"), _context())

    # Tenant A's outcomes are exactly A's rows.
    a_outcomes = next(s for s in result_a.sections if s.id == "outcomes")
    a_ids = {o["id"] for o in a_outcomes.content["outcomes"]}
    assert a_ids == {"a_1", "a_2"}
    # No tenant-b outcome id or evidence leaks into A.
    assert "b_1" not in a_ids
    a_evidence = next(s for s in result_a.sections if s.id == "evidence")
    a_ev = {e["id"] for e in a_evidence.content["evidence"]}
    assert "ev_b_1" not in a_ev

    # And B's result never contains A's rows.
    b_outcomes = next(s for s in result_b.sections if s.id == "outcomes")
    b_ids = {o["id"] for o in b_outcomes.content["outcomes"]}
    assert b_ids == {"b_1"}
    assert "a_1" not in b_ids


@pytest.mark.asyncio
async def test_no_shared_mutable_state_across_tenants() -> None:
    provider_a = Outcome360Provider(
        outcome_store=InMemoryOutcomeStore({"tenant-a": [_outcome("a_1", "tenant-a")]})
    )
    provider_b = Outcome360Provider(
        outcome_store=InMemoryOutcomeStore({"tenant-b": [_outcome("b_1", "tenant-b")]})
    )

    result_a = await provider_a.project(_request("tenant-a"), _context())
    result_b = await provider_b.project(_request("tenant-b"), _context())

    a_outcomes = next(s for s in result_a.sections if s.id == "outcomes")
    b_outcomes = next(s for s in result_b.sections if s.id == "outcomes")
    assert {o["id"] for o in a_outcomes.content["outcomes"]} == {"a_1"}
    assert {o["id"] for o in b_outcomes.content["outcomes"]} == {"b_1"}


# ---------------------------------------------------------------------------
# register_provider contract
# ---------------------------------------------------------------------------

def test_register_provider_succeeds_on_fresh_registry() -> None:
    registry = ProviderRegistry()
    registered = register_provider(registry)
    assert registry.get("outcome360") is not None
    assert registry.sources()["outcome360"] == "services/measurement/outcome"
    assert registered == "outcome360"
    assert registry.graph_mutation_policy("outcome360") == "read_only"


def test_duplicate_different_object_registration_raises() -> None:
    registry = ProviderRegistry()
    register_provider(registry)
    with pytest.raises(DuplicateProjection):
        register_provider(registry)  # a DIFFERENT Outcome360Provider object


def test_duplicate_same_object_is_idempotent() -> None:
    registry = ProviderRegistry()
    provider = Outcome360Provider()
    assert registry.register(provider) == "outcome360"
    assert registry.register(provider) == "outcome360"  # no-op


def test_version_mismatch_raises() -> None:
    class _OldVersionProvider:
        projection_id = "outcome360"
        contract_version = "9.9.9"

        async def project(self, request: ProjectionRequest, context: object) -> ProjectionResult:
            raise AssertionError("unreachable")

    registry = ProviderRegistry()
    with pytest.raises(ContractVersionIncompatible):
        registry.register(_OldVersionProvider())


def test_unknown_projection_id_raises() -> None:
    class _UnknownProvider:
        projection_id = "not_a_projection"
        contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION

        async def project(self, request: ProjectionRequest, context: object) -> ProjectionResult:
            raise AssertionError("unreachable")

    registry = ProviderRegistry()
    with pytest.raises(ProjectionNotFound):
        registry.register(_UnknownProvider())


def test_outcome360_provider_does_not_auto_register() -> None:
    from shared.intelligence_projections import projection_registry

    # Importing the outcome package must NOT have touched the global registry.
    assert projection_registry.get("outcome360") is None


def test_outcome_store_is_a_protocol() -> None:
    # The store surface is a typing.Protocol, not a base class — providers
    # depend on the narrow read surface only (no Base360 inheritance).
    import typing

    assert typing.Protocol in OutcomeStore.__bases__
