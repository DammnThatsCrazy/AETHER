"""Inbound outcome callbacks land only in the tenant bound to the delivery.

Each test posts through the real public route (Jira, Linear, Aether callback),
then drains the inbox with the real processor. The receiving tenant must come
from the stored ExternalResourceLink chain — never from an
``X-Aether-Tenant-ID`` header or a ``?tenant_id=`` query parameter.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
import os
import time
import uuid

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

GLOBAL_SECRET = "platform-wide-inbound-secret"


class _MemRepo:
    def __init__(self):
        self._store: dict[str, dict] = {}

    async def find_many(self, filters: dict | None = None, limit: int = 100, **kw) -> list[dict]:
        rows = list(self._store.values())
        for k, v in (filters or {}).items():
            rows = [r for r in rows if r.get(k) == v]
        return rows[:limit]

    async def find_by_id(self, record_id: str) -> dict | None:
        return self._store.get(record_id)

    async def insert(self, record_id: str, data: dict) -> dict:
        self._store[record_id] = {**data, "id": record_id}
        return self._store[record_id]

    async def update(self, record_id: str, data: dict) -> dict:
        if record_id in self._store:
            self._store[record_id].update(data)
        return self._store.get(record_id, {})

    async def mark_processed(self, record_id: str, error: str | None = None) -> None:
        self._store[record_id]["processed"] = True
        self._store[record_id]["processing"] = False
        if error:
            self._store[record_id]["processing_error"] = error

    async def claim_pending(self, limit: int = 20) -> list[dict]:
        out = []
        for record in self._store.values():
            if record.get("processed") or record.get("processing"):
                continue
            record["processing"] = True
            out.append(dict(record))
        return out[:limit]


class _Suggestions:
    def __init__(self):
        self.rows: dict[str, dict] = {}

    async def patch(self, record_id: str, tenant_id: str, data: dict) -> dict:
        row = self.rows.get(record_id)
        if row is None or row["tenant_id"] != tenant_id:
            raise KeyError(record_id)
        row.update(data)
        return row


class _World:
    def __init__(self):
        self.inbox = _MemRepo()
        self.outcomes = _MemRepo()
        self.links = _MemRepo()
        self.receipts = _MemRepo()
        self.jobs = _MemRepo()
        self.suggestions = _Suggestions()
        self.secrets: dict[tuple[str, str], str] = {}

    async def resolve_secret(self, job: dict) -> str | None:
        ref = (job.get("provider_config") or {}).get("secret_ref") or ""
        return self.secrets.get((job.get("tenant_id") or "", ref))

    async def bind(
        self, *, tenant: str, provider: str, external_id: str,
        provider_config: dict | None = None, receipt_raw: dict | None = None,
        secret: str | None = None,
    ) -> str:
        suggestion_id = f"sugg-{uuid.uuid4().hex[:8]}"
        self.suggestions.rows[suggestion_id] = {"tenant_id": tenant, "outcome_state": "pending"}
        job_id, receipt_id, link_id = (str(uuid.uuid4()) for _ in range(3))
        config = dict(provider_config or {})
        if secret is not None:
            config["secret_ref"] = f"notif_channel:{job_id}"
            self.secrets[(tenant, config["secret_ref"])] = secret
        await self.jobs.insert(job_id, {
            "tenant_id": tenant, "provider_adapter": provider, "provider_config": config,
        })
        await self.receipts.insert(receipt_id, {
            "tenant_id": tenant, "job_id": job_id, "provider_adapter": provider,
            "external_id": external_id, "raw_response": receipt_raw or {},
        })
        await self.links.insert(link_id, {
            "tenant_id": tenant, "provider": provider, "external_id": external_id,
            "receipt_id": receipt_id, "intent_id": f"intent-{tenant}",
            "resource_type": "suggestion", "resource_id": suggestion_id,
        })
        return suggestion_id

    async def drain(self) -> None:
        from actions.delivery.outcome_processor import OutcomeRouter, WebhookInboxProcessor

        processor = WebhookInboxProcessor(
            inbox_repo=self.inbox,
            outcome_repo=self.outcomes,
            link_repo=self.links,
            router=OutcomeRouter(
                outcome_repo=self.outcomes, link_repo=self.links,
                suggestion_repo=self.suggestions,
            ),
            receipt_repo=self.receipts,
            job_repo=self.jobs,
            secret_resolver=self.resolve_secret,
        )
        await processor.process_pending()

    def state(self, suggestion_id: str) -> str:
        return self.suggestions.rows[suggestion_id]["outcome_state"]

    def outcome_tenants(self) -> list[str]:
        return [o["tenant_id"] for o in self.outcomes._store.values()]

    def errors(self) -> list[str | None]:
        return [r.get("processing_error") for r in self.inbox._store.values()]


@pytest.fixture
def world(monkeypatch):
    import journeys.notification_intelligence.routes as routes
    from config.settings import settings

    w = _World()
    monkeypatch.setattr(routes, "_webhook_inbox_repo", w.inbox)
    monkeypatch.setattr(settings, "delivery", dataclasses.replace(
        settings.delivery,
        jira_webhook_secret=GLOBAL_SECRET,
        linear_webhook_secret=GLOBAL_SECRET,
        webhook_signing_secret=GLOBAL_SECRET,
        inbound_jira_webhook_enabled=True,
    ))
    app = FastAPI()
    app.include_router(routes.router)
    w.client = TestClient(app)
    return w


# ── Jira ──────────────────────────────────────────────────────────────────────


def _post_jira(world: _World, body: dict, **headers) -> int:
    raw = json.dumps(body).encode()
    sig = "sha256=" + hmac.new(GLOBAL_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    resp = world.client.post(
        "/v1/notifications/webhooks/jira/events", content=raw,
        headers={"X-Hub-Signature-256": sig, **headers},
    )
    return resp.status_code


def _jira_event(site: str, key: str = "OPS-7") -> dict:
    return {
        "webhookEvent": "jira:issue_deleted",
        "issue": {"key": key, "self": f"https://{site}/rest/api/2/issue/10001"},
    }


@pytest.mark.asyncio
async def test_jira_routes_by_issue_key_and_site_not_by_header(world):
    sugg_a = await world.bind(
        tenant="tenant-A", provider="jira", external_id="OPS-7",
        provider_config={"base_url": "https://a-co.atlassian.net"},
    )
    sugg_b = await world.bind(
        tenant="tenant-B", provider="jira", external_id="OPS-7",
        provider_config={"base_url": "https://b-co.atlassian.net"},
    )

    assert _post_jira(world, _jira_event("b-co.atlassian.net"), **{"X-Aether-Tenant-ID": "tenant-A"}) == 200
    assert [r["tenant_id"] for r in world.inbox._store.values()] == [""]
    await world.drain()

    assert world.outcome_tenants() == ["tenant-B"]
    assert world.state(sugg_b) == "rejected"
    assert world.state(sugg_a) == "pending"


@pytest.mark.asyncio
async def test_jira_unknown_site_is_dead_lettered(world):
    sugg = await world.bind(
        tenant="tenant-B", provider="jira", external_id="OPS-7",
        provider_config={"base_url": "https://b-co.atlassian.net"},
    )
    _post_jira(world, _jira_event("other-site.atlassian.net"), **{"X-Aether-Tenant-ID": "tenant-B"})
    await world.drain()

    assert world.outcome_tenants() == []
    assert world.errors() == ["unbound_delivery"]
    assert world.state(sugg) == "pending"


@pytest.mark.asyncio
async def test_jira_route_is_404_when_disabled(world, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "delivery", dataclasses.replace(
        settings.delivery, inbound_jira_webhook_enabled=False,
    ))
    assert _post_jira(world, _jira_event("b-co.atlassian.net")) == 404
    assert world.inbox._store == {}


# ── Linear ────────────────────────────────────────────────────────────────────


def _post_linear(world: _World, body: dict, **headers) -> int:
    raw = json.dumps(body).encode()
    sig = hmac.new(GLOBAL_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return world.client.post(
        "/v1/notifications/webhooks/linear/events", content=raw,
        headers={"Linear-Signature": sig, **headers},
    ).status_code


def _linear_event(issue_id: str, *, age_s: float = 0, team="team-B", org="org-B") -> dict:
    return {
        "type": "Issue", "action": "remove",
        "data": {"id": issue_id, "teamId": team},
        "organizationId": org,
        "webhookTimestamp": int((time.time() - age_s) * 1000),
    }


async def _bind_linear(world: _World, tenant: str, issue_id: str) -> str:
    return await world.bind(
        tenant=tenant, provider="linear", external_id=issue_id,
        provider_config={"team_id": "team-B"},
        receipt_raw={"data": {"issueCreate": {"issue": {
            "id": issue_id, "team": {"id": "team-B", "organization": {"id": "org-B"}},
        }}}},
    )


@pytest.mark.asyncio
async def test_linear_routes_by_issue_id_not_by_header(world):
    sugg = await _bind_linear(world, "tenant-B", "lin-uuid-B")
    _post_linear(world, _linear_event("lin-uuid-B"), **{"X-Aether-Tenant-ID": "tenant-A"})
    assert [r["tenant_id"] for r in world.inbox._store.values()] == [""]
    await world.drain()

    assert world.outcome_tenants() == ["tenant-B"]
    assert world.state(sugg) == "rejected"


@pytest.mark.asyncio
async def test_linear_stale_timestamp_is_rejected(world):
    sugg = await _bind_linear(world, "tenant-B", "lin-uuid-B")
    _post_linear(world, _linear_event("lin-uuid-B", age_s=86400))
    await world.drain()

    assert world.outcome_tenants() == []
    assert world.errors() == ["signature_unverified"]
    assert world.state(sugg) == "pending"


@pytest.mark.asyncio
async def test_linear_missing_timestamp_is_rejected(world):
    await _bind_linear(world, "tenant-B", "lin-uuid-B")
    body = _linear_event("lin-uuid-B")
    del body["webhookTimestamp"]
    _post_linear(world, body)
    await world.drain()

    assert world.outcome_tenants() == []


@pytest.mark.asyncio
async def test_linear_organisation_mismatch_is_dropped(world):
    sugg = await _bind_linear(world, "tenant-B", "lin-uuid-B")
    _post_linear(world, _linear_event("lin-uuid-B", org="org-X"))
    await world.drain()

    assert world.outcome_tenants() == []
    assert world.errors() == ["unbound_delivery"]
    assert world.state(sugg) == "pending"


@pytest.mark.asyncio
async def test_linear_issue_moved_to_another_team_still_routes_in_its_organisation(world):
    sugg = await _bind_linear(world, "tenant-B", "lin-uuid-B")
    _post_linear(world, _linear_event("lin-uuid-B", team="team-X"))
    await world.drain()

    assert world.outcome_tenants() == ["tenant-B"]
    assert world.state(sugg) == "rejected"


@pytest.mark.asyncio
async def test_linear_team_mismatch_is_dropped_without_a_stored_organisation(world):
    sugg = await world.bind(
        tenant="tenant-B", provider="linear", external_id="lin-uuid-B",
        provider_config={"team_id": "team-B"},
    )
    _post_linear(world, _linear_event("lin-uuid-B", team="team-X"))
    await world.drain()

    assert world.outcome_tenants() == []
    assert world.errors() == ["unbound_delivery"]
    assert world.state(sugg) == "pending"


@pytest.mark.asyncio
async def test_inbox_row_without_received_at_uses_its_created_at(world):
    """Rows written before ``received_at`` existed are judged by ``created_at``."""
    from datetime import datetime, timezone

    sugg = await _bind_linear(world, "tenant-B", "lin-uuid-B")
    _post_linear(world, _linear_event("lin-uuid-B", age_s=86400))
    (row,) = world.inbox._store.values()
    del row["received_at"]
    row["created_at"] = datetime.fromtimestamp(time.time() - 86400, timezone.utc).isoformat()
    await world.drain()

    assert world.outcome_tenants() == ["tenant-B"]
    assert world.state(sugg) == "rejected"


# ── Aether delivery callback ──────────────────────────────────────────────────


def _post_callback(world: _World, body: dict, secret: str, *, ts: str | None = None, query: str = "") -> int:
    raw = json.dumps(body)
    ts = str(int(time.time())) if ts is None else ts
    sig = hmac.new(secret.encode(), f"{ts}.{raw}".encode(), hashlib.sha256).hexdigest()
    headers = {"X-Aether-Signature": f"v1={sig}"}
    if ts:
        headers["X-Aether-Timestamp"] = ts
    return world.client.post(
        f"/v1/notifications/webhooks/aether/callback{query}", content=raw.encode(), headers=headers,
    ).status_code


@pytest.mark.asyncio
async def test_callback_routes_by_delivery_id_with_channel_secret(world):
    sugg = await world.bind(tenant="tenant-B", provider="webhook", external_id="del-B", secret="secret-B")
    _post_callback(world, {"event_type": "rejected", "delivery_id": "del-B"}, "secret-B", query="?tenant_id=tenant-A")
    assert [r["tenant_id"] for r in world.inbox._store.values()] == [""]
    await world.drain()

    assert world.outcome_tenants() == ["tenant-B"]
    assert [o["external_id"] for o in world.outcomes._store.values()] == ["del-B"]
    assert world.state(sugg) == "rejected"


@pytest.mark.asyncio
async def test_callback_signed_with_platform_secret_is_rejected(world):
    sugg = await world.bind(tenant="tenant-B", provider="webhook", external_id="del-B", secret="secret-B")
    _post_callback(world, {"event_type": "rejected", "delivery_id": "del-B"}, GLOBAL_SECRET)
    await world.drain()

    assert world.outcome_tenants() == []
    assert world.errors() == ["signature_unverified"]
    assert world.state(sugg) == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("age_s", [None, 3600])
async def test_callback_missing_or_stale_timestamp_is_rejected(world, age_s):
    ts = "" if age_s is None else str(int(time.time()) - age_s)
    sugg = await world.bind(tenant="tenant-B", provider="webhook", external_id="del-B", secret="secret-B")
    _post_callback(world, {"event_type": "rejected", "delivery_id": "del-B"}, "secret-B", ts=ts)
    await world.drain()

    assert world.outcome_tenants() == []
    assert world.state(sugg) == "pending"


@pytest.mark.asyncio
async def test_callback_for_unknown_or_ambiguous_delivery_is_dropped(world):
    await world.bind(tenant="tenant-A", provider="webhook", external_id="del-shared", secret="s")
    await world.bind(tenant="tenant-B", provider="webhook", external_id="del-shared", secret="s")
    _post_callback(world, {"event_type": "rejected", "delivery_id": "del-shared"}, "s")
    _post_callback(world, {"event_type": "rejected", "delivery_id": "del-unknown"}, "s")
    await world.drain()

    assert world.outcome_tenants() == []
    assert world.errors() == ["unbound_delivery", "unbound_delivery"]


# ── Round trip: outbound adapter signature → inbound callback ─────────────────


async def _adapter_request(monkeypatch, body: dict, secret: str | None, delivery_id: str) -> tuple[bytes, dict]:
    """The exact bytes and headers the outbound WebhookAdapter sends."""
    import types

    import actions.delivery.adapters.webhook as webhook_mod

    sent: dict = {}

    async def _capture(method, url, *, headers, content, **kw):
        sent.update(headers=dict(headers), content=content)
        return types.SimpleNamespace(status_code=200, text="ok", headers={})

    monkeypatch.setattr(webhook_mod, "send_public_request", _capture)
    await webhook_mod.WebhookAdapter().dispatch(
        payload=body, provider_config={"url": "https://receiver.example/hook"},
        credential=secret, idempotency_key=delivery_id,
    )
    return sent["content"], sent["headers"]


def _replay(world: _World, content: bytes, headers: dict) -> int:
    keep = {k: v for k, v in headers.items() if k.startswith("X-Aether-")}
    return world.client.post(
        "/v1/notifications/webhooks/aether/callback", content=content, headers=keep,
    ).status_code


@pytest.mark.asyncio
async def test_outbound_signed_callback_round_trips(world, monkeypatch):
    sugg = await world.bind(tenant="tenant-B", provider="webhook", external_id="del-RT", secret="secret-B")
    content, headers = await _adapter_request(
        monkeypatch, {"event_type": "rejected", "delivery_id": "del-RT"}, "secret-B", "del-RT",
    )
    assert headers["X-Aether-Timestamp"].isdigit()
    assert _replay(world, content, headers) == 200
    await world.drain()

    assert world.outcome_tenants() == ["tenant-B"]
    assert world.state(sugg) == "rejected"


@pytest.mark.asyncio
async def test_outbound_signed_callback_tampered_is_rejected(world, monkeypatch):
    sugg = await world.bind(tenant="tenant-B", provider="webhook", external_id="del-RT", secret="secret-B")
    content, headers = await _adapter_request(
        monkeypatch, {"event_type": "rejected", "delivery_id": "del-RT"}, "secret-B", "del-RT",
    )
    _replay(world, content.replace(b"rejected", b"resolved"), headers)
    await world.drain()

    assert world.outcome_tenants() == []
    assert world.errors() == ["signature_unverified"]
    assert world.state(sugg) == "pending"


@pytest.mark.asyncio
async def test_outbound_signed_callback_stale_is_rejected(world, monkeypatch):
    import types

    import actions.delivery.adapters.webhook as webhook_mod

    sugg = await world.bind(tenant="tenant-B", provider="webhook", external_id="del-RT", secret="secret-B")
    monkeypatch.setattr(webhook_mod, "time", types.SimpleNamespace(time=lambda: time.time() - 3600))
    content, headers = await _adapter_request(
        monkeypatch, {"event_type": "rejected", "delivery_id": "del-RT"}, "secret-B", "del-RT",
    )
    _replay(world, content, headers)
    await world.drain()

    assert world.outcome_tenants() == []
    assert world.errors() == ["signature_unverified"]
    assert world.state(sugg) == "pending"


# ── Dead letters and unsigned sends are counted ──────────────────────────────


def _dead_letters(reason: str) -> int:
    from shared.logger.logger import metrics

    return metrics.get_counter(
        "delivery_inbox_dead_lettered_total", {"provider": "webhook", "reason": reason},
    )


@pytest.mark.asyncio
async def test_dead_lettered_callbacks_are_counted_by_reason(world):
    unbound, unverified = _dead_letters("unbound_delivery"), _dead_letters("signature_unverified")
    await world.bind(tenant="tenant-B", provider="webhook", external_id="del-B", secret="secret-B")
    _post_callback(world, {"event_type": "rejected", "delivery_id": "del-B"}, GLOBAL_SECRET)
    _post_callback(world, {"event_type": "rejected", "delivery_id": "del-unknown"}, "secret-B")
    await world.drain()

    assert _dead_letters("unbound_delivery") == unbound + 1
    assert _dead_letters("signature_unverified") == unverified + 1


@pytest.mark.asyncio
async def test_outbound_webhook_without_a_signing_secret_is_counted(monkeypatch):
    from shared.logger.logger import metrics

    before = metrics.get_counter("delivery_webhook_unsigned_total")
    _, headers = await _adapter_request(monkeypatch, {"delivery_id": "del-U"}, None, "del-U")

    assert "X-Aether-Signature" not in headers
    assert metrics.get_counter("delivery_webhook_unsigned_total") == before + 1
