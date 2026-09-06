"""WS-E 5 — golden cross-path observation fixture.

One canonical observation payload is defined ONCE and asserted end-to-end
across three distinct ingestion execution paths, all landing the SAME golden
observation on the canonical bus surface (``Topic.SDK_EVENTS_VALIDATED``):

* Path A — canonical server API batch path: the golden BaseEvent is ingested
  through ``services.ingestion.batch.ingest_events`` (the shared spine behind
  POST /v1/batch) → accepted, published once, Bronze-durable.
* Path C — replay / re-import path: the durable Bronze row Path A wrote is
  re-entered through the WS-B4 replay runner (Bronze scan → replay adapter →
  universal gateway → republish). Invariant #15: event_id + occurrence stay
  ORIGINAL; the receipt/ingest stamps are the fresh replay instant; provenance
  is OPERATOR_REPLAY; the durable row is NOT re-minted.
* Path B — legacy server-API import surface: the SAME logical golden action is
  submitted through the WS-B2-converged ``POST /v1/ingest/events`` alias route,
  which now routes through the same canonical spine → accepted and published as
  the canonical normalized observation (per-event validation / scrub / durable
  Bronze / publish parity with /v1/batch).

The fixture asserts the canonical facts of the golden observation (tenant, user,
session, event type, properties, device, occurrence instant) survive every
path, and that no path duplicates a publish. Flag OFF defaults throughout — this
test never depends on any WS-E/OFF flag to pass, so it is a pure convergence +
replay + canonical-output regression test wired into the gate test surface.
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

from shared.auth.auth import Permissions

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

_BACKEND_PREFIXES = (
    "config", "services", "shared", "middleware", "dependencies", "repositories",
)

TENANT = "g-t1"
GOLDEN = {
    "event_id": "g-evt-1",
    "timestamp": "2026-09-05T00:00:00.000Z",
    "session_id": "gs-9",
    "anonymous_id": "ganon-9",
    "user_id": "gu-9",
    "properties": {"k": "v", "n": 42},
    "device_id": "dev-9",
    "library": {"name": "@aether/web", "version": "8.12.0"},
    "event_type": "track",
}


def _evict_backend() -> None:
    for name in list(sys.modules):
        if name.split(".", 1)[0] in _BACKEND_PREFIXES:
            sys.modules.pop(name, None)


class _FakeCache:
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
    """Captures both publish_batch (batch/alias) and publish (replay)."""

    def __init__(self) -> None:
        self.events: list = []

    async def publish_batch(self, events) -> None:
        self.events.extend(events)

    async def publish(self, event) -> None:
        self.events.append(event)


class _FakeTenant:
    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        self.checked_perms: list = []

    def require_permission(self, perm) -> None:
        self.checked_perms.append(perm)


class _FakeRequest:
    def __init__(self, tenant_id: str) -> None:
        self.state = SimpleNamespace(tenant=_FakeTenant(tenant_id))
        self.headers = {}
        self.client = None


def _run(coro):
    return asyncio.run(coro)


@contextmanager
def _fresh():
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
        from services.ingestion import replay

        env = SimpleNamespace(
            repos=repos, routes=routes, batch=batch, settings=settings,
            replay=replay, cache=_FakeCache(), producer=_FakeProducer(),
        )
        env.batch.get_registry = lambda: _FakeRegistry(env.cache)
        env.batch.get_identity_resolver = lambda: None
        env.batch._resolve_identity_safe = _noop_async
        replay.reset_run_journal()
        yield env
    finally:
        replay.reset_run_journal()
        _evict_backend()
        os.environ.clear()
        os.environ.update(saved)


async def _noop_async(*_a, **_k) -> None:
    return None


def _golden_canonical(batch_mod) -> "object":
    ctx = batch_mod.EventContext(
        library=GOLDEN["library"], device={"id": GOLDEN["device_id"]},
    )
    return batch_mod.BaseEvent(
        id=GOLDEN["event_id"],
        type=GOLDEN["event_type"],
        timestamp=GOLDEN["timestamp"],
        sessionId=GOLDEN["session_id"],
        anonymousId=GOLDEN["anonymous_id"],
        userId=GOLDEN["user_id"],
        properties=GOLDEN["properties"],
        context=ctx,
    )


def _golden_wire(routes) -> "object":
    return routes.SDKEvent(
        event_type=GOLDEN["event_type"],
        session_id=GOLDEN["session_id"],
        user_id=GOLDEN["user_id"],
        device_id=GOLDEN["device_id"],
        properties=GOLDEN["properties"],
        timestamp=GOLDEN["timestamp"],
    )


def _assert_golden_facts(payload: dict, *, path: str) -> None:
    """Canonical facts every ingestion path must preserve for the observation."""
    assert payload["event_type"] == GOLDEN["event_type"], path
    assert payload["tenant_id"] == TENANT, path
    assert payload["session_id"] == GOLDEN["session_id"], path
    assert payload["user_id"] == GOLDEN["user_id"], path
    assert payload["properties"] == GOLDEN["properties"], path
    assert payload["schema_version"] == "1.0.0", path
    assert payload["timestamp"] == GOLDEN["timestamp"], path
    assert payload["context"]["device"] == {"id": GOLDEN["device_id"]}, path


def test_golden_observation_across_batch_replay_and_alias_import_paths():
    with _fresh() as env:
        req_privacy = SimpleNamespace(gpc=False, dnt=False, malformed=())

        # ── Path A: canonical /v1/batch spine ───────────────────────────────
        resp_a = _run(env.batch.ingest_events(
            [_golden_canonical(env.batch)], tenant_id=TENANT,
            request_privacy=req_privacy, server_context=None,
            granted_consents=frozenset(), sent_at=None,
            producer=env.producer,
        ))
        assert resp_a.accepted == 1
        assert resp_a.rejected == 0

        # ── Path C: replay / re-import of the durable Bronze row ───────────
        replay_result = _run(env.replay.replay_events(
            TENANT, dry_run=False, producer=env.producer,
            replay_run_id="golden-run-1",
        ))
        assert replay_result["scanned"] == 1
        assert replay_result["replayed"] == 1
        assert replay_result["published"] == 1
        assert replay_result["errors"] == []
        assert replay_result["replayed_event_ids"] == [GOLDEN["event_id"]]

        # ── Path B: legacy server-API import surface (WS-B2 converged) ─────
        req = _FakeRequest(TENANT)
        resp_b = _run(env.routes.ingest_single_event(
            _golden_wire(env.routes), req, producer=env.producer,
        ))
        assert resp_b["data"]["status"] == "accepted"
        assert req.state.tenant.checked_perms == [Permissions.WRITE]

        # ── Assertions ─────────────────────────────────────────────────────
        by_source: dict[str, list] = {}
        for ev in env.producer.events:
            by_source.setdefault(getattr(ev, "source_service", ""), []).append(ev)

        batch_published = by_source.get("ingestion.batch", [])
        replay_published = by_source.get(env.replay.REPLAY_SOURCE_SERVICE, [])
        # Two live-surface deliveries (Path A + Path B) and one replay delivery.
        assert len(batch_published) == 2
        assert len(replay_published) == 1

        # Path A payload (the golden event id).
        pa_payload = next(
            ev.payload for ev in batch_published
            if ev.payload["event_id"] == GOLDEN["event_id"]
        )
        _assert_golden_facts(pa_payload, path="batch")
        assert pa_payload["anonymous_id"] == GOLDEN["anonymous_id"]
        assert "sdk_tier" not in pa_payload  # WS-E compat flag is OFF by default
        assert pa_payload["source"] == "sdk"

        # Path C replay delivery preserves the identity-critical surface
        # (Invariant #15) and stamps replay provenance.
        (rc_event,) = replay_published
        rc = rc_event.payload
        assert rc["event_id"] == GOLDEN["event_id"]
        assert rc["timestamp"] == GOLDEN["timestamp"]
        assert rc["replayed_from_event_id"] == GOLDEN["event_id"]
        assert rc["observation_envelope"]["source"]["source_type"] == "replay"
        assert rc["observation_envelope"]["provenance"]["adapter"] == "replay"
        assert rc["observation_envelope"]["provenance"]["credential_class"] == "OPERATOR_REPLAY"
        _assert_golden_facts(rc, path="replay")
        # Fresh replay receipt stamps differ from the original received_at.
        assert rc["received_at"] != pa_payload["received_at"]
        assert rc["received_at"] == rc["ingested_at"]

        # Path B (alias) payload carries the same canonical golden facts; the
        # documented legacy-wire translation mirrors anonymous → session id and
        # generates a fresh server event id.
        alias_event_id = resp_b["data"]["event_id"]
        assert alias_event_id != GOLDEN["event_id"]
        pb_payload = next(
            ev.payload for ev in batch_published
            if ev.payload["event_id"] == alias_event_id
        )
        _assert_golden_facts(pb_payload, path="alias-import")
        assert pb_payload["anonymous_id"] == GOLDEN["session_id"]
        assert pb_payload["context"]["device"] == {"id": GOLDEN["device_id"]}

        # End-to-end: two durable Bronze rows (Path A golden + Path B alias);
        # replay never minted a second row for g-evt-1.
        bronze = env.repos._IN_MEMORY_STORES["bronze_sdk_events"]
        row_ids = sorted(
            row.get("provider_record_id") for row in bronze.values()
        )
        assert row_ids == sorted([GOLDEN["event_id"], alias_event_id])

        # The golden observation is delivered exactly twice total (the live
        # batch delivery and the replay re-delivery) — never a third time.
        golden_deliveries = [
            ev for ev in env.producer.events
            if ev.payload["event_id"] == GOLDEN["event_id"]
        ]
        assert len(golden_deliveries) == 2
