"""Access Kit source attribution joins the existing audit, metering, and notification authorities."""
from __future__ import annotations

from types import SimpleNamespace

from starlette.requests import Request
from starlette.responses import Response

import billing.billing.revops as revops
import governance.security.audit_ledger as audit_ledger
import journeys.notification_intelligence.delivery_outbox as delivery_outbox
from middleware.middleware import _record_access_interaction
from shared.auth.auth import Role


def _request(*, surface="cli", route="/v1/entities", method="GET"):
    headers = [(b"x-aether-access-surface", surface.encode())]
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "https", "path": route, "raw_path": route.encode(),
        "query_string": b"", "headers": headers, "server": ("api.example.test", 443),
        "client": ("192.0.2.10", 1234),
    }
    request = Request(scope)
    request.state.tenant = SimpleNamespace(
        tenant_id="tenant-a", user_id="user-a", role=Role.EDITOR, permissions=[],
    )
    request.state.request_id = "request-1"
    request.state.access_route_template = route
    return request


async def test_access_kit_read_records_audit_usage_and_minimized_outbound_event(monkeypatch):
    recorded_audit = {}
    recorded_meter = {}
    queued = []

    class Ledger:
        async def record(self, **kwargs):
            recorded_audit.update(kwargs)
            return SimpleNamespace(audit_event_id="audit-1")

    class UsageEvent:
        def __init__(self, **kwargs):
            recorded_meter.update(kwargs)

    class Metering:
        async def record_event(self, event):
            return {"metering_event_id": "meter-1", **recorded_meter}

    async def queue(tenant_id, event):
        queued.append((tenant_id, event))

    monkeypatch.setattr(audit_ledger, "AuditLedger", Ledger)
    monkeypatch.setattr(revops, "UsageMeteringEvent", UsageEvent)
    monkeypatch.setattr(revops, "MeteringService", Metering)
    monkeypatch.setattr(delivery_outbox, "queue_access_interaction_event", queue)

    response = Response(status_code=200)
    refs = await _record_access_interaction(_request(surface="mcp_http"), response)

    assert refs == {
        "X-Aether-Audit-Event-ID": "audit-1",
        "X-Aether-Usage-Event-ID": "meter-1",
    }
    assert recorded_audit["event_type"] == "access.interaction"
    assert recorded_audit["resource_id"] == "entities.list"
    assert recorded_audit["outcome"] == "allowed"
    assert recorded_meter["event_type"] == "access_interaction"
    assert recorded_meter["source_type"] == "access_kit"
    assert recorded_meter["source_id"] == "request-1"
    assert recorded_meter["billable"] is False
    assert queued[0][0] == "tenant-a"
    event = queued[0][1]
    assert event["type"] == "access.interaction.completed"
    assert event["surface"] == "mcp_http"
    assert event["capability_id"] == "entities.list"
    assert event["audit_event_id"] == "audit-1"
    assert "entity_id" not in event and "query" not in event


async def test_blocked_access_is_audited_without_allowing_arbitrary_surface_values(monkeypatch):
    recorded = []

    class Ledger:
        async def record(self, **kwargs):
            recorded.append(kwargs)
            return SimpleNamespace(audit_event_id="audit-blocked")

    class Metering:
        async def record_event(self, _event):
            return None

    async def queue(_tenant_id, event):
        recorded.append(event)

    monkeypatch.setattr(audit_ledger, "AuditLedger", Ledger)
    monkeypatch.setattr(revops, "MeteringService", Metering)
    monkeypatch.setattr(delivery_outbox, "queue_access_interaction_event", queue)
    blocked = await _record_access_interaction(_request(), Response(status_code=403))
    assert blocked == {"X-Aether-Audit-Event-ID": "audit-blocked"}
    assert recorded[0]["outcome"] == "blocked"
    assert recorded[1]["type"] == "access.interaction.blocked"

    ignored = await _record_access_interaction(
        _request(surface="customer-supplied"), Response(status_code=200),
    )
    assert ignored == {}
    assert len(recorded) == 2


async def test_usage_summary_itself_is_not_metered(monkeypatch):
    monkeypatch.setattr(
        audit_ledger, "AuditLedger",
        lambda: (_ for _ in ()).throw(AssertionError("usage summary must be excluded")),
    )
    request = _request(route="/v1/billing/usage/summary")
    assert await _record_access_interaction(request, Response(status_code=200)) == {}
