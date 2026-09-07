"""Tests for the ingestion-level replay runner + operator route (WS-B4).

Covers the Bronze scan/iteration (stable order + type / family / occurrence-
window filters on the ORIGINAL instant), dry-run (counts only, zero publishes),
a real run (publishes SDK_EVENTS_VALIDATED events whose event_id / timestamp /
envelope occurred_at stay ORIGINAL per Invariant #15 while received_at /
ingested_at are the fresh replay stamps, source_service == ingestion.replay),
gateway rejection counting (never published), re-replay idempotency across
distinct run ids (identity-critical payload equality; the sdk_bronze_writer
consumer skips replay-originated events so no second Bronze row is minted),
the replay_run_id no-op, and the operator route kill switch (dry-run always
allowed; a real run is refused while AETHER_INGESTION_REPLAY_ENABLED is off).
"""

from __future__ import annotations

import pytest

from repositories.repos import _IN_MEMORY_STORES, reset_in_memory_stores
from services.ingestion.replay import (
    REPLAY_SOURCE_SERVICE,
    iter_bronze_observations,
    replay_events,
    reset_run_journal,
)

TENANT = "tenant_replay"


class FakeProducer:
    """In-memory producer capturing every published Event."""

    def __init__(self) -> None:
        self.events = []

    async def publish(self, event) -> None:  # noqa: ANN001
        self.events.append(event)


@pytest.fixture(autouse=True)
def _isolate():
    reset_in_memory_stores()
    reset_run_journal()
    yield
    reset_in_memory_stores()
    reset_run_journal()


def _seed(
    event_id: str,
    *,
    tenant: str = TENANT,
    event_type: str = "track",
    family: str = "core",
    occurred: str = "2026-09-05T00:00:00.000Z",
    received: str = "2026-09-05T00:00:00.100Z",
) -> None:
    """Seed a durable V2-shaped Bronze row whose payload is the flat normalized
    SDK dict the replay rebuild path consumes."""
    store = _IN_MEMORY_STORES.setdefault("bronze_sdk_events", {})
    store[event_id] = {
        "id": f"bronze::{tenant}:{event_id}",
        "tenant_id": tenant,
        "event_id": event_id,
        "schema_version": "1.0.0",
        "event_type": event_type,
        "event_family": family,
        "event_timestamp": occurred,
        "received_at": received,
        "payload": {
            "event_id": event_id,
            "tenant_id": tenant,
            "event_type": event_type,
            "event_family": family,
            "timestamp": occurred,
            "received_at": received,
            "ingested_at": "2026-09-05T00:00:00.200Z",
            "anonymous_id": f"anon-{event_id}",
            "user_id": f"u-{event_id}",
            "properties": {"amount": 1, "currency": "USD"},
            "context": {},
        },
    }


def _published(event) -> dict:  # noqa: ANN001
    return event.payload


# ── Bronze scan ───────────────────────────────────────────────────────────────

async def test_iter_bronze_observations_returns_stable_scan() -> None:
    _seed("e0", occurred="2026-09-05T00:00:00.000Z", received="2026-09-05T00:00:00.100Z")
    _seed("e1", occurred="2026-09-05T00:00:01.000Z", received="2026-09-05T00:00:00.300Z")
    _seed("e2", occurred="2026-09-05T00:00:02.000Z", received="2026-09-05T00:00:00.200Z")
    rows = await iter_bronze_observations(TENANT)
    assert [r["event_id"] for r in rows] == ["e0", "e2", "e1"]  # (received_at, event_id)


async def test_iter_bronze_observations_filters() -> None:
    _seed("e0", event_type="track", family="core", occurred="2026-09-05T00:00:00.000Z")
    _seed("e1", event_type="page", family="core", occurred="2026-09-05T00:30:00.000Z")
    _seed("e2", event_type="track", family="core", occurred="2026-09-05T01:00:00.000Z")

    by_type = await iter_bronze_observations(TENANT, event_types=["page"])
    assert [r["event_id"] for r in by_type] == ["e1"]

    by_family = await iter_bronze_observations(TENANT, families=["core"])
    assert {r["event_id"] for r in by_family} == {"e0", "e1", "e2"}

    # Window applies to the ORIGINAL occurrence instant (Invariant #15).
    window = await iter_bronze_observations(
        TENANT, occurred_from="2026-09-05T00:15:00.000Z", occurred_to="2026-09-05T00:45:00.000Z"
    )
    assert [r["event_id"] for r in window] == ["e1"]

    limited = await iter_bronze_observations(TENANT, limit=2)
    assert len(limited) == 2


