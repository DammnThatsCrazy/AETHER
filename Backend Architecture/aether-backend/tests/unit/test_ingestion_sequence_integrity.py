"""In-batch sequence integrity: analyzer findings + the ingestion meter hook.

``analyze_batch_sequences`` is pure and stateless — it inspects one batch's
``context.sequence.event`` counters per session and reports gaps (missing
integers) and duplicates (repeated integers). ``_emit_sequence_integrity_meters``
in services/ingestion/batch.py turns findings into the
``ingestion_sequence_gap_total`` / ``ingestion_sequence_duplicate_total``
meters, tenant-labelled like every other ingestion meter. Cross-batch tracking
is a documented non-goal of this slice.
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Optional

os.environ.setdefault("AETHER_ENV", "local")

from services.ingestion import batch as batch_module  # noqa: E402
from services.ingestion.batch import BaseEvent, EventContext  # noqa: E402
from services.ingestion.sequence_integrity import (  # noqa: E402
    SequenceFinding,
    analyze_batch_sequences,
)


def _event(
    sequence_event: Optional[int] = None,
    *,
    session_id: str = "sess-1",
    context: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    ctx: dict[str, Any] = dict(context or {})
    if sequence_event is not None:
        ctx["sequence"] = {"event": sequence_event}
    return {"sessionId": session_id, "context": ctx}


# ── analyze_batch_sequences ───────────────────────────────────────────────────


def test_contiguous_sequence_yields_no_findings():
    events = [_event(n) for n in (0, 1, 2, 3)]
    assert analyze_batch_sequences(events) == []


def test_single_missing_integer_is_a_gap():
    events = [_event(n) for n in (0, 1, 3)]
    assert analyze_batch_sequences(events) == [
        SequenceFinding(
            kind="gap", session_id="sess-1",
            sequence_start=2, sequence_end=2, count=1,
        ),
    ]


def test_contiguous_missing_run_is_one_gap_finding():
    events = [_event(0), _event(5)]
    assert analyze_batch_sequences(events) == [
        SequenceFinding(
            kind="gap", session_id="sess-1",
            sequence_start=1, sequence_end=4, count=4,
        ),
    ]


def test_repeated_counter_is_a_duplicate():
    events = [_event(n) for n in (1, 2, 2, 3)]
    assert analyze_batch_sequences(events) == [
        SequenceFinding(
            kind="duplicate", session_id="sess-1",
            sequence_start=2, sequence_end=2, count=1,
        ),
    ]


def test_triplicate_counts_extra_occurrences():
    events = [_event(n) for n in (7, 7, 7)]
    assert analyze_batch_sequences(events) == [
        SequenceFinding(
            kind="duplicate", session_id="sess-1",
            sequence_start=7, sequence_end=7, count=2,
        ),
    ]


def test_unordered_arrival_within_batch_is_not_a_finding():
    """SDKs may flush out of order; only missing/repeated integers matter."""
    events = [_event(n) for n in (3, 1, 2, 0)]
    assert analyze_batch_sequences(events) == []


def test_gap_and_duplicate_reported_together():
    events = [_event(n) for n in (0, 2, 2)]
    findings = analyze_batch_sequences(events)
    assert findings == [
        SequenceFinding(
            kind="gap", session_id="sess-1",
            sequence_start=1, sequence_end=1, count=1,
        ),
        SequenceFinding(
            kind="duplicate", session_id="sess-1",
            sequence_start=2, sequence_end=2, count=1,
        ),
    ]


def test_absent_sequence_yields_no_findings():
    events = [
        {"sessionId": "sess-1", "context": {}},
        {"sessionId": "sess-1", "context": {"sequence": {}}},
        {"sessionId": "sess-1"},
        {"sessionId": "sess-1", "context": None},
    ]
    assert analyze_batch_sequences(events) == []


def test_non_integral_counters_are_ignored():
    events = [
        _event(0),
        _event(context={"sequence": {"event": "2"}}),
        _event(context={"sequence": {"event": True}}),
        _event(context={"sequence": {"event": 1.5}}),
        _event(context={"sequence": {"event": -1}}),
        _event(1),
    ]
    assert analyze_batch_sequences(events) == []


def test_missing_session_id_is_ignored():
    events = [{"sessionId": "", "context": {"sequence": {"event": 0}}},
              {"context": {"sequence": {"event": 9}}}]
    assert analyze_batch_sequences(events) == []


def test_sessions_are_analyzed_independently():
    events = [
        _event(0, session_id="sess-a"),
        _event(1, session_id="sess-a"),
        _event(0, session_id="sess-b"),
        _event(2, session_id="sess-b"),
    ]
    assert analyze_batch_sequences(events) == [
        SequenceFinding(
            kind="gap", session_id="sess-b",
            sequence_start=1, sequence_end=1, count=1,
        ),
    ]


# ── batch.py meter hook ───────────────────────────────────────────────────────


class _MetricsRecorder:
    """Capture stand-in for shared.logger.logger.metrics."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int, Optional[dict]]] = []

    def increment(self, name: str, value: int = 1, labels: Optional[dict] = None) -> None:
        self.calls.append((name, value, labels))


def _sdk_event(sequence_event: Optional[int], session_id: str = "sess-1") -> BaseEvent:
    context = (
        EventContext(sequence={"event": sequence_event})
        if sequence_event is not None
        else EventContext()
    )
    return BaseEvent(
        id=f"evt-{uuid.uuid4().hex[:8]}",
        type="track",
        timestamp="2026-07-23T00:00:00Z",
        sessionId=session_id,
        anonymousId="anon-1",
        properties={},
        context=context,
    )


def test_batch_hook_emits_gap_and_duplicate_meters(monkeypatch):
    recorder = _MetricsRecorder()
    monkeypatch.setattr(batch_module, "metrics", recorder)

    batch = [_sdk_event(0), _sdk_event(2), _sdk_event(2)]
    batch_module._emit_sequence_integrity_meters(batch, "tenant-seq")

    assert recorder.calls == [
        ("ingestion_sequence_gap_total", 1, {"tenant_id": "tenant-seq"}),
        ("ingestion_sequence_duplicate_total", 1, {"tenant_id": "tenant-seq"}),
    ]


def test_batch_hook_is_silent_without_sequence_context(monkeypatch):
    recorder = _MetricsRecorder()
    monkeypatch.setattr(batch_module, "metrics", recorder)

    batch = [_sdk_event(None), _sdk_event(None)]
    batch_module._emit_sequence_integrity_meters(batch, "tenant-seq")

    assert recorder.calls == []


def test_batch_hook_is_silent_for_contiguous_sequences(monkeypatch):
    recorder = _MetricsRecorder()
    monkeypatch.setattr(batch_module, "metrics", recorder)

    batch = [_sdk_event(0), _sdk_event(1), _sdk_event(2)]
    batch_module._emit_sequence_integrity_meters(batch, "tenant-seq")

    assert recorder.calls == []
