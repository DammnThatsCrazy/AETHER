"""Reconnecting stream driver for derivatives venue WebSocket feeds.

Sits on top of ``services.derivatives.streams.SequenceTracker`` (duplicate
detection, bounded out-of-order buffering, gap detection + recovery) and adds
the transport concern the tracker deliberately leaves out: opening a frame
source, resuming from the last contiguous sequence after a drop, and bounded
reconnection.

The frame source is INJECTABLE — a ``Callable[[resume_cursor], AsyncIterator]``.
Tests inject a fake async generator (no socket). Production wraps a real
WebSocket via :class:`WebSocketFrameSource` (``websockets`` imported lazily
inside the method, so module import stays offline-safe). A source raises
:class:`StreamDisconnect` to simulate/represent a dropped connection; a clean
``StopAsyncIteration`` means the stream ended normally.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Mapping, Optional

from services.derivatives.streams import SequenceTracker

# A frame source is opened with an optional resume cursor (the next contiguous
# sequence expected) and yields provider frames until it ends or disconnects.
FrameSourceFactory = Callable[[Optional[int]], AsyncIterator[Mapping[str, Any]]]


class StreamDisconnect(Exception):
    """Raised by a frame source to signal a recoverable connection drop.

    The driver reconnects (bounded) and resumes from the last contiguous
    sequence. A clean ``StopAsyncIteration`` instead means the stream completed.
    """


@dataclass
class StreamResult:
    accepted: list[dict] = field(default_factory=list)
    duplicates: int = 0
    buffered: int = 0
    reconnects: int = 0
    gaps_detected: int = 0
    gaps_recovered: int = 0
    completed: bool = False
    disconnected_out: bool = False
    cancelled: bool = False
    emitted_events: list[dict] = field(default_factory=list)


def default_sequence_of(frame: Mapping[str, Any]) -> int:
    """Default frame → provider sequence extractor."""
    return int(frame["sequence"])


def default_payload_of(frame: Mapping[str, Any]) -> dict[str, Any]:
    """Default frame → message payload extractor (the frame's ``payload`` or itself)."""
    payload = frame.get("payload")
    return dict(payload) if isinstance(payload, Mapping) else dict(frame)


class ReconnectingStream:
    """Drives a venue frame source through a :class:`SequenceTracker`.

    Bounded reconnection with cursor resume. All ordering / gap logic is
    delegated to the tracker so this class only owns transport + resume.
    """

    def __init__(
        self,
        source_factory: FrameSourceFactory,
        *,
        venue_id: str,
        market_id: str,
        channel: str,
        tenant_id: str = "public",
        sequence_of: Callable[[Mapping[str, Any]], int] = default_sequence_of,
        payload_of: Callable[[Mapping[str, Any]], dict[str, Any]] = default_payload_of,
        max_reconnects: int = 5,
        buffer_size: int = 512,
        gap_threshold: int = 3,
        sleeper: Optional[Callable[[float], Awaitable[Any]]] = None,
        reconnect_backoff: float = 0.0,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._factory = source_factory
        self._venue_id = venue_id
        self._market_id = market_id
        self._channel = channel
        self._tenant_id = tenant_id
        self._sequence_of = sequence_of
        self._payload_of = payload_of
        self._max_reconnects = max(0, int(max_reconnects))
        self._sleeper = sleeper
        self._reconnect_backoff = float(reconnect_backoff)
        self._should_stop = should_stop
        self._last_result: Optional[StreamResult] = None
        self.tracker = SequenceTracker(
            venue_id,
            market_id,
            channel,
            tenant_id=tenant_id,
            buffer_size=buffer_size,
            gap_threshold=gap_threshold,
        )

    @property
    def last_cursor(self) -> Optional[int]:
        """The next contiguous provider sequence — the restart/resume cursor.

        After a clean completion, a disconnect, or a cooperative shutdown this
        is exactly where a restart should resume from (at-least-once: the
        boundary sequence is re-fetched and deduped downstream).
        """
        return self.tracker.expected_next

    @property
    def last_result(self) -> Optional[StreamResult]:
        """The most recent run's partial/final result (available after a
        ``CancelledError`` too, so a supervisor can persist evidence)."""
        return self._last_result

    async def run(self, *, resume_cursor: Optional[int] = None) -> StreamResult:
        """Consume the stream to completion, reconnecting on disconnects.

        ``resume_cursor`` is the next contiguous sequence to resume from (e.g.
        a persisted checkpoint). Returns a :class:`StreamResult` aggregating
        accepted messages, reconnect count, and gap statistics.

        Production behavior:
        * Cooperative shutdown — when ``should_stop()`` returns True the run
          finishes the current frame, marks ``result.cancelled`` and returns
          promptly (a supervisor can persist the partial cursor + gap evidence).
        * Cancellation — an ``asyncio.CancelledError`` closes the frame source,
          records the partial result on :attr:`last_result`, marks
          ``result.cancelled`` and re-raises, so task cancellation is never
          swallowed and the restart cursor is never lost.
        * Restart-from-cursor — the caller reads :attr:`last_cursor` after any
          exit and resumes a fresh run with ``resume_cursor=last_cursor``.
        """
        result = StreamResult()
        cursor = resume_cursor
        try:
            while True:
                source = self._factory(cursor)
                try:
                    async for frame in source:
                        self._consume(frame, result)
                        if self._should_stop is not None and self._should_stop():
                            result.cancelled = True
                            break
                    else:
                        result.completed = True
                        break
                    # Cooperative shutdown (or a source that ended while the
                    # stop flag flipped): no more frames to consume.
                    if result.completed:
                        break
                except StreamDisconnect:
                    # Recoverable drop: resume from the next contiguous sequence.
                    cursor = self.tracker.expected_next
                    if result.reconnects >= self._max_reconnects:
                        result.disconnected_out = True
                        break
                    result.reconnects += 1
                    if self._sleeper is not None and self._reconnect_backoff:
                        await self._sleeper(self._reconnect_backoff * result.reconnects)
                    continue
                finally:
                    aclose = getattr(source, "aclose", None)
                    if callable(aclose):
                        await aclose()
                if result.cancelled or result.disconnected_out or result.completed:
                    break
        except asyncio.CancelledError:
            result.cancelled = True
            self._finalize(result)
            raise
        self._finalize(result)
        return result

    def _finalize(self, result: StreamResult) -> None:
        result.emitted_events = list(self.tracker.emitted_events)
        result.gaps_detected = sum(
            1
            for event in self.tracker.emitted_events
            if event["event_name"] == "derivatives_stream_gap_detected"
        )
        result.gaps_recovered = sum(
            1
            for event in self.tracker.emitted_events
            if event["event_name"] == "derivatives_stream_gap_recovered"
        )
        self._last_result = result

    def _consume(self, frame: Mapping[str, Any], result: StreamResult) -> None:
        sequence = self._sequence_of(frame)
        payload = self._payload_of(frame)
        outcome = self.tracker.ingest(sequence, payload)
        result.accepted.extend(outcome.accepted)
        result.duplicates += outcome.duplicates
        result.buffered += outcome.buffered


class WebSocketFrameSource:
    """Production frame source backed by a real WebSocket (``websockets``).

    Import-safe: ``websockets`` is imported lazily inside ``__call__`` so module
    import never opens a socket. Never used in local mode / CI — the connector
    only constructs it when live-configured and a real transport is intended.
    Each frame is expected to be a JSON object carrying a provider sequence.
    """

    def __init__(
        self,
        url: str,
        *,
        subscribe_message: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        self._url = url
        self._subscribe_message = subscribe_message
        self._headers = dict(headers or {})

    async def __call__(
        self, resume_cursor: Optional[int]
    ) -> AsyncIterator[Mapping[str, Any]]:
        import json as _json

        import websockets  # lazy: offline-safe import

        async with websockets.connect(
            self._url, additional_headers=self._headers or None
        ) as socket:
            if self._subscribe_message is not None:
                message = dict(self._subscribe_message)
                if resume_cursor is not None:
                    message.setdefault("resume", resume_cursor)
                await socket.send(_json.dumps(message))
            try:
                async for raw in socket:
                    yield _json.loads(raw)
            except Exception as exc:  # pragma: no cover - live-socket surface
                raise StreamDisconnect(str(exc)) from exc


__all__ = [
    "FrameSourceFactory",
    "StreamDisconnect",
    "StreamResult",
    "ReconnectingStream",
    "WebSocketFrameSource",
    "default_sequence_of",
    "default_payload_of",
]
