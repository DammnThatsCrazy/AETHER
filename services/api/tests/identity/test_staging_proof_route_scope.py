"""Staging identity proof routes are tenant-admin scoped, not platform-operator.

They read and write only the calling tenant's staging proof evidence, so the
rehearsal calls them with its run-scoped tenant admin key. Under /v1/admin the
route registry demanded a platform operator, and rehearsal run 43387214569
got 403 from every call.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.routing import APIRoute

from governance.security.route_registry import classify
from identity.identity import staging_capture_routes

MAIN = Path(__file__).resolve().parents[2] / "main.py"


def test_proof_routes_are_tenant_scoped_identity_routes():
    paths = {
        (sorted(route.methods)[0], route.path)
        for route in staging_capture_routes.router.routes
        if isinstance(route, APIRoute)
    }
    assert paths == {
        ("GET", "/v1/identity/staging-proof-capture"),
        ("POST", "/v1/identity/staging-proof-scenarios"),
    }
    for method, path in paths:
        policy = classify(path, method)
        assert policy is not None
        assert policy.requires_auth and policy.tenant_scoped
        assert not policy.platform_operator_required
        assert not policy.kyber_operator_required


def test_proof_router_is_mounted_only_in_staging():
    source = MAIN.read_text(encoding="utf-8")
    assert "from identity.identity.staging_capture_routes import router as identity_staging_capture_router" in source
    assert 'if settings.env.value == "staging":\n        app.include_router(identity_staging_capture_router)' in source
