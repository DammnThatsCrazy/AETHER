"""Decimal-only P&L correctness and stream sequence handling."""

from __future__ import annotations

from decimal import Decimal

import pytest

from services.derivatives.pnl import exposure, realized_pnl_average_entry, unrealized_pnl
from services.derivatives.streams import SequenceTracker


# ── P&L ──────────────────────────────────────────────────────────────────────

def test_long_average_entry_realized_pnl_exact():
    fills = [
        {"side": "buy", "price": "100", "quantity": "2"},
        {"side": "buy", "price": "110", "quantity": "2"},   # avg entry 105
        {"side": "sell", "price": "120", "quantity": "3"},  # realize (120-105)*3 = 45
    ]
    result = realized_pnl_average_entry(fills)
    assert result["realized_pnl"] == Decimal("45")
    assert result["open_position"] == Decimal("1")
    assert result["avg_entry"] == Decimal("105")


def test_short_average_entry_realized_pnl_exact():
    fills = [
        {"side": "sell", "price": "100", "quantity": "4"},
        {"side": "buy", "price": "90", "quantity": "4"},  # realize (90-100)*4*(-1) = 40
    ]
    result = realized_pnl_average_entry(fills)
    assert result["realized_pnl"] == Decimal("40")
    assert result["open_position"] == Decimal("0")


def test_reversal_opens_new_exposure_at_fill_price():
    fills = [
        {"side": "buy", "price": "100", "quantity": "1"},
        {"side": "sell", "price": "120", "quantity": "2"},  # close 1 (+20), open short 1 @120
    ]
    result = realized_pnl_average_entry(fills)
    assert result["realized_pnl"] == Decimal("20")
    assert result["open_position"] == Decimal("-1")
    assert result["avg_entry"] == Decimal("120")


def test_float_inputs_are_rejected_everywhere():
    with pytest.raises(TypeError):
        realized_pnl_average_entry([{"side": "buy", "price": 100.5, "quantity": "1"}])
    with pytest.raises(TypeError):
        unrealized_pnl(1.5, "100", "110")
    with pytest.raises(TypeError):
        exposure([{"size": "1", "mark_price": 100.0}])


def test_unrealized_linear_and_inverse():
    assert unrealized_pnl("2", "100", "110", "linear") == Decimal("20")
    assert unrealized_pnl("-2", "100", "90", "linear") == Decimal("20")
    # Inverse: (1/entry - 1/mark) * size — long profits when mark rises.
    inverse = unrealized_pnl("1000", "100", "125", "inverse")
    assert inverse == (Decimal(1) / Decimal(100) - Decimal(1) / Decimal(125)) * Decimal(1000)


def test_quanto_is_honestly_unsupported():
    with pytest.raises(NotImplementedError):
        unrealized_pnl("1", "100", "110", "quanto")


def test_exposure_gross_and_net():
    result = exposure([
        {"size": "2", "mark_price": "100"},
        {"size": "-1", "mark_price": "100"},
    ])
    assert result["gross_exposure"] == Decimal("300")
    assert result["net_exposure"] == Decimal("100")


# ── Streams ──────────────────────────────────────────────────────────────────

def _tracker(**kwargs) -> SequenceTracker:
    return SequenceTracker("venue:sim", "sim:btc-perp", "trades", **kwargs)


def test_in_order_passthrough_and_duplicates():
    tracker = _tracker()
    assert tracker.ingest(1, {"seq": 1}).accepted
    assert tracker.ingest(2, {"seq": 2}).accepted
    duplicate = tracker.ingest(2, {"seq": 2})
    assert duplicate.duplicates == 1
    assert not duplicate.accepted


def test_gap_detection_after_threshold_and_recovery():
    tracker = _tracker(gap_threshold=3)
    tracker.ingest(1, {"seq": 1})
    buffered = tracker.ingest(5, {"seq": 5})  # hole of 3 (2,3,4)
    assert buffered.buffered == 1
    assert buffered.gap_detected is not None
    assert any(e["event_name"] == "derivatives_stream_gap_detected"
               for e in tracker.emitted_events)

    # Missing sequences arrive; contiguous drain recovers the gap.
    tracker.ingest(2, {"seq": 2})
    tracker.ingest(3, {"seq": 3})
    recovered = tracker.ingest(4, {"seq": 4})
    assert [m["seq"] for m in recovered.accepted] == [4, 5]
    assert recovered.gap_recovered
    assert any(e["event_name"] == "derivatives_stream_gap_recovered"
               for e in tracker.emitted_events)


def test_small_reorder_below_threshold_buffers_silently():
    tracker = _tracker(gap_threshold=3)
    tracker.ingest(1, {"seq": 1})
    result = tracker.ingest(3, {"seq": 3})  # hole of 1 — no gap yet
    assert result.gap_detected is None
    drained = tracker.ingest(2, {"seq": 2})
    assert [m["seq"] for m in drained.accepted] == [2, 3]


def test_buffer_is_bounded():
    tracker = _tracker(buffer_size=4, gap_threshold=2)
    tracker.ingest(1, {"seq": 1})
    for seq in range(10, 20):
        tracker.ingest(seq, {"seq": seq})
    assert len(tracker._buffer) <= 4
