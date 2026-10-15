"""Platform-wide admin and diagnostics routes require a platform operator.

Every self-serve customer owner holds role ``admin``, which satisfies every
``require_permission()`` check. The route policy and the handlers themselves
must still refuse that owner on routes that act on other tenants or on
platform-wide state, while a tenant listed in ``PLATFORM_OPERATOR_TENANT_IDS``
keeps access and owners keep their own tenant's customer routes.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "services" / "api"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests")

OPERATOR_TENANT = "tenant-platform-ops"
CUSTOMER_TENANT = "tenant-customer"
OTHER_TENANT = "tenant-other"
OTHER_KEY_ID = "otherkey0001"

PLATFORM_ROUTES = [
    ("GET", f"/v1/admin/tenants/{OTHER_TENANT}", None),
    ("PATCH", f"/v1/admin/tenants/{OTHER_TENANT}", {"name": "renamed"}),
    ("POST", f"/v1/admin/tenants/{OTHER_TENANT}/api-keys", {"name": "k", "permissions": ["read"]}),
    ("POST", f"/v1/admin/tenants/{OTHER_TENANT}/deactivate", None),
    ("DELETE", f"/v1/admin/tenants/{OTHER_TENANT}", None),
    ("DELETE", f"/v1/admin/api-keys/{OTHER_KEY_ID}", None),
    ("GET", "/v1/admin/delivery/jobs", None),
    ("PUT", "/v1/fraud/config", {"block_threshold": 90}),
    ("GET", "/v1/diagnostics/errors", None),
]

# Routes whose handlers refuse a non-operator on their own, independent of the
# route policy.
HANDLER_GUARDED_ROUTES = PLATFORM_ROUTES + [
    ("POST", "/v1/admin/tenants", {"name": "new tenant", "contact_email": "ops@example.com"}),
    ("GET", "/v1/diagnostics/health", None),
    ("GET", "/v1/diagnostics/report", None),
    ("GET", "/v1/diagnostics/circuit-breakers", None),
    ("POST", "/v1/diagnostics/errors/fp-1/resolve", None),
    ("POST", "/v1/diagnostics/errors/fp-1/suppress", None),
    ("GET", "/v1/diagnostics/observability/metrics", None),
    ("GET", "/v1/diagnostics/observability/metrics/http", None),
]


def _platform_writer_routes():
    from graph.assets import seeds

    asset = seeds.fiat_asset_rows()[0]
    chain = seeds.chain_rows()[0]
    fiat = seeds.fiat_currency_rows()[0]
    deployment = seeds.native_deployment_rows()[0]
    alias = seeds.alias_rows()[0]
    routes = [("POST", "/v1/assets/seed", None)]
    for prefix in ("/v1/assets", "/v1/admin/assets"):
        routes += [
            ("POST", f"{prefix}/assets", asset),
            ("POST", f"{prefix}/chains", chain),
            ("POST", f"{prefix}/fiat", fiat),
            ("POST", f"{prefix}/deployments", deployment),
            ("POST", f"{prefix}/aliases", alias),
        ]
    routes += [
        ("POST", "/v1/assets/capabilities", {"asset_id": asset["id"], "capability": "canonical"}),
        ("POST", "/v1/admin/assets/discovery/apply", {"raw_reference": "USDC", "canonical_asset_id": "stablecoin:USDC"}),
        ("POST", "/v1/valuation/observe", {
            "asset_id": "stablecoin:USDC", "provider": "manual", "price": "1.00",
            "quote_asset_id": "fiat:USD", "observed_at": "2026-10-15T00:00:00+00:00", "source": "test",
        }),
    ]
    return routes

SDK_DIAGNOSTICS_ROUTES = [
    ("POST", "/v1/diagnostics/sdk/heartbeat", {"sdk_id": "sdk-1", "sdk_version": "1.0.0", "platform": "web"}),
    ("GET", "/v1/diagnostics/sdk/health", None),
    ("GET", "/v1/diagnostics/sdk/health/sdk-1", None),
    ("GET", "/v1/diagnostics/sdk/silent", None),
]

# Tenant-selecting SDK diagnostics: own tenant is fine, another needs an operator.
SDK_TENANT_SELECTING_ROUTES = [
    ("POST", "/v1/diagnostics/sdk/drift/analyze", {"sdk_id": "sdk-1", "tenant_id": "{tenant}"}),
    ("GET", "/v1/diagnostics/sdk/fleet?tenant_id={tenant}", None),
]

OWN_TENANT_ROUTES = [
    ("GET", "/v1/me/api-keys", None),
    ("POST", "/v1/me/api-keys", {"name": "own key", "permissions": ["read"]}),
    ("GET", "/v1/billing/plan", None),
    ("GET", "/v1/billing/entitlements", None),
]


def _principal(name: str):
    from shared.auth.auth import PlanTier, Role, TenantContext
    from tenancy.account_organization.grants import grants_for

    owner_role, owner_permissions = grants_for("owner")
    member_role, member_permissions = grants_for("member")
    principals = {
        "operator": (OPERATOR_TENANT, owner_role, owner_permissions),
        "customer_owner": (CUSTOMER_TENANT, owner_role, owner_permissions),
        "customer_member": (CUSTOMER_TENANT, member_role, member_permissions),
    }
    tenant_id, role, permissions = principals[name]
    return TenantContext(
        tenant_id=tenant_id,
        user_id=f"user-{name}",
        role=Role(role),
        plan_tier=PlanTier.DELTA,
        permissions=list(permissions),
    )


async def _seed() -> None:
    from actions.delivery.routes import _job_repo
    from repositories.repos import AdminRepository, APIKeyRepository

    await AdminRepository().insert(OTHER_TENANT, {"name": "Other", "status": "active", "plan_tier": "delta"})
    await APIKeyRepository().insert(OTHER_KEY_ID, {
        "tenant_id": OTHER_TENANT, "name": "other", "key_hash": "0" * 64, "permissions": ["read"],
    })
    await _job_repo.insert("job-other-1", {
        "id": "job-other-1", "intent_id": "intent-1", "tenant_id": OTHER_TENANT, "channel": "webhook",
        "provider_adapter": "webhook", "state": "queued", "payload": {}, "provider_config": {},
    })


def _client(monkeypatch, *, enforced: bool):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import middleware.middleware as mw
    from actions.delivery.routes import admin_router as delivery_admin_router
    from billing.billing.routes import router as billing_router
    from config.settings import settings
    from governance.admin.routes import router as admin_router
    from governance.diagnostics.observability_routes import router as observability_router
    from governance.diagnostics.routes import router as diagnostics_router
    from graph.assets.admin_routes import admin_router as assets_admin_router
    from graph.assets.routes import router as assets_router
    from ingestion.sdk_drift.routes import router as sdk_drift_router
    from ingestion.sdk_health.routes import router as sdk_health_router
    from intelligence.fraud.routes import router as fraud_router
    from repositories.repos import reset_in_memory_stores
    from shared.auth import platform_operator
    from tenancy.auth.routes import admin_auth_router
    from tenancy.me.routes import router as me_router
    from value.valuation.routes import router as valuation_router

    reset_in_memory_stores()
    platform_operator.reset_platform_operator_cache()
    monkeypatch.setattr(settings, "security_governance", dataclasses.replace(
        settings.security_governance, platform_operator_tenant_ids=[OPERATOR_TENANT],
    ))
    monkeypatch.setattr(settings, "route_registry", dataclasses.replace(
        settings.route_registry, policy_enforcement_enabled=True, route_registry_enforced=enforced,
    ))
    monkeypatch.setattr(settings, "assets", dataclasses.replace(
        settings.assets, api_enabled=True, ingestion_enabled=True, admin_enabled=True, admin_mode=True,
    ))
    monkeypatch.setattr(settings, "valuation", dataclasses.replace(
        settings.valuation, api_enabled=True, ingestion_enabled=True,
    ))

    async def _authenticate(request, jwt_handler, api_key_validator):
        return _principal(request.headers["X-Test-Principal"])

    monkeypatch.setattr(mw, "_authenticate_async", _authenticate)

    app = FastAPI()
    for router in (
        admin_router, admin_auth_router, delivery_admin_router, fraud_router,
        diagnostics_router, observability_router, sdk_drift_router, sdk_health_router,
        me_router, billing_router, assets_router, assets_admin_router, valuation_router,
    ):
        app.include_router(router)
    mw.register_middleware(app)
    asyncio.run(_seed())
    return TestClient(app, raise_server_exceptions=False)


def _call(client, principal: str, method: str, path: str, body):
    return client.request(method, path, headers={"X-Test-Principal": principal}, json=body)


@pytest.fixture()
def enforced_client(monkeypatch):
    from shared.auth import platform_operator

    yield _client(monkeypatch, enforced=True)
    platform_operator.reset_platform_operator_cache()


@pytest.fixture()
def observe_client(monkeypatch):
    from shared.auth import platform_operator

    yield _client(monkeypatch, enforced=False)
    platform_operator.reset_platform_operator_cache()


@pytest.mark.parametrize("principal", ["customer_owner", "customer_member"])
@pytest.mark.parametrize(("method", "path", "body"), PLATFORM_ROUTES)
def test_customer_principals_are_refused_on_platform_routes(enforced_client, principal, method, path, body):
    response = _call(enforced_client, principal, method, path, body)
    assert response.status_code == 403, response.text


@pytest.mark.parametrize(("method", "path", "body"), PLATFORM_ROUTES)
def test_platform_operator_reaches_platform_routes(enforced_client, method, path, body):
    response = _call(enforced_client, "operator", method, path, body)
    assert 200 <= response.status_code < 300, response.text


@pytest.mark.parametrize(("method", "path", "body"), HANDLER_GUARDED_ROUTES)
def test_handlers_refuse_customer_owner_without_route_enforcement(observe_client, method, path, body):
    response = _call(observe_client, "customer_owner", method, path, body)
    assert response.status_code == 403, response.text


@pytest.mark.parametrize(("method", "path", "body"), HANDLER_GUARDED_ROUTES)
def test_handlers_admit_platform_operator_without_route_enforcement(observe_client, method, path, body):
    response = _call(observe_client, "operator", method, path, body)
    assert 200 <= response.status_code < 300, response.text


@pytest.mark.parametrize("mode", ["enforced_client", "observe_client"])
def test_platform_writers_refuse_customer_owner(request, mode):
    client = request.getfixturevalue(mode)
    for method, path, body in _platform_writer_routes():
        response = _call(client, "customer_owner", method, path, body)
        assert response.status_code == 403, (path, response.text)


@pytest.mark.parametrize("mode", ["enforced_client", "observe_client"])
def test_platform_writers_admit_platform_operator(request, mode):
    client = request.getfixturevalue(mode)
    for method, path, body in _platform_writer_routes():
        if path == "/v1/admin/assets/discovery/apply":
            continue  # needs a resolver-verified mapping; its refusal is covered above
        response = _call(client, "operator", method, path, body)
        assert 200 <= response.status_code < 300, (path, response.text)


def _for_tenant(path: str, body, tenant: str):
    if body is not None:
        body = {k: (v.format(tenant=tenant) if isinstance(v, str) else v) for k, v in body.items()}
    return path.format(tenant=tenant), body


@pytest.mark.parametrize(("method", "path", "body"), SDK_TENANT_SELECTING_ROUTES)
def test_sdk_diagnostics_refuse_another_tenant_without_route_enforcement(observe_client, method, path, body):
    own_path, own_body = _for_tenant(path, body, CUSTOMER_TENANT)
    other_path, other_body = _for_tenant(path, body, OTHER_TENANT)

    assert _call(observe_client, "customer_owner", method, own_path, own_body).status_code == 200
    assert _call(observe_client, "customer_owner", method, other_path, other_body).status_code == 403
    assert _call(observe_client, "operator", method, other_path, other_body).status_code == 200


@pytest.mark.parametrize("principal", ["customer_owner", "customer_member"])
@pytest.mark.parametrize(("method", "path", "body"), SDK_DIAGNOSTICS_ROUTES)
def test_tenant_sdk_diagnostics_stay_open_to_tenants(enforced_client, principal, method, path, body):
    response = _call(enforced_client, principal, method, path, body)
    assert 200 <= response.status_code < 300, response.text


@pytest.mark.parametrize(("method", "path", "body"), OWN_TENANT_ROUTES)
def test_customer_owner_keeps_own_tenant_routes(enforced_client, method, path, body):
    response = _call(enforced_client, "customer_owner", method, path, body)
    assert 200 <= response.status_code < 300, response.text


def test_registry_marks_platform_routes_operator_required():
    from governance.security.route_registry import classify

    for template in (
        "/v1/admin/tenants",
        "/v1/admin/tenants/{tenant_id}",
        "/v1/admin/api-keys/{key_id}",
        "/v1/admin/delivery/jobs",
        "/v1/diagnostics/errors",
        "/v1/diagnostics/sdk/fleet",
        "/v1/diagnostics/sdk/drift/analyze",
    ):
        assert classify(template).platform_operator_required is True, template

    for template in (
        "/v1/admin/billing/stripe/webhook",
        "/v1/diagnostics/sdk/heartbeat",
        "/v1/diagnostics/sdk/health",
        "/v1/diagnostics/sdk/health/{sdk_id}",
        "/v1/diagnostics/sdk/health/sdk-1",
        "/v1/diagnostics/sdk/silent",
        "/v1/fraud/config",
        "/v1/me/api-keys",
        "/v1/billing/plan",
    ):
        assert classify(template).platform_operator_required is False, template
