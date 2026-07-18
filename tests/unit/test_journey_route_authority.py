"""/v1/journeys authority — the persisted measurement router owns the surface.

Regression: the in-memory JourneyStitchingService router (services/journeys/
routes.py) was mounted *before* the persisted authority and shadowed
GET /v1/journeys/{journey_id} and /summary with an always-empty in-process
store (FastAPI first-match-wins). It is now unmounted; this pins the persisted
measurement router as the sole owner and keeps the operator-only journey-health
admin router intact.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests")

from fastapi.routing import APIRoute  # noqa: E402

_INMEMORY_MODULE = "services.journeys.routes"
_PERSISTED_MODULE = "services.measurement.routes.journeys"


def _api_routes(app):
    # Mirror tests/unit/test_route_registry_coverage.py: some routers are
    # exposed via a wrapper carrying the real APIRoutes on ``original_router``.
    for route in app.routes:
        if isinstance(route, APIRoute):
            yield route
        original = getattr(route, "original_router", None)
        if original is not None:
            for inner in original.routes:
                if isinstance(inner, APIRoute):
                    yield inner


def test_journey_id_owned_by_persisted_authority():
    import main

    owners = [
        r.endpoint.__module__
        for r in _api_routes(main.app)
        if r.path == "/v1/journeys/{journey_id}"
    ]
    assert owners, "GET /v1/journeys/{journey_id} is not mounted"
    assert all(m == _PERSISTED_MODULE for m in owners), (
        f"/v1/journeys/{{journey_id}} owned by {owners}, expected {_PERSISTED_MODULE}"
    )


def test_inmemory_stitcher_router_not_mounted_under_v1_journeys():
    import main

    leaked = [
        r.path
        for r in _api_routes(main.app)
        if r.endpoint.__module__ == _INMEMORY_MODULE
        and r.path.startswith("/v1/journeys")
    ]
    assert not leaked, f"retired in-memory stitcher paths still mounted: {leaked}"


def test_journey_health_admin_router_still_mounted():
    import main

    admin_paths = [
        r.path
        for r in _api_routes(main.app)
        if r.endpoint.__module__ == _INMEMORY_MODULE
        and r.path.startswith("/v1/admin/journey-health")
    ]
    assert admin_paths, "journey-health admin router unexpectedly missing"
