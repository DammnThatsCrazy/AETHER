"""Staging identity proof routes are tenant-admin scoped, not platform-operator.

They read and write only the calling tenant's staging proof evidence, so the
rehearsal calls them with its run-scoped tenant admin key. Under /v1/admin the
route registry demanded a platform operator, and rehearsal run 43387214569
got 403 from every call.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
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
        # Leaving /v1/admin dropped only the operator requirement: the routes
        # that write durable proof evidence stay sensitive and audited.
        assert policy.sensitive and policy.audit_required


@pytest.mark.parametrize("environment, mounted", [
    ("staging", True), ("production", False), ("local", False), ("development", False),
])
def test_proof_routes_are_mounted_only_on_staging(environment, mounted):
    app = FastAPI()
    assert staging_capture_routes.mount_if_staging(app, environment) is mounted
    # Included routers mount lazily in this FastAPI version; the OpenAPI
    # schema lists what the app actually serves.
    paths = set(app.openapi()["paths"])
    proof = {"/v1/identity/staging-proof-capture", "/v1/identity/staging-proof-scenarios"}
    assert (proof <= paths) is mounted
    assert not (proof & paths) or mounted


def test_create_app_mounts_through_the_staging_gate():
    # create_app passes the running environment to the gate; building the full
    # app as staging needs the fail-closed staging wiring, so this binds the
    # call site while the behaviour is covered above.
    source = MAIN.read_text(encoding="utf-8")
    assert "mount_staging_identity_proof_routes(app, settings.env.value)" in source
    assert "identity_staging_capture_router" not in source
