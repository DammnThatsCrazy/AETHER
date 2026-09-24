"""Analytics event store projection: ``analytics_event_recorder`` → ``events``/``sessions``.

The stream-ingestion-projection consumer records every validated SDK event in
the tenant analytics store that ``AnalyticsRepository`` serves to
``/v1/analytics/events/query``, ``/v1/analytics/dashboard/summary`` and the
Profile 360 timeline. Covers:

* the recorded row shape matches the query filters (session/user/type/time);
* redelivery (SQS at-least-once) never duplicates the event or the session count;
* strict tenant scoping of reads, record ids and the summary;
* the safe-field policy (no context, no PII-named or PII-shaped properties);
* the session rollup (first/last seen, event count);
* the dashboard summary is computed from the store;
* empty query results are never cached (a poll cannot stick on an empty read);
* the stream-ingestion-projection spec subscribes the recorder.

Every behaviour runs against the in-memory backend. The PostgreSQL half runs the
same assertions when ``ANALYTICS_TEST_DATABASE_URL`` points at a database; each
test uses its own tenant ids, so a shared database needs no truncation.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

os.environ.setdefault("AETHER_ENV", "local")

import pytest  # noqa: E402

from repositories.repos import (  # noqa: E402
    AnalyticsRepository,
    analytics_event_record_id,
    analytics_session_record_id,
    canonical_utc_timestamp,
    reset_in_memory_stores,
)
from services.ingestion import workers  # noqa: E402
from shared.events.events import Event, Topic  # noqa: E402

try:  # asyncpg ships with the backend runtime; guard so collection never fails.
    import asyncpg
except ImportError:  # pragma: no cover
    asyncpg = None  # type: ignore[assignment]

PG_URL = os.getenv("ANALYTICS_TEST_DATABASE_URL")
BACKENDS = ["inmem", "pg"]


class _DictCache:
    def __init__(self) -> None:
        self.store: dict = {}
        self.sets: list = []

    async def get_json(self, key):
        return self.store.get(key)

    async def set_json(self, key, value, ttl=None):
        self.sets.append(key)
        self.store[key] = value


@pytest.fixture
async def repo(request):
    """An AnalyticsRepository bound to the requested backend, also used by the
    recorder under test."""
    kind = request.param
    cache = _DictCache()
    analytics = AnalyticsRepository(cache)
    pool = None
    if kind == "pg":
        if asyncpg is None or not PG_URL:
            pytest.skip("ANALYTICS_TEST_DATABASE_URL not set")
        try:
            pool = await asyncpg.create_pool(PG_URL, min_size=1, max_size=4)
        except Exception as exc:  # pragma: no cover - environment-dependent
            pytest.skip(f"postgres unavailable: {exc}")
        analytics._events._pool = pool
        analytics._sessions._pool = pool
    else:
        reset_in_memory_stores()
    previous = workers._analytics_repository
    workers._analytics_repository = analytics
    try:
        yield analytics
    finally:
        workers._analytics_repository = previous
        if pool is not None:
            await pool.close()


def _tenant() -> str:
    return f"t-{uuid.uuid4().hex[:12]}"


def _now(offset_s: float = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_s)).isoformat()


def _bus_event(tenant_id: str, **overrides) -> Event:
    payload = {
        "event_id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "event_type": "page",
        "event_family": "core",
        "session_id": f"s-{uuid.uuid4().hex}",
        "anonymous_id": f"a-{uuid.uuid4().hex}",
        "user_id": f"u-{uuid.uuid4().hex}",
        "properties": {"path": "/pricing", "run": "424242"},
        "context": {
            "ip": "203.0.113.9",
            "userAgent": "Mozilla/5.0",
            "fingerprint": {"canvas": "abc"},
            "schemaVersion": "1.0.0",
        },
        "timestamp": _now(),
        "received_at": _now(),
        "batch_id": "b-1",
        "schema_version": "1.0.0",
        "source": "sdk",
    }
    payload.update(overrides)
    return Event(
        topic=Topic.SDK_EVENTS_VALIDATED,
        tenant_id=tenant_id,
        source_service="ingestion.batch",
        payload=payload,
    )


# ── Record shape / query contract ────────────────────────────────────────


@pytest.mark.parametrize("repo", BACKENDS, indirect=True)
async def test_processed_event_is_queryable_by_session_and_user(repo):
    tenant = _tenant()
    event = _bus_event(tenant)
    await workers.analytics_event_recorder(event)
    p = event.payload

    # The rehearsal's exact query: EventQuery.model_dump() includes ``limit``.
    by_session = await repo.query_events(tenant, {"session_id": p["session_id"], "limit": 1}, limit=1)
    assert [r["event_id"] for r in by_session] == [p["event_id"]]
    row = by_session[0]
    assert row["tenant_id"] == tenant
    assert row["session_id"] == p["session_id"]
    assert row["anonymous_id"] == p["anonymous_id"]
    assert row["user_id"] == p["user_id"]
    assert row["event_type"] == "page"
    assert row["event_family"] == "core"
    assert row["schema_version"] == "1.0.0"
    assert row["occurred_at"] == canonical_utc_timestamp(p["timestamp"])
    assert row["id"] == analytics_event_record_id(tenant, p["event_id"])

    by_user = await repo.query_events(tenant, {"user_id": p["user_id"]}, limit=10)
    assert [r["event_id"] for r in by_user] == [p["event_id"]]
    by_type = await repo.query_events(
        tenant, {"user_id": p["user_id"], "event_type": "track"}, limit=10
    )
    assert by_type == []

    fetched = await repo.get_event(p["event_id"], tenant_id=tenant)
    assert fetched["event_id"] == p["event_id"]


@pytest.mark.parametrize("repo", BACKENDS, indirect=True)
async def test_time_bounds_filter_on_occurred_at(repo):
    tenant = _tenant()
    user = f"u-{uuid.uuid4().hex}"
    early = _bus_event(tenant, user_id=user, timestamp="2026-01-10T08:00:00Z")
    late = _bus_event(tenant, user_id=user, timestamp="2026-01-12T23:30:00+02:00")
    for ev in (early, late):
        await workers.analytics_event_recorder(ev)

    def ids(rows):
        return {r["event_id"] for r in rows}

    only_late = await repo.query_events(tenant, {"user_id": user, "start_date": "2026-01-11"}, 10)
    assert ids(only_late) == {late.payload["event_id"]}
    # Date-only end bound covers the whole day (late is 21:30Z on the 12th).
    through_12th = await repo.query_events(tenant, {"user_id": user, "end_date": "2026-01-12"}, 10)
    assert ids(through_12th) == {early.payload["event_id"], late.payload["event_id"]}
    only_early = await repo.query_events(
        tenant, {"user_id": user, "end_date": "2026-01-10T08:00:00Z"}, 10
    )
    assert ids(only_early) == {early.payload["event_id"]}


# ── Idempotency ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("repo", BACKENDS, indirect=True)
async def test_redelivery_does_not_duplicate_event_or_session_count(repo):
    tenant = _tenant()
    event = _bus_event(tenant)
    for _ in range(3):  # SQS at-least-once: the same message delivered three times
        await workers.analytics_event_recorder(event)
    assert await repo.record_processed_event(
        workers.build_analytics_event_record(
            event.payload, tenant_id=tenant, event_id=event.payload["event_id"]
        )
    ) is False

    rows = await repo.query_events(tenant, {"session_id": event.payload["session_id"]}, 50)
    assert len(rows) == 1
    session = await repo._sessions.find_by_id(
        analytics_session_record_id(tenant, event.payload["session_id"])
    )
    assert session["event_count"] == 1
    summary = await repo.dashboard_summary(tenant)
    assert summary["total_events"] == 1
    assert summary["total_sessions"] == 1


# ── Tenant scoping ───────────────────────────────────────────────────────


@pytest.mark.parametrize("repo", BACKENDS, indirect=True)
async def test_tenant_isolation_of_reads_ids_and_summary(repo):
    tenant_a, tenant_b = _tenant(), _tenant()
    event = _bus_event(tenant_a)
    await workers.analytics_event_recorder(event)
    p = event.payload

    assert await repo.query_events(tenant_b, {"session_id": p["session_id"]}, 10) == []
    assert await repo.query_events(tenant_b, {"user_id": p["user_id"]}, 10) == []
    # tenant_id in query params can never widen the scope.
    assert await repo.query_events(
        tenant_b, {"session_id": p["session_id"], "tenant_id": tenant_a}, 10
    ) == []
    assert await repo.query_events("", {"session_id": p["session_id"]}, 10) == []
    assert analytics_event_record_id(tenant_a, p["event_id"]) != analytics_event_record_id(
        tenant_b, p["event_id"]
    )

    # The same SDK event id under another tenant is a separate record.
    twin = _bus_event(tenant_b, event_id=p["event_id"], session_id=p["session_id"])
    await workers.analytics_event_recorder(twin)
    assert len(await repo.query_events(tenant_a, {"session_id": p["session_id"]}, 10)) == 1
    assert len(await repo.query_events(tenant_b, {"session_id": p["session_id"]}, 10)) == 1

    empty = await repo.dashboard_summary(_tenant())
    assert empty["total_events"] == 0
    assert empty["total_sessions"] == 0
    assert empty["unique_users"] == 0
    assert empty["top_event_types"] == []


async def test_unscoped_event_is_skipped():
    reset_in_memory_stores()
    event = _bus_event("")
    event.tenant_id = ""
    event.payload["tenant_id"] = ""
    await workers.analytics_event_recorder(event)
    analytics = AnalyticsRepository(_DictCache())
    assert analytics._events._store == {}


# ── Safe-field policy ────────────────────────────────────────────────────


@pytest.mark.parametrize("repo", BACKENDS, indirect=True)
async def test_only_safe_fields_are_persisted(repo):
    tenant = _tenant()
    event = _bus_event(
        tenant,
        properties={
            "path": "/checkout",
            "plan": "pro",
            "count": 3,
            "ratio": 0.5,
            "flag": True,
            "email": "jane@example.com",
            "userEmail": "jane@example.com",
            "contact": "reach me at jane@example.com",
            "phone_number": "+15551234567",
            "ip_address": "198.51.100.4",
            "client": "198.51.100.4",
            "deviceFingerprint": "fp-123",
            "firstName": "Jane",
            "street_address": "1 Main St",
            "password": "hunter2",
            "api_key": "sk_live_x",
            "card_number": "4111111111111111",
            "url": "https://user:pw@shop.example.com/cart?email=jane@example.com&token=abc#frag",
            "nested": {"email": "jane@example.com"},
            "items": [1, 2],
            "long": "x" * 1000,
        },
    )
    await workers.analytics_event_recorder(event)
    [row] = await repo.query_events(tenant, {"session_id": event.payload["session_id"]}, 1)

    assert "context" not in row
    assert "batch_id" not in row
    blob = repr(row)
    for secret in ("203.0.113.9", "Mozilla", "canvas", "jane@example.com", "198.51.100.4",
                   "hunter2", "sk_live_x", "4111111111111111", "fp-123", "Jane", "Main St",
                   "token=abc", "pw@"):
        assert secret not in blob, secret

    props = row["properties"]
    assert props["path"] == "/checkout"
    assert props["plan"] == "pro"
    assert props["count"] == 3
    assert props["ratio"] == 0.5
    assert props["flag"] is True
    assert props["url"] == "https://shop.example.com/cart"
    assert len(props["long"]) == workers.ANALYTICS_MAX_PROPERTY_CHARS
    assert set(props) == {"path", "plan", "count", "ratio", "flag", "url", "long"}


def test_safe_properties_bounds_key_count():
    props = {f"k{i}": i for i in range(workers.ANALYTICS_MAX_PROPERTIES + 10)}
    assert len(workers.safe_analytics_properties(props)) == workers.ANALYTICS_MAX_PROPERTIES
    assert workers.safe_analytics_properties(None) == {}
    assert workers.safe_analytics_properties(["a"]) == {}


# ── Sessions rollup ──────────────────────────────────────────────────────


@pytest.mark.parametrize("repo", BACKENDS, indirect=True)
async def test_session_rollup_tracks_first_last_and_count(repo):
    tenant = _tenant()
    session_id = f"s-{uuid.uuid4().hex}"
    anon = f"a-{uuid.uuid4().hex}"
    middle = _bus_event(tenant, session_id=session_id, anonymous_id=anon, user_id=None,
                        timestamp="2026-03-01T10:05:00Z")
    first = _bus_event(tenant, session_id=session_id, anonymous_id=anon, user_id=None,
                       timestamp="2026-03-01T10:00:00Z")
    last = _bus_event(tenant, session_id=session_id, anonymous_id=anon, user_id="u-late",
                      event_type="identify", timestamp="2026-03-01T10:09:00Z")
    # Out-of-order arrival plus a redelivery of the first.
    for ev in (middle, first, last, first):
        await workers.analytics_event_recorder(ev)

    session = await repo._sessions.find_by_id(analytics_session_record_id(tenant, session_id))
    assert session["record_type"] == "analytics_session"
    assert session["tenant_id"] == tenant
    assert session["session_id"] == session_id
    assert session["anonymous_id"] == anon
    assert session["user_id"] == "u-late"
    assert session["event_count"] == 3
    assert session["first_seen_at"] == "2026-03-01T10:00:00.000000Z"
    assert session["last_seen_at"] == "2026-03-01T10:09:00.000000Z"


# ── Dashboard summary ────────────────────────────────────────────────────


@pytest.mark.parametrize("repo", BACKENDS, indirect=True)
async def test_dashboard_summary_is_computed_from_the_store(repo):
    tenant = _tenant()
    s1, s2 = f"s-{uuid.uuid4().hex}", f"s-{uuid.uuid4().hex}"
    events = [
        _bus_event(tenant, session_id=s1, user_id="alice", event_type="page"),
        _bus_event(tenant, session_id=s1, user_id="alice", event_type="page"),
        _bus_event(tenant, session_id=s1, user_id="alice", event_type="track"),
        _bus_event(tenant, session_id=s2, user_id=None, anonymous_id="anon-1", event_type="page"),
        _bus_event(tenant, session_id=s2, user_id="bob", event_type="identify"),
    ]
    for ev in events:
        await workers.analytics_event_recorder(ev)
    await workers.analytics_event_recorder(_bus_event(_tenant()))  # another tenant's noise

    summary = await repo.dashboard_summary(tenant)
    assert summary == {
        "period": "24h",
        "total_events": 5,
        "total_sessions": 2,
        "unique_users": 3,  # alice, bob, anonymous visitor anon-1
        "top_event_types": [
            {"event_type": "page", "count": 3},
            {"event_type": "identify", "count": 1},
            {"event_type": "track", "count": 1},
        ],
    }

    cross_tenant = await repo.dashboard_summary(None)
    assert cross_tenant["total_events"] >= 6


async def test_dashboard_summary_excludes_rows_outside_the_window():
    reset_in_memory_stores()
    analytics = AnalyticsRepository(_DictCache())
    tenant = _tenant()
    stale = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    await analytics.record_event("old", {"tenant_id": tenant, "event_type": "page",
                                         "user_id": "u"})
    analytics._events._store["old"]["created_at"] = stale
    await analytics.record_event("new", {"tenant_id": tenant, "event_type": "track",
                                         "user_id": "u"})
    summary = await analytics.dashboard_summary(tenant)
    assert summary["total_events"] == 1
    assert summary["top_event_types"] == [{"event_type": "track", "count": 1}]


# ── Query cache ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("repo", BACKENDS, indirect=True)
async def test_empty_results_are_never_cached(repo):
    tenant = _tenant()
    event = _bus_event(tenant)
    query = {"session_id": event.payload["session_id"], "limit": 1}

    assert await repo.query_events(tenant, query, limit=1) == []
    assert repo.cache.sets == []  # the in-flight poll left nothing behind

    await workers.analytics_event_recorder(event)
    rows = await repo.query_events(tenant, query, limit=1)
    assert [r["event_id"] for r in rows] == [event.payload["event_id"]]
    assert len(repo.cache.sets) == 1


def test_invalid_time_bound_is_rejected():
    with pytest.raises(ValueError):
        canonical_utc_timestamp("not-a-date")
    assert canonical_utc_timestamp(None) is None
    assert canonical_utc_timestamp("2026-01-12", end_of_day=True) == "2026-01-12T23:59:59.999999Z"


# ── Consumer wiring ──────────────────────────────────────────────────────


def test_stream_ingestion_projection_subscribes_the_recorder():
    from services.runtime.consumer_specs import CONSUMER_SPECS

    spec = next(s for s in CONSUMER_SPECS if s.name == "stream-ingestion-projection")

    class _Consumer:
        def __init__(self) -> None:
            self.subscriptions: list = []

        def subscribe(self, topic, handler) -> None:
            self.subscriptions.append((topic, handler))

    class _Registry:
        consumer = _Consumer()

    spec.handler_factory(_Registry)
    assert (Topic.SDK_EVENTS_VALIDATED, workers.analytics_event_recorder) in (
        _Registry.consumer.subscriptions
    )
    assert spec.role == "stream-worker"
