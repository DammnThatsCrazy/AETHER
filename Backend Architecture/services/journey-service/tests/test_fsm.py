"""Pure-FSM tests for the journey boundary policy.

No I/O, no Postgres. Validates the boundary cases from the v1 plan:
  1. open when there is no open journey
  2. extend on same-origin event within window
  3. inactivity boundary closes + opens
  4. new-origin boundary closes + opens
  5. conversion marks without closing
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# Loaded by tests/conftest.py (registers stable aliases in sys.modules)
import journey_fsm   # type: ignore
import policies      # type: ignore


def _ev(ts: str, *, type_: str = "page", source: str = "google", campaign: str = "spring") -> dict:
    return {
        "id": "e1",
        "timestamp": ts,
        "type": type_,
        "sessionId": "s1",
        "context": {"campaign": {"source": source, "campaign": campaign}},
    }


def _journey(*, last_event_at: str, origin: str) -> dict:
    return {
        "journey_id": "j1",
        "last_event_at": last_event_at,
        "entry_attribution": {"origin": origin},
    }


def test_open_when_no_open_journey():
    p = policies.JourneyPolicy(project_id="p")
    d = journey_fsm.decide(event=_ev("2026-01-01T00:00:00+00:00"), open_journey=None, policy=p)
    assert d.action == "open"
    assert d.open_new is True


def test_extend_on_same_origin_within_window():
    p = policies.JourneyPolicy(project_id="p")
    open_j = _journey(
        last_event_at="2026-01-01T00:00:00+00:00",
        origin=policies.attribution_origin(_ev("2026-01-01T00:00:00+00:00")),
    )
    d = journey_fsm.decide(event=_ev("2026-01-01T00:05:00+00:00"), open_journey=open_j, policy=p)
    assert d.action == "extend"


def test_inactivity_boundary_breaks_journey():
    p = policies.JourneyPolicy(project_id="p", inactivity_window_days=1)
    open_j = _journey(
        last_event_at="2026-01-01T00:00:00+00:00",
        origin=policies.attribution_origin(_ev("2026-01-01T00:00:00+00:00")),
    )
    later = (datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=2)).isoformat()
    d = journey_fsm.decide(event=_ev(later), open_journey=open_j, policy=p)
    assert d.action == "close_then_open"
    assert d.close_reason == "inactivity"


def test_new_origin_breaks_journey():
    p = policies.JourneyPolicy(project_id="p")
    open_j = _journey(
        last_event_at="2026-01-01T00:00:00+00:00",
        origin=policies.attribution_origin(_ev("2026-01-01T00:00:00+00:00", source="google")),
    )
    d = journey_fsm.decide(event=_ev("2026-01-01T00:05:00+00:00", source="bing"), open_journey=open_j, policy=p)
    assert d.action == "close_then_open"
    assert d.close_reason == "new_origin"


def test_conversion_marks_without_closing():
    p = policies.JourneyPolicy(project_id="p")
    open_j = _journey(
        last_event_at="2026-01-01T00:00:00+00:00",
        origin=policies.attribution_origin(_ev("2026-01-01T00:00:00+00:00")),
    )
    d = journey_fsm.decide(
        event=_ev("2026-01-01T00:05:00+00:00", type_="payment_completed"),
        open_journey=open_j, policy=p,
    )
    assert d.is_conversion is True
    assert d.action == "extend"
