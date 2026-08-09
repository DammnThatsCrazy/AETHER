"""Bounded market-stream sequence correctness.

Pure in-process sequence tracking per (venue, market, channel): duplicate
detection, bounded out-of-order buffering, gap detection with recovery.
Transport is deliberately out of scope — this runtime consumes whatever
feed the caller wires (local asyncio today; Kafka topic provisioning is
deferred and documented as such, never claimed). The DECLARATIVE topic
contract (topics, schemas, partitions, retention, DLQ routing, consumer
ownership) lives in :mod:`services.derivatives.topic_contract`, validated
with no broker.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

from services.derivatives.foundation import make_event, utc_now_iso

DEFAULT_BUFFER_SIZE = 512
DEFAULT_GAP_THRESHOLD = 3


@dataclass
class SequenceResult:
    accepted: list[dict] = field(default_factory=list)
    duplicates: int = 0
    buffered: int = 0
    gap_detected: Optional[dict] = None
    gap_recovered: bool = False
    evicted: int = 0


class SequenceTracker:
    """Tracks one stream key. Messages carry a provider sequence number;
    only contiguous sequences are released to consumers."""

    def __init__(
        self,
        venue_id: str,
        market_id: str,
        channel: str,
        tenant_id: str = "public",
        buffer_size: int = DEFAULT_BUFFER_SIZE,
        gap_threshold: int = DEFAULT_GAP_THRESHOLD,
    ) -> None:
        self.venue_id = venue_id
        self.market_id = market_id
        self.channel = channel
        self.tenant_id = tenant_id
        self.expected_next: Optional[int] = None
        self.gap_threshold = gap_threshold
        self._buffer: deque[tuple[int, dict]] = deque(maxlen=buffer_size)
        self._gap_open = False
        # The gap is recovered only once the contiguous stream has advanced
        # past the sequence that revealed the hole.
        self._gap_open_until: int = 0
        self.emitted_events: list[dict] = []

    def ingest(self, sequence: int, message: dict[str, Any]) -> SequenceResult:
        result = SequenceResult()

        if self.expected_next is None:
            self.expected_next = sequence + 1
            result.accepted.append(message)
            return result

        if sequence < self.expected_next:
            result.duplicates = 1
            return result

        if sequence == self.expected_next:
            result.accepted.append(message)
            self.expected_next += 1
            self._drain(result)
            if self._gap_open and self.expected_next > self._gap_open_until:
                self._gap_open = False
                result.gap_recovered = True
                self.emitted_events.append(make_event(
                    "derivatives_stream_gap_recovered", self.tenant_id, self._key_payload(),
                ))
            return result

        # Future sequence: buffer, and open a gap once the hole is wide/old enough.
        before = len(self._buffer)
        self._buffer.append((sequence, message))
        result.evicted = max(0, before + 1 - len(self._buffer))
        result.buffered = 1
        if not self._gap_open and sequence - self.expected_next >= self.gap_threshold:
            self._gap_open = True
            self._gap_open_until = sequence
            gap_record = {
                **self._key_payload(),
                "expected_sequence": self.expected_next,
                "received_sequence": sequence,
                "detected_at": utc_now_iso(),
                "status": "open",
            }
            result.gap_detected = gap_record
            self.emitted_events.append(make_event(
                "derivatives_stream_gap_detected", self.tenant_id, gap_record,
            ))
            try:
                from shared.logger.logger import metrics
                metrics.increment("derivatives_stream_gap_detected")
            except Exception:
                pass
        return result

    def _drain(self, result: SequenceResult) -> None:
        """Release buffered messages that became contiguous."""
        progressed = True
        while progressed:
            progressed = False
            for item in sorted(self._buffer, key=lambda pair: pair[0]):
                sequence, message = item
                if sequence == self.expected_next:
                    result.accepted.append(message)
                    self.expected_next += 1
                    self._buffer.remove(item)
                    progressed = True
                    break
                if sequence < self.expected_next:
                    self._buffer.remove(item)
                    result.duplicates += 1
                    progressed = True
                    break

    def _key_payload(self) -> dict[str, Any]:
        return {
            "venue_id": self.venue_id,
            "canonical_market_id": self.market_id,
            "channel": self.channel,
        }
