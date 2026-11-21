"""Access Kit kernel: CLI/MCP calls are read (query), send (observe), account (write/auth); never act."""
from __future__ import annotations

import pytest

import billing.billing.revops as revops
import governance.security.audit_ledger as audit_ledger
import journeys.notification_intelligence.delivery_outbox as delivery_outbox
import middleware.middleware as mw
from starlette.responses import Response
from tests.unit.test_access_kit_interaction_accounting import _request


@pytest.mark.parametrize("method,route", [
    ("GET", "/v1/entities"),
    ("POST", "/v1/batch"),
    ("GET", "/v1/agent/agents/{agent_ref}/behavior"),
    ("POST", "/v1/continuations"),
    ("GET", "/v1/me/sessions"),
])
def test_named_capabilities_are_allowed(method, route):
    assert mw._access_kit_refusal(_request(surface="cli", route=route, method=method), route) is None


@pytest.mark.parametrize("method,route", [
    ("POST", "/v1/campaigns/{campaign_id}/pause"),
    ("POST", "/v1/integrations/data-rights/grants"),
    ("POST", "/v1/provider-connections"),
    ("DELETE", "/v1/entities/{entity_id}"),
])
def test_anything_else_marked_cli_or_mcp_is_refused(method, route):
    refusal = mw._access_kit_refusal(_request(surface="mcp_http", route=route, method=method), route)
    assert refusal is not None and "ACCESS_KIT_CAPABILITY_UNAVAILABLE" in str(refusal.to_dict())


def test_calls_without_an_access_surface_are_not_the_kernels_business():
    request = _request(surface="", route="/v1/campaigns/{campaign_id}/pause", method="POST")
    assert mw._access_kit_refusal(request, "/v1/campaigns/{campaign_id}/pause") is None


def test_a_capability_classed_act_is_refused_even_when_named(monkeypatch):
    monkeypatch.setitem(mw._ACCESS_KIT_CAPABILITY_CLASS, "entities.list", "act")
    assert mw._access_kit_refusal(_request(surface="cli"), "/v1/entities") is not None


def test_no_offered_capability_is_classed_act():
    names = set(mw._ACCESS_KIT_CAPABILITIES.values()) | set(mw._ACCESS_KIT_UNCAPPED_ROUTES.values())
    assert {mw._access_kit_class(n) for n in names} <= mw._ACCESS_KIT_ALLOWED_CLASSES


def test_batch_stays_out_of_the_per_credential_cap():
    assert ("POST", "/v1/batch") not in mw._ACCESS_KIT_CAPABILITIES


def _capture(monkeypatch):
    seen = {"audit": {}, "meter": None}

    class Ledger:
        async def record(self, **kwargs):
            seen["audit"].update(kwargs)
            from types import SimpleNamespace
            return SimpleNamespace(audit_event_id="audit-1")

    class Metering:
        async def record_event(self, event):
            seen["meter"] = event
            return {"metering_event_id": "meter-1"}

    async def queue(tenant_id, event):
        return None

    monkeypatch.setattr(audit_ledger, "AuditLedger", Ledger)
    monkeypatch.setattr(revops, "UsageMeteringEvent", lambda **kw: kw)
    monkeypatch.setattr(revops, "MeteringService", Metering)
    monkeypatch.setattr(delivery_outbox, "queue_access_interaction_event", queue)
    return seen


async def test_interactions_record_protocol_and_class(monkeypatch):
    seen = _capture(monkeypatch)
    await mw._record_access_interaction(_request(surface="mcp_stdio"), Response(status_code=200))
    assert seen["audit"]["metadata"]["protocol"] == "mcp"
    assert seen["audit"]["metadata"]["interaction_class"] == "query"


async def test_observations_through_the_cli_are_audited_but_not_metered_twice(monkeypatch):
    seen = _capture(monkeypatch)
    refs = await mw._record_access_interaction(
        _request(surface="cli", route="/v1/batch", method="POST"), Response(status_code=200),
    )
    assert seen["audit"]["resource_id"] == "observations.submit"
    assert seen["audit"]["metadata"]["interaction_class"] == "observe"
    assert seen["meter"] is None and "X-Aether-Usage-Event-ID" not in refs
