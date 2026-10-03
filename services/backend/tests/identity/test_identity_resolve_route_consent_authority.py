from __future__ import annotations

from types import SimpleNamespace
from dataclasses import replace

import pytest
from starlette.requests import Request

from services.consent import authority
from services.identity import routes
from services.identity.schemas import IdentityResolveRequest
from config.settings import settings


class _Tenant:
    tenant_id = "tenant-consent-boundary"

    def require_permission(self, permission):
        assert permission == "write"


def _request():
    return Request({
        "type": "http", "method": "POST", "path": "/v1/identity/resolve",
        "headers": [], "query_string": b"", "state": {"tenant": _Tenant()},
    })


class _Resolver:
    def __init__(self):
        self.events = []

    async def resolve_event(self, event, tenant_id):
        self.events.append((event, tenant_id))
        return SimpleNamespace(
            tenant_id=tenant_id,
            canonical_entity_id="canonical-1",
            decision=SimpleNamespace(value="create"),
            confidence=0.9,
            confidence_tier=SimpleNamespace(value="high"),
            reason_codes=[],
            linked_aliases=[], candidate_entity_ids=[], conflict_id=None,
            source_event_ids=[], graph_edges_written=[], blocked_reason=None,
            audit_id=None, is_new_entity=True,
        )


@pytest.mark.asyncio
async def test_caller_consent_snapshot_cannot_replace_server_receipt(monkeypatch):
    async def denied(tenant_id, anonymous_id):
        assert tenant_id == _Tenant.tenant_id
        assert anonymous_id == "anonymous-1"
        return False, "consent_receipt_missing", None

    resolver = _Resolver()
    monkeypatch.setattr(authority, "evaluate_identity_link_consent", denied)
    monkeypatch.setattr(routes, "_get_resolver", lambda: resolver)
    response = await routes.resolve_identity(IdentityResolveRequest(
        event_id="request-1", anonymous_id="anonymous-1",
        user_id="claimed-user", email="person@example.test",
        consent_snapshot={"purposes": {"identity": True}},
    ), _request())

    assert response["data"]["decision"] == "blocked"
    assert response["data"]["blocked_reason"] == "consent_receipt_missing"
    assert response["data"]["canonical_entity_id"] == ""
    assert resolver.events == []


@pytest.mark.asyncio
async def test_resolver_receives_only_server_authoritative_consent_context(monkeypatch):
    server_context = {
        "purposes": {"analytics": True}, "authority": "server_consent_receipt",
        "scope": "identity", "receipt_id": "receipt-opaque",
    }

    async def allowed(tenant_id, anonymous_id):
        assert tenant_id == _Tenant.tenant_id
        assert anonymous_id == "anonymous-2"
        return True, None, server_context

    resolver = _Resolver()
    monkeypatch.setattr(authority, "evaluate_identity_link_consent", allowed)
    monkeypatch.setattr(routes, "_get_resolver", lambda: resolver)
    response = await routes.resolve_identity(IdentityResolveRequest(
        event_id="request-2", anonymous_id="anonymous-2",
        user_id="claimed-user", email="person@example.test",
        consent_snapshot={"forged": True, "purposes": {"identity": False}},
    ), _request())

    assert response["data"]["canonical_entity_id"] == "canonical-1"
    assert resolver.events[0][0]["context"]["consent"] == server_context
    assert resolver.events[0][0]["context"]["consent"] != {"forged": True}


@pytest.mark.asyncio
async def test_direct_identity_route_obeys_resolution_kill_switch_before_consent_lookup(monkeypatch):
    async def consent_lookup_must_not_run(*_args):
        raise AssertionError("disabled identity resolution must not look up consent")

    resolver = _Resolver()
    monkeypatch.setattr(settings, "identity_continuity", replace(
        settings.identity_continuity, resolution_enabled=False
    ))
    monkeypatch.setattr(authority, "evaluate_identity_link_consent", consent_lookup_must_not_run)
    monkeypatch.setattr(routes, "_get_resolver", lambda: resolver)

    response = await routes.resolve_identity(IdentityResolveRequest(
        event_id="request-disabled", anonymous_id="anonymous-disabled",
        user_id="claimed-user", email="person@example.test",
        consent_snapshot={"purposes": {"identity": True}},
    ), _request())

    assert response["data"]["decision"] == "blocked"
    assert response["data"]["canonical_entity_id"] == ""
    assert response["data"]["blocked_reason"] == "identity_resolution_disabled"
    assert resolver.events == []
