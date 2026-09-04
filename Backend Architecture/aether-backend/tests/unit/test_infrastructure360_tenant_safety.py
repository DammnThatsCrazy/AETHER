"""Infrastructure360 vertical slice — tenant isolation tests.

ADR-010 security invariant: tenant scope is server-authoritative end to end;
cross-tenant evidence leakage is forbidden. The provider derives everything
from ``request.tenantId`` and re-filters reader output by tenant as a backstop,
so tenant A's projection can never surface tenant B's deployments or evidence —
even when the underlying reader is given both tenants' records.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from services.infrastructure.contracts import (  # noqa: E402
    Deployment,
    InfrastructureEntity,
    InfrastructureEntityType,
    InfrastructureState,
)
from services.infrastructure.provider import (  # noqa: E402
    CanonicalInfrastructureRead,
    Infrastructure360Provider,
    build_projection_request,
)
from shared.intelligence_projections.contracts import (  # noqa: E402
    ProjectionContext,
    ProjectionResult,
    ProjectionSubject,
)


def _entity(ident: str, tenant_id: str) -> InfrastructureEntity:
    return InfrastructureEntity(
        id=ident,
        tenant_id=tenant_id,
        kind=InfrastructureEntityType.HOST,
        state=InfrastructureState.ACTIVE,
        display_name=ident,
    )


def _deployment(ident: str, tenant_id: str) -> Deployment:
    return Deployment(
        id=ident,
        tenant_id=tenant_id,
        service_id=f"svc-{ident}",
        artifact_ref=f"aether/{ident}:1.0.0",
        state=InfrastructureState.ACTIVE,
        started_at="2026-08-24T09:00:00Z",
        completed_at=None,
        version="1.0.0",
        infra_entity_ref=f"host-{ident}",
    )


def _context(tenant_id: str) -> ProjectionContext:
    return ProjectionContext.model_construct(
        projectionId="infrastructure360",
        tenantId=tenant_id,
        registryState="implemented",
        dependencyState=[],
        warnings=[],
    )


@pytest.mark.asyncio
async def test_tenant_a_projection_never_surfaces_tenant_b_records() -> None:
    # The reader is GIVEN both tenants' records (a hostile / misbehaving
    # reader). The provider must still project only tenant A.
    read = CanonicalInfrastructureRead(
        entities=(
            _entity("host-a", "tenant-a"),
            _entity("host-b", "tenant-b"),
        ),
        deployments=(
            _deployment("dep-a", "tenant-a"),
            _deployment("dep-b", "tenant-b"),
        ),
        health={"shared": "active"},
    )
    provider = Infrastructure360Provider(canonical_reader=lambda _t: read)

    result = await provider.project(
        build_projection_request(
            projection_id="infrastructure360",
            tenant_id="tenant-a",
            subject=ProjectionSubject(kind="entity", id="inf_1"),
        ),
        _context("tenant-a"),
    )

    assert result.tenantId == "tenant-a"
    sections = {s.id: s for s in result.sections}

    # Deployments section: only tenant A's deployment record.
    deployment_ids = [
        d["id"] for d in sections["deployments"].content["deployments"]
    ]
    assert deployment_ids == ["dep-a"]
    assert "dep-b" not in deployment_ids

    # State section: only tenant A's entity.
    assert sections["state"].content["byState"] == {"active": 1}
    assert sections["summary"].content["entityCount"] == 1
    assert sections["summary"].content["deploymentCount"] == 1

    # Evidence: every EvidenceRef is derived from tenant A records only.
    for claim in result.claims:
        for ref in claim.evidenceRefs:
            assert ref.id.startswith(("fact:host-a", "dep:dep-a")), (
                f"tenant A claim referenced cross-tenant evidence {ref.id!r}"
            )


@pytest.mark.asyncio
async def test_tenant_a_projection_contains_no_tenant_b_evidence_ids() -> None:
    read = CanonicalInfrastructureRead(
        entities=(_entity("host-b", "tenant-b"),),
        deployments=(_deployment("dep-b", "tenant-b"),),
    )
    provider = Infrastructure360Provider(canonical_reader=lambda _t: read)

    # Ask about tenant A when the reader only holds tenant B records.
    result = await provider.project(
        build_projection_request(
            projection_id="infrastructure360",
            tenant_id="tenant-a",
            subject=ProjectionSubject(kind="entity", id="inf_1"),
        ),
        _context("tenant-a"),
    )

    assert result.tenantId == "tenant-a"
    assert result.claims == []
    assert all(s.state == "empty" for s in result.sections)
    serialized = result.model_dump(mode="json")
    assert "host-b" not in str(serialized)
    assert "dep-b" not in str(serialized)


@pytest.mark.asyncio
async def test_tenant_scope_is_server_authoritative_from_request() -> None:
    # Two concurrent projections for different tenants never share state; each
    # result derives its tenant from the request, not from a module/global.
    read = CanonicalInfrastructureRead(
        entities=(_entity("host-a", "tenant-a"), _entity("host-b", "tenant-b")),
        deployments=(_deployment("dep-a", "tenant-a"),),
    )
    provider = Infrastructure360Provider(canonical_reader=lambda _t: read)

    result_a = await provider.project(
        build_projection_request(
            projection_id="infrastructure360",
            tenant_id="tenant-a",
            subject=ProjectionSubject(kind="entity", id="inf_1"),
        ),
        _context("tenant-a"),
    )
    result_b = await provider.project(
        build_projection_request(
            projection_id="infrastructure360",
            tenant_id="tenant-b",
            subject=ProjectionSubject(kind="entity", id="inf_2"),
        ),
        _context("tenant-b"),
    )

    assert result_a.tenantId == "tenant-a"
    assert result_b.tenantId == "tenant-b"
    a_sections = {s.id: s for s in result_a.sections}
    b_sections = {s.id: s for s in result_b.sections}
    assert [d["id"] for d in a_sections["deployments"].content["deployments"]] == [
        "dep-a"
    ]
    assert b_sections["deployments"].state == "empty"
