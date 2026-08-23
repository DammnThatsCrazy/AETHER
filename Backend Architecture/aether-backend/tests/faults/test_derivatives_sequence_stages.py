"""Stage-boundary failures: derivatives stream sequence.

Pipeline: open stream -> consume frame -> sequence check (duplicate /
out-of-order / gap) -> persist cursor (durable resume).

Boundary recovery asserted:

  * persist: the advanced cursor is persisted BEFORE run_once returns, so a
    worker killed immediately after still resumes from it (at-least-once). A
    process restart over the same durable checkpoint resumes at the exact next
    contiguous sequence — no replay of already-acked frames, no skip.
  * duplicate: a re-sent frame (sequence < expected) is detected and never
    re-accepted.
  * out-of-order: a future frame is buffered and released in provider order
    when the hole closes — never emitted out of order, never lost.
  * disconnect: a connection drop reconnects and resumes from the next
    contiguous sequence — both frames land exactly once, no data loss.
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

from faultkit import PlanSource, frame  # noqa: E402
from repositories.derivatives_repos import ConnectorCheckpointRepo  # noqa: E402
from services.derivatives.adapters.hyperliquid import HyperliquidAdapter  # noqa: E402
from services.derivatives.connectors.stream import StreamDisconnect  # noqa: E402
from services.derivatives.sequence import SupervisedStreamWorker  # noqa: E402

TENANT = "t1"
CONNECTOR = "hyperliquid"


def _adapter(source):
    return HyperliquidAdapter(stream_factory=source)


def _worker(adapter):
    return SupervisedStreamWorker(adapter, tenant_id=TENANT, connector_id=CONNECTOR)


def _fill_ids(result) -> list[str]:
    return [p["fill_id"] for p in result.accepted]


# ── cursor persist / restart boundary ───────────────────────────────────

class ResumeBoundarySource:
    """Venue-faithful source: after a process restart it opens AT the resume
    cursor and only re-sends frames at or beyond that boundary (a real venue
    never re-sends acked frames). Records the cursor it was asked to resume
    from."""

    def __init__(self, plan) -> None:
        self.plan = list(plan)
        self.resume_cursors = []

    async def __call__(self, resume_cursor=None):
        self.resume_cursors.append(resume_cursor)
        for item in self.plan:
            if isinstance(item, dict) and resume_cursor is not None:
                seq = item.get("sequence")
                if seq is not None and seq < resume_cursor:
                    continue  # already acked before the restart
            yield item


@pytest.mark.asyncio
async def test_cursor_persist_boundary_restart_resumes_at_exact_next_sequence():
    first_source = ResumeBoundarySource([frame(1, {"fill_id": "f1"}), frame(2, {"fill_id": "f2"})])
    first = await _worker(_adapter(first_source)).run_once()
    assert _fill_ids(first) == ["f1", "f2"]
    # The cursor is durable BEFORE run_once returns (kill-proof).
    assert await _worker(_adapter(first_source)).restore_cursor() == 3

    # PROCESS RESTART: a fresh worker over the SAME durable checkpoint.
    restart_source = ResumeBoundarySource([frame(3, {"fill_id": "f3"})])
    restarted = await _worker(_adapter(restart_source)).run_once()
    # The venue was asked to resume from the persisted boundary — never scratch.
    assert restart_source.resume_cursors == [3]
    assert _fill_ids(restarted) == ["f3"]  # no replay of f1/f2, no skip
    assert await _worker(_adapter(restart_source)).restore_cursor() == 4

    # Exactly one durable checkpoint row (idempotent persist).
    rows = await ConnectorCheckpointRepo().find_many(
        {"tenant_id": TENANT, "connector_id": CONNECTOR}, limit=10,
    )
    assert len(rows) == 1


# ── duplicate boundary ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_duplicate_boundary_resent_frame_never_re_accepted():
    source = PlanSource([frame(1, {"fill_id": "f1"}), frame(1, {"fill_id": "f1"}), frame(2, {"fill_id": "f2"})])
    result = await _worker(_adapter(source)).run_once()
    assert _fill_ids(result) == ["f1", "f2"]  # the re-sent frame was deduped
    assert result.duplicates == 1
    assert result.accepted  # the real frames were delivered (not swallowed)


# ── out-of-order boundary ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_out_of_order_boundary_buffered_then_released_in_order():
    source = PlanSource([
        frame(1, {"fill_id": "f1"}),
        frame(3, {"fill_id": "f3"}),  # arrives before f2
        frame(2, {"fill_id": "f2"}),
    ])
    result = await _worker(_adapter(source)).run_once()
    assert result.buffered == 1
    # Released in provider order once the hole closed — never out of order.
    assert _fill_ids(result) == ["f1", "f2", "f3"]
    assert result.gaps_detected == 0  # one-frame buffer, no gap
    # The stream advanced past every frame; cursor is the true tail.
    assert await _worker(_adapter(source)).restore_cursor() == 4


# ── disconnect / reconnect boundary ─────────────────────────────────────

class DropOnceSource:
    """Drops the connection right after frame 1; on reconnect resumes from the
    next contiguous sequence with only the remaining frame."""

    def __init__(self) -> None:
        self.calls = 0
        self.resume_cursors = []

    async def __call__(self, resume_cursor=None):
        self.calls += 1
        self.resume_cursors.append(resume_cursor)
        if self.calls == 1:
            yield frame(1, {"fill_id": "f1"})
            raise StreamDisconnect("venue socket dropped")
        yield frame(2, {"fill_id": "f2"})


@pytest.mark.asyncio
async def test_disconnect_boundary_reconnect_resumes_no_data_loss():
    drop = DropOnceSource()
    result = await _worker(_adapter(drop)).run_once()
    assert result.reconnects == 1
    # Resumed from expected_next (2): frame 1 not replayed, frame 2 not skipped.
    assert drop.resume_cursors == [None, 2]
    assert _fill_ids(result) == ["f1", "f2"]
    assert result.duplicates == 0
    assert await _worker(_adapter(drop)).restore_cursor() == 3
