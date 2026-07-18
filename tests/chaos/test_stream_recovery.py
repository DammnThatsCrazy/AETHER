"""WebSocket stream chaos — disconnect + resume, gap recovery, out-of-order,
duplicate frames.

Drives the REAL reconnecting stream driver (``services.derivatives.connectors.
stream.ReconnectingStream``) against a scripted in-process frame source
(``scripted_ws_factory`` from tests/unit/derivatives/mock_venues.py). NO live
socket. A ``("disconnect", [...])`` connection yields its frames then raises the
recoverable ``StreamDisconnect``; the driver reconnects with a resume cursor.

Scenarios covered here:
  * WebSocket disconnect   -> bounded reconnect, resume from last contiguous seq
  * out-of-order events    -> small reorder buffered then drained in order
  * duplicate storm        -> duplicate sequences dropped, effect-once
  * gap detect + recover   -> a hole is detected and back-filled (in-conn + across reconnect)
  * unbounded disconnect   -> driver gives up after max_reconnects (no infinite loop)
"""

from __future__ import annotations

from tests.chaos.conftest import noop_sleeper
from tests.unit.derivatives import mock_venues as mv

from services.derivatives.connectors.stream import ReconnectingStream


def _frame(seq: int) -> dict:
    return {"sequence": seq, "payload": {"seq": seq, "channel": "userFills"}}


def _stream(factory, **kw) -> ReconnectingStream:
    return ReconnectingStream(
        factory,
        venue_id="hyperliquid",
        market_id="hyperliquid:mainnet:BTC",
        channel="account",
        gap_threshold=3,
        **kw,
    )


# ── WebSocket disconnect + resume ─────────────────────────────────────────────
async def test_websocket_disconnect_resumes_from_last_contiguous_sequence():
    factory, calls = mv.scripted_ws_factory([
        ("disconnect", [_frame(1), _frame(2), _frame(3)]),  # drops after 3
        ("frames", [_frame(4), _frame(5)]),                 # resumes cleanly
    ])
    result = await _stream(factory, sleeper=noop_sleeper).run()
    assert [m["seq"] for m in result.accepted] == [1, 2, 3, 4, 5]
    assert result.reconnects == 1
    assert result.completed is True
    # the resumed connection was opened asking for the next expected sequence
    assert calls.resumes[1] == 4


async def test_websocket_disconnect_gives_up_after_max_reconnects():
    """Every connection immediately drops -> the driver stops, does not loop."""
    factory, _ = mv.scripted_ws_factory([("disconnect", [])] * 10)
    result = await _stream(factory, sleeper=noop_sleeper, max_reconnects=3).run()
    assert result.reconnects == 3
    assert result.disconnected_out is True
    assert result.completed is False


# ── out-of-order events ───────────────────────────────────────────────────────
async def test_out_of_order_below_threshold_buffers_then_drains():
    factory, _ = mv.scripted_ws_factory([("frames", [_frame(1), _frame(3), _frame(2), _frame(4)])])
    result = await _stream(factory).run()
    assert [m["seq"] for m in result.accepted] == [1, 2, 3, 4]
    assert result.gaps_detected == 0


# ── duplicate storm ───────────────────────────────────────────────────────────
async def test_duplicate_frame_storm_is_deduped():
    """A storm of repeated sequences collapses to one accepted frame each."""
    # 25 repeats of seq 2: the first is accepted, the other 24 are duplicates.
    frames = [_frame(1)] + [_frame(2)] * 25 + [_frame(3)]
    factory, _ = mv.scripted_ws_factory([("frames", frames)])
    result = await _stream(factory).run()
    assert [m["seq"] for m in result.accepted] == [1, 2, 3]
    assert result.duplicates == 24


# ── gap detection + recovery ──────────────────────────────────────────────────
async def test_gap_detected_and_recovered_within_one_connection():
    factory, _ = mv.scripted_ws_factory([
        ("frames", [_frame(1), _frame(5), _frame(2), _frame(3), _frame(4)]),
    ])
    result = await _stream(factory).run()
    assert [m["seq"] for m in result.accepted] == [1, 2, 3, 4, 5]
    assert result.gaps_detected == 1
    assert result.gaps_recovered == 1


async def test_gap_recovers_across_a_reconnect():
    factory, _ = mv.scripted_ws_factory([
        ("disconnect", [_frame(1), _frame(5)]),          # gap opened, then drop
        ("frames", [_frame(2), _frame(3), _frame(4)]),   # missing frames arrive on resume
    ])
    result = await _stream(factory, sleeper=noop_sleeper).run()
    assert [m["seq"] for m in result.accepted] == [1, 2, 3, 4, 5]
    assert result.gaps_detected == 1
    assert result.gaps_recovered == 1
    assert result.reconnects == 1
