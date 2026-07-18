"""Backing-store interruption + consumer restart (in-process models).

These scenarios need external infrastructure to validate END TO END (a live
Redis, a live ClickHouse, a live message bus). That live leg is OUT OF
credentialless scope — it is exercised by the staging runbooks
(docs/runbooks/STAGING_PREFLIGHT.md and the per-domain runbooks). What we CAN
and DO validate credentiallessly here is the RECOVERABLE IN-PROCESS PORTION: the
retry / degrade / buffer-and-flush / lease-reclaim + idempotent-consume logic
that must hold regardless of which server sits behind it.

The at-least-once outbox model mirrors the real durable relay
(``services.ingestion.outbox_relay.EventOutboxRelay``), which is separately
covered against the in-memory ``event_outbox`` backend by
tests/unit/test_outbox_relay.py.

Time comes from ``shared.temporal`` clocks; no wall-clock, no float.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from shared.temporal.clock import FixedClock


# ── Redis interruption (mocked) ───────────────────────────────────────────────
class _FakeRedis:
    """In-memory KV that raises ConnectionError for the first ``fail_next`` ops."""

    def __init__(self, fail_next: int = 0):
        self._data: dict[str, str] = {}
        self.fail_next = fail_next
        self.calls = 0

    def _maybe_fail(self):
        self.calls += 1
        if self.fail_next > 0:
            self.fail_next -= 1
            raise ConnectionError("redis connection reset")

    def get(self, key):
        self._maybe_fail()
        return self._data.get(key)

    def set(self, key, value):
        self._maybe_fail()
        self._data[key] = value


class _ResilientCache:
    """Bounded-retry cache-aside wrapper: retries transient Redis errors, and on
    exhaustion DEGRADES to the origin loader instead of propagating the outage."""

    def __init__(self, redis: _FakeRedis, max_retries: int = 3):
        self._redis = redis
        self._max_retries = max_retries
        self.degraded = False

    def get_or_load(self, key: str, loader):
        for _ in range(self._max_retries):
            try:
                cached = self._redis.get(key)
                if cached is not None:
                    return cached
                value = loader()
                try:
                    self._redis.set(key, value)
                except ConnectionError:
                    self.degraded = True  # write-through failed; value still served
                return value
            except ConnectionError:
                continue
        # Retries exhausted: serve from origin, mark degraded, never crash.
        self.degraded = True
        return loader()


def test_redis_transient_interruption_recovers_within_retry_budget():
    redis = _FakeRedis(fail_next=2)  # two transient blips, then healthy
    cache = _ResilientCache(redis, max_retries=3)
    value = cache.get_or_load("k1", lambda: "loaded-value")
    assert value == "loaded-value"
    assert cache.degraded is False  # recovered inside the retry budget


def test_redis_hard_outage_degrades_to_origin_without_crashing():
    redis = _FakeRedis(fail_next=100)  # outage exceeds the retry budget
    cache = _ResilientCache(redis, max_retries=3)
    value = cache.get_or_load("k1", lambda: "origin-value")
    assert value == "origin-value"     # correctness preserved via the origin loader
    assert cache.degraded is True      # outage surfaced, not swallowed silently


# ── ClickHouse interruption (mocked) ──────────────────────────────────────────
class _FakeClickHouse:
    def __init__(self):
        self.rows: list[dict] = []
        self.down = False

    def insert(self, rows: list[dict]):
        if self.down:
            raise ConnectionError("clickhouse unavailable")
        self.rows.extend(rows)


class _BufferedWriter:
    """Buffers analytics rows while the sink is down; flushes on recovery so no
    row is dropped during the interruption."""

    def __init__(self, sink: _FakeClickHouse):
        self._sink = sink
        self._buffer: list[dict] = []

    def write(self, rows: list[dict]):
        self._buffer.extend(rows)
        self.flush()

    def flush(self) -> bool:
        if not self._buffer:
            return True
        try:
            self._sink.insert(list(self._buffer))
            self._buffer.clear()
            return True
        except ConnectionError:
            return False  # keep buffering; nothing lost

    @property
    def pending(self) -> int:
        return len(self._buffer)


def test_clickhouse_interruption_buffers_then_flushes_without_loss():
    sink = _FakeClickHouse()
    writer = _BufferedWriter(sink)

    sink.down = True
    assert writer.flush() is True  # nothing buffered yet
    writer.write([{"metric": "a", "v": "1"}])
    writer.write([{"metric": "b", "v": "2"}])
    assert writer.pending == 2      # held safely during the outage
    assert sink.rows == []          # nothing written while down

    sink.down = False               # ClickHouse recovers
    assert writer.flush() is True
    assert writer.pending == 0
    assert [r["metric"] for r in sink.rows] == ["a", "b"]  # both rows delivered, in order


# ── consumer restart: at-least-once lease + idempotent consume ────────────────
class _LeaseOutbox:
    """Minimal model of the durable event-outbox relay: lease -> publish ->
    mark, with a crash-safe lease that another worker reclaims once it expires.
    Mirrors ``services.ingestion.outbox_relay.EventOutboxRelay`` semantics."""

    def __init__(self, clock: FixedClock, lease_seconds: int = 30):
        self._rows: dict[str, dict] = {}
        self._clock = clock
        self._lease = lease_seconds

    def enqueue(self, row_id: str, payload: dict):
        self._rows[row_id] = {"id": row_id, "payload": payload, "status": "pending",
                              "lease_until": None, "attempts": 0}

    def claim(self, worker: str) -> list[dict]:
        now = self._clock.now()
        claimed = []
        for row in self._rows.values():
            reclaimable = row["status"] == "claimed" and row["lease_until"] is not None \
                and row["lease_until"] <= now
            if row["status"] == "pending" or reclaimable:
                row["status"] = "claimed"
                row["attempts"] += 1  # increment at CLAIM time (converges to DLQ, never loops)
                row["lease_until"] = _plus_seconds(now, self._lease)
                row["leased_by"] = worker
                claimed.append(row)
        return claimed

    def mark_published(self, row_id: str):
        self._rows[row_id]["status"] = "published"

    def status(self, row_id: str) -> str:
        return self._rows[row_id]["status"]


def _plus_seconds(instant: datetime, seconds: int) -> datetime:
    from datetime import timedelta
    return instant + timedelta(seconds=seconds)


def test_consumer_restart_reclaims_lease_and_consumes_effectively_once():
    """A consumer claims a row, applies the effect, then CRASHES before marking
    it published. After the lease expires a restarted consumer reclaims it and
    re-applies — but the idempotent effect fires exactly once."""
    clock = FixedClock(datetime(2026, 7, 18, tzinfo=timezone.utc))
    outbox = _LeaseOutbox(clock, lease_seconds=30)
    outbox.enqueue("evt-1", {"kind": "reward.ready"})

    effects: set[str] = set()

    def idempotent_consume(row: dict):
        effects.add(row["id"])  # set semantics == idempotent

    # Worker A claims, applies the effect, then crashes before mark_published.
    claimed_a = outbox.claim("worker-A")
    assert [r["id"] for r in claimed_a] == ["evt-1"]
    idempotent_consume(claimed_a[0])
    # ...crash... (no mark_published)
    assert outbox.status("evt-1") == "claimed"

    # Before the lease expires, the row is NOT reclaimable (no double-processing).
    clock.advance(10)
    assert outbox.claim("worker-B") == []

    # After the lease expires, worker B reclaims and completes the delivery.
    clock.advance(30)
    claimed_b = outbox.claim("worker-B")
    assert [r["id"] for r in claimed_b] == ["evt-1"]
    idempotent_consume(claimed_b[0])
    outbox.mark_published("evt-1")

    assert outbox.status("evt-1") == "published"
    assert effects == {"evt-1"}                 # at-least-once delivery, effect-once
    assert outbox._rows["evt-1"]["attempts"] == 2  # both claims counted (DLQ convergence)
