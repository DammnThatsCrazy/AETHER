"""Causality scoring.

v1 ships a deterministic baseline:
  • triggered_by_event_id  = the immediately previous event in the same
    session+actor pair, if any.
  • influencing_event_ids  = up to N prior events in the same journey on
    the same surface (e.g. same page path / screen).
  • causal_score           = decaying weight 1/(1+age_minutes/60).

The same module exposes the contract the future ML model will fill in.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional


MAX_INFLUENCERS = 5


def _surface(event: dict) -> str:
    ctx = event.get("context") or {}
    page = ctx.get("page") or {}
    if isinstance(page, dict) and page.get("path"):
        return f"page:{page['path']}"
    if event.get("type") == "screen":
        props = event.get("properties") or {}
        return f"screen:{props.get('name', 'unknown')}"
    return f"type:{event.get('type', 'unknown')}"


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def compute(
    *,
    event: dict,
    journey_history: Iterable[dict],
) -> dict:
    """Return {triggered_by_event_id, influencing_event_ids, causal_score}.

    `journey_history` is an ordered iterable of prior events in this journey,
    oldest first. Caller is responsible for windowing it (e.g. last 100).
    """
    history = list(journey_history)
    surface = _surface(event)
    event_ts = _parse(event["timestamp"])

    triggered_by: Optional[str] = None
    same_session = [h for h in history if h.get("sessionId") == event.get("sessionId")]
    if same_session:
        triggered_by = same_session[-1].get("id")

    influencers: list[tuple[str, float]] = []
    for h in reversed(history):  # newest first
        if _surface(h) != surface:
            continue
        if h.get("id") == triggered_by:
            continue
        age_minutes = max(0.0, (event_ts - _parse(h["timestamp"])).total_seconds() / 60.0)
        weight = 1.0 / (1.0 + age_minutes / 60.0)
        influencers.append((h["id"], weight))
        if len(influencers) >= MAX_INFLUENCERS:
            break

    causal_score = max((w for _, w in influencers), default=0.0)
    return {
        "triggered_by_event_id": triggered_by,
        "influencing_event_ids": [eid for eid, _ in influencers],
        "causal_score": round(causal_score, 4),
    }
