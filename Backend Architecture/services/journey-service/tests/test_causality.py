"""Causality module — deterministic baseline tests."""

from __future__ import annotations

import causality   # type: ignore  (loaded via conftest.py)


def _e(eid: str, ts: str, *, session: str = "s1", path: str = "/home", type_: str = "page") -> dict:
    return {
        "id": eid,
        "timestamp": ts,
        "type": type_,
        "sessionId": session,
        "context": {"page": {"path": path}},
    }


def test_no_history_returns_empty():
    out = causality.compute(event=_e("e2", "2026-01-01T00:01:00+00:00"), journey_history=[])
    assert out["triggered_by_event_id"] is None
    assert out["influencing_event_ids"] == []
    assert out["causal_score"] == 0.0


def test_triggered_by_previous_in_same_session():
    history = [
        _e("e1", "2026-01-01T00:00:00+00:00"),
        _e("e2", "2026-01-01T00:00:30+00:00"),
    ]
    out = causality.compute(event=_e("e3", "2026-01-01T00:01:00+00:00"), journey_history=history)
    assert out["triggered_by_event_id"] == "e2"


def test_influencers_share_surface():
    history = [
        _e("a", "2026-01-01T00:00:00+00:00", path="/home"),
        _e("b", "2026-01-01T00:00:30+00:00", path="/other"),
        _e("c", "2026-01-01T00:00:45+00:00", path="/home"),
    ]
    out = causality.compute(event=_e("d", "2026-01-01T00:01:00+00:00", path="/home"), journey_history=history)
    # Influencers are same-surface, excluding the triggered_by event
    assert "a" in out["influencing_event_ids"]
    assert "b" not in out["influencing_event_ids"]
    assert 0.0 < out["causal_score"] <= 1.0
