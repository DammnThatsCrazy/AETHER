"""Durable pull-cursor + stream-gap persistence for derivatives connectors.

Closes the write-path gaps from the Phase-0 audit for the derivatives domain:

  * ``ConnectorCheckpointRepo`` had NO write path — ``pull_events`` returned
    checkpoints but nothing persisted or restored them, so a restarted pull
    always began from scratch (cursor moved backward, boundary records
    re-emitted / possibly skipped on a boundary key).
  * ``StreamGapRepo`` had NO insert path — ``SequenceTracker`` emitted
    ``derivatives_stream_gap_detected`` events but nothing wrote
    ``derivatives_stream_gaps`` rows, so gap evidence was never durable.

This module composes the existing typed repositories
(``repositories.derivatives_repos``) with a small, crash-safe write layer:

  * ``persist_connector_checkpoint`` / ``restore_connector_checkpoint`` —
    idempotent cursor storage keyed deterministically on ``(tenant_id,
    connector_id)``; re-persisting the same cursor collapses instead of
    duplicating.
  * ``persist_stream_gap`` / ``resolve_stream_gap`` — deterministic gap rows
    (``stream_gap_id`` derived from venue/market/channel + expected sequence) so
    a re-emitted gap event never double-writes; ``recovered_at`` starts NULL and
    is set only when the stream advances past the hole.
  * :class:`DerivativesPullRunner` — the crash-boundary driver: restore →
    pull → return the advanced checkpoint for the caller to ACK after
    downstream processing (:meth:`DerivativesPullRunner.persist_checkpoint`) →
    persist emitted gap events. At-least-once by construction: on restart it
    resumes from the last ACKED cursor, and the checkpoint idempotency key
    dedups replays. Idempotent replay of the same cursor yields zero new events
    (the adapter's high-water filter) so there is never duplication *or* skip.

Observation-only invariant: ``execution_by_aether`` is always False. This module
never places, amends, or cancels anything.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from repositories.derivatives_repos import ConnectorCheckpointRepo, StreamGapRepo
from services.derivatives.connectors.base import DerivativesConnectorCheckpoint
from services.derivatives.connectors.stream import StreamResult
from services.derivatives.foundation import (
    deterministic_id,
    deterministic_idempotency_key,
    utc_now_iso,
)

GAP_DETECTED_EVENT = "derivatives_stream_gap_detected"
GAP_RECOVERED_EVENT = "derivatives_stream_gap_recovered"


# ═══════════════════════════════════════════════════════════════════════════
# Connector checkpoint write path
# ═══════════════════════════════════════════════════════════════════════════

def _checkpoint_key(tenant_id: str, connector_id: str) -> str:
    return f"{tenant_id}|{connector_id}"


def connector_checkpoint_id(tenant_id: str, connector_id: str) -> str:
    return deterministic_id("ccp_", _checkpoint_key(tenant_id, connector_id))


def connector_checkpoint_idempotency_key(tenant_id: str, connector_id: str) -> str:
    return deterministic_idempotency_key(_checkpoint_key(tenant_id, connector_id))


async def persist_connector_checkpoint(
    repo: ConnectorCheckpointRepo,
    *,
    tenant_id: str,
    connector_id: str,
    checkpoint_value: str,
    advanced_at: Optional[str] = None,
    state: str = "ok",
) -> dict:
    """Persist one connector pull cursor durably (idempotent).

    Keyed on ``(tenant_id, connector_id)``: a repeated persist of the same
    cursor is a no-op (the ``insert`` conflict key collapses it); an advanced
    cursor updates the stored row in place via ``update_by_key``. Returns the
    stored row shape.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required to persist a connector checkpoint")
    if not connector_id:
        raise ValueError("connector_id is required to persist a connector checkpoint")
    advanced_at = advanced_at or utc_now_iso()

    existing = await repo.find_one({
        "tenant_id": tenant_id,
        "connector_id": connector_id,
    })
    if existing is not None:
        await repo.update_by_key(
            {"tenant_id": tenant_id, "connector_id": connector_id},
            {
                "state": state,
                "checkpoint_value": checkpoint_value,
                "advanced_at": advanced_at,
            },
        )
        return {
            "tenant_id": tenant_id,
            "connector_checkpoint_id": existing.get("connector_checkpoint_id"),
            "connector_id": connector_id,
            "state": state,
            "checkpoint_value": checkpoint_value,
            "advanced_at": advanced_at,
        }

    checkpoint_id = connector_checkpoint_id(tenant_id, connector_id)
    record = {
        "tenant_id": tenant_id,
        "connector_checkpoint_id": checkpoint_id,
        "connector_id": connector_id,
        "state": state,
        "checkpoint_value": checkpoint_value,
        "advanced_at": advanced_at,
        "idempotency_key": connector_checkpoint_idempotency_key(tenant_id, connector_id),
        "execution_by_aether": False,
    }
    await repo.insert(record)
    return record


