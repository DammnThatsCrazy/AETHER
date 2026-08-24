"""Unit tests for the Economic360 intelligence-projection provider (slice S3).

The provider is a read-only, fail-isolated, tenant-scoped projection over
canonical economic truth (ADR-010). These tests cover:

* a valid ``ProjectionResult`` with the registry's typed sections and
  evidence-grounded claims;
* ``extra="forbid"`` conformance (the plane fails closed);
* honest degradation when ``profile360`` / ``relationship360`` / ``outcome360``
  are still ``in_flight`` — recorded in ``dependencyState``, projection still
  returns, never raises;
* degraded results stay content-free when a backing source is unavailable;
* tenant isolation — tenant A never surfaces tenant B's sections/evidence;
* registration via ``register_provider`` (success, duplicate, version
  mismatch, unknown id).
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

from services.economic.economic360_provider import (  # noqa: E402
    OUTPUT_SECTIONS,
    Economic360Provider,
    RepositoryEconomicSourceReader,
    register_provider,
)
from services.operational_intelligence.models import EvidenceRef  # noqa: E402
from shared.intelligence_projections import (  # noqa: E402
    ContractVersionIncompatible,
    DuplicateProjection,
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
    ProjectionContext,
    ProjectionNotFound,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
    ProviderRegistry,
)


def _request(tenant: str = "tenant-a", **overrides: object) -> ProjectionRequest:
    values: dict[str, object] = {
        "projectionId": "economic360",
        "tenantId": tenant,
        "subject": ProjectionSubject(kind="campaign", id="camp_1"),
    }
    values.update(overrides)
    return ProjectionRequest(**values)


async def _make_context(
    reg: ProviderRegistry, tenant: str = "tenant-a"
) -> ProjectionContext:
    """Build a runtime context for an economic360 request (registry truth)."""
    return await reg.build_context("economic360", _request(tenant=tenant))


class FakeSource:
    """Canonical-source test double returning tenant-scoped value records."""

    def __init__(
        self,
        records: list[dict],
        *,
        raises: Exception | None = None,
    ) -> None:
        self._records = records
        self._raises = raises

    async def records(self, *, tenant_id: str, subject: object) -> list[dict]:
        if self._raises is not None:
            raise self._raises
        return list(self._records)


def _record(
    tenant: str,
    amount: str,
    currency: str,
    *,
    usd: str | None = None,
    metric: str = "gross_value",
    ident: str = "ev",
) -> dict:
    return {
        "tenant_id": tenant,
        "amount": amount,
        "currency": currency,
        "value_usd": usd,
        "metric_kind": "flow",
        "_source": "test",
        "_evidence_id": ident,
        "_evidence_type": "transaction",
        "_evidence_source": "test/fake",
        "_evidence_uri": f"store://test/{ident}",
        "_metric_name": metric,
    }


@pytest.fixture
def healthy_source() -> FakeSource:
    return FakeSource(
        [
            _record("tenant-a", "1000.00", "USD", usd="1000.00", metric="campaign_spend", ident="a_spend"),
            _record("tenant-a", "2500.00", "USD", usd="2500.00", metric="gross_value", ident="a_gross"),
        ]
    )


# ---------------------------------------------------------------------------
# Valid result: typed sections + evidence-grounded claims
# ---------------------------------------------------------------------------

async def test_project_returns_valid_result(healthy_source: FakeSource) -> None:
    provider = Economic360Provider(sources=healthy_source)
    request = _request()
    result = await provider.project(request, await _make_context(ProviderRegistry()))

    assert isinstance(result, ProjectionResult)
    assert result.projectionId == "economic360"
    assert result.tenantId == "tenant-a"
    assert result.contractVersion == INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    assert result.generatedAt  # ISO-8601 UTC
    assert result.degradedReasons == []


async def test_project_emits_exact_registry_sections(healthy_source: FakeSource) -> None:
    provider = Economic360Provider(sources=healthy_source)
    result = await provider.project(_request(), await _make_context(ProviderRegistry()))

    assert [s.id for s in result.sections] == list(OUTPUT_SECTIONS)
    assert OUTPUT_SECTIONS == ("summary", "state", "evidence", "outcomes", "findings")


async def test_section_states_are_typed(healthy_source: FakeSource) -> None:
    provider = Economic360Provider(sources=healthy_source)
    result = await provider.project(_request(), await _make_context(ProviderRegistry()))
    valid_states = {
        "available", "degraded", "empty", "missing", "not_applicable", "unknown",
    }
    for section in result.sections:
        assert section.state in valid_states, section.id


async def test_claims_are_evidence_grounded(healthy_source: FakeSource) -> None:
    provider = Economic360Provider(sources=healthy_source)
    result = await provider.project(_request(), await _make_context(ProviderRegistry()))

    assert result.claims, "expected evidence-grounded claims"
    for claim in result.claims:
        assert isinstance(claim.subject, ProjectionSubject)
        assert claim.evidenceRefs, (
            f"requiresEvidence: claim {claim.id!r} must carry EvidenceRefs"
        )
        for ref in claim.evidenceRefs:
            assert isinstance(ref, EvidenceRef)
            assert ref.id
    # The spend claim reflects the absorbed campaign_spend metric vocabulary.
    spend_claims = [c for c in result.claims if c.kind == "campaign_spend"]
    assert spend_claims


async def test_summary_surfaces_absorbed_metrics(healthy_source: FakeSource) -> None:
    provider = Economic360Provider(sources=healthy_source)
    result = await provider.project(_request(), await _make_context(ProviderRegistry()))

    summary = next(s for s in result.sections if s.id == "summary")
    metrics = summary.content["metrics"]
    assert metrics["campaign_spend"]["unit"] == "usd"
    assert metrics["campaign_spend"]["usd_value"] == "1000.00"
    assert metrics["gross_value"]["usd_value"] == "2500.00"
    assert metrics["campaign_roas"]["value"] == "2.5000"
    # Not derivable without customer counts — honest absence, never fabricated.
    assert metrics["campaign_cac"]["usd_value"] is None
    assert metrics["campaign_ltv"]["usd_value"] is None


# ---------------------------------------------------------------------------
# extra="forbid" conformance
# ---------------------------------------------------------------------------

def test_projection_result_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ProjectionResult(
            projectionId="economic360",
            tenantId="tenant-a",
            contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
            sections=[],
            claims=[],
            dependencyState=[],
            generatedAt="2026-08-24T00:00:00Z",
            degradedReasons=[],
            unexpectedField="nope",
        )


def test_section_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ProjectionSection(id="summary", state="available", surprise="x")


async def test_provider_result_conforms_to_extra_forbid(healthy_source: FakeSource) -> None:
    provider = Economic360Provider(sources=healthy_source)
    result = await provider.project(_request(), await _make_context(ProviderRegistry()))
    # Round-trip through the strict contract proves no unexpected fields leak.
    dumped = result.model_dump(mode="json")
    ProjectionResult(**dumped)


# ---------------------------------------------------------------------------
# Missing in_flight dependencies -> recorded + degraded, never raising
# ---------------------------------------------------------------------------

async def test_missing_dependencies_recorded_in_dependency_state(
    healthy_source: FakeSource,
) -> None:
    reg = ProviderRegistry()  # nothing registered -> all siblings "missing"
    context = await _make_context(reg)
    assert {d.projectionId for d in context.dependencyState} == {
        "outcome360", "profile360", "relationship360",
    }
    assert all(d.state == "missing" for d in context.dependencyState)

    provider = Economic360Provider(sources=healthy_source)
    result = await provider.project(_request(), context)

    # The provider echoes the registry-computed dependency state verbatim.
    assert result.dependencyState == context.dependencyState
    assert {d.projectionId for d in result.dependencyState} == {
        "outcome360", "profile360", "relationship360",
    }


async def test_outcome_section_degraded_when_outcome360_missing(
    healthy_source: FakeSource,
) -> None:
    provider = Economic360Provider(sources=healthy_source)
    result = await provider.project(_request(), await _make_context(ProviderRegistry()))

    outcomes = next(s for s in result.sections if s.id == "outcomes")
    assert outcomes.state == "degraded"
    assert "not yet implemented" in outcomes.content["reason"]
    # Honest degradation still surfaces what canonical truth provides.
    assert outcomes.content["outcome_value_usd"] == "2500.00"


async def test_dependency_degradation_does_not_raise(healthy_source: FakeSource) -> None:
    provider = Economic360Provider(sources=healthy_source)
    # No registration, no deps available, and yet the projection returns.
    result = await provider.project(_request(), await _make_context(ProviderRegistry()))
    assert result.projectionId == "economic360"
    assert [s.id for s in result.sections] == list(OUTPUT_SECTIONS)


# ---------------------------------------------------------------------------
# Degraded results stay content-free (never crash, never fabricate)
# ---------------------------------------------------------------------------

async def test_unavailable_source_degrades_without_raising() -> None:
    provider = Economic360Provider(
        sources=FakeSource([], raises=RuntimeError("boom: secret-detail"))
    )
    result = await provider.project(_request(), await _make_context(ProviderRegistry()))

    assert result.projectionId == "economic360"
    assert result.degradedReasons == []
    summary = next(s for s in result.sections if s.id == "summary")
    assert summary.state == "missing"
    # No exception message / secret detail leaks into the result.
    assert "secret-detail" not in result.model_dump_json()
    assert "boom" not in result.model_dump_json()


async def test_raising_reader_never_fabricates_a_total() -> None:
    provider = Economic360Provider(sources=FakeSource([], raises=RuntimeError("x")))
    result = await provider.project(_request(), await _make_context(ProviderRegistry()))
    summary = next(s for s in result.sections if s.id == "summary")
    assert summary.content["total_usd"] is None  # not 0, not invented


# ---------------------------------------------------------------------------
# Tenant isolation — tenant A never surfaces tenant B
# ---------------------------------------------------------------------------

async def test_tenant_a_never_surfaces_tenant_b_economics() -> None:
    source = FakeSource(
        [
            _record("tenant-a", "1000.00", "USD", usd="1000.00", metric="campaign_spend", ident="a_spend"),
            _record("tenant-a", "2500.00", "USD", usd="2500.00", metric="gross_value", ident="a_gross"),
            _record("tenant-b", "999999.00", "USD", usd="999999.00", metric="gross_value", ident="b_gross"),
            _record("tenant-b", "12345.00", "USD", usd="12345.00", metric="campaign_spend", ident="b_spend"),
        ]
    )
    provider = Economic360Provider(sources=source)
    result = await provider.project(
        _request(tenant="tenant-a"), await _make_context(ProviderRegistry(), tenant="tenant-a")
    )

    assert result.tenantId == "tenant-a"
    evidence = next(s for s in result.sections if s.id == "evidence")
    evidence_ids = [e["id"] for e in evidence.content["evidence"]]
    assert all(ident.startswith("a_") for ident in evidence_ids), evidence_ids
    summary = next(s for s in result.sections if s.id == "summary")
    # Total reflects only tenant-a records.
    assert summary.content["total_usd"] == "3500.00"
    # No tenant-b identifier surfaces anywhere in the result.
    serialized = result.model_dump_json()
    assert "tenant-b" not in serialized
    assert "999999" not in serialized


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_register_provider_succeeds_on_fresh_registry() -> None:
    reg = ProviderRegistry()
    register_provider(reg)
    assert "economic360" in reg.sources()
    assert reg.sources()["economic360"] == "services/economic"
    provider = reg.require("economic360")
    assert isinstance(provider, Economic360Provider)


def test_register_duplicate_different_object_raises() -> None:
    reg = ProviderRegistry()
    register_provider(reg)
    with pytest.raises(DuplicateProjection) as excinfo:
        register_provider(reg)
    assert excinfo.value.projection_id == "economic360"


def test_register_version_mismatch_raises() -> None:
    class _WrongVersion:
        projection_id = "economic360"
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
    assert (
        Economic360Provider.contract_version
        == INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    )
    # The default reader is the repository-backed one (no injection).
    assert isinstance(Economic360Provider()._sources, RepositoryEconomicSourceReader)
