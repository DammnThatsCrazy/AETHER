"""Event-outbox relay worker (PR 6 / FT-6-OUTBOX-RELAY).

Exercises ``services.ingestion.outbox_relay.EventOutboxRelay`` against the
in-memory ``event_outbox`` backend (AETHER_ENV=local, no asyncpg), plus the
runtime-role and worker-spec wiring:

  * pending rows are claimed, published to the bus, and marked published
  * published events carry the relay source_service + original topic/payload
  * rows with a future available_at are not claimed
  * publish failure → retry with exponential backoff + last_error
  * attempt ceiling → dead_letter (terminal, kept for ops)
  * an expired claim lease is reclaimed; an unexpired lease is not
  * at-least-once: a crash between publish and mark republishes on reclaim
  * a poison row (unknown topic) converges to dead_letter, never loops
  * sdk_bronze_writer SKIPS relay-originated events (V2 Bronze row is
    already durable in the ingest transaction) but still writes V1 events
  * the outbox-relay runtime role owns the event_outbox_relay spec and the
    spec is gated on OUTBOX_RELAY_ENABLED

Robust to suite ordering: every test evicts and re-imports the backend
modules so a single consistent generation of config.settings /
repositories.repos / services.ingestion.* is used, resets the in-memory
stores, and flips ``settings.ingestion_v2`` on the LIVE singleton.
"""

from __future__ import annotations

import asyncio
import dataclasses
import importlib
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

_BACKEND_PREFIXES = (
    "config", "services", "shared", "middleware", "dependencies", "repositories",
)


def _evict_backend() -> None:
    for name in list(sys.modules):
        if name.split(".", 1)[0] in _BACKEND_PREFIXES:
            sys.modules.pop(name, None)


class _Backend:
    """Freshly-imported, mutually-consistent backend module handle."""

    def __init__(self, **iv2_overrides):
        _evict_backend()
        self.settings_mod = importlib.import_module("config.settings")
        self.repos = importlib.import_module("repositories.repos")
        self.repos.reset_in_memory_stores()
        self.bulk = importlib.import_module("services.ingestion.bronze_bulk")
        self.relay_mod = importlib.import_module("services.ingestion.outbox_relay")
        self.settings = self.settings_mod.settings
        if iv2_overrides:
            object.__setattr__(
                self.settings,
                "ingestion_v2",
                dataclasses.replace(self.settings.ingestion_v2, **iv2_overrides),
            )

    @property
    def bronze_store(self) -> dict:
        return self.repos._IN_MEMORY_STORES.setdefault("bronze_sdk_events", {})

    @property
    def outbox_store(self) -> dict:
        return self.repos._IN_MEMORY_STORES.setdefault("event_outbox", {})


@contextmanager
def fresh(**iv2_overrides):
    b = _Backend(**iv2_overrides)
    try:
        yield b
    finally:
        _evict_backend()


def _run(coro):
    return asyncio.run(coro)


# ── Fakes / builders ─────────────────────────────────────────────────────────

class FakeProducer:
    """Records publishes; optionally fails the first ``fail_times`` calls."""

    def __init__(self, fail_times: int = 0):
        self.published = []
        self.fail_times = fail_times
        self.attempts = 0

    async def publish(self, event) -> None:
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise RuntimeError("bus unavailable")
        self.published.append(event)


def _seed(b, *, tenant="t1", event_id="e1", topic="aether.sdk.events.validated"):
    """Write one Bronze+outbox pair through the real V2 transactional path."""
    payload = {
        "event_id": event_id,
        "tenant_id": tenant,
        "event_type": "track",
        "batch_id": "batch-1",
        "properties": {"k": "v"},
    }
    rec = b.bulk.BronzeSDKEvent(
        tenant_id=tenant,
        event_id=event_id,
        schema_version="1.0.0",
        batch_id="batch-1",
        event_type="track",
        event_family="behavioral",
        event_timestamp="2026-07-16T00:00:00+00:00",
        received_at="2026-07-16T00:00:01+00:00",
        session_id="s1",
        anonymous_id="anon-1",
        user_id=None,
        entity_id="anon-1",
        payload=payload,
    )
    ob = b.bulk.OutboxEvent(
        tenant_id=tenant,
        event_id=event_id,
        topic=topic,
        partition_key="anon-1",
        payload=payload,
    )
    result = _run(b.bulk.ingest_many([rec], [ob]))
    assert result.accepted_count == 1
    return payload


