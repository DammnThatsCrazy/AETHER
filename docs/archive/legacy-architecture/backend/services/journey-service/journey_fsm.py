"""Journey finite-state machine.

Pure logic — no I/O. The same FSM is used by the streaming consumer and by
the nightly batch reconciliation, guaranteeing identical semantics.

Boundary rules (per the v1 plan):
  • Open a new journey on the actor's first event after >N days inactivity
    OR a fresh attribution origin (new utm_campaign / referrer domain).
  • Close on conversion event (state='converted', exit_reason='conversion'),
    OR after the inactivity window elapses (state='abandoned',
    exit_reason='inactivity'), OR when a new origin appears
    (exit_reason='new_origin').
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from .policies import JourneyPolicy, attribution_origin, is_conversion


@dataclass
class FsmDecision:
    action: str                    # 'extend' | 'close_then_open' | 'open' | 'close'
    close_reason: Optional[str] = None    # 'conversion' | 'inactivity' | 'new_origin'
    open_new: bool = False
    is_conversion: bool = False


def _parse_iso(ts: str) -> datetime:
    # Accept both Z-suffixed and offset ISO strings.
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def decide(
    *,
    event: dict,
    open_journey: Optional[dict],
    policy: JourneyPolicy,
) -> FsmDecision:
    """Decide what to do for one incoming event.

    `open_journey` is the actor's currently-open journey row (or None).
    """
    event_ts = _parse_iso(event["timestamp"])
    converted = is_conversion(event, policy)
    new_origin_key = attribution_origin(event)

    if open_journey is None:
        return FsmDecision(action="open", open_new=True, is_conversion=converted)

    # Inactivity gate
    last_ts = _parse_iso(open_journey["last_event_at"])
    if event_ts - last_ts > timedelta(seconds=policy.inactivity_window_seconds):
        return FsmDecision(
            action="close_then_open",
            close_reason="inactivity",
            open_new=True,
            is_conversion=converted,
        )

    # New-origin gate
    if policy.new_origin_breaks:
        prior_origin = (open_journey.get("entry_attribution") or {}).get("origin")
        if prior_origin and prior_origin != new_origin_key:
            return FsmDecision(
                action="close_then_open",
                close_reason="new_origin",
                open_new=True,
                is_conversion=converted,
            )

    if converted:
        # Mark conversion but keep the journey open for post-conversion
        # retention analysis. The journey will close on next inactivity
        # tick or explicit policy.
        return FsmDecision(
            action="extend",
            is_conversion=True,
            close_reason="conversion",  # used to set conversion_event_id
        )

    return FsmDecision(action="extend")
