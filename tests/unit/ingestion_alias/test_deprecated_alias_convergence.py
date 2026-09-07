"""WS-B2 — deprecated-alias convergence tests.

Covers the behavior of POST /v1/ingest/events and POST /v1/ingest/events/batch
after convergence onto the canonical V1 spine
(``services.ingestion.batch.ingest_events``):

* kill flag OFF (default) → both handlers still return dispositions (never
  410); an accepted legacy event publishes EXACTLY ONCE to
  ``SDK_EVENTS_VALIDATED`` with the canonical normalized shape.
* Convergence semantics: unknown legacy event types and privacy-signal
  suppressed (consent-enforcement) events are rejected per-event — never
  published, never Bronze-durable; sensitive legacy fields are scrubbed before
  they can reach the bus or Bronze; accepted events are Bronze-durable BEFORE
  the bus publish; a publish failure raises 503 and releases the claimed
  idempotency keys so a retry succeeds.
* kill flag ON → both handlers return HTTP 410 with the retire body and no
  publish / no Bronze side effects.
* Direct ``ingest_events()`` unit test over a small ``Sequence[BaseEvent]``
  (accepted / unknown-type rejected / literal consent-denied / intra-request
  duplicate) proving the refactor preserved the V1 counts and per-event
  statuses.

Each test uses a freshly-imported, mutually-consistent backend generation with
the in-memory stores reset (same eviction discipline as
``tests/unit/test_ingestion_v2.py``) so the observation/gateway flags default
OFF and no real Redis / Postgres / SNS is touched.
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

_BACKEND_PREFIXES = (
    "config", "services", "shared", "middleware", "dependencies", "repositories",
)


def _evict_backend() -> None:
    for name in list(sys.modules):
        if name.split(".", 1)[0] in _BACKEND_PREFIXES:
            sys.modules.pop(name, None)


# ── In-memory stand-ins ───────────────────────────────────────────────────────

class _FakeCache:
    """In-memory stand-in for CacheClient (get / set_nx / delete only)."""

    def __init__(self) -> None:
        self._store: dict = {}

    async def get(self, key: str):
        return self._store.get(key)

    async def set_nx(self, key: str, value: str, ttl=None) -> bool:
        if key in self._store:
            return False
        self._store[key] = value
        return True

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)


class _FakeRegistry:
    def __init__(self, cache: _FakeCache) -> None:
        self.cache = cache


class _FakeProducer:
    """Captures publish_batch; can be told to fail exactly once per request."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.published: list = []

    async def publish_batch(self, events) -> None:
        if self.fail:
            self.fail = False  # fail once, succeed on the caller's retry
            raise RuntimeError("simulated bus failure")
        self.published.extend(events)


class _FakeTenant:
    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        self.checked_perms: list = []

    def require_permission(self, perm) -> None:
        self.checked_perms.append(perm)


class _FakeRequest:
    def __init__(self, tenant_id: str, headers: dict | None = None) -> None:
        self.state = SimpleNamespace(tenant=_FakeTenant(tenant_id))
        self.headers = headers or {}
        self.client = None


def _run(coro):
    return asyncio.run(coro)


# ── Fresh backend generation ──────────────────────────────────────────────────

@contextmanager
def _fresh(kill: bool = False):
    """Import a fresh, mutually-consistent backend generation and reset stores."""
    saved = dict(os.environ)
    os.environ["AETHER_ENV"] = "local"
    os.environ.setdefault("JWT_SECRET", "test-secret")
    _evict_backend()
    try:
        repos = importlib.import_module("repositories.repos")
        repos.reset_in_memory_stores()
        routes = importlib.import_module("services.ingestion.routes")
        batch = importlib.import_module("services.ingestion.batch")
        settings = importlib.import_module("config.settings").settings

        env = SimpleNamespace(
            repos=repos,
            routes=routes,
            batch=batch,
            settings=settings,
            cache=_FakeCache(),
        )
        # Route the canonical spine's registry onto our in-memory cache so the
        # set_nx idempotency claim / release-on-failure paths are deterministic.
        env.batch.get_registry = lambda: _FakeRegistry(env.cache)
        # Neutralize identity resolution (fire-and-forget, out of scope here).
        env.batch.get_identity_resolver = lambda: None
        env.batch._resolve_identity_safe = _noop_async
        if kill:
            _set_kill(settings, True)
        yield env
    finally:
        _evict_backend()
        os.environ.clear()
        os.environ.update(saved)


