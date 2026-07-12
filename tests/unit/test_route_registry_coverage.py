"""Route policy registry coverage (PR 2b) — default-deny at CI.

Enumerates every mounted route (via the same app-import + APIRoute descent used by
tests/unit/test_route_conflicts.py) and asserts:
  1. every route classifies in config/route_registry.yaml — an unclassified prefix
     fails here (the default-deny ratchet: a new route prefix must be classified);
  2. every `/kyber` route is kyber_operator_required + audit_required + high risk;
  3. every sensitive route is audit_required;
  4. every public path (feature-gate allowlist) that is mounted classifies as public,
     and no route is both public and Kyber-operator-required;
  5. an unknown prefix classifies to None (the ratchet actually denies).
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


def _iter_api_routes(app):
    for route in app.routes:
        if isinstance(route, APIRoute):
            yield route
        original = getattr(route, "original_router", None)
        if original is not None:
            for inner in original.routes:
                if isinstance(inner, APIRoute):
                    yield inner


def _routes():
    import main
    seen = {}
    for route in _iter_api_routes(main.app):
        seen[route.path] = route
    return sorted(seen)


def test_every_mounted_route_is_classified():
    from services.security.route_registry import classify
    unclassified = [p for p in _routes() if classify(p) is None]
    assert not unclassified, (
        "Unclassified route prefixes (add them to config/route_registry.yaml "
        f"known_prefixes — default-deny): {sorted({__import__('services.security.route_registry', fromlist=['prefix_of']).prefix_of(p) for p in unclassified})}"
    )


def test_kyber_routes_require_operator_and_audit():
    from services.security.route_registry import classify
    offenders = []
    for path in _routes():
        if "/kyber" in path:
            pol = classify(path)
            if pol is None or not (pol.kyber_operator_required and pol.audit_required and pol.risk_class == "high"):
                offenders.append(path)
    assert not offenders, f"/kyber routes must be operator-required + audited + high risk: {offenders}"


def test_sensitive_routes_are_audited():
    from services.security.route_registry import classify
    offenders = [p for p in _routes() if (c := classify(p)) and c.sensitive and not c.audit_required]
    assert not offenders, f"sensitive routes must be audit_required: {offenders}"


def test_public_paths_classify_public_and_not_kyber():
    from services.security.route_registry import classify, is_public_path
    mounted = set(_routes())
    for path in mounted:
        pol = classify(path)
        if pol is None:
            continue
        if is_public_path(path):
            assert pol.public is True, f"{path} is a public path but not classified public"
            assert pol.kyber_operator_required is False, f"{path} cannot be both public and Kyber-operator"


def test_unknown_prefix_denies():
    from services.security.route_registry import classify
    assert classify("/v1/totally-new-surface/thing") is None
    assert classify("/v1/kyber/anything") is not None  # kyber prefix is known