async def persist_checkpoint_dataclass(
    repo: ConnectorCheckpointRepo,
    checkpoint: DerivativesConnectorCheckpoint,
    *,
    state: str = "ok",
) -> dict:
    """Persist a :class:`DerivativesConnectorCheckpoint` (the connector contract
    dataclass) through the same idempotent write path."""
    return await persist_connector_checkpoint(
        repo,
        tenant_id=checkpoint.tenant_id,
        connector_id=checkpoint.connector_id,
        checkpoint_value=checkpoint.checkpoint_value,
        advanced_at=checkpoint.advanced_at,
        state=state,
    )


async def restore_connector_checkpoint(
    repo: ConnectorCheckpointRepo,
    *,
    tenant_id: str,
    connector_id: str,
) -> Optional[str]:
    """Restore the last persisted cursor value for ``(tenant, connector)``.

    Returns ``None`` when no checkpoint was ever persisted (fresh start). The
    caller parses the returned opaque cursor (JSON string for the venue adapters)
    and resumes from exactly that point — never from scratch.
    """
    existing = await repo.find_one({
        "tenant_id": tenant_id,
        "connector_id": connector_id,
    })
    if existing is None:
        return None
    value = existing.get("checkpoint_value")
    return value if isinstance(value, str) and value else None


async def latest_connector_checkpoint(
    repo: ConnectorCheckpointRepo,
    *,
    tenant_id: str,
    connector_id: str,
) -> Optional[dict]:
    """Return the full persisted checkpoint row (or None)."""
    return await repo.find_one({
        "tenant_id": tenant_id,
        "connector_id": connector_id,
    })


# ═══════════════════════════════════════════════════════════════════════════
# Stream-gap write path
# ═══════════════════════════════════════════════════════════════════════════

def _gap_key(
    tenant_id: str,
    venue_id: str,
    canonical_market_id: str,
    channel: str,
    expected_sequence: Any,
) -> str:
    return "|".join([
        tenant_id or "",
        venue_id or "",
        canonical_market_id or "",
        channel or "",
        str(expected_sequence),
    ])


def stream_gap_id(
    tenant_id: str,
    venue_id: str,
    canonical_market_id: str,
    channel: str,
    expected_sequence: Any,
) -> str:
    return deterministic_id("dsg_", _gap_key(
        tenant_id, venue_id, canonical_market_id, channel, expected_sequence,
    ))


def stream_gap_idempotency_key(
    tenant_id: str,
    venue_id: str,
    canonical_market_id: str,
    channel: str,
    expected_sequence: Any,
) -> str:
    return deterministic_idempotency_key(_gap_key(
        tenant_id, venue_id, canonical_market_id, channel, expected_sequence,
    ))