async def _noop_async(*_a, **_k) -> None:
    return None


def _set_kill(settings, value: bool) -> None:
    cfg = dataclasses.replace(settings.deprecated_ingest_aliases, kill_enabled=value)
    object.__setattr__(settings, "deprecated_ingest_aliases", cfg)


# ── Wire / payload builders ───────────────────────────────────────────────────

def _legacy(event_type: str = "track", **overrides) -> dict:
    wire = {
        "event_type": event_type,
        "session_id": "sess-1",
        "user_id": "u-1",
        "device_id": "dev-1",
        "properties": {"k": "v"},
    }
    wire.update(overrides)
    return wire


def _canonical(batch_mod, *, event_id: str, event_type: str = "track",
               consent: dict | None = None, **overrides) -> "object":
    ctx = batch_mod.EventContext(consent=consent) if consent else batch_mod.EventContext()
    fields = {
        "id": event_id,
        "type": event_type,
        "timestamp": "2026-09-05T00:00:00.000Z",
        "sessionId": "sess-1",
        "anonymousId": "anon-1",
        "userId": "u-1",
        "properties": {},
        "context": ctx,
    }
    fields.update(overrides)
    return batch_mod.BaseEvent(**fields)


# ═══════════════════════════════════════════════════════════════════════════
# 1. Kill flag OFF — handlers still return dispositions, never 410
# ═══════════════════════════════════════════════════════════════════════════

def test_single_route_kill_off_accepts_and_publishes_once():
    with _fresh() as env:
        producer = _FakeProducer()
        req = _FakeRequest("t1")
        resp = _run(env.routes.ingest_single_event(
            env.routes.SDKEvent(**_legacy()),
            req,
            producer=producer,
        ))

        # No 410 — a disposition is returned, response schema preserved.
        assert resp["data"]["status"] == "accepted"
        event_id = resp["data"]["event_id"]

        # Permission parity: the alias now requires WRITE like /v1/batch + /feed.
        from shared.auth.auth import Permissions
        assert req.state.tenant.checked_perms == [Permissions.WRITE]

        # Accepted event published EXACTLY ONCE to SDK_EVENTS_VALIDATED.
        assert len(producer.published) == 1
        ev = producer.published[0]
        from shared.events.events import Topic
        assert ev.topic == Topic.SDK_EVENTS_VALIDATED
        assert ev.tenant_id == "t1"
        assert ev.correlation_id  # internal batch id — canonical spine
        p = ev.payload
        # Canonical normalized shape (as /v1/batch produces).
        assert p["event_id"] == event_id
        assert p["event_type"] == "track"
        assert p["tenant_id"] == "t1"
        assert p["session_id"] == "sess-1"
        # Legacy wire has no anonymous concept → mirrors session id.
        assert p["anonymous_id"] == "sess-1"
        assert p["user_id"] == "u-1"
        # Legacy device_id mapped onto canonical context.device.id
        # (touchpoint_projector reads context.device.id).
        assert p["context"]["device"] == {"id": "dev-1"}
        assert p["properties"] == {"k": "v"}
        assert p["schema_version"] == "1.0.0"
        assert p["received_at"]
        assert p["source"] == "sdk"

        # Durable Bronze row for the accepted event.
        bronze = env.repos._IN_MEMORY_STORES["bronze_sdk_events"]
        assert len(bronze) == 1
        row = next(iter(bronze.values()))
        assert row["provider_record_id"] == event_id
        assert row["tenant_id"] == "t1"
        assert row["payload"]["event_id"] == event_id


def test_batch_route_kill_off_returns_dispositions_and_skips_unknown_type():
    with _fresh() as env:
        producer = _FakeProducer()
        body = env.routes.BatchEventsRequest(events=[
            env.routes.SDKEvent(**_legacy("track", session_id="s1")),
            env.routes.SDKEvent(**_legacy("page_view", session_id="s2")),
        ])
        resp = _run(env.routes.ingest_batch_events(body, _FakeRequest("t1"), producer=producer))

        # Response schema preserved: {accepted, event_ids}; only accepted listed.
        assert resp["data"]["accepted"] == 1
        assert len(resp["data"]["event_ids"]) == 1

        # Only the accepted track event is published; page_view is rejected.
        assert len(producer.published) == 1
        assert producer.published[0].payload["event_type"] == "track"
        assert producer.published[0].payload["session_id"] == "s1"

        # Only the accepted event is Bronze-durable.
        bronze = env.repos._IN_MEMORY_STORES["bronze_sdk_events"]
        assert len(bronze) == 1