# ── Dry run ───────────────────────────────────────────────────────────────────

async def test_dry_run_counts_without_publishing() -> None:
    for i in range(3):
        _seed(f"e{i}", occurred=f"2026-09-05T00:00:0{i}.000Z")
    producer = FakeProducer()
    result = await replay_events(TENANT, dry_run=True, producer=producer, replay_run_id="dry1")
    assert result["dry_run"] is True
    assert result["status"] == "dry_run"
    assert result["scanned"] == 3
    assert result["replayed"] == 3
    assert result["rejected"] == 0
    assert result["skipped"] == 0
    assert producer.events == []  # nothing published


# ── Real run: original-time preservation + replay surface ─────────────────────

async def test_real_run_publishes_replayed_observations() -> None:
    _seed("e0")
    producer = FakeProducer()
    result = await replay_events(TENANT, dry_run=False, producer=producer, replay_run_id="run1")
    assert result["status"] == "completed"
    assert result["replayed"] == 1
    assert result["published"] == 1
    assert result["replayed_event_ids"] == ["e0"]

    (event,) = producer.events
    from shared.events.events import Topic

    assert event.topic == Topic.SDK_EVENTS_VALIDATED
    assert event.source_service == REPLAY_SOURCE_SERVICE
    assert event.correlation_id == "run1"
    assert event.tenant_id == TENANT
    assert event.event_id == "e0"  # original event identity rides the bus Event

    p = _published(event)
    # Invariant #15: event_id + occurrence stay ORIGINAL…
    assert p["event_id"] == "e0"
    assert p["timestamp"] == "2026-09-05T00:00:00.000Z"
    env = p["observation_envelope"]
    assert env["observation"]["observation_id"] == "e0"
    # Same ORIGINAL instant (the additive JSON serializer may render UTC as Z).
    from datetime import datetime

    assert datetime.fromisoformat(
        env["observation"]["occurred_at"].replace("Z", "+00:00")
    ).isoformat() == "2026-09-05T00:00:00+00:00"
    # …while the receipt/ingest stamps are the FRESH replay instant. (The flat
    # payload keeps utc_now()'s "+00:00" spelling; the envelope JSON serializer
    # renders the same instant as "Z" — compare parsed instants.)
    assert p["received_at"] != "2026-09-05T00:00:00.100Z"
    assert p["received_at"] == p["ingested_at"]
    assert datetime.fromisoformat(
        env["observation"]["received_at"].replace("Z", "+00:00")
    ).isoformat() == datetime.fromisoformat(p["received_at"]).isoformat()
    # Replay delivery surface on the envelope (gateway-stamped provenance).
    assert env["source"]["source_type"] == "replay"
    assert env["source"]["source_provider"] == "sdk"
    assert env["source"]["source_native_id"] == "e0"
    assert env["provenance"]["adapter"] == "replay"
    assert env["provenance"]["credential_class"] == "OPERATOR_REPLAY"
    assert env["provenance"]["source_trust"] == "OPERATOR_REPLAY"
    assert env["quality"]["validation_state"] == "gateway:accepted"
    assert env["lineage"]["raw_record_ref"] == f"bronze::{TENANT}:e0"
    assert p["replayed_from_event_id"] == "e0"


async def test_gateway_rejected_row_is_counted_and_never_published() -> None:
    _seed("good")  # track/core → accepted
    _seed("bad", event_type="not_a_real_event", family="core")  # gateway rejection
    producer = FakeProducer()
    result = await replay_events(TENANT, dry_run=False, producer=producer, replay_run_id="run2")
    assert result["scanned"] == 2
    assert result["replayed"] == 1
    assert result["rejected"] == 1
    assert result["rejected_event_ids"] == ["bad"]
    assert result["published"] == 1
    assert [e.event_id for e in producer.events] == ["good"]


# ── Filters on a real run ─────────────────────────────────────────────────────

