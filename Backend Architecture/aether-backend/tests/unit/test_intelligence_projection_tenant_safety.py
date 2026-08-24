"""Tenant-isolation tests for the intelligence projection registry (P0.5, group 7).

A projection is tenant-scoped: a provider must build sections ONLY from the
requesting tenant's ``tenantId`` / ``subject``. The registry itself must hold no
tenant data — two sequential ``project()`` calls for different tenants leave no
residue, and interleaved awaits never cross tenants. Tenant B's sections must
never appear in tenant A's result.
"""

from __future__ import annotations

import asyncio
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

from shared.intelligence_projections import (  # noqa: E402
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
    ProviderRegistry,
)


def _request(tenant_id: str, subject_id: str) -> ProjectionRequest:
    return ProjectionRequest(
        projectionId="profile360",
        tenantId=tenant_id,
        subject=ProjectionSubject(kind="entity", id=subject_id),
    )


class _TenantScopedProvider:
    """Builds sections from the REQUESTING tenant + subject — never global state."""

    projection_id = "profile360"
    contract_version = "1.0.0"

    async def project(self, request: ProjectionRequest, context: object) -> ProjectionResult:
        # The only tenant identity this provider knows is the one on the request.
        return ProjectionResult(
            projectionId=request.projectionId,
            tenantId=request.tenantId,
            contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
            sections=[
                ProjectionSection(
                    id="summary",
                    state="available",
                    title="Tenant summary",
                    content={
                        "tenantId": request.tenantId,
                        "subjectId": request.subject.id,
                    },
                ),
            ],
            claims=[],
            dependencyState=context.dependencyState,  # type: ignore[attr-defined]
            generatedAt="2026-08-23T12:00:00Z",
            degradedReasons=[],
        )


def _tenant_ids(result: ProjectionResult) -> set[tuple[str, str]]:
    return {(section.id, section.content["subjectId"]) for section in result.sections}


# ---------------------------------------------------------------------------
# Sequential isolation: tenant A never sees tenant B
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_two_tenants_on_same_registry_yield_only_own_sections() -> None:
    registry = ProviderRegistry()
    registry.register(_TenantScopedProvider())

    result_a = await registry.project("profile360", _request("tenant-a", "ent_a_1"))
    result_b = await registry.project("profile360", _request("tenant-b", "ent_b_1"))

    # Each result is tagged with its OWN tenant.
    assert result_a.tenantId == "tenant-a"
    assert result_b.tenantId == "tenant-b"
    # Sections carry ONLY the requesting tenant's identity.
    assert _tenant_ids(result_a) == {("summary", "ent_a_1")}
    assert _tenant_ids(result_b) == {("summary", "ent_b_1")}
    # Cross-contamination check: no tenant-a section inside tenant-b's result
    # and no tenant-b section inside tenant-a's result.
    assert "tenant-a" not in [s.content["tenantId"] for s in result_b.sections]
    assert "tenant-b" not in [s.content["tenantId"] for s in result_a.sections]


# ---------------------------------------------------------------------------
# No shared mutable state in the registry instance
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_registry_holds_no_tenant_data_and_leaves_no_residue() -> None:
    registry = ProviderRegistry()
    registry.register(_TenantScopedProvider())

    await registry.project("profile360", _request("tenant-a", "ent_a_1"))
    await registry.project("profile360", _request("tenant-b", "ent_b_1"))

    # The registry's public introspection exposes NO tenant data — only
    # registration facts (this is also a fail-closed shape guarantee).
    entry = registry.availability()["profile360"]
    assert set(entry) == {"registered", "registryState", "contractCompatible"}
    assert "tenant" not in "".join(str(registry.sources())).lower()

    # A third call for tenant-a reproduces tenant-a's EXACT result — no residue
    # from the intervening tenant-b call.
    again = await registry.project("profile360", _request("tenant-a", "ent_a_1"))
    first = await registry.project("profile360", _request("tenant-a", "ent_a_1"))
    assert again == first
    assert _tenant_ids(again) == {("summary", "ent_a_1")}


# ---------------------------------------------------------------------------
# Interleaved awaits never cross tenants
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_interleaved_awaits_do_not_cross_tenants() -> None:
    registry = ProviderRegistry()
    registry.register(_TenantScopedProvider())

    # Interleave the awaits so both coroutines share the same registry instance.
    results = await asyncio.gather(
        registry.project("profile360", _request("tenant-a", "ent_a_1")),
        registry.project("profile360", _request("tenant-b", "ent_b_1")),
        registry.project("profile360", _request("tenant-a", "ent_a_1")),
        registry.project("profile360", _request("tenant-c", "ent_c_1")),
    )

    # Every result carries exactly its requesting tenant's identity.
    by_tenant: dict[str, set[tuple[str, str]]] = {}
    for result in results:
        by_tenant.setdefault(result.tenantId, set()).update(_tenant_ids(result))
    assert by_tenant == {
        "tenant-a": {("summary", "ent_a_1")},
        "tenant-b": {("summary", "ent_b_1")},
        "tenant-c": {("summary", "ent_c_1")},
    }