async def persist_stream_gap(
    repo: StreamGapRepo,
    gap_event: dict[str, Any],
    *,
    tenant_id: str,
) -> Optional[dict]:
    """Insert a ``derivatives_stream_gaps`` row from a gap-detected event.

    ``gap_event`` is the canonical event dict produced by ``SequenceTracker``
    (``event_name`` + ``payload`` carrying venue_id, canonical_market_id,
    channel, expected_sequence, received_sequence, detected_at). The row id is
    deterministic so a re-emitted gap event collapses instead of duplicating.
    ``recovered_at`` is written NULL (the hole is still open). Returns the
    persisted row, or ``None`` when the event is not a gap event / lacks the
    identity fields.
    """
    payload = gap_event.get("payload") or {} if isinstance(gap_event, dict) else {}
    venue_id = payload.get("venue_id") or payload.get("venue", "")
    market_id = payload.get("canonical_market_id") or payload.get("market_id", "")
    channel = payload.get("channel", "")
    expected_sequence = payload.get("expected_sequence")
    if expected_sequence is None:
        return None

    gap_id = stream_gap_id(tenant_id, venue_id, market_id, channel, expected_sequence)
    record = {
        "tenant_id": tenant_id,
        "stream_gap_id": gap_id,
        "venue_id": venue_id,
        "canonical_market_id": market_id,
        "channel": channel,
        "expected_sequence": expected_sequence,
        "received_sequence": payload.get("received_sequence"),
        "detected_at": payload.get("detected_at") or utc_now_iso(),
        "recovered_at": None,
        "status": "open",
        "idempotency_key": stream_gap_idempotency_key(
            tenant_id, venue_id, market_id, channel, expected_sequence,
        ),
        "evidence": {"event_name": gap_event.get("event_name", GAP_DETECTED_EVENT)},
        "execution_by_aether": False,
    }
    await repo.insert(record)
    return record


async def resolve_stream_gap(
    repo: StreamGapRepo,
    *,
    tenant_id: str,
    venue_id: str,
    canonical_market_id: str,
    channel: str,
    recovered_at: Optional[str] = None,
) -> int:
    """Mark every OPEN gap for a stream key recovered (append-only-correct).

    ``SequenceTracker`` recovers a gap once the contiguous stream has advanced
    past the sequence that revealed the hole; at that point the recovery event
    carries only the stream key, so every still-open row for that key is
    resolved. ``recovered_at`` is set (evidence preserved — never deleted).
    Returns the number of rows resolved.
    """
    recovered_at = recovered_at or utc_now_iso()
    rows = await repo.find_many({
        "tenant_id": tenant_id,
        "venue_id": venue_id,
        "canonical_market_id": canonical_market_id,
        "channel": channel,
        "status": "open",
    }, limit=1000)
    resolved = 0
    for row in rows:
        updated = await repo.update_by_key(
            {
                "tenant_id": tenant_id,
                "stream_gap_id": row["stream_gap_id"],
            },
            {"status": "recovered", "recovered_at": recovered_at},
        )
        if updated:
            resolved += 1
    return resolved


async def persist_stream_gap_events(
    repo: StreamGapRepo,
    events: list[dict[str, Any]],
    *,
    tenant_id: str,
) -> dict[str, int]:
    """Persist the gap events emitted by one :class:`SequenceTracker` /
    :class:`ReconnectingStream` run. Returns ``{"detected": n, "recovered": n}``.
    """
    detected = 0
    recovered = 0
    for event in events or []:
        event_name = event.get("event_name") if isinstance(event, dict) else None
        if event_name == GAP_DETECTED_EVENT:
            if await persist_stream_gap(repo, event, tenant_id=tenant_id) is not None:
                detected += 1
        elif event_name == GAP_RECOVERED_EVENT:
            payload = event.get("payload") or {}
            recovered += await resolve_stream_gap(
                repo,
                tenant_id=tenant_id,
                venue_id=payload.get("venue_id") or "",
                canonical_market_id=(
                    payload.get("canonical_market_id") or payload.get("market_id") or ""
                ),
                channel=payload.get("channel", ""),
            )
    return {"detected": detected, "recovered": recovered}


# ═══════════════════════════════════════════════════════════════════════════
# Crash-boundary pull driver
# ═══════════════════════════════════════════════════════════════════════════

