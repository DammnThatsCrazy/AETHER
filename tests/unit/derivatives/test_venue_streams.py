"""Venue WebSocket stream tests — sequence tracking, gap detection + recovery,
bounded reconnect with cursor resume, duplicate + out-of-order handling.

Drives the reconnecting stream driver + adapters against a scripted in-process
frame source (``stream_factory=``) — NO live socket.
"""

from __future__ import annotations

import mock_venues as mv

from services.derivatives.adapters.hyperliquid import HyperliquidAdapter
from services.derivatives.connectors.stream import ReconnectingStream


def _frame(seq: int) -> dict:
    return {"sequence": seq, "payload": {"seq": seq, "channel": "userFills"}}


def _stream(factory, **kw) -> ReconnectingStream:
    return ReconnectingStream(
        factory, venue_id="hyperliquid", market_id="hyperliquid:mainnet:BTC",
        channel="account", gap_threshold=3, **kw,
    )


async def _noop(_seconds):
    return None


# ── in-order + duplicates ─────────────────────────────────────────────────────
async def test_in_order_frames_pass_through():
    factory, _ = mv.scripted_ws_factory([("frames", [_frame(1), _frame(2), _frame(3)])])
    result = await _stream(factory).run()
    assert [m["seq"] for m in result.accepted] == [1, 2, 3]
    assert result.completed is True
    assert result.reconnects == 0


async def test_duplicate_frames_are_dropped():
    factory, _ = mv.scripted_ws_factory([("frames", [_frame(1), _frame(2), _frame(2), _frame(3)])])
    result = await _stream(factory).run()
    assert [m["seq"] for m in result.accepted] == [1, 2, 3]
    assert result.duplicates == 1


async def test_small_reorder_below_threshold_buffers_then_drains():
    factory, _ = mv.scripted_ws_factory([("frames", [_frame(1), _frame(3), _frame(2), _frame(4)])])
    result = await _stream(factory).run()
    assert [m["seq"] for m in result.accepted] == [1, 2, 3, 4]
    assert result.gaps_detected == 0


# ── gap detection + recovery ──────────────────────────────────────────────────
async def test_gap_detected_and_recovered_within_one_connection():
    # 1 then 5 opens a gap (hole 2,3,4); the missing frames arrive and recover it.
    factory, _ = mv.scripted_ws_factory([
        ("frames", [_frame(1), _frame(5), _frame(2), _frame(3), _frame(4)]),
    ])
    result = await _stream(factory).run()
    assert [m["seq"] for m in result.accepted] == [1, 2, 3, 4, 5]
    assert result.gaps_detected == 1
    assert result.gaps_recovered == 1
    names = [e["event_name"] for e in result.emitted_events]
    assert "derivatives_stream_gap_detected" in names
    assert "derivatives_stream_gap_recovered" in names


# ── reconnect with cursor resume ──────────────────────────────────────────────
async def test_reconnect_resumes_from_last_contiguous_sequence():
    factory, calls = mv.scripted_ws_factory([
        ("disconnect", [_frame(1), _frame(2), _frame(3)]),  # drops after 3
        ("frames", [_frame(4), _frame(5)]),                 # resumes cleanly
    ])
    result = await _stream(factory, sleeper=_noop).run()
    assert [m["seq"] for m in result.accepted] == [1, 2, 3, 4, 5]
    assert result.reconnects == 1
    assert result.completed is True
    # second connection was opened with resume cursor = next expected (4)
    assert calls.resumes[1] == 4


async def test_gap_recovers_across_a_reconnect():
    # first connection yields 1 then 5 (gap) then drops; the missing 2,3,4 arrive
    # on the resumed connection and recover the gap.
    factory, _ = mv.scripted_ws_factory([
        ("disconnect", [_frame(1), _frame(5)]),
        ("frames", [_frame(2), _frame(3), _frame(4)]),
    ])
    result = await _stream(factory, sleeper=_noop).run()
    assert [m["seq"] for m in result.accepted] == [1, 2, 3, 4, 5]
    assert result.gaps_detected == 1
    assert result.gaps_recovered == 1
    assert result.reconnects == 1


async def test_bounded_reconnect_gives_up():
    # every connection immediately drops → driver stops after max_reconnects.
    factory, calls = mv.scripted_ws_factory([("disconnect", [])] * 10)
    result = await _stream(factory, sleeper=_noop, max_reconnects=3).run()
    assert result.reconnects == 3
    assert result.disconnected_out is True
    assert result.completed is False


# ── adapter-level stream integration ──────────────────────────────────────────
async def test_adapter_run_stream_drives_gap_tracking():
    factory, _ = mv.scripted_ws_factory([("frames", [_frame(1), _frame(5), _frame(2), _frame(3), _frame(4)])])
    adapter = HyperliquidAdapter(stream_factory=factory, account_ref="0xabc")
    result = await adapter.run_stream()
    assert [m["seq"] for m in result.accepted] == [1, 2, 3, 4, 5]
    assert result.gaps_recovered == 1


async def test_adapter_subscribe_account_stream_yields_bronze():
    factory, _ = mv.scripted_ws_factory([("frames", [mv.ws_frame(1, 7), mv.ws_frame(2, 8)])])
    adapter = HyperliquidAdapter(stream_factory=factory, account_ref="0xabc")
    observations = [obs async for obs in adapter.subscribe_account_stream(account_ref="0xabc")]
    assert len(observations) == 2
    assert all(obs.record_type == "websocket_message" for obs in observations)
    assert all(obs.execution_by_aether is False for obs in observations)


async def test_unconfigured_adapter_stream_is_empty():
    adapter = HyperliquidAdapter(account_ref="0xabc")  # no stream_factory
    result = await adapter.run_stream()
    assert result.accepted == []
    assert result.completed is True
