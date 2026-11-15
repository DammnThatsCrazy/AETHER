"""Traffic-window anomalies scored by the ML ``anomaly_detection`` model.

The IsolationForest + autoencoder model in ``services/ml`` is trained on
*window-level* traffic metrics, not on individual entities, so it is used for
what it was trained on: each clock hour of the evidence window becomes one
feature row matching the model's ``anomaly_detection_v1`` contract:

==================== =======================================================
traffic_volume       events in the hour
conversion_rate      share of outcome-bearing events that ended ``ok``
avg_session_duration mean seconds between first and last event per session
bounce_rate          share of sessions with exactly one event
error_rate           share of outcome-bearing events that ended ``fail``
api_latency_p99      p99 of observed ``latency_ms``/``duration_ms`` (0 when none)
bot_traffic_ratio    share of events whose user agent is a known automation agent
unique_visitors      distinct entities in the hour
revenue              sum of ``amount`` on successful events
==================== =======================================================

Metrics the evidence cannot support are reported in ``unobserved_features``
on every pattern so a reviewer knows which inputs were zero by absence.
Scoring is I/O, so :mod:`service` calls the model (flag
``PATTERN_DISCOVERY_ML_ENABLED``) and hands the engine ``{window_start: score}``;
without scores this detector reports nothing.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime
from typing import Any

from ..contracts import KIND_TRAFFIC_ANOMALY, EvidenceItem, RawPattern
from .base import DetectorOutput
from .frame import DiscoveryFrame, event_refs, plural

NAME = "ml_windows"
MODEL = "anomaly_detection"
ANOMALY_THRESHOLD = 0.5
MAX_WINDOWS = 24 * 14


def _hour(ts: datetime) -> str:
    return ts.replace(minute=0, second=0, microsecond=0).isoformat()


def window_features(events) -> list[dict[str, Any]]:
    """One contract-shaped feature row per clock hour (oldest first)."""
    by_hour: dict[str, list] = defaultdict(list)
    for e in events:
        if e.ts:
            by_hour[_hour(e.ts)].append(e)
    rows = []
    for hour in sorted(by_hour)[-MAX_WINDOWS:]:
        evs = by_hour[hour]
        outcomes = [e.outcome for e in evs if e.outcome]
        sessions: dict[str, list] = defaultdict(list)
        for e in evs:
            if e.session_id:
                sessions[e.session_id].append(e.ts)
        durations = [(max(t) - min(t)).total_seconds() for t in sessions.values() if len(t) > 1]
        latencies = sorted(e.latency_ms for e in evs if e.latency_ms is not None)
        unobserved = []
        if not outcomes:
            unobserved += ["conversion_rate", "error_rate"]
        if not sessions:
            unobserved += ["avg_session_duration", "bounce_rate"]
        if not latencies:
            unobserved.append("api_latency_p99")
        features = {
            "traffic_volume": float(len(evs)),
            "conversion_rate": (outcomes.count("ok") / len(outcomes)) if outcomes else 0.0,
            "avg_session_duration": statistics.fmean(durations) if durations else 0.0,
            "bounce_rate": (sum(1 for t in sessions.values() if len(t) == 1) / len(sessions)) if sessions else 0.0,
            "error_rate": (outcomes.count("fail") / len(outcomes)) if outcomes else 0.0,
            "api_latency_p99": latencies[min(len(latencies) - 1, int(0.99 * len(latencies)))] if latencies else 0.0,
            "bot_traffic_ratio": sum(1 for e in evs if e.is_bot) / len(evs),
            "unique_visitors": float(len({e.entity for e in evs if e.entity})),
            "revenue": float(sum(abs(e.amount) for e in evs if e.amount is not None and e.outcome != "fail")),
        }
        rows.append({"window_start": hour, "features": {k: round(v, 6) for k, v in features.items()},
                     "unobserved_features": unobserved, "events": evs})
    return rows


def detect_traffic_anomalies(frame: DiscoveryFrame) -> DetectorOutput:
    scores: dict[str, float] = getattr(frame, "ml_window_scores", None) or {}
    if not scores:
        return DetectorOutput(NAME, [], {}, {"reported": 0, "note": "no ML window scores supplied"})
    windows = {w["window_start"]: w for w in window_features(frame.events)}
    flagged = sorted(h for h, s in scores.items() if s > ANOMALY_THRESHOLD and h in windows)
    if not flagged:
        return DetectorOutput(NAME, [], {}, {"windows_scored": len(scores), "reported": 0})
    evs = [e for h in flagged for e in windows[h]["events"]]
    ents = sorted({e.entity for e in evs if e.entity})[:500]
    top = max(flagged, key=lambda h: scores[h])
    unobserved = sorted({f for h in flagged for f in windows[h]["unobserved_features"]})
    first = min(e.ts for e in evs if e.ts)
    last = max(e.ts for e in evs if e.ts)
    pattern = RawPattern(
        kind=KIND_TRAFFIC_ANOMALY,
        signature={"model": MODEL, "windows": len(flagged) >= 3},
        title=f"ML traffic anomaly in {plural(len(flagged), 'hour')}",
        summary=(f"The anomaly_detection model flagged {plural(len(flagged), 'hourly window')} "
                 f"(peak score {scores[top]:.2f} at {top}); {plural(len(ents), 'entity')} were active."),
        affected_entities=ents,
        evidence=[
            EvidenceItem("anomalous_windows", "observed", 0.1, {
                "windows": [{"window_start": h, "score": round(scores[h], 4), "features": windows[h]["features"]}
                            for h in flagged[:24]],
            }, event_refs(evs)),
            EvidenceItem("ml_anomaly_score", "inferred", min(0.4, 0.5 * scores[top]), {
                "model": MODEL, "threshold": ANOMALY_THRESHOLD, "peak_score": round(scores[top], 4),
                "unobserved_features": unobserved,
            }),
        ],
        occurrence_count=len(evs),
        first_observed_at=first,
        last_observed_at=last,
        risk_categories=["operational", "temporal"],
        competing_explanations=[
            {"id": "model_drift_or_cold_start", "note": "The model was trained on other traffic; new tenants and seasonal shifts score high."},
            {"id": "absent_inputs", "note": "Inputs the evidence could not supply were sent as zero; see unobserved_features."},
        ],
        novelty=1.0,
        baseline={"windows_scored": len(scores), "windows_flagged": len(flagged)},
        episode_count=len(flagged),
        detector=NAME,
    )
    return DetectorOutput(NAME, [pattern], {}, {"windows_scored": len(scores), "reported": 1})