async def test_real_run_applies_type_and_window_filters() -> None:
    _seed("early", event_type="track", family="core", occurred="2026-09-05T00:00:00.000Z")
    _seed("late", event_type="track", family="core", occurred="2026-09-05T02:00:00.000Z")
    producer = FakeProducer()
    result = await replay_events(
        TENANT,
        event_types=["track"],
        occurred_from="2026-09-05T01:00:00.000Z",
        dry_run=False,
        producer=producer,
        replay_run_id="run3",
    )
    assert result["scanned"] == 1
    assert [e.event_id for e in producer.events] == ["late"]


# ── Idempotency / replay_run_id semantics ────────────────────────────────────

async def test_re_replay_across_run_ids_is_identity_preserving() -> None:
    """Distinct run ids re-deliver the SAME original event. The replay stamps
    (received_at/ingested_at) are fresh per run by design (Invariant #15), so
    the two payloads cannot be byte-identical; the identity-critical surface —
    event_id, occurrence timestamp, envelope occurred_at/observation_id and the
    replay provenance — is asserted equal instead."""
    _seed("e0")
    producer = FakeProducer()
    r1 = await replay_events(TENANT, dry_run=False, producer=producer, replay_run_id="r1")
    r2 = await replay_events(TENANT, dry_run=False, producer=producer, replay_run_id="r2")
    assert r1["published"] == 1 and r2["published"] == 1
    assert len(producer.events) == 2

    a, b = (_published(e) for e in producer.events)
    assert a["event_id"] == b["event_id"] == "e0"
    assert a["timestamp"] == b["timestamp"]
    assert a["replayed_from_event_id"] == b["replayed_from_event_id"]
    assert a["observation_envelope"]["observation"]["occurred_at"] == b[
        "observation_envelope"
    ]["observation"]["occurred_at"]
    assert a["observation_envelope"]["observation"]["observation_id"] == b[
        "observation_envelope"
    ]["observation"]["observation_id"]
    assert a["observation_envelope"]["source"] == b["observation_envelope"]["source"]
    assert a["observation_envelope"]["provenance"] == b["observation_envelope"]["provenance"]
    # Fresh replay receipt stamps per run — observed-vs-received split.
    assert a["received_at"] != b["received_at"]


async def test_replaying_never_mints_a_second_bronze_row() -> None:
    """The sdk_bronze_writer consumer skips replay-originated events — the
    durable Bronze row already exists (it is what was replayed)."""
    _seed("e0")
    producer = FakeProducer()
    await replay_events(TENANT, dry_run=False, producer=producer, replay_run_id="rb1")

    from services.ingestion.workers import sdk_bronze_writer

    for event in producer.events:
        await sdk_bronze_writer(event)  # must no-op for source_service replay

    store = _IN_MEMORY_STORES["bronze_sdk_events"]
    assert len(store) == 1  # exactly the seeded row — no V1 duplicate


async def test_repeated_replay_run_id_is_a_no_op() -> None:
    _seed("e0")
    producer = FakeProducer()
    first = await replay_events(TENANT, dry_run=False, producer=producer, replay_run_id="same")
    second = await replay_events(TENANT, dry_run=False, producer=producer, replay_run_id="same")
    assert second == first
    assert len(producer.events) == 1  # published once only


# ── Operator route wiring ─────────────────────────────────────────────────────

async def test_route_allows_dry_run_preview_while_replay_disabled() -> None:
    """Dry-run is the safe default and never needs the feature flag."""
    _seed("e0")
    from services.ingestion.replay_routes import ReplayRequest, replay_endpoint

    body = ReplayRequest(tenant_id=TENANT, dry_run=True)
    result = await replay_endpoint(body, producer=FakeProducer())
    assert result["dry_run"] is True
    assert result["replayed"] == 1


async def test_route_refuses_a_real_run_while_replay_disabled(monkeypatch) -> None:  # noqa: ANN001
    import types

    from shared.common.common import ForbiddenError

    import services.ingestion.replay_routes as rr

    # Patch the module's settings reference (frozen dataclass — patch the name,
    # not the attribute) to guarantee the kill switch is OFF for this test.
    monkeypatch.setattr(
        rr,
        "settings",
        types.SimpleNamespace(
            ingest_replay=types.SimpleNamespace(enabled=False),
            observation_envelope=types.SimpleNamespace(enabled=False),
            ingress_gateway=types.SimpleNamespace(enabled=False),
        ),
    )
    body = rr.ReplayRequest(tenant_id=TENANT, dry_run=False)
    with pytest.raises(ForbiddenError):
        await rr.replay_endpoint(body, producer=FakeProducer())
