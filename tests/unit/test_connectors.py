"""CI-gated tests for the inbound connector framework + adapters (Phase 2)."""
from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
_PREFIXES = ("config", "services", "shared", "middleware", "dependencies", "repositories")


@contextmanager
def backend_module_path():
    original = list(sys.path)
    for prefix in _PREFIXES:
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                sys.modules.pop(name, None)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for prefix in _PREFIXES:
            for name in list(sys.modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)


@pytest.fixture()
def conn(monkeypatch):
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    with backend_module_path():
        repos = importlib.import_module("repositories.repos")
        repos.reset_in_memory_stores()
        audit_mod = importlib.import_module("services.security.audit_ledger")
        audit_mod._TENANT_TAIL.clear()
        audit_mod._TENANT_SEQ.clear()
        registry = importlib.import_module("services.integrations.connectors.registry")
        service = importlib.import_module("services.integrations.connectors.service")
        base = importlib.import_module("services.integrations.connectors.base")
        routes = importlib.import_module("services.integrations.connectors.routes")
        yield SimpleNamespace(registry=registry, service=service.connector_service, base=base, routes=routes)


def req(tenant_id="tenant-a", permissions=None):
    perms = list(permissions if permissions is not None else ["read", "write", "admin"])

    class T:
        def __init__(self):
            self.tenant_id = tenant_id
            self.user_id = "u-" + tenant_id
            self.permissions = perms

        def has_permission(self, p):
            return p in self.permissions

        def require_permission(self, p):
            if p not in self.permissions:
                raise PermissionError(p)

    return SimpleNamespace(state=SimpleNamespace(tenant=T()), client=None, headers={})


def unwrap(resp):
    return resp["data"]


EXPECTED = {"slack", "webhook", "shopify", "stripe", "hubspot", "salesforce", "klaviyo",
            "segment", "posthog", "ga4", "jira", "linear", "zendesk", "intercom", "dune",
            # ADR-C11: multi-provider comms cohort (Klaviyo + webhook-only + pull-capable
            # Iterable) plus the ADR-C11 follow-up cohort (HubSpot marketing, Iterable,
            # pull-first Braze).
            "customerio", "mailchimp", "postmark", "sendgrid", "iterable", "braze"}


def test_registry_has_all_21(conn):
    assert set(conn.registry.CONNECTORS.keys()) == EXPECTED


def test_validate_config_rejects_secret_keys(conn):
    slack = conn.registry.get_connector("slack")
    cfg = conn.base.ConnectorConfig(tenant_id="t", connector_type="slack", config={"api_key": "x"})
    with pytest.raises(ValueError):
        slack.validate_config(cfg)


async def test_configure_strips_secrets_and_disabled_by_default(conn):
    stored = await conn.service.configure("tenant-a", "slack", config={"api_key": "leak", "channel": "#ops"})
    assert "api_key" not in stored["config"]
    assert stored["config"]["channel"] == "#ops"
    assert stored["enabled"] is False  # disabled by default


async def test_tenant_isolation(conn):
    await conn.service.configure("tenant-a", "shopify", enabled=True)
    a = await conn.service.list_for_tenant("tenant-a")
    b = await conn.service.list_for_tenant("tenant-b")
    a_shopify = next(c for c in a if c["connector_type"] == "shopify")
    b_shopify = next(c for c in b if c["connector_type"] == "shopify")
    assert a_shopify["enabled"] is True
    assert b_shopify["enabled"] is False  # other tenant unaffected


async def test_connection_states(conn, monkeypatch):
    disabled = await conn.service.test("tenant-a", "slack")
    assert disabled.status == "disabled"
    await conn.service.configure("tenant-a", "slack", enabled=True)
    no_secret = await conn.service.test("tenant-a", "slack")
    assert no_secret.status == "not_configured"

    async def successful_provider_check(config, secret=None):
        assert secret == "test-vault-credential"
        return conn.base.ConnectionTestResult(
            connector_type="slack",
            ok=True,
            status="ready",
            detail="provider accepted credential",
        )

    monkeypatch.setattr(
        conn.registry.get_connector("slack"),
        "test_connection",
        successful_provider_check,
    )
    await conn.service.configure(
        "tenant-a", "slack", enabled=True, credential="test-vault-credential"
    )
    ready = await conn.service.test("tenant-a", "slack")
    assert ready.ok is True and ready.status == "ready"


async def test_sync_disabled_then_enabled_requires_vault_credential(conn):
    disabled = await conn.service.sync("tenant-a", "stripe")
    assert disabled.status == "disabled"
    await conn.service.configure("tenant-a", "stripe", enabled=True)
    with pytest.raises(ValueError, match="credential is unavailable"):
        await conn.service.sync("tenant-a", "stripe")


async def test_webhook_disabled_rejected_then_ingested(conn):
    import json
    disabled = await conn.service.ingest_webhook("segment", "tenant-a", raw_body=b"{}")
    assert disabled["accepted"] is False
    await conn.service.configure("tenant-a", "segment", enabled=True)
    body = json.dumps({"type": "track", "event": "Order Completed", "messageId": "m1"}).encode()
    res = await conn.service.ingest_webhook("segment", "tenant-a", raw_body=body)
    assert res["accepted"] is True and res["events_ingested"] == 1
    assert res["events"][0]["event_type"] == "segment.track"


async def test_webhook_invalid_signature_rejected(conn):
    await conn.service.configure("tenant-a", "slack", enabled=True)
    res = await conn.service.ingest_webhook(
        "slack", "tenant-a", raw_body=b'{"event":{"type":"message"}}',
        signature="bad", timestamp="123", secret="whsec_test",
    )
    assert res["accepted"] is False and res["reason"] == "invalid signature"


async def test_kyber_overview_requires_operator(conn):
    from shared.common.common import ForbiddenError
    with pytest.raises(ForbiddenError):
        await conn.routes.connectors_overview(req("tenant-a", permissions=["admin", "read"]))
    data = unwrap(await conn.routes.connectors_overview(req("ops", permissions=["kyber:operator"])))
    assert data["available_connectors"] == 21


async def test_tenant_route_lists_connectors(conn):
    data = unwrap(await conn.routes.list_connectors(req("tenant-a")))
    assert len(data["items"]) == 21
    assert "tenant-b" not in str(data)
