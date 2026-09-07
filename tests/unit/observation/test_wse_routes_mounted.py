"""WS-E 3/4 — the ingestion control-plane route surfaces are mounted on the
real ``main.app`` and classify under the route-policy registry.

Locks the program-tip seams for the WS-E operator + health + manifest routes:

* ``GET /v1/health/pipeline`` — the previously-phantom health route the Kyber
  operator hook called now exists and returns a 200-shaped pipeline payload
  (disabled/zeroed while ``AETHER_INGESTION_OBSERVABILITY_ENABLED`` is OFF).
* ``GET /v1/config/sdk/versions`` — the SDK version-tier capability manifest.
* The Kyber ingestion observability router (funnel + Observation Inspector) is
  mounted under ``/v1/kyber/ingest/observability`` and classifies
  Kyber-operator-required (the default-deny ratchet never lets a mounted route
  go unclassified), with exactly one route per path (no conflicts).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests")

import pytest  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402

HEALTH_PIPELINE = "/v1/health/pipeline"
VERSIONS = "/v1/config/sdk/versions"
OBS_STATUS = "/v1/kyber/ingest/observability"
OBS_FUNNEL = "/v1/kyber/ingest/observability/funnel"
OBS_TRACE = "/v1/kyber/ingest/observability/traces/{event_id}"
OBS_TRACES = "/v1/kyber/ingest/observability/traces"

OBSERVABILITY_ROUTES = (OBS_STATUS, OBS_FUNNEL, OBS_TRACE, OBS_TRACES)


def _mounted_paths() -> dict[str, set[str]]:
    import main

    by_path: dict[str, set[str]] = {}
    for route in main.app.routes:
        if isinstance(route, APIRoute):
            by_path.setdefault(route.path, set()).update(sorted(route.methods or []))
        original = getattr(route, "original_router", None)
        if original is not None:
            for inner in original.routes:
                if isinstance(inner, APIRoute):
                    by_path.setdefault(inner.path, set()).update(sorted(inner.methods or []))
    return by_path


def test_ws_e_routes_are_mounted_on_main_app():
    mounted = _mounted_paths()
    assert HEALTH_PIPELINE in mounted
    assert "GET" in mounted[HEALTH_PIPELINE]
    assert VERSIONS in mounted
    assert "GET" in mounted[VERSIONS]
    for path in OBSERVABILITY_ROUTES:
        assert path in mounted, f"{path} must be mounted"
        assert "GET" in mounted[path]


def test_ws_e_routes_mount_exactly_once():
    mounted = _mounted_paths()
    for path in (HEALTH_PIPELINE, VERSIONS) + OBSERVABILITY_ROUTES:
        assert len(mounted[path]) == 1, f"exactly one route for {path}"


def test_ws_e_route_policy_classification():
    """Default-deny ratchet: every mounted route classifies; the Kyber
    observability router is operator-required + audited + high risk; the health
    and manifest surfaces are NOT operator-gated (public/tenant surfaces)."""
    from services.security.route_registry import classify

    for path in OBSERVABILITY_ROUTES:
        policy = classify(path, method="GET")
        assert policy is not None, f"{path} must classify (default-deny ratchet)"
        assert policy.kyber_operator_required is True, f"{path} must be operator-required"
        assert policy.audit_required is True
        assert policy.risk_class == "high"

    for path in (HEALTH_PIPELINE, VERSIONS):
        policy = classify(path, method="GET")
        assert policy is not None, f"{path} must classify (default-deny ratchet)"
        assert policy.kyber_operator_required is False


def _leaf_routes() -> list:
    """All APIRoutes visible on the app, including mounted routers."""
    import main

    leaves: list = []
    for route in main.app.routes:
        if isinstance(route, APIRoute):
            leaves.append(route)
        original = getattr(route, "original_router", None)
        if original is not None:
            leaves.extend(
                r for r in original.routes if isinstance(r, APIRoute)
            )
    return leaves


async def test_health_pipeline_endpoint_returns_disabled_payload_while_flag_off():
    """The once-phantom hook now resolves to a real endpoint that returns a
    200-shaped payload (status disabled, enabled false) by default."""
    mounted = _mounted_paths()
    assert len(mounted[HEALTH_PIPELINE]) == 1

    route = next(
        r for r in _leaf_routes()
        if r.path == HEALTH_PIPELINE and "GET" in (r.methods or [])
    )
    payload = await route.endpoint()
    assert payload["probe"] == "ingestion-pipeline"
    assert payload["enabled"] is False
    assert payload["status"] == "disabled"
    assert payload["pipeline"]["received"] == 0
