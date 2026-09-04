"""Communication360 vertical slice — read-surface route tests.

The ``/v1/communication360`` router is a read-only projection surface. These
tests pin the route shape, the health probe, the tenant read gate (fail-closed
on a missing declared capability), and the tolerant projection-request builder.
The router is mounted flag-gated (``AETHER_COMMUNICATION360_ENABLED``, OFF by
default), so these tests exercise the module directly with an injected registry.
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from shared.common.common import ForbiddenError  # noqa: E402
from shared.intelligence_projections.contracts import ProjectionSubject  # noqa: E402

import services.communication360.routes as routes_mod  # noqa: E402
from services.communication360.routes import (  # noqa: E402
    EXPLORE_CAPABILITY,
    PROJECTION_ID,
    READ_CAPABILITY,
    create_router,
)


class _Tenant:
    def __init__(self, tenant_id: str, can_read: bool = True) -> None:
        self.tenant_id = tenant_id
        self._can_read = can_read

    def require_permission(self, permission: str) -> None:
        if permission != "read" or not self._can_read:
            raise ForbiddenError(f"missing permission {permission!r}")


class _Request:
    def __init__(self, tenant: _Tenant) -> None:
        self.state = SimpleNamespace(tenant=tenant)


def _registry_double() -> SimpleNamespace:
    return SimpleNamespace(
        availability=lambda: {
            PROJECTION_ID: {
                "registered": True,
                "contractCompatible": True,
                "registryState": "implemented",
            }
        },
        project=lambda *a, **k: None,
    )


def test_route_surface_constants() -> None:
    assert PROJECTION_ID == "communication360"
    assert READ_CAPABILITY == "communication360.read"
    assert EXPLORE_CAPABILITY == "communication360.explore"


def test_create_router_shape() -> None:
    router = create_router(registry=_registry_double())
    assert router.prefix == "/v1/communication360"
    path_specs = {(r.path, tuple(sorted(r.methods or []))) for r in router.routes}
    assert ("/v1/communication360/health", ("GET",)) in path_specs
    assert (
        "/v1/communication360/{subject_kind}/{subject_id}",
        ("GET",),
    ) in path_specs


def test_health_probe_reports_read_only_projection() -> None:
    body = routes_mod._registry_health(_registry_double())
    assert body["projectionId"] == "communication360"
    assert body["graphMutationPolicy"] == "read_only"
    assert body["capabilityKeys"] == ["communication360.read", "communication360.explore"]
    assert body["availability"]["registryState"] == "implemented"


def test_read_gate_returns_tenant_when_permission_and_capability_declared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        routes_mod,
        "PROJECTION_CAPABILITY_MAP",
        {PROJECTION_ID: {READ_CAPABILITY, EXPLORE_CAPABILITY}},
    )
    tenant_id = routes_mod._require_communication360_read(_Request(_Tenant("tenant-a")))
    assert tenant_id == "tenant-a"


def test_read_gate_fails_closed_when_capability_undeclared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Absence (not just contradiction) fails closed: a generated capability map
    # that predates the row must never silently open a read gate.
    monkeypatch.setattr(routes_mod, "PROJECTION_CAPABILITY_MAP", {})
    with pytest.raises(ForbiddenError):
        routes_mod._require_communication360_read(_Request(_Tenant("tenant-a")))


def test_read_gate_fails_closed_without_read_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        routes_mod,
        "PROJECTION_CAPABILITY_MAP",
        {PROJECTION_ID: {READ_CAPABILITY}},
    )
    with pytest.raises(ForbiddenError):
        routes_mod._require_communication360_read(_Request(_Tenant("tenant-a", can_read=False)))


def test_build_projection_request_is_tenant_bound() -> None:
    request = routes_mod._build_projection_request(
        projection_id=PROJECTION_ID,
        tenant_id="tenant-a",
        subject=ProjectionSubject(kind="campaign", id="camp_1"),
    )
    assert request.projectionId == PROJECTION_ID
    assert request.tenantId == "tenant-a"
    assert request.subject.kind == "campaign"
    assert request.subject.id == "camp_1"