def test_single_route_unknown_legacy_type_rejected_never_published():
    """page_view is NOT in CANONICAL_EVENT_TYPES → per-event rejected (WS-B2
    intended enforcement: no more silent publish of non-canonical types)."""
    with _fresh() as env:
        producer = _FakeProducer()
        resp = _run(env.routes.ingest_single_event(
            env.routes.SDKEvent(**_legacy("page_view")),
            _FakeRequest("t1"),
            producer=producer,
        ))
        assert resp["data"]["status"] == "rejected"
        assert len(producer.published) == 0
        assert env.repos._IN_MEMORY_STORES.get("bronze_sdk_events", {}) == {}


# ═══════════════════════════════════════════════════════════════════════════
# 2. Convergence — per-event consent/privacy enforcement + durable-Bronze
#    ordering + scrub + release-on-publish-failure
# ═══════════════════════════════════════════════════════════════════════════

def test_privacy_signal_suppresses_analytics_event_per_event():
    """DNT:1 suppresses analytics-purpose events through the canonical validator
    (consent/privacy enforcement the old alias never had). Rejected per-event —
    never published, never Bronze-durable."""
    with _fresh() as env:
        producer = _FakeProducer()
        req = _FakeRequest("t1", headers={"dnt": "1"})
        resp = _run(env.routes.ingest_single_event(
            env.routes.SDKEvent(**_legacy("track")),
            req,
            producer=producer,
        ))
        assert resp["data"]["status"] == "rejected"
        assert len(producer.published) == 0
        assert env.repos._IN_MEMORY_STORES.get("bronze_sdk_events", {}) == {}


def test_sensitive_legacy_property_scrubbed_before_bus_and_bronze():
    """Sensitive legacy fields are redacted (matching /v1/batch scrub) so the
    raw secret never reaches the published payload or the durable Bronze row."""
    with _fresh() as env:
        producer = _FakeProducer()
        resp = _run(env.routes.ingest_single_event(
            env.routes.SDKEvent(**_legacy("track", properties={"password": "hunter2"})),
            _FakeRequest("t1"),
            producer=producer,
        ))
        assert resp["data"]["status"] == "accepted"
        assert len(producer.published) == 1
        published_props = producer.published[0].payload["properties"]
        assert published_props["password"] == "[REDACTED]"
        assert "hunter2" not in str(producer.published[0].payload)

        bronze = env.repos._IN_MEMORY_STORES["bronze_sdk_events"]
        assert len(bronze) == 1
        row = next(iter(bronze.values()))
        assert row["payload"]["properties"]["password"] == "[REDACTED]"
        assert "hunter2" not in str(row["payload"])


def test_publish_failure_returns_503_and_leaves_durable_bronze():
    """Accepted events are Bronze-durable BEFORE the bus publish; a publish
    failure surfaces 503 (ServiceUnavailableError) and never acks the client."""
    with _fresh() as env:
        producer = _FakeProducer(fail=True)
        from shared.common.common import ServiceUnavailableError
        with pytest.raises(ServiceUnavailableError) as excinfo:
            _run(env.routes.ingest_single_event(
                env.routes.SDKEvent(**_legacy("track")),
                _FakeRequest("t1"),
                producer=producer,
            ))
        assert excinfo.value.code.value == 503
        # Bronze row is already durable even though the bus publish failed.
        bronze = env.repos._IN_MEMORY_STORES["bronze_sdk_events"]
        assert len(bronze) == 1


