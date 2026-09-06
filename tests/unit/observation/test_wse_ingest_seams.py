"""WS-E seam tests — flag-gated instrumentation + SDK tier advisory/blocking
driven through the real canonical ingestion spine (``ingest_events``).

These prove the WS-E seams actually fire where they are wired, without changing
event dispositions:

* ingestion-observability OFF (default) → the spine behaves exactly as before
  (dispositions identical) and the operator snapshots report disabled/zeroed.
* ingestion-observability ON  → RECEIVED / VALIDATED / BRONZE funnel buckets
  and per-observation Inspector traces are recorded through the real spine for
  accepted / rejected / duplicate outcomes; the pipeline health surface flips
  healthy/degraded accordingly.
* SDK version-compat OFF (default) → every client is treated identically (no
  ``sdk_tier`` key is ever added).
* SDK version-compat ON (mode=shadow) → an accepted event whose
  ``context.library`` reports a version carries an additive advisory
  ``normalized["sdk_tier"]``; clients without a library are untouched.
* SDK version-compat ON (mode=enforce) → blocked-after-date bands are rejected
  per-event (reason ``sdk_version_blocked:<band>:<label>``) ONLY once the
  blocked-after date has arrived; before that date the same 5.x event is
  accepted with the advisory. Supported bands always pass.

Each test imports a fresh, mutually-consistent backend generation with the
in-memory stores reset (same eviction discipline as
``tests/unit/ingestion_alias/test_deprecated_alias_convergence.py``).
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
    """Captures publish_batch; accepted events are asserted via published[]."""

    def __init__(self) -> None:
        self.published: list = []

    async def publish_batch(self, events) -> None:
        self.published.extend(events)


def _run(coro):
    return asyncio.run(coro)


def _canonical(batch_mod, *, event_id: str, event_type: str = "track",
               consent: dict | None = None, library: dict | None = None,
               **overrides) -> "object":
    ctx_kwargs: dict = {}
    if consent is not None:
        ctx_kwargs["consent"] = consent
    if library is not None:
        ctx_kwargs["library"] = library
    ctx = batch_mod.EventContext(**ctx_kwargs) if ctx_kwargs else batch_mod.EventContext()
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


@contextmanager
def _fresh():
    """Fresh, mutually-consistent backend generation with stores reset."""
    saved = dict(os.environ)
    os.environ["AETHER_ENV"] = "local"
    os.environ.setdefault("JWT_SECRET", "test-secret")
    _evict_backend()
    try:
        repos = importlib.import_module("repositories.repos")
        repos.reset_in_memory_stores()
        batch = importlib.import_module("services.ingestion.batch")
        settings = importlib.import_module("config.settings").settings

        env = SimpleNamespace(
            repos=repos,
            batch=batch,
            settings=settings,
            cache=_FakeCache(),
        )
        env.batch.get_registry = lambda: _FakeRegistry(env.cache)
        env.batch.get_identity_resolver = lambda: None
        env.batch._resolve_identity_safe = _noop_async
        yield env
    finally:
        _evict_backend()
        os.environ.clear()
        os.environ.update(saved)


async def _noop_async(*_a, **_k) -> None:
    return None


def _toggle_observability(settings, enabled: bool) -> None:
    cfg = dataclasses.replace(settings.ingestion_observability, enabled=enabled)
    object.__setattr__(settings, "ingestion_observability", cfg)


def _toggle_version_compat(settings, *, enabled: bool, mode: str) -> None:
    cfg = dataclasses.replace(
        settings.sdk_version_compat, enabled=enabled, mode=mode
    )
    object.__setattr__(settings, "sdk_version_compat", cfg)


def _fresh_obs_module():
    return importlib.import_module("services.ingestion.ingestion_observability")


def _fresh_tiers_module():
    return importlib.import_module("services.ingestion.sdk_version_tiers")


def _req_privacy() -> SimpleNamespace:
    return SimpleNamespace(gpc=False, dnt=False, malformed=())


def _ingest(env, events, producer) -> "object":
    return _run(env.batch.ingest_events(
        events, tenant_id="t1", request_privacy=_req_privacy(),
        server_context=None, granted_consents=frozenset(),
        sent_at=None, producer=producer,
    ))


# ═══════════════════════════════════════════════════════════════════════════
# Baseline — flag OFF must preserve today's dispositions exactly
# ═══════════════════════════════════════════════════════════════════════════

def test_spine_default_flags_off_is_exactly_today_no_sdk_tier_no_telemetry():
    with _fresh() as env:
        producer = _FakeProducer()
        resp = _ingest(env, [
            _canonical(env.batch, event_id="evt-ok"),
            _canonical(env.batch, event_id="evt-unknown", event_type="page_view"),
            _canonical(
                env.batch, event_id="evt-lib",
                library={"name": "@aether/web", "version": "8.12.0"},
            ),
        ], producer)

        # Dispositions unchanged (1 accepted, 1 unknown-type rejected, 1 accepted).
        assert resp.accepted == 2
        assert resp.rejected == 1
        assert [e.status for e in resp.events] == [
            "accepted", "rejected", "accepted",
        ]
        assert resp.events[1].reason == "unknown_event_type:page_view"

        # No advisory tier label ever appears while the compat flag is OFF.
        for ev in producer.published:
            assert "sdk_tier" not in ev.payload

        # Observability OFF → zeroed disabled snapshots, no traces.
        obs = _fresh_obs_module()
        snap = obs.funnel_snapshot()
        assert snap["enabled"] is False
        assert snap["rollup"]["received"] == 0
        assert obs.pipeline_snapshot()["status"] == "disabled"
        assert obs.trace_snapshot("t1", "evt-ok") is None
        assert obs.recent_trace_snapshot() == []


# ═══════════════════════════════════════════════════════════════════════════
# Flag ON — real-spine funnel + Observation Inspector traces
# ═══════════════════════════════════════════════════════════════════════════

def test_spine_observability_on_records_funnel_and_traces():
    with _fresh() as env:
        _toggle_observability(env.settings, True)
        producer = _FakeProducer()
        resp = _ingest(env, [
            _canonical(env.batch, event_id="evt-ok"),
            _canonical(env.batch, event_id="evt-bad", event_type="page_view"),
        ], producer)
        assert resp.accepted == 1
        assert resp.rejected == 1

        obs = _fresh_obs_module()
        snap = obs.funnel_snapshot()
        assert snap["enabled"] is True
        assert snap["rollup"] == {
            "received": 2, "accepted": 1, "duplicates": 0, "rejected": 1, "degraded": 0,
        }
        # Pipeline health: a rejection marks the pipeline degraded.
        pipe = obs.pipeline_snapshot()
        assert pipe["status"] == "degraded"
        assert pipe["pipeline"]["received"] == 2

        # Accepted trace climbs RECEIVED → VALIDATED → BRONZE.
        ok = obs.trace_snapshot("t1", "evt-ok")
        assert ok is not None
        assert [sp["stage"] for sp in ok["spans"]] == ["received", "validated", "bronze"]
        assert [sp["status"] for sp in ok["spans"]] == ["observed", "accepted", "accepted"]
        assert ok["outcome"] == "accepted"
        assert ok["complete"] is True

        # Rejected trace stops at VALIDATED (rejected), never BRONZE.
        bad = obs.trace_snapshot("t1", "evt-bad")
        assert [sp["stage"] for sp in bad["spans"]] == ["received", "validated"]
        assert bad["outcome"] == "rejected"
        assert bad["complete"] is True


def test_spine_observability_on_counts_duplicates_and_publishes_once():
    """A second delivery of the same event id is a duplicate on the funnel, and
    the shared trace shows the accepted pass followed by the duplicate claim."""
    with _fresh() as env:
        _toggle_observability(env.settings, True)
        p1 = _FakeProducer()
        assert _ingest(env, [_canonical(env.batch, event_id="evt-dup")], p1).accepted == 1

        p2 = _FakeProducer()
        resp2 = _ingest(env, [
            _canonical(env.batch, event_id="evt-dup"),
            _canonical(env.batch, event_id="evt-bad", event_type="page_view"),
        ], p2)
        assert resp2.duplicates == 1
        assert resp2.rejected == 1

        obs = _fresh_obs_module()
        rollup = obs.funnel_snapshot()["rollup"]
        assert rollup["received"] == 3  # 1 + 2 across both deliveries
        assert rollup["accepted"] == 1
        assert rollup["duplicates"] == 1
        assert rollup["rejected"] == 1

        # Exactly one publish of evt-dup across both calls (idempotency intact).
        published_ids = [e.payload["event_id"] for e in (p1.published + p2.published)]
        assert published_ids.count("evt-dup") == 1

        # The evt-dup trace records the accepted pass then the duplicate claim.
        trace = obs.trace_snapshot("t1", "evt-dup")
        statuses = [(sp["stage"], sp["status"]) for sp in trace["spans"]]
        assert ("validated", "accepted") in statuses
        assert ("bronze", "accepted") in statuses
        assert statuses[-1] == ("validated", "duplicate")


# ═══════════════════════════════════════════════════════════════════════════
# SDK version tiers — advisory label (shadow) + enforce-mode blocking
# ═══════════════════════════════════════════════════════════════════════════

def test_spine_compat_shadow_attaches_advisory_sdk_tier_label():
    with _fresh() as env:
        _toggle_version_compat(env.settings, enabled=True, mode="shadow")
        producer = _FakeProducer()
        resp = _ingest(env, [
            _canonical(
                env.batch, event_id="evt-lib",
                library={"name": "@aether/web", "version": "8.12.0"},
            ),
            _canonical(
                env.batch, event_id="evt-old6",
                library={"name": "@aether/web", "version": "6.2.0"},
            ),
            _canonical(env.batch, event_id="evt-nolib"),
        ], producer)
        assert resp.accepted == 3

        payloads = {e.payload["event_id"]: e.payload for e in producer.published}
        adv = payloads["evt-lib"]["sdk_tier"]
        assert adv["consulted"] is True
        assert adv["mode"] == "shadow"
        assert adv["tier"] == "supported"
        assert adv["source"] == {"name": "@aether/web", "version": "8.12.0"}
        assert "batch_ingestion" in adv["capabilities"]

        # 6.x is read-compatible (flat capability set, no Envelope-B cap).
        adv6 = payloads["evt-old6"]["sdk_tier"]
        assert adv6["tier"] == "read_compatible"
        assert adv6["blocked_after"] is None

        # A client without a library block is untouched — advisory is additive.
        assert "sdk_tier" not in payloads["evt-nolib"]


def test_spine_compat_enforce_rejects_blocked_bands_only_after_block_date():
    with _fresh() as env:
        _toggle_version_compat(env.settings, enabled=True, mode="enforce")
        # Block date has arrived (fresh module is the one batch imported).
        import services.ingestion.sdk_version_tiers as st
        assert st.BLOCKED_AFTER_DATE == "2027-01-31"
        st._utc_today_iso = lambda: "2027-02-01"

        producer = _FakeProducer()
        resp = _ingest(env, [
            _canonical(
                env.batch, event_id="evt-old5",
                library={"name": "@aether/web", "version": "5.2.0"},
            ),
            _canonical(
                env.batch, event_id="evt-old4",
                library={"name": "@aether/web", "version": "4.1.0"},
            ),
            _canonical(
                env.batch, event_id="evt-ok8",
                library={"name": "@aether/web", "version": "8.12.0"},
            ),
        ], producer)

        assert resp.accepted == 1
        assert resp.rejected == 2
        reasons = {e.id: e.reason for e in resp.events}
        assert reasons["evt-old5"] == "sdk_version_blocked:blocked:blocked-after-date"
        assert reasons["evt-old4"] == "sdk_version_blocked:unsupported:unsupported"
        # Blocked events are never published, never Bronze-durable.
        assert [e.payload["event_id"] for e in producer.published] == ["evt-ok8"]
        bronze = env.repos._IN_MEMORY_STORES["bronze_sdk_events"]
        assert [row.get("provider_record_id") for row in bronze.values()] == ["evt-ok8"]
        # Supported client keeps an advisory tier label.
        assert producer.published[0].payload["sdk_tier"]["tier"] == "supported"


def test_spine_compat_enforce_before_block_date_is_advisory_only():
    with _fresh() as env:
        _toggle_version_compat(env.settings, enabled=True, mode="enforce")
        import services.ingestion.sdk_version_tiers as st
        st._utc_today_iso = lambda: "2026-09-05"  # before 2027-01-31

        producer = _FakeProducer()
        resp = _ingest(env, [
            _canonical(
                env.batch, event_id="evt-old5",
                library={"name": "@aether/web", "version": "5.2.0"},
            ),
        ], producer)
        # Fail-closed by date, never by band alone: 5.x is still accepted.
        assert resp.accepted == 1
        assert resp.rejected == 0
        payload = producer.published[0].payload
        assert payload["sdk_tier"]["tier"] == "blocked"
        assert payload["sdk_tier"]["blocked_after"] == "2027-01-31"
        assert payload["sdk_tier"]["mode"] == "enforce"


def test_spine_compat_enforce_never_blocks_missing_library():
    with _fresh() as env:
        _toggle_version_compat(env.settings, enabled=True, mode="enforce")
        import services.ingestion.sdk_version_tiers as st
        st._utc_today_iso = lambda: "2027-02-01"

        producer = _FakeProducer()
        resp = _ingest(env, [
            _canonical(env.batch, event_id="evt-nolib"),
            _canonical(
                env.batch, event_id="evt-unclass",
                library={"name": "@aether/web", "version": "latest"},
            ),
        ], producer)
        assert resp.accepted == 2
        assert "sdk_tier" not in producer.published[0].payload
        assert producer.published[1].payload["sdk_tier"]["tier"] == "unclassified"


# ═══════════════════════════════════════════════════════════════════════════
# Worker-stage seams — NORMALIZED (silver_normalizer) and PROJECTIONS
# (silver_fact_projector) are recorded by the ingestion worker functions.
# ═══════════════════════════════════════════════════════════════════════════

def _enable_observability(monkeypatch: pytest.MonkeyPatch):
    import importlib
    import types

    obs = importlib.import_module("services.ingestion.ingestion_observability")
    monkeypatch.setattr(obs, "_funnel", obs.IngestionFunnel())
    monkeypatch.setattr(obs, "_traces", obs.TraceStore())
    monkeypatch.setattr(
        obs,
        "settings",
        types.SimpleNamespace(
            ingestion_observability=types.SimpleNamespace(enabled=True),
        ),
    )
    return obs


class _CaptureSilverRepo:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def upsert_record(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return {}


async def test_worker_silver_normalizer_records_normalized_stage(monkeypatch) -> None:
    import services.ingestion.workers as workers

    obs = _enable_observability(monkeypatch)
    repo = _CaptureSilverRepo()
    monkeypatch.setattr(workers, "_silver", repo)

    from shared.events.events import Event, Topic

    await workers.silver_normalizer(Event(
        topic=Topic.SDK_EVENTS_VALIDATED,
        tenant_id="t1",
        source_service="ingestion.batch",
        payload={
            "event_id": "n-evt-1",
            "tenant_id": "t1",
            "event_type": "track",
            "timestamp": "2026-09-05T00:00:00.000Z",
            "user_id": "u-1",
            "anonymous_id": "a-1",
            "session_id": "s-1",
            "schema_version": "1.0.0",
        },
    ))

    assert len(repo.calls) == 1
    assert repo.calls[0]["entity_id"] == "u-1"

    snap = obs.funnel_snapshot()
    assert snap["enabled"] is True
    stages = {s["stage"]: s for s in snap["stages"]}
    assert stages["normalized"]["by_status"] == {"accepted": 1}
    trace = obs.trace_snapshot("t1", "n-evt-1")
    assert trace is not None
    assert trace["spans"][-1]["stage"] == "normalized"
    assert trace["spans"][-1]["status"] == "accepted"
    assert trace["path"] == "ingestion.batch"


async def test_worker_silver_fact_projector_records_projections_stage(monkeypatch) -> None:
    import services.ingestion.workers as workers
    from services.silver import dispatcher as dispatcher_module
    from services.silver import writer as writer_module

    obs = _enable_observability(monkeypatch)

    class _FakeDispatcher:
        def __init__(self) -> None:
            self.captured: list[dict] = []

        def handles(self, event_type: str) -> bool:
            return True

        async def project_with_outcome(self, envelope: dict):
            self.captured.append(dict(envelope))
            return dispatcher_module.ProjectionOutcome(
                event_type="track", results=[{"id": 1}], projector_status=[],
            )

    class _FakeFactWriter:
        async def persist(self, results) -> int:
            return len(results)

    fake_dispatcher = _FakeDispatcher()
    monkeypatch.setattr(dispatcher_module, "SilverDispatcher", lambda: fake_dispatcher)
    monkeypatch.setattr(writer_module, "SilverFactWriter", _FakeFactWriter)

    from shared.events.events import Event, Topic

    await workers.silver_fact_projector(Event(
        topic=Topic.SDK_EVENTS_VALIDATED,
        tenant_id="t1",
        source_service="ingestion.batch",
        payload={
            "event_id": "p-evt-1",
            "tenant_id": "t1",
            "event_type": "track",
            "timestamp": "2026-09-05T00:00:00.000Z",
            "user_id": "u-1",
            "anonymous_id": "a-1",
            "session_id": "s-1",
            "schema_version": "1.0.0",
        },
    ))

    assert len(fake_dispatcher.captured) == 1

    snap = obs.funnel_snapshot()
    stages = {s["stage"]: s for s in snap["stages"]}
    assert stages["projections"]["by_status"] == {"accepted": 1}
    trace = obs.trace_snapshot("t1", "p-evt-1")
    assert trace is not None
    assert trace["spans"][-1]["stage"] == "projections"
    assert trace["spans"][-1]["status"] == "accepted"
