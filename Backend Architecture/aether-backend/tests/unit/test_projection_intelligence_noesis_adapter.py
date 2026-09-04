"""Noesis Projection-Intelligence adapter (S6) — read-only 360 projection reads.

The Noesis projection adapter runs a tenant-scoped intelligence projection
through the S1 engine behind the same read-only / tenant-gated posture as the
rest of the Noesis adapter family. Under test: tenant-scoped invocation, tenant
isolation across calls, and the content-free fail-closed degradation path.
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

from shared.intelligence_projections.contracts import (  # noqa: E402
    ProjectionContext,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
)
from shared.intelligence_projections.generated_registry import (  # noqa: E402
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)
from shared.intelligence_projections.registry import ProviderRegistry  # noqa: E402
from shared.projection_engine.executor import ProjectionExecutor  # noqa: E402
from shared.projection_engine.runtime import ProjectionRuntime  # noqa: E402

from services.noesis.adapters.projection_intelligence_adapter import (  # noqa: E402
    ProjectionIntelligenceNoesisAdapter,
)


class _EchoTenantProvider:
    """A provider recording which tenants it is asked about."""

    def __init__(self, projection_id: str) -> None:
        self.projection_id = projection_id
        self.contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
        self.request: ProjectionRequest | None = None
        self.requests: list[str] = []

    async def project(
        self, request: ProjectionRequest, context: ProjectionContext
    ) -> ProjectionResult:
        self.request = request
        self.requests.append(request.tenantId)
        return ProjectionResult(
            projectionId=request.projectionId,
            tenantId=request.tenantId,
            contractVersion=self.contract_version,
            sections=[
                ProjectionSection(
                    id="summary",
                    state="available",
                    content={"tenant": request.tenantId},
                )
            ],
            claims=[],
            dependencyState=list(context.dependencyState),
            generatedAt="2026-09-02T12:00:00Z",
            degradedReasons=[],
        )


def _runtime(projection_id: str = "outcome360") -> ProjectionRuntime:
    registry = ProviderRegistry()
    # outcome360 declares temporal360 as a hard dependency — register it so the
    # run is un-degraded and only the target content flows through.
    registry.register(_EchoTenantProvider("temporal360"))
    registry.register(_EchoTenantProvider(projection_id))
    return ProjectionRuntime(executor=ProjectionExecutor(registry=registry))


def _adapter(*, runtime=None) -> ProjectionIntelligenceNoesisAdapter:
    return ProjectionIntelligenceNoesisAdapter(
        runtime=runtime if runtime is not None else _runtime()
    )


# ---------------------------------------------------------------------------
# Tenant-scoped invocation + read-only envelope
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_projection_read_is_tenant_scoped_and_read_only() -> None:
    registry = ProviderRegistry()
    registry.register(_EchoTenantProvider("temporal360"))
    provider = _EchoTenantProvider("outcome360")
    registry.register(provider)
    runtime = ProjectionRuntime(executor=ProjectionExecutor(registry=registry))
    adapter = _adapter(runtime=runtime)

    result = await adapter.projection_read(
        "tenant-a", "outcome360", subject_kind="campaign", subject_id="camp_1"
    )

    # Standard noesis envelope — read-only projection read, never a write.
    assert result["degraded"] is False
    assert result["reason"] is None
    assert result["sufficient"] is True
    assert result["sources"] == ["intelligence_projection_runtime"]
    # The projection plane answered for exactly the requested tenant, surfacing
    # digest + per-section state (never raw provider content).
    assert result["results"][0]["tenantId"] == "tenant-a"
    assert result["results"][0]["sections"] == [{"id": "summary", "state": "available"}]
    assert isinstance(result["results"][0]["digest"], str)
    # The request the engine saw was tenant-scoped and passed the subject through.
    assert provider.request.tenantId == "tenant-a"
    assert provider.request.tenantId == result["results"][0]["tenantId"]
    assert provider.request.subject.kind == "campaign"
    assert provider.request.subject.id == "camp_1"


@pytest.mark.asyncio
async def test_projection_read_isolates_tenants() -> None:
    registry = ProviderRegistry()
    registry.register(_EchoTenantProvider("temporal360"))
    provider = _EchoTenantProvider("outcome360")
    registry.register(provider)
    runtime = ProjectionRuntime(executor=ProjectionExecutor(registry=registry))
    adapter = _adapter(runtime=runtime)

    a = await adapter.projection_read("tenant-a", "outcome360")
    b = await adapter.projection_read("tenant-b", "outcome360")

    # Each answer reports exactly the tenant it was asked about (the adapter
    # surfaces digest + per-section state only — never provider content).
    assert a["results"][0]["tenantId"] == "tenant-a"
    assert b["results"][0]["tenantId"] == "tenant-b"
    assert a["results"][0]["sections"] == [{"id": "summary", "state": "available"}]
    assert b["results"][0]["sections"] == [{"id": "summary", "state": "available"}]
    # The engine saw exactly one tenant per call, in call order — never the
    # other tenant, never a cross-tenant aggregation.
    assert provider.requests == ["tenant-a", "tenant-b"]


# ---------------------------------------------------------------------------
# Fail-isolated, content-free degradation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_projection_degrades_content_free() -> None:
    # No runtime is reached — the projection id is rejected before any call.
    adapter = _adapter(runtime=ProjectionRuntime())

    result = await adapter.projection_read("tenant-a", "made_up_projection")

    assert result["degraded"] is True
    assert result["reason"] == "unknown_projection"
    assert result["sufficient"] is False
    assert result["results"] == []
    assert "made_up_projection" not in result["answer"]


@pytest.mark.asyncio
async def test_invalid_subject_kind_degrades_content_free() -> None:
    adapter = _adapter()

    result = await adapter.projection_read(
        "tenant-a", "outcome360", subject_kind="not_a_subject_kind"
    )

    assert result["degraded"] is True
    assert result["reason"] == "invalid_subject_kind"
    assert result["sufficient"] is False


@pytest.mark.asyncio
async def test_missing_provider_degrades_content_free() -> None:
    # outcome360 is a registered projection but has no provider registered —
    # the engine answers a fully-degraded result and the adapter degrades with
    # a content-free reason rather than raising or echoing engine internals.
    empty_registry = ProviderRegistry()
    runtime = ProjectionRuntime(executor=ProjectionExecutor(registry=empty_registry))
    adapter = _adapter(runtime=runtime)

    result = await adapter.projection_read("tenant-a", "outcome360")

    assert result["degraded"] is True
    assert result["reason"] == "provider_unavailable"
    assert result["sufficient"] is False
    assert result["results"] == []