def test_publish_failure_releases_idempotency_key_so_retry_accepts():
    """Direct spine proof that a publish failure releases the claimed Redis
    idempotency key, so retrying the SAME canonical event id re-accepts (the
    duplicate claim path would otherwise poison the retry)."""
    with _fresh() as env:
        event = _canonical(env.batch, event_id="evt-retry-1")
        req_privacy = SimpleNamespace(gpc=False, dnt=False, malformed=())
        producer = _FakeProducer(fail=True)
        with pytest.raises(Exception):
            _run(env.batch.ingest_events(
                [event], tenant_id="t1", request_privacy=req_privacy,
                server_context=None, granted_consents=frozenset(),
                sent_at=None, producer=producer,
            ))
        # The claimed key was released on publish failure.
        assert env.cache._store == {}
        # Bronze already holds the row; the retry (same event id) re-accepts
        # and Bronze stays idempotent at one row.
        bronze = env.repos._IN_MEMORY_STORES["bronze_sdk_events"]
        assert len(bronze) == 1

        producer2 = _FakeProducer()
        resp = _run(env.batch.ingest_events(
            [event], tenant_id="t1", request_privacy=req_privacy,
            server_context=None, granted_consents=frozenset(),
            sent_at=None, producer=producer2,
        ))
        assert resp.accepted == 1
        assert len(producer2.published) == 1
        assert len(env.repos._IN_MEMORY_STORES["bronze_sdk_events"]) == 1


# ═══════════════════════════════════════════════════════════════════════════
# 3. Kill flag ON — both routes return HTTP 410 with no side effects
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("handler", ["ingest_single_event", "ingest_batch_events"])
def test_kill_flag_on_returns_410(handler):
    with _fresh(kill=True) as env:
        from fastapi import HTTPException
        producer = _FakeProducer()
        if handler == "ingest_single_event":
            args = (env.routes.SDKEvent(**_legacy("track")), _FakeRequest("t1"))
        else:
            body = env.routes.BatchEventsRequest(events=[env.routes.SDKEvent(**_legacy("track"))])
            args = (body, _FakeRequest("t1"))
        with pytest.raises(HTTPException) as excinfo:
            _run(getattr(env.routes, handler)(*args, producer=producer))
        assert excinfo.value.status_code == 410
        detail = excinfo.value.detail
        assert detail["replacement"] == "POST /v1/batch"
        assert detail["deprecated"] is True
        assert "retired" in detail["message"]
        # No publish / no Bronze side effects.
        assert producer.published == []
        assert env.repos._IN_MEMORY_STORES.get("bronze_sdk_events", {}) == {}


# ═══════════════════════════════════════════════════════════════════════════
# 4. Direct ingest_events() — accepted / rejected / duplicate counts preserved
# ═══════════════════════════════════════════════════════════════════════════

def test_ingest_events_direct_mixed_batch_counts():
    """A small Sequence[BaseEvent] with a mix of accepted / unknown-type /
    literal consent-denied / intra-request duplicate returns the correct
    BatchResponse counts and per-event statuses (refactor preserved V1)."""
    with _fresh() as env:
        req_privacy = SimpleNamespace(gpc=False, dnt=False, malformed=())
        events = [
            _canonical(env.batch, event_id="evt-ok"),
            _canonical(env.batch, event_id="evt-ok"),           # intra-request duplicate
            _canonical(env.batch, event_id="evt-unknown", event_type="page_view"),
            _canonical(env.batch, event_id="evt-denied", consent={"analytics": False}),
        ]
        producer = _FakeProducer()
        resp = _run(env.batch.ingest_events(
            events, tenant_id="t1", request_privacy=req_privacy,
            server_context=None, granted_consents=frozenset(),
            sent_at=None, producer=producer,
        ))

        assert resp.accepted == 1
        assert resp.duplicates == 1
        assert resp.rejected == 2
        assert resp.batchId
        assert resp.receivedAt
        assert [e.status for e in resp.events] == [
            "accepted", "duplicate", "rejected", "rejected",
        ]
        assert resp.events[2].reason == "unknown_event_type:page_view"
        assert resp.events[3].reason == "consent_denied:analytics"

        # Only the accepted event is durable + published exactly once.
        assert len(env.repos._IN_MEMORY_STORES["bronze_sdk_events"]) == 1
        assert len(producer.published) == 1
        assert producer.published[0].payload["event_id"] == "evt-ok"
        # The duplicate/denied/unknown rows were never published.
        published_ids = {e.payload["event_id"] for e in producer.published}
        assert published_ids == {"evt-ok"}

        # Idempotency claim path: the accepted key is claimed in the cache.
        assert len(env.cache._store) == 1
