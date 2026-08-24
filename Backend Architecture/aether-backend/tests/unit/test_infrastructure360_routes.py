"""Infrastructure360 vertical slice — route + route-classification tests.

The projection's public API is a **read-only** FastAPI router at prefix
``/v1/infrastructure`` (every route a GET), classified in
``config/route_registry.yaml`` ``known_prefixes`` (default-deny ratchet), and a
surface entry in ``surface-capability-registry.json``. The projection handler
composes a ``ProjectionRequest`` and delegates to the fail-isolated
``ProviderRegistry``.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

# parents[3] is the "Backend Architecture" directory; parents[4] is the repo
# root (config/route_registry.yaml and packages/… live at the repo root).
BACKEND_DIR = Path(__file__).resolve().parents[3]
BACKEND_ROOT = BACKEND_DIR / "aether-backend"
REPO_ROOT = Path(__file__).resolve().parents[4]

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

import yaml  # noqa: E402

from services.infrastructure.routes import (  # noqa: E402
    EXPLORE_CAPABILITY,
    READ_CAPABILITY,
    create_router,
    router,
)
from shared.intelligence_projections.contracts import (  # noqa: E402
    ProjectionRequest,
    ProjectionResult,
)
from shared.intelligence_projections.generated_registry import (  # noqa: E402
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
)


# ---------------------------------------------------------------------------
# Router shape — prefix + read-only
# ---------------------------------------------------------------------------

def test_router_prefix_is_v1_infrastructure() -> None:
    assert router.prefix == "/v1/infrastructure"


def test_every_route_is_a_read_only_get() -> None:
    assert router.routes, "router must expose routes"
    for route in router.routes:
        methods = getattr(route, "methods", None)
        assert methods is not None
        assert methods <= {"GET"}, (
            f"infrastructure360 routes are read-only; {sorted(methods)} found"
        )
    paths = {getattr(r, "path", "") for r in router.routes}
    assert "/v1/infrastructure/{subject_kind}/{subject_id}" in paths
    assert "/v1/infrastructure/health" in paths


def test_capability_keys_are_the_projection_registry_keys() -> None:
    assert READ_CAPABILITY == "infrastructure360.read"
    assert EXPLORE_CAPABILITY == "infrastructure360.explore"


# ---------------------------------------------------------------------------
# Route classification — config/route_registry.yaml + surface registry
# ---------------------------------------------------------------------------

def test_route_registry_declares_v1_infrastructure_prefix() -> None:
    route_registry_path = REPO_ROOT / "config" / "route_registry.yaml"
    assert route_registry_path.exists()
    data = yaml.safe_load(route_registry_path.read_text())
    known_prefixes = data["known_prefixes"]
    assert "/v1/infrastructure" in known_prefixes
    # Placed alphabetically between /v1/imports and /v1/ingest.
    assert known_prefixes.index("/v1/imports") < known_prefixes.index(
        "/v1/infrastructure"
    ) < known_prefixes.index("/v1/ingest")


def test_surface_registry_declares_infrastructure360_surface() -> None:
    surface_path = (
        REPO_ROOT / "packages" / "shared" / "contracts" / "surface-capability-registry.json"
    )
    assert surface_path.exists()
    data = json.loads(surface_path.read_text())
    surface_ids = [s["surfaceId"] for s in data["surfaces"]]
    assert "infrastructure360" in surface_ids
    surface = data["surfaces"][surface_ids.index("infrastructure360")]
    # The append must satisfy the surface validator's vocabulary constraints.
    field_categories = {
        "entity",
        "time",
        "geography",
        "device",
        "graph",
        "risk",
        "campaign",
        "economic",
        "truth",
    }
    assert set(surface["supportedFieldCategories"]) <= field_categories
    assert surface["supportedFieldCategories"]
    assert set(surface["supportedTemporalModes"]) <= set(data["temporalModes"])
    assert set(surface["supportedViews"]) <= set(data["views"])
    for key in (
        "supportsFacets",
        "supportsComparison",
        "supportsSelectionSets",
        "supportsSavedViews",
        "supportsExport",
    ):
        assert isinstance(surface[key], bool)


# ---------------------------------------------------------------------------
# create_router + health probe
# ---------------------------------------------------------------------------

def test_create_router_binds_a_registry() -> None:
    bound = create_router(registry=SimpleNamespace())
    assert bound.prefix == "/v1/infrastructure"


def test_health_probe_is_read_only_introspection() -> None:
    from services.infrastructure.routes import _registry_health

    class _FakeRegistry:
        def availability(self) -> dict[str, dict[str, Any]]:
            return {
                "infrastructure360": {
                    "registered": True,
                    "registryState": "implemented",
                    "contractCompatible": True,
                }
            }

    health = _registry_health(_FakeRegistry())
    assert health["projectionId"] == "infrastructure360"
    assert health["graphMutationPolicy"] == "read_only"
    assert health["availability"]["registered"] is True
    assert health["capabilityKeys"] == [READ_CAPABILITY, EXPLORE_CAPABILITY]


@pytest.mark.asyncio
async def test_projection_endpoint_composes_request_and_delegates() -> None:
    seen: dict[str, Any] = {}

    class _FakeRegistry:
        async def project(self, projection_id: str, request: ProjectionRequest) -> ProjectionResult:
            seen["projection_id"] = projection_id
            seen["request"] = request
            return ProjectionResult.model_construct(
                projectionId=projection_id,
                tenantId=request.tenantId,
                contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
                sections=[],
                claims=[],
                dependencyState=[],
                generatedAt="2026-08-24T00:00:00Z",
                degradedReasons=[],
            )

    bound = create_router(registry=_FakeRegistry())
    projection_route = next(
        r for r in bound.routes if getattr(r, "path", "") == "/v1/infrastructure/{subject_kind}/{subject_id}"
    )

    fake_tenant = SimpleNamespace(tenant_id="tenant-a", require_permission=lambda p: None)
    fake_request = SimpleNamespace(state=SimpleNamespace(tenant=fake_tenant))

    payload = await projection_route.endpoint(
        subject_kind="entity", subject_id="inf_1", request=fake_request
    )

    assert seen["projection_id"] == "infrastructure360"
    assert seen["request"].tenantId == "tenant-a"
    assert seen["request"].subject.kind == "entity"
    assert seen["request"].subject.id == "inf_1"
    # The tenant in the payload is the authenticated tenant, never the path.
    assert payload["tenantId"] == "tenant-a"
    assert payload["projectionId"] == "infrastructure360"


def test_projection_endpoint_is_tenant_scoped_from_request_state() -> None:
    # The handler derives tenantId from the authenticated request, so a caller
    # can never ask the projection about another tenant via the path.
    endpoint = next(
        r.endpoint
        for r in router.routes
        if getattr(r, "path", "") == "/v1/infrastructure/{subject_kind}/{subject_id}"
    )
    # The endpoint's signature is (subject_kind, subject_id, request) — there is
    # no tenant path parameter to tamper with.
    import inspect

    signature = inspect.signature(endpoint)
    assert "tenant" not in signature.parameters
    assert "subject_kind" in signature.parameters
    assert "subject_id" in signature.parameters


def test_capability_gate_fails_closed_when_projection_not_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Fail-CLOSED, not fail-open: a projection whose capabilityKeys are absent
    # from the generated map (e.g. a stale twin) must DENY, never silently open
    # a read gate.
    from services.infrastructure import routes as infra_routes
    from shared.common.common import ForbiddenError

    monkeypatch.setattr(
        infra_routes, "PROJECTION_CAPABILITY_MAP", {"profile360": {"profile360.read"}}
    )
    fake_tenant = SimpleNamespace(tenant_id="tenant-a", require_permission=lambda p: None)
    fake_request = SimpleNamespace(state=SimpleNamespace(tenant=fake_tenant))
    with pytest.raises(ForbiddenError):
        infra_routes._require_infrastructure360_read(fake_request)
