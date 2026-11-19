"""End-to-end email click journey through the real backend code paths.

Mirrors the staging check (one campaign, several inboxes) in-process:

1. the sending system tags a message with ``POST /v1/comms/click-tokens/tag-links``;
2. the recipient clicks; the web SDK lands with ``?ae=<token>`` and sends a
   page event carrying ``trafficSource.clickToken``;
3. ingestion (``build_normalized_payload``) seals the token to the event and
   the Bronze/outbox rows never contain it;
4. the identity worker links the visitor to the recipient's email alias;
5. the Silver dispatcher attributes the landing touchpoint to the recipient;
6. a friend opening the forwarded link on another browser is ``forwarded``
   in both places;
7. the recipient later signs up with that email and lands on the same profile.
"""

from __future__ import annotations

import os
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "services" / "api"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
os.environ.setdefault("AETHER_ENV", "local")

import pytest

pytest.importorskip("fastapi", reason="Backend deps not installed")

TENANT = "tenant-journey"
CONSENT = {"analytics": True, "marketing": True, "policyVersion": "2026-09"}


class FakeCache:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def set_nx(self, key, value, ttl=0):
        if key in self.data:
            return False
        self.data[key] = value
        return True

    async def get(self, key):
        return self.data.get(key)


class FakeProducer:
    def __init__(self) -> None:
        self.published: list = []

    async def publish(self, event) -> None:
        self.published.append(event)


@pytest.fixture
def env(monkeypatch):
    from config.settings import settings
    import dependencies.providers as providers
    from repositories.repos import reset_in_memory_stores

    reset_in_memory_stores()
    monkeypatch.setattr(settings, "identity_continuity", replace(
        settings.identity_continuity,
        resolution_enabled=True,
        auto_merge_enabled=True,
        sdk_late_binding_enabled=True,
        anonymous_to_known_binding_enabled=True,
    ))
    cache = FakeCache()
    monkeypatch.setattr(providers, "get_cache", lambda: cache)

    async def _no_invalidate(_tenant_id):
        return None

    from identity.identity import ingestion_worker

    monkeypatch.setattr(ingestion_worker, "_invalidate_activity_queries", _no_invalidate)
    yield SimpleNamespace(cache=cache)
    reset_in_memory_stores()


class _Tenant:
    tenant_id = TENANT

    def require_permission(self, _permission):
        return None


async def _tagged_links() -> dict[str, str]:
    from journeys.comms.routes import TagLinksBody, tag_links_route

    response = await tag_links_route(
        SimpleNamespace(state=SimpleNamespace(tenant=_Tenant())),
        TagLinksBody(
            campaign_id="campaign-65",
            external_message_id="msg-65",
            allowed_hosts=["shop.test"],
            text="Our sale: https://shop.test/sale?utm_source=email",
            recipients=[{"recipient_email": "jane@example.com"}, {"recipient_email": "sam@example.com"}],
        ),
    )
    copies = response["data"]["recipients"]
    return {
        "jane": copies[0]["text"].split(": ", 1)[1],
        "sam": copies[1]["text"].split(": ", 1)[1],
    }


def _sdk_page(event_id: str, url: str, *, anon: str):
    """The page event the web SDK sends on landing (token in trafficSource)."""
    from ingestion.ingestion.batch import BaseEvent

    token = parse_qs(urlsplit(url).query)["ae"][0]
    return BaseEvent(
        id=event_id,
        type="page",
        timestamp="2026-11-19T12:00:00Z",
        sessionId=f"sess-{anon}",
        anonymousId=anon,
        properties={"url": "https://shop.test/sale?utm_source=email", "path": "/sale"},
        context={
            "library": {"name": "@olympuslabs/aether-web", "version": "9.1.0"},
            "consent": CONSENT,
            "surface": "web",
            "trafficSource": {
                "clickToken": token,
                "utmSource": "email",
                "landingPage": "https://shop.test/sale?utm_source=email",
                "clickIds": {},
                "referrer": "",
                "referrerDomain": "",
            },
            "page": {"url": "https://shop.test/sale?utm_source=email", "path": "/sale"},
        },
    ), token


async def _ingest(event_id: str, url: str, *, anon: str) -> dict:
    """Ingestion boundary + Bronze/outbox rows; returns the bus payload."""
    from ingestion.ingestion.bronze_bulk import BronzeSDKEvent, OutboxEvent, _bronze_row, _outbox_row
    from ingestion.ingestion.validation import build_normalized_payload

    sdk_event, token = _sdk_page(event_id, url, anon=anon)
    payload = build_normalized_payload(sdk_event, TENANT, "batch-1", "2026-11-19T12:00:01Z")
    bronze = _bronze_row(BronzeSDKEvent(
        tenant_id=TENANT, event_id=event_id, schema_version="1", batch_id="batch-1",
        event_type="page", event_family="web", event_timestamp="2026-11-19T12:00:00Z",
        received_at="2026-11-19T12:00:01Z", session_id=f"sess-{anon}", anonymous_id=anon,
        user_id=None, entity_id=anon, payload=payload,
    ))
    outbox = _outbox_row(OutboxEvent(
        tenant_id=TENANT, event_id=event_id, topic="sdk.events.validated",
        partition_key=anon, payload=payload,
    ))
    for stored in (payload, bronze, outbox):
        assert token not in repr(stored), "the reusable link token must never be persisted"
    assert "verified_click" in payload
    return payload


