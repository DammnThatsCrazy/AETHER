"""Stateless in-batch sequence-integrity analysis for SDK event batches.

SDKs stamp ``context.sequence.event`` — a per-session monotonic event counter
(``SequenceContext`` in packages/shared/events.ts). This module inspects one
batch at a time and reports where that counter has holes (events lost before
they reached ingestion) or repeats (client-side re-emission). Findings feed the
``ingestion_sequence_gap_total`` / ``ingestion_sequence_duplicate_total``
meters emitted by services/ingestion/batch.py — metrics only, never a
rejection or a write.

Cross-batch tracking (a durable per-session high-water mark surviving between
batches) is a documented non-goal of this slice; analysis is stateless and
strictly in-batch.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class SequenceFinding:
    """One sequence-integrity violation observed within a single batch.

    ``kind == "gap"``: a contiguous run of missing counter values for a
    session — ``sequence_start`` / ``sequence_end`` bound the missing run and
    ``count`` is how many values are missing.

    ``kind == "duplicate"``: a counter value that appeared more than once —
    ``sequence_start == sequence_end`` is the repeated value and ``count`` is
    the number of extra occurrences beyond the first.
    """

    kind: Literal["gap", "duplicate"]
    session_id: str
    sequence_start: int
    sequence_end: int
    count: int


def analyze_batch_sequences(
    events: Sequence[Mapping[str, Any]],
) -> list[SequenceFinding]:
    """Detect sequence gaps and duplicates within one batch of SDK events.

    Events are grouped by ``sessionId``; only events carrying an integral
    ``context.sequence.event`` participate. Within each session the counters
    are sorted before comparison, so out-of-order arrival inside the batch is
    NOT a finding — only missing integers (gaps) and repeated integers
    (duplicates) are. Events without a session or sequence counter produce no
    findings. Pure and deterministic: findings are ordered by session, gaps
    before duplicates, ascending by sequence value.
    """
    by_session: dict[str, list[int]] = {}
    for event in events:
        session_id = event.get("sessionId")
        if not session_id:
            continue
        number = _sequence_event_number(event)
        if number is None:
            continue
        by_session.setdefault(str(session_id), []).append(number)

    findings: list[SequenceFinding] = []
    for session_id in sorted(by_session):
        occurrences = Counter(by_session[session_id])
        distinct = sorted(occurrences)
        for prev, nxt in zip(distinct, distinct[1:]):
            if nxt - prev > 1:
                findings.append(SequenceFinding(
                    kind="gap",
                    session_id=session_id,
                    sequence_start=prev + 1,
                    sequence_end=nxt - 1,
                    count=nxt - prev - 1,
                ))
        for value in distinct:
            if occurrences[value] > 1:
                findings.append(SequenceFinding(
                    kind="duplicate",
                    session_id=session_id,
                    sequence_start=value,
                    sequence_end=value,
                    count=occurrences[value] - 1,
                ))
    return findings


def _sequence_event_number(event: Mapping[str, Any]) -> int | None:
    """Extract a non-negative integral ``context.sequence.event``; else None."""
    context = event.get("context")
    if not isinstance(context, Mapping):
        return None
    sequence = context.get("sequence")
    if not isinstance(sequence, Mapping):
        return None
    number = sequence.get("event")
    if isinstance(number, bool) or not isinstance(number, int) or number < 0:
        return None
    return number
