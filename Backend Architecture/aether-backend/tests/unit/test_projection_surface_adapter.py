"""ProjectionSurfaceAdapter (S6) — 360 projection surfaces through the S1 engine.

The exploration fabric's migration seam maps the three projection-backed 360
surfaces (outcome360 / economic360 / infrastructure360) onto their intelligence
projections and executes them through the S1 engine's fail-isolated executor.
Under test: surface→projection mapping, typed-section composition into an
AdapterResult carrying digest + per-section state, tenant isolation, and the
content-free fail-closed degradation path (missing provider / invalid lens
frame) — plus the no-shadowing guarantee for already-owned surfaces.
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

from shared.exploration.models import (  # noqa: E402
    ExplorationAnchor,
    ExplorationContextV1,
    ExplorationScope,
    SelectionSet,
    TemporalSelection,
)
from shared.intelligence_projections.contracts import (  # noqa: E402
    ClaimEnvelope,
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

from services.exploration.adapters import (  # noqa: E402
    AdapterContext,
    get_adapter,
    available_surfaces,
)
from services.exploration.adapters.campaign import CampaignSurfaceAdapter  # noqa: E402
from services.exploration.adapters.geo import GeoSurfaceAdapter  # noqa: E402
from services.exploration.adapters.graph import GraphSurfaceAdapter  # noqa: E402
from services.exploration.adapters.profile import ProfileSurfaceAdapter  # noqa: E402
from services.exploration.adapters.projection import (  # noqa: E402
    Economic360SurfaceAdapter,
    Infrastructure360SurfaceAdapter,
    Outcome360SurfaceAdapter,
)

# Registered output sections per newly-added 360 surface (registry rows).
_OUTPUT_SECTIONS = {
    "outcome360": ("summary", "state", "evidence", "outcomes", "findings"),
    "economic360": ("summary", "state", "evidence", "outcomes", "findings"),
    "infrastructure360": ("summary", "state", "deployments", "evidence", "findings"),
}

# Projection dependencies (registry graph, flat closure) registered so clean
# runs are un-degraded: outcome360 -> temporal360; economic360 -> outcome360/
# profile360/relationship360 (plus their own transitive deps: outcome360 and
# relationship360 both require temporal360); infrastructure360 has none.
_DEPS = {
    "outcome360": ("temporal360",),
    "economic360": (
        "outcome360",
        "profile360",
        "relationship360",
        "temporal360",
    ),
    "infrastructure360": (),
}


def _context(
    surface: str,
    tenant_id: str = "tenant-a",
    *,
    lens_set=None,
    temporal_mode=None,
    focus=None,
) -> ExplorationContextV1:
    return ExplorationContextV1(
        scope=ExplorationScope(tenant_id=tenant_id, surface=surface),
        temporal=TemporalSelection(mode="window", field="occurred_at", timezone="UTC"),
        lens_set=lens_set,
        temporal_mode=temporal_mode,
        selection=SelectionSet(focused=focus) if focus is not None else None,
    )


class _SectionedProvider:
    """A provider rendering typed sections (real vocab) + a contentful claim."""

    def __init__(self, projection_id: str) -> None:
        self.projection_id = projection_id
        self.contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
        self.request: ProjectionRequest | None = None

    async def project(
        self, request: ProjectionRequest, context: ProjectionContext
    ) -> ProjectionResult:
        self.request = request
        section_ids = _OUTPUT_SECTIONS.get(
            self.projection_id, (f"{self.projection_id}.summary",)
        )
        return ProjectionResult(
            projectionId=request.projectionId,
            tenantId=request.tenantId,
            contractVersion=self.contract_version,
            sections=[
                ProjectionSection(
                    id=sid,
                    state="available",
                    title=f"{self.projection_id} {sid}",
                    content={"projection": self.projection_id, "section": sid},
                )
                for sid in section_ids
            ],
            claims=[
                ClaimEnvelope(
                    id=f"{self.projection_id}.claim.1",
                    kind="observation",
                    subject=request.subject,
                    evidenceRefs=[],
                    claims=["typed-section observation"],
                )
            ],
            dependencyState=list(context.dependencyState),
            generatedAt="2026-09-02T12:00:00Z",
            degradedReasons=[],
        )


class _TenantAwareProvider:
    """A provider recording which tenants it is asked about (isolation)."""

    def __init__(self, projection_id: str) -> None:
        self.projection_id = projection_id
        self.contract_version = INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
        self.requests: list[str] = []

    async def project(
        self, request: ProjectionRequest, context: ProjectionContext
    ) -> ProjectionResult:
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


def _adapter(
    cls: type,
    projection_id: str,
    *,
    with_provider: bool = True,
    tenant_aware: bool = False,
) -> tuple:
    """Build a concrete projection-surface adapter over a fresh registry."""
    registry = ProviderRegistry()
    if with_provider:
        provider_cls = _TenantAwareProvider if tenant_aware else _SectionedProvider
        for dep in _DEPS[projection_id]:
            registry.register(_SectionedProvider(dep))
        registry.register(provider_cls(projection_id))
    runtime = ProjectionRuntime(executor=ProjectionExecutor(registry=registry))
    return cls(runtime=runtime), registry


def _adapter_ctx(adapter, **kwargs) -> AdapterContext:
    return AdapterContext(
        tenant_id=kwargs.pop("tenant_id", "tenant-a"),
        context=_context(adapter.surface_id, **kwargs),
        applied_filters=[],
    )


# ---------------------------------------------------------------------------
# Surface → projection mapping + registry wiring
# ---------------------------------------------------------------------------

def test_surfaces_map_to_their_projection_ids() -> None:
    for cls, surface in (
        (Outcome360SurfaceAdapter, "outcome360"),
        (Economic360SurfaceAdapter, "economic360"),
        (Infrastructure360SurfaceAdapter, "infrastructure360"),
    ):
        adapter = cls()
        assert adapter.surface_id == surface
        assert adapter.resolved_projection_id == surface


def test_registered_surfaces_do_not_shadow_owned_ones() -> None:
    # The three 360 surfaces are now available...
    assert isinstance(get_adapter("outcome360"), Outcome360SurfaceAdapter)
    assert isinstance(get_adapter("economic360"), Economic360SurfaceAdapter)
    assert isinstance(get_adapter("infrastructure360"), Infrastructure360SurfaceAdapter)
    for surface in ("outcome360", "economic360", "infrastructure360"):
        assert surface in available_surfaces()

    # ...while every already-owned surface keeps its original adapter (no shadow).
    assert isinstance(get_adapter("profile360"), ProfileSurfaceAdapter)
    assert get_adapter("profile360").surface_id == "profile360"
    assert isinstance(get_adapter("campaign360"), CampaignSurfaceAdapter)
    assert get_adapter("campaign360").surface_id == "campaign360"
    assert isinstance(get_adapter("graph"), GraphSurfaceAdapter)
    assert isinstance(get_adapter("geo"), GeoSurfaceAdapter)

    # A non-360 surface this adapter does not own stays absent (honest not-available).
    assert get_adapter("comparison_workbench") is None


# ---------------------------------------------------------------------------
# Composition through a fresh-registry stub provider
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cls", "surface"),
    [
        (Outcome360SurfaceAdapter, "outcome360"),
        (Economic360SurfaceAdapter, "economic360"),
        (Infrastructure360SurfaceAdapter, "infrastructure360"),
    ],
)
async def test_projection_surface_composes_typed_sections(cls, surface) -> None:
    adapter, _ = _adapter(cls, surface)
    result = await adapter.execute(_adapter_ctx(adapter))

    assert result.populated is True
    assert result.backend == "intelligence_projection"
    assert result.surface == surface
    assert result.data["available"] is True
    assert result.data["projectionId"] == surface
    assert result.data["tenantId"] == "tenant-a"
    assert isinstance(result.data["digest"], str) and len(result.data["digest"]) == 64
    assert result.data["degradationState"] == "none"
    section_ids = {s["id"] for s in result.data["sections"]}
    assert section_ids == set(_OUTPUT_SECTIONS[surface])
    assert {s["state"] for s in result.data["sections"]} == {"available"}


@pytest.mark.asyncio
async def test_projection_surface_derives_subject_from_focused_anchor() -> None:
    adapter, registry = _adapter(Infrastructure360SurfaceAdapter, "infrastructure360")
    focus = ExplorationAnchor(kind="deployment", id="dep-42")
    result = await adapter.execute(
        _adapter_ctx(adapter, focus=focus)
    )
    assert result.populated is True
    # The surface adapter's runtime delegated to the stub which recorded the
    # request — the focused deployment became the projection subject.
    provider = registry.list()[0]
    assert provider.request.subject.kind == "deployment"
    assert provider.request.subject.id == "dep-42"


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_projection_surface_is_tenant_scoped() -> None:
    adapter, registry = _adapter(
        Outcome360SurfaceAdapter, "outcome360", tenant_aware=True
    )
    provider = next(p for p in registry.list() if p.projection_id == "outcome360")
    # Two tenants run through the SAME adapter/registry — every request the
    # engine saw carried exactly the tenant the context scoped, never the other.
    result_a = await adapter.execute(_adapter_ctx(adapter, tenant_id="tenant-a"))
    result_b = await adapter.execute(_adapter_ctx(adapter, tenant_id="tenant-b"))

    assert result_a.data["tenantId"] == "tenant-a"
    assert result_b.data["tenantId"] == "tenant-b"
    assert provider.requests == ["tenant-a", "tenant-b"]


# ---------------------------------------------------------------------------
# Fail-isolated degradation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_missing_provider_degrades_content_free() -> None:
    # No provider (nor dependency) registered for the surface's projection.
    adapter, _ = _adapter(
        Infrastructure360SurfaceAdapter, "infrastructure360", with_provider=False
    )
    result = await adapter.execute(_adapter_ctx(adapter))

    assert result.populated is False
    assert result.data["available"] is False
    assert result.data["reason"] == "provider_unavailable"
    assert result.data["sections"] == []
    assert result.warnings == ["provider_unavailable"]
    # Content-free: the static code, never a provider/engine diagnostic string.
    assert "no provider registered" not in result.data["reason"]


@pytest.mark.asyncio
async def test_missing_target_provider_degrades_when_dependency_registered() -> None:
    # outcome360's temporal360 dependency exists but the outcome360 target does
    # not -> the surface still degrades content-free rather than raising.
    adapter, registry = _adapter(Outcome360SurfaceAdapter, "outcome360")
    registry.unregister("outcome360")

    result = await adapter.execute(_adapter_ctx(adapter))
    assert result.populated is False
    assert result.data["available"] is False
    assert result.data["reason"] == "provider_unavailable"


@pytest.mark.asyncio
async def test_invalid_lens_frame_degrades_content_free() -> None:
    adapter, _ = _adapter(Outcome360SurfaceAdapter, "outcome360")
    result = await adapter.execute(
        _adapter_ctx(adapter, lens_set=["not_a_registered_lens"])
    )
    assert result.populated is False
    assert result.data["available"] is False
    assert result.data["reason"] == "lens_frame_invalid"
    assert result.warnings == ["lens_frame_invalid"]