async def _identity(payload: dict) -> str:
    from identity.identity.ingestion_worker import resolve_sdk_observation
    from identity.identity.routes import get_identity_resolver
    from shared.events.events import Event, Topic

    producer = FakeProducer()
    await resolve_sdk_observation(
        Event(
            topic=Topic.SDK_EVENTS_VALIDATED, tenant_id=TENANT, source_service="test",
            correlation_id=payload["event_id"], event_id=payload["event_id"], payload=deepcopy(payload),
        ),
        producer,
    )
    resolved = [e for e in producer.published if e.payload.get("event_id") == payload["event_id"]]
    assert resolved, "identity worker resolved the observation"
    entity = resolved[-1].payload["canonical_entity_id"]
    return await get_identity_resolver()._repo.resolve_surviving_canonical_entity_id(TENANT, entity)


async def _touchpoint(monkeypatch, payload: dict) -> dict:
    from ingestion.ingestion.workers import _bus_payload_to_sdk_envelope
    from ingestion.silver import dispatcher as dispatcher_module
    from ingestion.silver.dispatcher import SilverDispatcher
    from ingestion.silver.projectors.touchpoint_projector import TouchpointProjector

    projector = TouchpointProjector()

    async def resolve_campaign(rows, *, table):
        for row in rows:
            row["_seen_campaign_hint"] = row.pop("_canonical_campaign_id_hint", None)
            row.pop("_utm_id", None)

    async def no_op(*_a, **_k):
        return None

    monkeypatch.setitem(dispatcher_module._TYPE_MAP, "page", [projector])
    monkeypatch.setattr(dispatcher_module, "_resolve_campaign_rows", resolve_campaign)
    monkeypatch.setattr(dispatcher_module, "_shadow_compare_touchpoints", no_op)
    monkeypatch.setattr(dispatcher_module._graph_projector, "maybe_emit", no_op)
    monkeypatch.setattr(dispatcher_module._capability_catalog, "maybe_record", no_op)
    monkeypatch.setattr(projector, "_emit_to_canonical_activity", no_op)

    results = await SilverDispatcher().project(_bus_payload_to_sdk_envelope(deepcopy(payload)))
    rows = [r for res in results for r in (res.rows or [])]
    assert len(rows) == 1
    return rows[0]


@pytest.mark.asyncio
async def test_email_click_journey(env, monkeypatch):
    from identity.identity.models import IdentitySignalType
    from identity.identity.routes import get_identity_resolver
    from journeys.comms.mailbox import build_email_alias

    links = await _tagged_links()
    assert links["jane"] != links["sam"], "every recipient gets their own link"
    jane_alias = build_email_alias("jane@example.com", TENANT).alias_hash

    # Jane clicks on her laptop. Identity runs first (as the worker usually
    # does), so her email alias exists by the time Silver projects the visit.
    click = await _ingest("evt-jane-click", links["jane"], anon="anon-jane")
    jane_entity = await _identity(click)
    repo = get_identity_resolver()._repo
    holders = await repo.find_subjects_by_alias(TENANT, IdentitySignalType.EMAIL_HASH, jane_alias)
    assert [await repo.resolve_surviving_canonical_entity_id(TENANT, h) for h in holders] == [jane_entity]

    row = await _touchpoint(monkeypatch, click)
    assert row["provenance"]["click_correlation"]["recipient_outcome"] == "resolved"
    assert row["identity_resolution_method"] == "signed_click"
    assert row["external_message_id"] == "msg-65"
    assert row["_seen_campaign_hint"] == "campaign-65"
    assert await repo.resolve_surviving_canonical_entity_id(TENANT, row["profile_id"]) == jane_entity

    # Jane forwards the email; Sam's friend opens Jane's link on another browser.
    forwarded = await _ingest("evt-friend-click", links["jane"], anon="anon-friend")
    friend_entity = await _identity(forwarded)
    assert friend_entity != jane_entity, "a forwarded link never joins the friend to Jane"
    friend_row = await _touchpoint(monkeypatch, forwarded)
    assert friend_row["provenance"]["click_correlation"]["recipient_outcome"] == "forwarded"
    assert friend_row["identity_resolution_method"] == "forwarded_link"
    assert friend_row["profile_id"] is None

    # Jane signs up later on the same laptop with her email: same profile.
    from identity.identity.ingestion_worker import resolve_sdk_observation
    from ingestion.ingestion.batch import BaseEvent
    from ingestion.ingestion.validation import build_normalized_payload
    from shared.events.events import Event, Topic

    signup = build_normalized_payload(BaseEvent(
        id="evt-jane-signup", type="identify", timestamp="2026-11-20T09:00:00Z",
        sessionId="sess-jane-2", anonymousId="anon-jane", userId="user-jane",
        properties={"userId": "user-jane", "traits": {"email": "Jane@Example.com"}},
        context={"library": {"name": "@olympuslabs/aether-web", "version": "9.1.0"},
                 "consent": CONSENT, "surface": "web"},
    ), TENANT, "batch-2", "2026-11-20T09:00:01Z")
    producer = FakeProducer()
    await resolve_sdk_observation(Event(
        topic=Topic.SDK_EVENTS_VALIDATED, tenant_id=TENANT, source_service="test",
        correlation_id="evt-jane-signup", event_id="evt-jane-signup", payload=signup,
    ), producer)
    signup_entity = producer.published[-1].payload["canonical_entity_id"]
    assert await repo.resolve_surviving_canonical_entity_id(TENANT, signup_entity) == \
        await repo.resolve_surviving_canonical_entity_id(TENANT, jane_entity)



