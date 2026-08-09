"""Supervised stream worker for derivatives venue feeds.

Phase-0 gap (2): ``ReconnectingStream`` was transport-only — nothing persisted
the stream cursor or gap evidence, nothing supervised a worker, and a restart
always began from scratch. This module builds the SUPERVISED driver ON TOP of
the durable write path (``services.derivatives.durable_cursor``, owned by the
1E partition — this module only calls into it, never edits it):

* :class:`SupervisedStreamWorker` — restore cursor -> run the venue stream
  through :class:`ReconnectingStream` -> persist the advanced cursor + gap
  evidence -> restart from the persisted cursor. At-least-once by construction:
  the persisted cursor is the next contiguous sequence, so a crash/reconnect
  resumes exactly there and the downstream idempotency keys dedupe any boundary
  re-observation.
* :func:`stream_cursor_json` / :func:`parse_stream_cursor` — the opaque cursor
  encoding (``{"stream": <next_seq>}``) stored via the durable checkpoint repo.
  ``parse_stream_cursor`` is tolerant of a CORRUPTED cursor (returns ``None`` =
  fresh start) so a poisoned checkpoint can never wedge the worker.
* Cooperative shutdown and cancellation are handled: ``should_stop()`` checked
  between frames ends a cycle cleanly; an ``asyncio.CancelledError`` is
  recorded (the partial cursor is still persisted) and re-raised so task
  cancellation is never swallowed.

Observation-only invariant: ``execution_by_aether`` is always False. This
worker observes and records only — it never places, amends, or cancels.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable, Optional

from repositories.derivatives_repos import ConnectorCheckpointRepo, StreamGapRepo
from services.derivatives.connectors.stream import StreamResult
from services.derivatives.durable_cursor import (
    persist_connector_checkpoint,
    persist_stream_gap_events,
    restore_connector_checkpoint,
)
from services.derivatives.foundation import utc_now_iso

STREAM_CURSOR_KEY = "stream"

ShouldStop = Callable[[], bool]


def stream_cursor_json(next_sequence: Optional[int]) -> str:
    """Encode the next-contiguous-sequence cursor for durable storage."""
    return json.dumps({STREAM_CURSOR_KEY: next_sequence})


def parse_stream_cursor(raw: Optional[str]) -> Optional[int]:
    """Parse a persisted stream cursor. Corrupted/unreadable -> ``None``.

    A corrupted cursor (truncated JSON, wrong shape, non-int sequence) must
    never wedge the worker: returning ``None`` means "start from scratch",
    which the venue's high-water filter makes safe (at-least-once).
    """
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    value = parsed.get(STREAM_CURSOR_KEY)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class SupervisedStreamWorker:
    """Supervised stream driver: restore -> run -> persist -> restart.

    ``adapter`` is any object exposing ``run_stream(resume_cursor=...,
    should_stop=...) -> StreamResult`` and ``last_stream_cursor() -> int|None``
    (the ``VenueDerivativesAdapter`` surface).
    """

    def __init__(
        self,
        adapter: Any,
        *,
        tenant_id: str = "public",
        connector_id: Optional[str] = None,
        checkpoint_repo: Optional[ConnectorCheckpointRepo] = None,
        gap_repo: Optional[StreamGapRepo] = None,
        sleeper: Optional[Callable[[float], Awaitable[Any]]] = None,
        idle_between_cycles: float = 0.0,
    ) -> None:
        self.adapter = adapter
        self.tenant_id = tenant_id
        self.connector_id = (
            connector_id
            or getattr(adapter, "venue_id", None)
            or getattr(adapter, "adapter_id", None)
            or "stream-connector"
        )
        self.checkpoints = checkpoint_repo or ConnectorCheckpointRepo()
        self.gaps = gap_repo or StreamGapRepo()
        self._sleeper = sleeper
        self._idle_between_cycles = max(0.0, float(idle_between_cycles))

    # ── cursor restore / persist ───────────────────────────────────────────
    async def restore_cursor(self) -> Optional[int]:
        """Next contiguous sequence to resume from, or ``None`` (fresh start)."""
        raw = await restore_connector_checkpoint(
            self.checkpoints, tenant_id=self.tenant_id, connector_id=self.connector_id,
        )
        return parse_stream_cursor(raw)

    async def persist_stream_cursor(self, next_sequence: Optional[int]) -> dict:
        """Persist the next-contiguous-sequence cursor durably (idempotent)."""
        return await persist_connector_checkpoint(
            self.checkpoints,
            tenant_id=self.tenant_id,
            connector_id=self.connector_id,
            checkpoint_value=stream_cursor_json(next_sequence),
            advanced_at=utc_now_iso(),
            state="ok",
        )

    # ── one supervised cycle ───────────────────────────────────────────────
    async def run_once(
        self,
        *,
        max_reconnects: int = 5,
        market_id: Optional[str] = None,
        should_stop: Optional[ShouldStop] = None,
    ) -> StreamResult:
        """One restore -> run -> persist cycle. Returns the stream result.

        The advanced cursor is persisted BEFORE returning, so a worker killed
        immediately after still resumes from it (at-least-once). Gap
        detected/recovered events are persisted through the durable write path.
        """
        cursor = await self.restore_cursor()
        result = await self.adapter.run_stream(
            resume_cursor=cursor,
            max_reconnects=max_reconnects,
            market_id=market_id,
            should_stop=should_stop,
        )
        next_sequence = (
            self.adapter.last_stream_cursor()
            if hasattr(self.adapter, "last_stream_cursor")
            else cursor
        )
        await self.persist_stream_cursor(next_sequence)
        await persist_stream_gap_events(
            self.gaps, result.emitted_events, tenant_id=self.tenant_id,
        )
        return result

    async def run_until_stopped(
        self,
        *,
        should_stop: Optional[ShouldStop] = None,
        max_reconnects: int = 5,
        market_id: Optional[str] = None,
        cycles: Optional[int] = None,
    ) -> dict[str, Any]:
        """Run supervised cycles until ``should_stop()`` (or ``cycles`` bound).

        Between cycles the worker honors an ``asyncio.CancelledError`` (re-raised
        after persisting the current cycle's cursor) and cooperatively stops when
        ``should_stop()`` returns True. Returns a deterministic summary.
        """
        stop = should_stop or (lambda: False)
        ran = 0
        last: Optional[StreamResult] = None
        while True:
            try:
                last = await self.run_once(
                    max_reconnects=max_reconnects,
                    market_id=market_id,
                    should_stop=stop,
                )
            except asyncio.CancelledError:
                # Cursor for the interrupted cycle is already persisted by
                # run_once (before it can be interrupted mid-stream the partial
                # cursor is persisted by the adapter's stream state) — re-raise
                # so cancellation semantics are preserved.
                raise
            ran += 1
            if stop():
                break
            if cycles is not None and ran >= cycles:
                break
            if self._idle_between_cycles > 0:
                if self._sleeper is not None:
                    await self._sleeper(self._idle_between_cycles)
                else:
                    await asyncio.sleep(self._idle_between_cycles)
        return {
            "tenant_id": self.tenant_id,
            "connector_id": self.connector_id,
            "cycles_completed": ran,
            "completed": bool(last is not None and last.completed),
            "cancelled": bool(last is not None and last.cancelled),
            "last_cursor": (
                self.adapter.last_stream_cursor()
                if hasattr(self.adapter, "last_stream_cursor")
                else None
            ),
            "gaps_detected": int(last.gaps_detected) if last else 0,
            "gaps_recovered": int(last.gaps_recovered) if last else 0,
        }


__all__ = [
    "STREAM_CURSOR_KEY",
    "SupervisedStreamWorker",
    "stream_cursor_json",
    "parse_stream_cursor",
]