def _relay(b, producer, **kw):
    kw.setdefault("backoff_base_s", 0.0)  # retries immediately claimable in tests
    return b.relay_mod.EventOutboxRelay(producer, **kw)


def _rows(b, status=None):
    rows = list(b.outbox_store.values())
    return [r for r in rows if status is None or r["status"] == status]


# ── Claim → publish → mark ───────────────────────────────────────────────────

def test_drain_publishes_pending_rows_and_marks_published():
    with fresh() as b:
        payload = _seed(b)
        producer = FakeProducer()
        stats = _run(_relay(b, producer).drain_once())

        assert (stats.claimed, stats.published) == (1, 1)
        assert stats.retried == 0 and stats.dead_lettered == 0
        [event] = producer.published
        assert event.topic.value == "aether.sdk.events.validated"
        assert event.tenant_id == "t1"
        assert event.source_service == b.relay_mod.RELAY_SOURCE_SERVICE
        assert event.correlation_id == "batch-1"
        assert event.payload == payload
        [row] = _rows(b)
        assert row["status"] == "published"
        assert row["published_at"] is not None
        assert row["last_error"] is None


def test_drain_is_a_noop_when_outbox_is_empty_or_rows_not_due():
    with fresh() as b:
        producer = FakeProducer()
        assert _run(_relay(b, producer).drain_once()).claimed == 0

        _seed(b)
        # Push the row's availability into the future — must not be claimed.
        [row] = _rows(b)
        row["available_at"] = "2999-01-01T00:00:00+00:00"
        stats = _run(_relay(b, producer).drain_once())
        assert stats.claimed == 0
        assert producer.published == []
        assert _rows(b, "pending")


def test_publish_failure_marks_retry_with_backoff_and_error():
    with fresh() as b:
        _seed(b)
        producer = FakeProducer(fail_times=1)
        relay = _relay(b, producer, backoff_base_s=60.0)
        stats = _run(relay.drain_once())

        assert (stats.claimed, stats.published, stats.retried) == (1, 0, 1)
        [row] = _rows(b)
        assert row["status"] == "retry"
        assert row["attempt_count"] == 1
        assert "bus unavailable" in row["last_error"]
        # Backoff pushed available_at into the future → not immediately reclaimed.
        assert _run(relay.drain_once()).claimed == 0


def test_row_dead_letters_after_max_attempts():
    with fresh() as b:
        _seed(b)
        producer = FakeProducer(fail_times=99)
        relay = _relay(b, producer, max_attempts=2, lease_seconds=0)

        assert _run(relay.drain_once()).retried == 1        # attempt 1
        stats = _run(relay.drain_once())                    # attempt 2 → ceiling
        assert stats.dead_lettered == 1
        [row] = _rows(b)
        assert row["status"] == "dead_letter"
        assert row["attempt_count"] == 2
        # Terminal: nothing further is ever claimed.
        assert _run(relay.drain_once()).claimed == 0


def test_expired_lease_is_reclaimed_and_unexpired_is_not():
    with fresh() as b:
        _seed(b, event_id="expired")
        _seed(b, event_id="held")
        expired = next(r for r in _rows(b) if r["event_id"] == "expired")
        held = next(r for r in _rows(b) if r["event_id"] == "held")
        # Simulate another relay's claims: one lapsed lease, one still live.
        expired.update(status="claimed", claim_owner="other-relay",
                       available_at="2000-01-01T00:00:00+00:00")
        held.update(status="claimed", claim_owner="other-relay",
                    available_at="2999-01-01T00:00:00+00:00")

        producer = FakeProducer()
        stats = _run(_relay(b, producer).drain_once())

        assert stats.claimed == 1 and stats.published == 1
        assert [e.payload["event_id"] for e in producer.published] == ["expired"]
        assert next(r for r in _rows(b) if r["event_id"] == "expired")["status"] == "published"
        assert next(r for r in _rows(b) if r["event_id"] == "held")["status"] == "claimed"


def test_at_least_once_republish_after_crash_between_publish_and_mark():
    with fresh() as b:
        _seed(b)
        crashed = FakeProducer()
        # Relay 1 claims (lease already expired: lease_seconds=0) and publishes,
        # then "crashes" before marking — we call the claim step only.
        relay1 = _relay(b, crashed, lease_seconds=0)
        [claimed_row] = relay1._memory_claim()
        _run(relay1._publish_row(claimed_row))
        assert len(crashed.published) == 1
        assert _rows(b, "claimed")  # never marked published

        # Relay 2 reclaims the lapsed lease and re-publishes → at-least-once.
        producer2 = FakeProducer()
        stats = _run(_relay(b, producer2).drain_once())
        assert stats.claimed == 1 and stats.published == 1
        assert len(producer2.published) == 1
        [row] = _rows(b)
        assert row["status"] == "published"