@pytest.mark.asyncio
async def test_link_from_external_sender_email_attributes_the_click(env, monkeypatch, tmp_path):
    """The external campaign sender mails the campaign; Jane clicks her link."""
    import asyncio
    import concurrent.futures
    import importlib.util
    import json as _json
    from email import message_from_bytes

    from journeys.comms import routes

    path = ROOT / "packages" / "sdk" / "examples" / "campaign-sender-python" / "aether_campaign_sender.py"
    spec = importlib.util.spec_from_file_location("aether_campaign_sender_e2e", path)
    sender = importlib.util.module_from_spec(spec)
    sys.modules["aether_campaign_sender_e2e"] = sender
    spec.loader.exec_module(sender)

    tenant = SimpleNamespace(tenant_id=TENANT, webhook_secret=None, require_permission=lambda _p: None)
    loop = asyncio.get_running_loop()

    async def dispatch(url, body, headers):
        raw = _json.dumps(body, separators=(",", ":")).encode()

        async def read_body():
            return raw

        request = SimpleNamespace(state=SimpleNamespace(tenant=tenant), headers=headers, body=read_body)
        if url.endswith("/tag-links"):
            return await routes.tag_links_route(request, routes.TagLinksBody(**body))
        return await routes.generic_comms_webhook(request, routes.CommsWebhookBody(**body))

    def post_json(url, body, headers):
        # The sender is synchronous; run each call on the test's event loop.
        return asyncio.run_coroutine_threadsafe(dispatch(url, body, headers), loop).result()

    sent: list = []

    class Smtp:
        def send_message(self, message):
            sent.append(message_from_bytes(bytes(message)))

        def quit(self):
            pass

    def run():
        return sender.run_send(
            client=sender.AetherClient("https://aether.test", "key", post_json=post_json),
            transport=sender.SmtpTransport("smtp.test", starttls=False, smtp_factory=lambda h, p: Smtp()),
            ledger=sender.SendLedger(str(tmp_path / "ledger.jsonl")),
            send_id="campaign-65-wave-1",
            message=sender.Message(
                subject="Our sale", mail_from="news@shop.test", allowed_hosts=["shop.test"],
                text="Our sale: https://shop.test/sale?utm_source=email", campaign_id="campaign-65",
            ),
            recipients=["jane@example.com", "sam@example.com"],
            log=lambda _l: None,
        )

    with concurrent.futures.ThreadPoolExecutor(1) as pool:
        summary = await loop.run_in_executor(pool, run)
    assert summary.counts == {"sent": 2} and summary.reported == 2

    jane_mail = next(m for m in sent if m["To"] == "jane@example.com")
    jane_link = jane_mail.get_payload(decode=True).decode().strip().split(": ", 1)[1]
    jane_message_id = jane_mail["X-Aether-Message-Id"]

    click = await _ingest("evt-external-click", jane_link, anon="anon-jane-inbox")
    jane_entity = await _identity(click)
    row = await _touchpoint(monkeypatch, click)
    assert row["provenance"]["click_correlation"]["recipient_outcome"] == "resolved"
    assert row["external_message_id"] == jane_message_id
    assert row["_seen_campaign_hint"] == "campaign-65"
    from identity.identity.routes import get_identity_resolver

    repo = get_identity_resolver()._repo
    assert await repo.resolve_surviving_canonical_entity_id(TENANT, row["profile_id"]) == jane_entity
