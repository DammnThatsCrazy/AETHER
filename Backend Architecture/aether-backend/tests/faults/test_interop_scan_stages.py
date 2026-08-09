"""Stage-boundary failures: durable interop scan cycle.

Pipeline: scan -> correlate -> dead-letter quarantine -> reconciliation
evidence -> persist reconciliation state -> graph projection -> checkpoint
persist -> event publish -> metering.

Boundary recovery asserted:

  * scan: a rate-limited / generic scan failure reports a failed cycle and
    NEVER advances the checkpoint — the cursor restarts from the same place.
  * persist: a checkpoint write failure raises loudly (no fabricated advance)
    and the re-run collapses — the correlated message row persists exactly
    once, never duplicated.
  * publish: a broker outage at the external publish boundary raises loudly;
    the authoritative state (message row + checkpoint) survives exactly once
    and a replay never re-emits or duplicates. Documented finding: the
    checkpoint is persisted BEFORE the external publish, so a post-advance
    broker failure drops the emitted analytics events (they are not replayed);
    the message repo remains the source of truth.
  * reconcile: a variance between the source and destination legs counts a
    reconciliation conflict in the durable checkpoint — never silent.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
ADV = Path(__file__).resolve().parents[1] / "adversarial"
if str(ADV) not in sys.path:
    sys.path.insert(0, str(ADV))

import faultkit  # noqa: E402
from faultkit import (  # noqa: E402
    BROKER_UNAVAILABLE,
    DB_UNAVAILABLE,
    RECONCILIATION_CONFLICT,
    arm,
    assert_no_duplicates,
    expect_fault,
    make_fault,
)
from repositories.interop_repos import (  # noqa: E402
    InteropMessageRepo,
    InteropProviderCheckpointRepo,
    InteropReconciliationRepo,
)
from services.interop.graph_wiring import InteropGraphProjector  # noqa: E402
from services.interop.providers.base import OperationalFieldsMixin  # noqa: E402
from services.interop.providers.transport import RpcRateLimited  # noqa: E402
from services.interop.publisher import InteropEventPublisher  # noqa: E402
from services.interop.scan_worker import ScanWorker, SENTINEL_NETWORK  # noqa: E402

PROVIDER = "fake"
TENANT = "public"


def _obs(phase: str, key: str, endpoint: dict) -> dict:
    return {
        "correlation_key": key,
        "provider_kind": "fake",
        "phase": phase,
        "endpoint_ref": endpoint,
        "observed_at": "2026-08-09T00:00:00Z",
    }


def _src(key: str, endpoint: dict) -> dict:
    return _obs("sent", key, endpoint)


def _dst(key: str, endpoint: dict) -> dict:
    return _obs("delivered", key, endpoint)


class FakeScanAdapter(OperationalFieldsMixin):
    """Windowed adapter: returns the same observations until its plan exhausts.

    Models a provider whose window has NOT advanced — the durable checkpoint is
    what prevents a restart from re-emitting. ``plan`` items are either
    ``(observations, checkpoint)`` tuples or exceptions raised from ``_scan_cycle``.
    """

    provider_id = PROVIDER
    provider_kind = "fake"

    def __init__(self, plan=None) -> None:
        self._plan = list(plan or [])
        self.scan_calls = 0
        self.rpc = object()  # wired client -> configured=True in operational state

    async def _scan_cycle(self, checkpoint):
        self.scan_calls += 1
        if not self._plan:
            return [], dict(checkpoint or {})
        item = self._plan.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def decode_log(self, raw_log):
        return raw_log


def _worker(adapter, publisher=None):
    return ScanWorker(
        tenant_id=TENANT,
        publisher=publisher or InteropEventPublisher(),
        graph_projector=InteropGraphProjector(enabled=False),
        adapters={PROVIDER: adapter},
    )


async def _assert_single_message(key: str) -> None:
    repo = InteropMessageRepo()
    rows = await repo.find_many({"tenant_id": TENANT, "provider_kind": "fake"}, limit=10)
    assert len(rows) == 1
    assert_no_duplicates(rows, "interop_message_id", label="interop message")
    assert rows[0]["correlation_key"] == key


# ── scan boundary ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scan_boundary_rate_limited_never_advances_checkpoint():
    adapter = FakeScanAdapter([
        RpcRateLimited("provider 429", retry_after=1.0),
    ])
    worker = _worker(adapter)
    summary = await worker.run_cycle(PROVIDER)
    assert summary["status"] == "rate_limited"
    # Checkpoint NEVER advanced on the failed scan.
    assert await InteropProviderCheckpointRepo().count({"tenant_id": TENANT, "provider_id": PROVIDER, "network_id": SENTINEL_NETWORK}) == 0
    assert await InteropMessageRepo().count({"tenant_id": TENANT}) == 0

    # Restart from the same cursor: a healthy scan then completes once.
    adapter2 = FakeScanAdapter([(
        [_src("k1", {"chain": "base", "address": "0xa"}),
         _dst("k1", {"chain": "base", "address": "0xb"})],
        {"networks": {}, "runtime": {}},
    )])
    ok = await _worker(adapter2).run_cycle(PROVIDER)
    assert ok["status"] == "ok" and ok["checkpoint_advanced"] is True
    await _assert_single_message("k1")


@pytest.mark.asyncio
async def test_scan_boundary_generic_error_records_failure_and_resumes():
    adapter = FakeScanAdapter([
        RuntimeError("rpc socket dropped"),
        (
            [_src("k2", {"chain": "base", "address": "0xa"}),
             _dst("k2", {"chain": "base", "address": "0xb"})],
            {"networks": {}, "runtime": {}},
        ),
    ])
    worker = _worker(adapter)
    first = await worker.run_cycle(PROVIDER)
    assert first["status"] == "error"  # loud, not silent-empty
    assert await InteropProviderCheckpointRepo().count({}) == 0  # not advanced

    second = await worker.run_cycle(PROVIDER)
    assert second["status"] == "ok" and second["checkpoint_advanced"] is True
    await _assert_single_message("k2")


# ── persist boundary ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_checkpoint_persist_boundary_failed_write_raises_and_replay_collapses():
    """A failed checkpoint write raises loudly (no fabricated advance); the
    message row correlated BEFORE the write is not lost and is never
    duplicated when the same window is rescanned."""
    observations = [
        _src("k3", {"chain": "base", "address": "0xa"}),
        _dst("k3", {"chain": "base", "address": "0xb"}),
    ]
    adapter = FakeScanAdapter([(observations, {"networks": {}, "runtime": {}})])
    worker = _worker(adapter)

    injector = faultkit.FaultInjector(make_fault(DB_UNAVAILABLE), mode="once")
    restore = arm(worker.checkpoints, "insert", injector)

    exc = await expect_fault(worker.run_cycle(PROVIDER), DB_UNAVAILABLE)
    assert faultkit.classify(exc) == DB_UNAVAILABLE
    # The correlated message row already landed (durable, before the crash).
    await _assert_single_message("k3")
    assert await InteropProviderCheckpointRepo().count({}) == 0  # no fabricated advance

    # Replay the SAME window: the message repo dedups, the checkpoint lands.
    restore()
    replay = await worker.run_cycle(PROVIDER)
    assert replay["status"] == "ok" and replay["checkpoint_advanced"] is True
    await _assert_single_message("k3")  # exactly one authoritative message, no duplicate
    assert await InteropProviderCheckpointRepo().count({}) == 1


# ── publish boundary ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_publish_boundary_broker_outage_keeps_authoritative_state():
    """A broker outage at the external publish raises loudly. The authoritative
    state (message + checkpoint) survives exactly once and a replay never
    duplicates. NOTE (adversarial finding): the checkpoint is persisted BEFORE
    the publish, so a post-advance broker failure drops the emitted analytics
    events (not replayed) — the message repo remains the source of truth."""
    observations = [
        _src("k4", {"chain": "base", "address": "0xa"}),
        _dst("k4", {"chain": "base", "address": "0xb"}),
    ]
    adapter = FakeScanAdapter([(observations, {"networks": {}, "runtime": {}})])
    publisher = InteropEventPublisher()
    worker = _worker(adapter, publisher=publisher)

    injector = faultkit.FaultInjector(make_fault(BROKER_UNAVAILABLE), mode="once")
    restore = arm(publisher, "publish_batch", injector)

    exc = await expect_fault(worker.run_cycle(PROVIDER), BROKER_UNAVAILABLE)
    assert faultkit.classify(exc) == BROKER_UNAVAILABLE
    # Authoritative state survived the failed publish.
    await _assert_single_message("k4")
    assert await InteropProviderCheckpointRepo().count({}) == 1  # checkpoint advanced

    # Restart: the same window is rescanned, correlation dedups (no new
    # events), so publish_batch is not called again and nothing duplicates.
    restore()
    replay = await worker.run_cycle(PROVIDER)
    assert replay["status"] == "ok"
    assert replay["events_published"] == 0
    await _assert_single_message("k4")
    assert len(publisher.published) == 0  # the analytics events were dropped here
    assert await InteropProviderCheckpointRepo().count({}) == 1


# ── reconcile boundary ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reconcile_boundary_conflict_counts_in_durable_checkpoint():
    """A source/destination variance (payload hash mismatch) is counted as a
    reconciliation conflict in the durable checkpoint — never silent."""
    observations = [
        _src("k5", {"chain": "base", "address": "0xa", "payload_hash": "h1"}),
        _dst("k5", {"chain": "base", "address": "0xb", "payload_hash": "h2"}),
    ]
    adapter = FakeScanAdapter([(observations, {"networks": {}, "runtime": {}})])
    summary = await _worker(adapter).run_cycle(PROVIDER)
    assert summary["status"] == "ok"
    assert summary["reconciliation_conflicts"] >= 1

    # The conflict is durable: it lives in the persisted checkpoint runtime.
    rows = await InteropProviderCheckpointRepo().find_many({}, limit=10)
    evidence = rows[0]["evidence"]
    assert evidence["runtime"]["reconciliation_conflicts"] >= 1
    assert evidence["runtime"].get("dead_letter_count", 0) == 0  # conflict != poison message

    # And the variance evidence row exists (immutable record).
    var_rows = await InteropReconciliationRepo().find_many({}, limit=10)
    assert any(r["status"] == "variance_detected" for r in var_rows)