def test_poison_row_with_unknown_topic_converges_to_dead_letter():
    with fresh() as b:
        _seed(b, event_id="poison", topic="not.a.real.topic")
        producer = FakeProducer()
        relay = _relay(b, producer, max_attempts=2, lease_seconds=0)

        assert _run(relay.drain_once()).retried == 1
        assert _run(relay.drain_once()).dead_lettered == 1
        [row] = _rows(b)
        assert row["status"] == "dead_letter"
        assert "ValueError" in row["last_error"]
        assert producer.published == []


def test_batch_size_bounds_each_claim():
    with fresh() as b:
        for i in range(5):
            _seed(b, event_id=f"e{i}")
        producer = FakeProducer()
        relay = _relay(b, producer, batch_size=2)

        assert _run(relay.drain_once()).claimed == 2
        assert _run(relay.drain_once()).claimed == 2
        assert _run(relay.drain_once()).claimed == 1
        assert len(_rows(b, "published")) == 5


# ── Bronze-writer interplay (no double Bronze write) ─────────────────────────

def test_sdk_bronze_writer_skips_relay_originated_events():
    with fresh() as b:
        workers = importlib.import_module("services.ingestion.workers")
        events_mod = importlib.import_module("shared.events.events")

        payload = {"event_id": "e-relay", "tenant_id": "t1", "event_type": "track"}
        relay_event = events_mod.Event(
            topic=events_mod.Topic.SDK_EVENTS_VALIDATED,
            tenant_id="t1",
            source_service=b.relay_mod.RELAY_SOURCE_SERVICE,
            payload=payload,
        )
        _run(workers.sdk_bronze_writer(relay_event))
        assert b.bronze_store == {}  # V2 row is transaction-durable — no rewrite

        v1_event = events_mod.Event(
            topic=events_mod.Topic.SDK_EVENTS_VALIDATED,
            tenant_id="t1",
            source_service="ingestion.batch",
            payload=dict(payload, event_id="e-v1"),
        )
        _run(workers.sdk_bronze_writer(v1_event))
        assert len(b.bronze_store) == 1  # V1/replay path still writes Bronze


# ── Runtime role + worker-spec wiring ────────────────────────────────────────

def test_outbox_relay_role_owns_the_event_outbox_relay_spec():
    with fresh() as b:
        roles = importlib.import_module("services.runtime.roles")
        owned = roles.ROLE_TO_SPEC_NAMES["outbox-relay"]
        assert {"notification_outbox", "event_outbox_relay"} <= owned
        picked = roles.specs_for_role(
            "outbox-relay", ["event_outbox_relay", "job_worker", "notification_outbox"]
        )
        assert set(picked) == {"event_outbox_relay", "notification_outbox"}
        assert roles.specs_for_role("api", ["event_outbox_relay"]) == []


def test_event_outbox_relay_spec_is_registered_and_flag_gated():
    with fresh(outbox_relay_enabled=False) as b:
        specs_mod = importlib.import_module("services.runtime.specs")
        specs = specs_mod.build_worker_specs(
            registry=SimpleNamespace(producer=None), settings=b.settings
        )
        spec = next(s for s in specs if s.name == "event_outbox_relay")
        assert spec.enabled() is False
        object.__setattr__(
            b.settings,
            "ingestion_v2",
            dataclasses.replace(b.settings.ingestion_v2, outbox_relay_enabled=True),
        )
        assert spec.enabled() is True
        assert spec.required is False


def test_relay_tuning_defaults_come_from_settings():
    with fresh() as b:
        iv2 = b.settings.ingestion_v2
        assert iv2.outbox_relay_batch_size == 100
        assert iv2.outbox_relay_poll_interval_s == 2
        assert iv2.outbox_relay_lease_seconds == 60
        assert iv2.outbox_relay_max_attempts == 8
        relay = b.relay_mod.EventOutboxRelay(FakeProducer())
        assert relay.batch_size == 100
        assert relay.max_attempts == 8
        assert relay.claim_owner  # unique per instance