class DerivativesPullRunner:
    """Durable pull driver: restore → pull → ack-after-processing.

    Crash contract: ``run_pull`` returns ``(events, new_checkpoint)`` WITHOUT
    advancing the durable cursor; the caller persists ``new_checkpoint`` via
    :meth:`persist_checkpoint` only after the events have been durably
    processed/acknowledged downstream. A worker killed between ``run_pull`` and
    that ack resumes from the last ACKED cursor on the next invocation and
    re-delivers the boundary events (the adapter's high-water filter + the
    checkpoint idempotency key dedup the replay) — at-least-once, never
    at-most-once.
    """

    def __init__(
        self,
        adapter: Any,
        *,
        tenant_id: str = "public",
        connector_id: Optional[str] = None,
        checkpoint_repo: Optional[ConnectorCheckpointRepo] = None,
        gap_repo: Optional[StreamGapRepo] = None,
    ) -> None:
        self.adapter = adapter
        self.tenant_id = tenant_id
        self.connector_id = (
            connector_id
            or getattr(adapter, "venue_id", None)
            or getattr(adapter, "adapter_id", None)
            or "connector"
        )
        self.checkpoints = checkpoint_repo or ConnectorCheckpointRepo()
        self.gaps = gap_repo or StreamGapRepo()

    async def restore_cursor(self) -> Optional[str]:
        """The opaque cursor to resume from, or None on first run."""
        return await restore_connector_checkpoint(
            self.checkpoints, tenant_id=self.tenant_id, connector_id=self.connector_id,
        )

    async def run_pull(self) -> tuple[list[dict], dict]:
        """One pull cycle: restore cursor → pull. Does NOT persist.

        Returns ``(events, new_checkpoint)``. The advanced checkpoint is NOT
        written here — it is persisted only when the caller calls
        :meth:`persist_checkpoint` AFTER the events are durably processed
        downstream. Persisting before that would resume past unhandled events
        on a crash (at-most-once).
        """
        cursor = await self.restore_cursor()
        checkpoint_arg: Optional[dict] = None
        if cursor:
            try:
                parsed = json.loads(cursor)
                checkpoint_arg = parsed if isinstance(parsed, dict) else {"cursors": parsed}
            except (ValueError, TypeError):
                checkpoint_arg = {"cursors": {cursor: ""}}
        events, new_checkpoint = await self.adapter.pull_events(checkpoint_arg)
        new_checkpoint = new_checkpoint or {}
        return events, new_checkpoint

    async def persist_checkpoint(self, new_checkpoint: dict) -> dict:
        """Acknowledge a pulled checkpoint AFTER downstream processing.

        The caller invokes this only once the events returned by :meth:`run_pull`
        are durably persisted/acknowledged (silver/bronze write, batch ack).
        Persisting earlier would skip those events on a crash (at-most-once).
        """
        return await persist_connector_checkpoint(
            self.checkpoints,
            tenant_id=self.tenant_id,
            connector_id=self.connector_id,
            checkpoint_value=json.dumps(new_checkpoint, sort_keys=True, default=str),
            advanced_at=utc_now_iso(),
            state="ok",
        )

    async def persist_stream_result(self, result: StreamResult) -> dict[str, int]:
        """Persist gap detected/recovered events from a ReconnectingStream run."""
        return await persist_stream_gap_events(
            self.gaps, result.emitted_events, tenant_id=self.tenant_id,
        )


__all__ = [
    "GAP_DETECTED_EVENT",
    "GAP_RECOVERED_EVENT",
    "connector_checkpoint_id",
    "connector_checkpoint_idempotency_key",
    "persist_connector_checkpoint",
    "persist_checkpoint_dataclass",
    "restore_connector_checkpoint",
    "latest_connector_checkpoint",
    "stream_gap_id",
    "stream_gap_idempotency_key",
    "persist_stream_gap",
    "resolve_stream_gap",
    "persist_stream_gap_events",
    "DerivativesPullRunner",
]
