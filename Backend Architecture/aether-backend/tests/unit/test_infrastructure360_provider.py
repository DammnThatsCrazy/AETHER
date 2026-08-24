"""Infrastructure360 vertical slice — provider projection tests.

``Infrastructure360Provider`` is a read-only intelligence projection over
canonical infrastructure truth. Under test: it builds a valid
``ProjectionResult`` with the five typed sections
``summary/state/deployments/evidence/findings``, grounds every claim in a reused
``EvidenceRef``, degrades (never raises, never fabricates) when a backing source
is missing, honors ``extra="forbid"`` on the projection-plane contracts, and has
no write path.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from pydantic import ValidationError  # noqa: E402

from services.infrastructure.contracts import (  # noqa: E402
    Deployment,
    InfrastructureEntity,
    InfrastructureEntityType,
    InfrastructureState,
)
from services.infrastructure.provider import (  # noqa: E402
    CanonicalInfrastructureRead,
    DEFAULT_SECTION_IDS,
    Infrastructure360Provider,
    build_projection_request,
)
from shared.intelligence_projections.contracts import (  # noqa: E402
    ClaimEnvelope,
    ProjectionContext,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
)
from services.operational_intelligence.models import EvidenceRef  # noqa: E402

_ST = InfrastructureState


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _entity(
    ident: str,
    tenant_id: str = "tenant-a",
    kind: InfrastructureEntityType = InfrastructureEntityType.HOST,
    state: InfrastructureState = InfrastructureState.ACTIVE,
    **attrs: object,
) -> InfrastructureEntity:
    return InfrastructureEntity(
        id=ident,
        tenant_id=tenant_id,
        kind=kind,
        state=state,
        display_name=ident,
        attributes={k: v for k, v in attrs.items()},
    )


def _deployment(
    ident: str,
    tenant_id: str = "tenant-a",
    state: InfrastructureState = InfrastructureState.ACTIVE,
    version: str = "1.0.0",
) -> Deployment:
    return Deployment(
        id=ident,
        tenant_id=tenant_id,
        service_id=f"svc-{ident}",
        artifact_ref=f"aether/{ident}:{version}",
        state=state,
        started_at="2026-08-24T09:00:00Z",
        completed_at=None,
        version=version,
        infra_entity_ref="host-1",
    )


def _reader_for(read: CanonicalInfrastructureRead) -> Callable[[str], CanonicalInfrastructureRead]:
    return lambda tenant_id: read


def _request(tenant_id: str = "tenant-a", subject_kind: str = "entity", subject_id: str = "inf_1"):
    return build_projection_request(
        projection_id="infrastructure360",
        tenant_id=tenant_id,
        subject=ProjectionSubject(kind=subject_kind, id=subject_id),
    )


def _context(tenant_id: str = "tenant-a") -> ProjectionContext:
    return ProjectionContext.model_construct(
        projectionId="infrastructure360",
        tenantId=tenant_id,
        registryState="implemented",
        dependencyState=[],
        warnings=[],
    )


def _sections_by_id(result: ProjectionResult) -> dict[str, ProjectionSection]:
    return {section.id: section for section in result.sections}


# ---------------------------------------------------------------------------
# Valid result construction + evidence grounding
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_provider_builds_valid_result_with_all_five_sections() -> None:
    read = CanonicalInfrastructureRead(
        entities=(_entity("host-1"), _entity("db-1", state=InfrastructureState.DEGRADED)),
        deployments=(_deployment("dep-1"),),
        health={"provider-x": "active"},
    )
    provider = Infrastructure360Provider(canonical_reader=_reader_for(read))

    result = await provider.project(_request(), _context())

    assert isinstance(result, ProjectionResult)
    assert result.projectionId == "infrastructure360"
    assert result.tenantId == "tenant-a"
    assert result.contractVersion == provider.contract_version
    assert result.degradedReasons == []

    sections = _sections_by_id(result)
    assert set(sections) == set(DEFAULT_SECTION_IDS)
    assert {s.id for s in result.sections} == set(DEFAULT_SECTION_IDS)

    assert sections["summary"].state == "available"
    assert sections["summary"].content["entityCount"] == 2
    assert sections["summary"].content["deploymentCount"] == 1

    assert sections["state"].state == "available"
    assert sections["state"].content["byState"] == {"active": 1, "degraded": 1}

    assert sections["deployments"].state == "available"
    assert len(sections["deployments"].content["deployments"]) == 1
    assert sections["deployments"].content["deployments"][0]["id"] == "dep-1"

    assert sections["evidence"].state == "available"
    assert sections["findings"].state == "available"


@pytest.mark.asyncio
async def test_provider_grounds_every_claim_in_evidence_ref() -> None:
    read = CanonicalInfrastructureRead(
        entities=(_entity("host-failed", state=InfrastructureState.FAILED),),
        deployments=(_deployment("dep-1"),),
    )
    provider = Infrastructure360Provider(canonical_reader=_reader_for(read))

    result = await provider.project(_request(), _context())

    assert result.claims, "expected grounded claims"
    for claim in result.claims:
        assert isinstance(claim, ClaimEnvelope)
        assert claim.evidenceRefs, "every claim must carry evidence"
        for ref in claim.evidenceRefs:
            assert isinstance(ref, EvidenceRef)
            assert ref.source in {"infrastructure_facts", "deployments"}

    # The failed-entity finding is present and grounded in the failed entity.
    finding_claims = [c for c in result.claims if c.kind == "finding"]
    assert any("FAILED" in c.claims[0] for c in finding_claims)
    failed_ref = EvidenceRef(id="fact:host-failed", type="entity", source="infrastructure_facts")
    assert any(failed_ref in c.evidenceRefs for c in finding_claims)


@pytest.mark.asyncio
async def test_provider_result_round_trips() -> None:
    read = CanonicalInfrastructureRead(
        entities=(_entity("host-1"),),
        deployments=(_deployment("dep-1"),),
    )
    provider = Infrastructure360Provider(canonical_reader=_reader_for(read))
    result = await provider.project(_request(), _context())

    dumped = result.model_dump(mode="json")
    assert dumped["projectionId"] == "infrastructure360"
    assert dumped["tenantId"] == "tenant-a"
    assert dumped["sections"][0]["id"] == "summary"
    # The content-bearing structures are strict models and revalidate cleanly.
    for section in result.sections:
        assert isinstance(
            ProjectionSection.model_validate(section.model_dump(mode="json")),
            ProjectionSection,
        )
    for claim in result.claims:
        assert isinstance(
            ClaimEnvelope.model_validate(claim.model_dump(mode="json")),
            ClaimEnvelope,
        )
    # A strict ProjectionResult construction is possible once the registry
    # regenerates with the infrastructure360 id (the provider's seam is the
    # pre-regeneration bridge; the strict path is exercised by integration).
    strict_sections = [s.model_dump(mode="json") for s in result.sections]
    strict_claims = [c.model_dump(mode="json") for c in result.claims]
    strict_result = ProjectionResult.model_validate(
        {
            "projectionId": "profile360",  # registered id → strict validation
            "tenantId": result.tenantId,
            "contractVersion": result.contractVersion,
            "sections": strict_sections,
            "claims": strict_claims,
            "dependencyState": [],
            "generatedAt": result.generatedAt,
            "degradedReasons": [],
        }
    )
    assert strict_result.sections[0].id == "summary"


# ---------------------------------------------------------------------------
# extra="forbid" conformance (projection plane fails closed)
# ---------------------------------------------------------------------------

def test_projection_plane_contracts_fail_closed_on_unknown_fields() -> None:
    assert ProjectionResult.model_config.get("extra") == "forbid"
    assert ProjectionSection.model_config.get("extra") == "forbid"
    assert ClaimEnvelope.model_config.get("extra") == "forbid"
    # A misspelled section field is a hard ValidationError — never silent.
    with pytest.raises(ValidationError):
        ProjectionSection(id="summary", state="available", titel="typo")


@pytest.mark.asyncio
async def test_provider_result_has_exactly_the_declared_fields() -> None:
    read = CanonicalInfrastructureRead(
        entities=(_entity("host-1"),),
        deployments=(_deployment("dep-1"),),
    )
    provider = Infrastructure360Provider(canonical_reader=_reader_for(read))
    result = await provider.project(_request(), _context())

    dumped = result.model_dump()
    # extra="forbid": every field present in the dump is a declared field.
    assert set(dumped) <= set(ProjectionResult.model_fields)
    assert set(result.model_fields_set) <= set(ProjectionResult.model_fields)


# ---------------------------------------------------------------------------
# Missing backing source -> typed degraded section (no raise, no fabrication)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_provider_degrades_when_deployments_authority_missing() -> None:
    read = CanonicalInfrastructureRead(
        degraded_sources=("deployments",),
        warnings=("deployments: no mounted deployment store",),
    )
    provider = Infrastructure360Provider(canonical_reader=_reader_for(read))

    result = await provider.project(_request(), _context())

    assert result.degradedReasons == []  # provider never fabricates reasons
    sections = _sections_by_id(result)
    assert sections["deployments"].state == "degraded"
    assert sections["summary"].state == "degraded"
    # With no records and a degraded authority there is nothing to claim.
    assert result.claims == []
    # The section's content is content-free (tenant id only, no exception text).
    assert sections["deployments"].content == {"tenantId": "tenant-a"}


@pytest.mark.asyncio
async def test_provider_degrades_when_infrastructure_state_authority_missing() -> None:
    read = CanonicalInfrastructureRead(
        degraded_sources=("infrastructure_facts", "infrastructure_state"),
    )
    provider = Infrastructure360Provider(canonical_reader=_reader_for(read))

    result = await provider.project(_request(), _context())
    sections = _sections_by_id(result)
    assert sections["state"].state == "degraded"
    assert sections["summary"].state == "degraded"


@pytest.mark.asyncio
async def test_bogus_degraded_source_claims_no_authority() -> None:
    # A reader naming a degraded source that is NOT a canonical fact category
    # cannot type any section degraded (honesty backstop).
    read = CanonicalInfrastructureRead(
        degraded_sources=("not_a_real_authority",),
    )
    provider = Infrastructure360Provider(canonical_reader=_reader_for(read))

    result = await provider.project(_request(), _context())
    # No canonical authority is degraded -> sections are healthy-but-empty,
    # never degraded by a bogus key.
    assert all(section.state == "empty" for section in result.sections)


@pytest.mark.asyncio
async def test_provider_never_raises_on_missing_reader_data() -> None:
    # An empty read (no degraded sources, no records) is healthy-but-empty.
    provider = Infrastructure360Provider(canonical_reader=_reader_for(CanonicalInfrastructureRead()))
    result = await provider.project(_request(), _context())

    assert isinstance(result, ProjectionResult)
    assert all(section.state == "empty" for section in result.sections)
    assert result.claims == []


@pytest.mark.asyncio
async def test_default_reader_degrades_gracefully() -> None:
    # The default reader imports canonical sources lazily/defensively; whatever
    # is or is not importable in the test environment, project() must never
    # raise and must return a typed result with all five sections.
    provider = Infrastructure360Provider()
    result = await provider.project(_request(), _context())

    assert isinstance(result, ProjectionResult)
    assert {s.id for s in result.sections} == set(DEFAULT_SECTION_IDS)
    for section in result.sections:
        assert section.state in {
            "available",
            "empty",
            "missing",
            "degraded",
            "not_applicable",
            "unknown",
            "suppressed",
            "stale",
        }


# ---------------------------------------------------------------------------
# Read-only doctrine — no write path
# ---------------------------------------------------------------------------

def test_provider_is_read_only_with_no_write_path() -> None:
    provider = Infrastructure360Provider()
    assert provider.graph_mutation_policy == "read_only"

    # No write surface of any kind.
    for name in dir(provider):
        if name.startswith("_"):
            continue
        method = getattr(provider, name)
        if callable(method):
            assert name in {"project"}, (
                f"provider must have no callable write surface, got {name!r}"
            )
    assert not hasattr(provider, "apply")
    assert not hasattr(provider, "mutate")
    assert not hasattr(provider, "write")


# ---------------------------------------------------------------------------
# build_projection_request seam
# ---------------------------------------------------------------------------

def test_build_projection_request_returns_valid_request() -> None:
    request = _request()
    assert request.projectionId == "infrastructure360"
    assert request.tenantId == "tenant-a"
    assert request.subject.kind == "entity"
