"""Crash-boundary tests for the derivatives durable cursor + stream-gap write
path (agent 1E). Proves:

  * ConnectorCheckpointRepo write path: a checkpoint is persisted on a
    successful pull batch and restored on a fresh runner instance (restart).
  * StreamGapRepo insert path: a SequenceTracker gap event inserts a
    derivatives_stream_gaps row with a deterministic id and resolved_at NULL;
    re-emitting the same gap event does NOT duplicate.
  * Crash -> restart -> resume: a worker killed after a pull resumes from the
    persisted cursor with no duplication and no skip (at-least-once).
  * Reorg/gap recovery is append-only: resolving a gap marks recovered_at and
    keeps the evidence row (never deletes).

Runs against the shared in-memory typed stores — no database, no network.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repositories.derivatives_repos import ConnectorCheckpointRepo, StreamGapRepo
from repositories.typed_repo import reset_typed_in_memory_stores
from services.derivatives.connectors.base import DerivativesConnectorCheckpoint
from services.derivatives.connectors.stream import StreamResult
from services.derivatives.durable_cursor import (
    DerivativesPullRunner,
    GAP_DETECTED_EVENT,
    GAP_RECOVERED_EVENT,
    latest_connector_checkpoint,
    persist_connector_checkpoint,
    persist_stream_gap,
    resolve_stream_gap,
    restore_connector_checkpoint,
    stream_gap_id,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_typed_in_memory_stores()
    yield


class _FakeAdapter:
    """Adapter-shaped fake: pull_events applies a high-water filter so a resumed
    pull emits only records beyond the last emitted key — the venue adapter's
    idempotency contract."""

    def __init__(self, records: list[dict]) -> None:
        self._records = list(records)
        self.pull_count = 0
        self.last_checkpoint_arg = None

    async def pull_events(self, checkpoint=None):
        self.pull_count += 1
        self.last_checkpoint_arg = checkpoint
        cursors = (checkpoint or {}).get("cursors") or {}
        hwm = cursors.get("seq", None)
        emitted = []
        latest = hwm
        for r in self._records:
            key = str(r["seq"])
            if hwm is None or int(key) > int(hwm):
                emitted.append(dict(r))
            if latest is None or int(key) > int(latest):
                latest = key
        return emitted, {"cursors": {"seq": str(latest) if latest is not None else "0"}}


def _records(n: int):
    return [{"seq": i, "payload": f"fill-{i}"} for i in range(1, n + 1)]


def _gap_event(payload: dict) -> dict:
    return {"event_name": GAP_DETECTED_EVENT, "payload": payload}


def _recovered_event(payload: dict) -> dict:
    return {"event_name": GAP_RECOVERED_EVENT, "payload": payload}


# ═══════════════════════════════════════════════════════════════════════════
# Connector checkpoint write path
# ═══════════════════════════════════════════════════════════════════════════

async def test_persist_and_restore_connector_checkpoint():
    repo = ConnectorCheckpointRepo()
    await persist_connector_checkpoint(
        repo, tenant_id="t1", connector_id="hyperliquid",
        checkpoint_value='{"cursors":{"raw_fill":"42"}}', state="ok",
    )
    restored = await restore_connector_checkpoint(
        repo, tenant_id="t1", connector_id="hyperliquid",
    )
    assert restored == '{"cursors":{"raw_fill":"42"}}'
    # No row for another connector.
    assert await restore_connector_checkpoint(repo, tenant_id="t1", connector_id="dydx") is None


async def test_repersist_same_checkpoint_is_idempotent():
    repo = ConnectorCheckpointRepo()
    await persist_connector_checkpoint(
        repo, tenant_id="t1", connector_id="gmx",
        checkpoint_value="cursor-a", state="ok",
    )
    await persist_connector_checkpoint(
        repo, tenant_id="t1", connector_id="gmx",
        checkpoint_value="cursor-a", state="ok",
    )
    rows = await repo.find_many({"tenant_id": "t1", "connector_id": "gmx"})
    assert len(rows) == 1


async def test_advanced_cursor_updates_in_place():
    repo = ConnectorCheckpointRepo()
    await persist_connector_checkpoint(
        repo, tenant_id="t1", connector_id="gmx", checkpoint_value="cursor-1",
    )
    await persist_connector_checkpoint(
        repo, tenant_id="t1", connector_id="gmx", checkpoint_value="cursor-2",
    )
    rows = await repo.find_many({"tenant_id": "t1", "connector_id": "gmx"})
    assert len(rows) == 1
    assert rows[0]["checkpoint_value"] == "cursor-2"
    assert await restore_connector_checkpoint(repo, tenant_id="t1", connector_id="gmx") == "cursor-2"


async def test_persist_checkpoint_dataclass():
    repo = ConnectorCheckpointRepo()
    cp = DerivativesConnectorCheckpoint(
        tenant_id="t1", connector_id="hyperliquid",
        checkpoint_value="fill:42:ts", advanced_at="2026-08-08T00:00:00+00:00",
    )
    await persist_connector_checkpoint(repo, tenant_id=cp.tenant_id, connector_id=cp.connector_id,
                                       checkpoint_value=cp.checkpoint_value, advanced_at=cp.advanced_at)
    row = await latest_connector_checkpoint(repo, tenant_id="t1", connector_id="hyperliquid")
    assert row is not None
    assert row["execution_by_aether"] is False


# ═══════════════════════════════════════════════════════════════════════════
# Stream-gap write path
# ═══════════════════════════════════════════════════════════════════════════

async def test_persist_stream_gap_inserts_deterministic_row():
    repo = StreamGapRepo()
    event = _gap_event({
        "venue_id": "hyperliquid", "canonical_market_id": "hl:mainnet:BTC",
        "channel": "account", "expected_sequence": 7, "received_sequence": 9,
        "detected_at": "2026-08-08T00:00:00+00:00", "status": "open",
    })
    row = await persist_stream_gap(repo, event, tenant_id="t1")
    assert row is not None
    assert row["tenant_id"] == "t1"
    assert row["recovered_at"] is None
    assert row["status"] == "open"
    assert row["expected_sequence"] == 7
    assert row["stream_gap_id"] == stream_gap_id("t1", "hyperliquid", "hl:mainnet:BTC", "account", 7)

    # Re-emit the same gap event -> collapses (no duplicate row).
    await persist_stream_gap(repo, event, tenant_id="t1")
    rows = await repo.find_many({"tenant_id": "t1", "stream_gap_id": row["stream_gap_id"]})
    assert len(rows) == 1


async def test_resolve_stream_gap_is_append_only():
    repo = StreamGapRepo()
    event = _gap_event({
        "venue_id": "hyperliquid", "canonical_market_id": "hl:mainnet:BTC",
        "channel": "account", "expected_sequence": 5, "received_sequence": 8,
        "detected_at": "2026-08-08T00:00:00+00:00", "status": "open",
    })
    row = await persist_stream_gap(repo, event, tenant_id="t1")
    resolved = await resolve_stream_gap(
        repo, tenant_id="t1", venue_id="hyperliquid",
        canonical_market_id="hl:mainnet:BTC", channel="account",
        recovered_at="2026-08-08T00:00:01+00:00",
    )
    assert resolved == 1
    rows = await repo.find_many({"tenant_id": "t1"})
    # Evidence preserved, not deleted: the row is marked recovered.
    assert len(rows) == 1
    assert rows[0]["status"] == "recovered"
    assert rows[0]["recovered_at"] == "2026-08-08T00:00:01+00:00"
    assert rows[0]["stream_gap_id"] == row["stream_gap_id"]


async def test_recovered_event_resolves_open_gap():
    repo = StreamGapRepo()
    await persist_stream_gap(
        repo,
        _gap_event({"venue_id": "v", "canonical_market_id": "m", "channel": "c",
                    "expected_sequence": 3, "received_sequence": 6}),
        tenant_id="t1",
    )
    result = await repo.find_many({"tenant_id": "t1", "status": "open"})
    assert len(result) == 1
    # SequenceTracker's recovery event carries only the stream key.
    from services.derivatives.durable_cursor import persist_stream_gap_events
    counts = await persist_stream_gap_events(
        repo,
        [_recovered_event({"venue_id": "v", "canonical_market_id": "m", "channel": "c"})],
        tenant_id="t1",
    )
    assert counts["recovered"] == 1
    rows = await repo.find_many({"tenant_id": "t1"})
    assert rows[0]["status"] == "recovered"
    assert rows[0]["recovered_at"] is not None


# ═══════════════════════════════════════════════════════════════════════════
# Crash -> restart -> resume
# ═══════════════════════════════════════════════════════════════════════════

async def test_crash_restart_resumes_from_persisted_cursor_no_duplication():
    adapter = _FakeAdapter(_records(5))
    first = DerivativesPullRunner(adapter, tenant_id="t1", connector_id="hyperliquid")
    events1, cp1 = await first.run_pull()
    assert len(events1) == 5
    assert cp1["cursors"]["seq"] == "5"
    # run_pull returns the advanced checkpoint WITHOUT persisting it — the
    # caller ack-persists only after the events are durably processed.
    assert await restore_connector_checkpoint(
        first.checkpoints, tenant_id="t1", connector_id="hyperliquid",
    ) is None
    await first.persist_checkpoint(cp1)  # downstream acknowledged -> advance
    assert await restore_connector_checkpoint(
        first.checkpoints, tenant_id="t1", connector_id="hyperliquid",
    ) is not None

    # ── CRASH: a fresh runner (no in-memory state) over the same durable stores.
    adapter2 = _FakeAdapter(_records(5))
    second = DerivativesPullRunner(adapter2, tenant_id="t1", connector_id="hyperliquid")
    events2, cp2 = await second.run_pull()
    # Resume from the ACKED cursor -> only records beyond seq 5 are new.
    assert events2 == []
    assert cp2["cursors"]["seq"] == "5"
    assert adapter2.last_checkpoint_arg is not None
    assert adapter2.last_checkpoint_arg["cursors"]["seq"] == "5"
    # No duplication of already-emitted events.
    all_rows = await ConnectorCheckpointRepo().find_many({"tenant_id": "t1"})
    assert len(all_rows) == 1


async def test_restart_after_crash_resumes_and_advances():
    adapter = _FakeAdapter(_records(3))
    first = DerivativesPullRunner(adapter, tenant_id="t1", connector_id="hyperliquid")
    events1, cp1 = await first.run_pull()  # pulls 1..3; cursor NOT yet durable
    assert [e["seq"] for e in events1] == [1, 2, 3]
    await first.persist_checkpoint(cp1)  # downstream ack advances the cursor

    # Provider advances to 6; a crashed runner restarts from the ACKED cursor.
    adapter2 = _FakeAdapter(_records(6))
    second = DerivativesPullRunner(adapter2, tenant_id="t1", connector_id="hyperliquid")
    events2, cp2 = await second.run_pull()
    assert [e["seq"] for e in events2] == [4, 5, 6]  # no skip, no duplication
    assert cp2["cursors"]["seq"] == "6"


async def test_run_pull_does_not_advance_until_ack():
    # At-least-once: a crash after run_pull but BEFORE the caller's ack must
    # resume from the OLD cursor and re-deliver the pulled events (never skip).
    adapter = _FakeAdapter(_records(3))
    runner = DerivativesPullRunner(adapter, tenant_id="t1", connector_id="hyperliquid")
    events, cp = await runner.run_pull()
    assert [e["seq"] for e in events] == [1, 2, 3]
    assert cp["cursors"]["seq"] == "3"
    # Nothing durable yet — a crash now resumes from scratch (fresh start).
    assert await restore_connector_checkpoint(
        runner.checkpoints, tenant_id="t1", connector_id="hyperliquid",
    ) is None

    # ── CRASH before ack: a fresh runner re-pulls the SAME records (no skip).
    adapter2 = _FakeAdapter(_records(3))
    fresh = DerivativesPullRunner(adapter2, tenant_id="t1", connector_id="hyperliquid")
    events2, cp2 = await fresh.run_pull()
    assert [e["seq"] for e in events2] == [1, 2, 3]
    # After downstream processing the caller acks and the cursor advances.
    await fresh.persist_checkpoint(cp2)
    assert await restore_connector_checkpoint(
        fresh.checkpoints, tenant_id="t1", connector_id="hyperliquid",
    ) is not None


async def test_fresh_start_restores_none():
    repo = ConnectorCheckpointRepo()
    assert await restore_connector_checkpoint(repo, tenant_id="t1", connector_id="nope") is None


async def test_stream_result_gaps_persisted():
    runner = DerivativesPullRunner(_FakeAdapter(_records(1)), tenant_id="t1", connector_id="x")
    result = StreamResult(
        emitted_events=[
            _gap_event({"venue_id": "v", "canonical_market_id": "m", "channel": "c",
                        "expected_sequence": 2, "received_sequence": 5}),
            _recovered_event({"venue_id": "v", "canonical_market_id": "m", "channel": "c"}),
        ]
    )
    counts = await runner.persist_stream_result(result)
    assert counts == {"detected": 1, "recovered": 1}
    rows = await StreamGapRepo().find_many({"tenant_id": "t1"})
    assert len(rows) == 1
    assert rows[0]["status"] == "recovered"
