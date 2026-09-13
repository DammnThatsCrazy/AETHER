"""Ingestion-level replay runner (WS-B4).

An OPERATOR-triggered, scan-run re-delivery of durable Bronze SDK events
through the universal ingestion gateway with **original-time preservation**
(Invariant #15). Reading ONLY the durable Bronze rows
(``_IN_MEMORY_STORES["bronze_sdk_events"]`` locally / the ``bronze_sdk_events``
table) and publishing validated events back onto ``Topic.SDK_EVENTS_VALIDATED``,
it drives the exact same downstream pipeline as a live ingest (Silver
normalization, fact projection, identity signals) — but each re-delivered event
keeps its ORIGINAL occurrence timestamp and event_id, so every idempotent
consumer recomputes the same downstream fact instead of minting a duplicate
observation.

Why is this the ingestion replay and NOT a job on the event-outbox relay /
durable control plane?

- **Outbox is forward-only.** The ``event_outbox`` relay drains *pending
  publishes* of events that were already written in the current V2 ingest
  transaction. Its rows are claims with a lease + attempt lifecycle, not a
  re-runnable log; nothing in it survives as a durable re-process source, and a
  replayed event is NOT a new Bronze row (the original already exists) — the
  outbox would have nothing to enqueue.
- **Bronze is the durable replay source.** The same invariant the semantic
  replay runner (``services/semantic_intelligence/replay.py``) relies on holds
  here: Bronze is the append-only record of every accepted event (Invariant
  #14), so a reprocessing pass must scan Bronze, not an ephemeral queue.
- **Scope honesty (this slice).** WS-B4 ships a *service runner + minimal
  OPERATOR route*, deliberately NOT a durable-jobs control plane (no persisted
  job table / cursor / lease). The run is synchronous and its idempotency unit
  is the caller-supplied ``replay_run_id`` (auto-generated when omitted): the
  in-memory ``_RUN_JOURNAL`` records each completed run so repeating a run id
  is a no-op, and downstream consumers are already idempotent on the original
  event identity. Durable job persistence / resumability is a later slice and
  is NOT claimed here.

Replay stamps (Invariant #15): the runner computes ONE fresh run instant
(``replay_received_at == replay_ingested_at``) and hands it to the replay
adapter per row. The adapter rewrites the envelope's ``received_at`` /
``ingested_at`` (and the runner mirrors it on the flat payload) while
``occurred_at`` / ``timestamp`` / ``event_id`` stay ORIGINAL. This is the
observed-vs-received split: a replay is a new *delivery*, not a new *event*.

Published events carry ``source_service == REPLAY_SOURCE_SERVICE`` so
downstream consumers can tell a replay delivery from a live one — in
particular the ``sdk_bronze_writer`` consumer SKIPS them (services/ingestion/
workers.py): replaying must never mint a second Bronze row for an event that is
already durable. This mirrors the existing outbox-relay skip
(``ingestion.outbox_relay``).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Optional, Sequence

from shared.common.common import utc_now
from shared.events.events import Event, Topic
from shared.logger.logger import get_logger, metrics

from services.ingestion.adapters.replay import (
    REPLAY_CONTEXT_KEY,
    ReplayIngressAdapter,
)
from services.ingestion.gateway import validate_and_stamp

logger = get_logger("aether.service.ingestion.replay")

# Events the replay runner publishes carry this source_service so downstream
# consumers can distinguish a replay delivery from a live one. The Bronze
# writer consumer MUST skip these — the event's durable Bronze row already
# exists (it is what the replay is re-delivering).
REPLAY_SOURCE_SERVICE = "ingestion.replay"

_BRONZE_TABLE = "bronze_sdk_events"

# In-memory run journal (local/test only; production runs are synchronous and
# the operator route carries the summary back directly). Keyed by replay_run_id
# so a repeated run id is a no-op — the idempotency unit of this slice.
_RUN_JOURNAL: dict[str, dict[str, Any]] = {}


def reset_run_journal() -> None:
    """Test helper: clear the in-memory replay run journal."""
    _RUN_JOURNAL.clear()


# ── Bronze scan / canonical projection ──────────────────────────────────────

def _payload_of(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    if isinstance(payload, dict):
        return dict(payload)
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
            if isinstance(parsed, dict):
                return parsed
        except (ValueError, TypeError):
            pass
    return {}


def _norm_iso(value: Any) -> Optional[str]:
    """Normalize an ISO-8601 instant to a comparable UTC string (or None)."""
    if isinstance(value, datetime):
        text = value.isoformat()
    else:
        text = str(value or "")
    if not text:
        return None
    return text.replace("Z", "+00:00")


def _project_row(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Project a durable Bronze row (V1 or V2 shape) onto a canonical replay row.

    The durable Bronze row is the source of truth; the flat payload it carries
    is the original normalized SDK dict. ``event_type``/``event_family`` fall
    back to the V2 typed columns when the payload does not carry them, and the
    ORIGINAL occurrence instant is read from the payload ``timestamp`` (or the
    V2 ``event_timestamp`` column).
    """
    payload = _payload_of(row)
    event_id = payload.get("event_id") or row.get("event_id") or row.get("provider_record_id")
    tenant_id = row.get("tenant_id")
    if not event_id or not tenant_id:
        return None
    flat = dict(payload)
    for col in ("event_type", "event_family"):
        if not flat.get(col) and row.get(col):
            flat[col] = row[col]
    occurred = _norm_iso(flat.get("timestamp") or row.get("event_timestamp"))
    return {
        "tenant_id": str(tenant_id),
        "event_id": str(event_id),
        "event_type": str(flat.get("event_type") or ""),
        "event_family": flat.get("event_family"),
        "occurred_at": occurred,
        "flat": flat,
        "bronze_ref": str(row.get("id") or row.get("provider_record_id") or event_id),
    }


def _matches(
    proj: dict[str, Any],
    *,
    event_types: Optional[Sequence[str]] = None,
    families: Optional[Sequence[str]] = None,
    occurred_from: Optional[str] = None,
    occurred_to: Optional[str] = None,
) -> bool:
    if event_types and proj["event_type"] not in event_types:
        return False
    if families and proj.get("event_family") not in families:
        return False
    # Occurrence-window filters compare the ORIGINAL occurrence instant
    # (Invariant #15) — never the replay receipt stamp.
    occurred = proj.get("occurred_at")
    if occurred is not None:
        if occurred_from and occurred < _norm_iso(occurred_from):
            return False
        if occurred_to and occurred > _norm_iso(occurred_to):
            return False
    return True


def _sort_key(proj: dict[str, Any]) -> tuple[str, str]:
    return (str(proj["flat"].get("received_at") or ""), proj["event_id"])


async def iter_bronze_observations(
    tenant_id: str,
    *,
    event_types: Optional[Sequence[str]] = None,
    families: Optional[Sequence[str]] = None,
    occurred_from: Optional[str] = None,
    occurred_to: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Scan the tenant's durable Bronze SDK rows (stable order, filtered).

    Local mode reads the shared ``bronze_sdk_events`` in-memory store; when a
    real pool is present it mirrors the semantic replay reader's SQL scan of
    the ``bronze_sdk_events`` table. Rows are projected canonically and
    returned in ``(received_at, event_id)`` order — the same stable order the
    semantic replay runner uses — so a later durable-cursor slice can resume
    deterministically.
    """
    from repositories.repos import _IN_MEMORY_STORES, get_pool

    filters = {
        "event_types": event_types,
        "families": families,
        "occurred_from": occurred_from,
        "occurred_to": occurred_to,
    }
    pool = await get_pool()
    if pool is None:
        store = _IN_MEMORY_STORES.setdefault(_BRONZE_TABLE, {})
        projected = [
            proj
            for row in store.values()
            if str(row.get("tenant_id", "")) == tenant_id
            for proj in [(_project_row(row) or {})]
            if proj and _matches(proj, **filters)
        ]
    else:
        async with pool.acquire() as conn:
            db_rows = await conn.fetch(
                f"SELECT tenant_id, event_id, event_type, event_family, event_timestamp, "
                f"received_at, payload FROM {_BRONZE_TABLE} WHERE tenant_id = $1 "
                "ORDER BY received_at ASC, event_id ASC",
                tenant_id,
            )
        projected = []
        for r in db_rows:
            row = dict(r)
            payload = row.get("payload")
            row["payload"] = payload if isinstance(payload, dict) else (
                json.loads(payload) if payload else {}
            )
            proj = _project_row(row)
            if proj and _matches(proj, **filters):
                projected.append(proj)
    projected.sort(key=_sort_key)
    if limit is not None and limit > 0:
        projected = projected[:limit]
    return projected


# ── Replay run ───────────────────────────────────────────────────────────────

async def replay_events(
    tenant_id: str,
    *,
    event_types: Optional[Sequence[str]] = None,
    families: Optional[Sequence[str]] = None,
    occurred_from: Optional[str] = None,
    occurred_to: Optional[str] = None,
    limit: Optional[int] = None,
    dry_run: bool = False,
    producer: Any = None,
    replay_run_id: Optional[str] = None,
) -> dict[str, Any]:
    """Re-deliver the tenant's matching durable Bronze SDK events.

    Each row is copied, given a fresh replay context (run-level stamps), run
    through the replay adapter + universal gateway, and — when accepted and not
    a dry run — published to ``Topic.SDK_EVENTS_VALIDATED`` with
    ``source_service == REPLAY_SOURCE_SERVICE``. ``event_id``/``timestamp`` and
    the envelope ``occurred_at`` stay ORIGINAL (Invariant #15).

    Returns a summary dict (never raises mid-run; per-row failures are
    collected in ``errors``):

        scanned / replayed / rejected / skipped / published,
        status ("completed" | "dry_run"), dry_run, replay_run_id,
        replayed_event_ids, rejected_event_ids, errors

    Idempotency: a caller-supplied ``replay_run_id`` is the unit — repeating a
    completed run id is a no-op that returns the recorded summary. Runs with an
    auto-generated id are journaled the same way (in-memory, this slice).
    """
    run_id = replay_run_id or uuid.uuid4().hex
    prior = _RUN_JOURNAL.get(run_id)
    if prior is not None:
        logger.info("replay run %s already recorded — no-op", run_id)
        return dict(prior)

    rows = await iter_bronze_observations(
        tenant_id,
        event_types=event_types,
        families=families,
        occurred_from=occurred_from,
        occurred_to=occurred_to,
        limit=limit,
    )

    summary: dict[str, Any] = {
        "scanned": len(rows),
        "replayed": 0,
        "rejected": 0,
        "skipped": 0,
        "published": 0,
        "status": "dry_run" if dry_run else "completed",
        "dry_run": dry_run,
        "replay_run_id": run_id,
        "replayed_event_ids": [],
        "rejected_event_ids": [],
        "errors": [],
    }

    if producer is None:
        from dependencies.providers import get_producer

        producer = get_producer()

    adapter = ReplayIngressAdapter()
    run_stamp = utc_now().isoformat()  # ONE fresh replay instant for the run
    if summary["scanned"]:
        metrics.increment(
            "ingestion_replay_scanned_total",
            value=summary["scanned"],
            labels={"tenant_id": tenant_id},
        )

    for proj in rows:
        event_id = proj["event_id"]
        try:
            flat = dict(proj["flat"])
            flat.pop(REPLAY_CONTEXT_KEY, None)  # never trust a stored context
            flat[REPLAY_CONTEXT_KEY] = {
                "original_event_id": event_id,
                "replay_received_at": run_stamp,
                "replay_ingested_at": run_stamp,
                "bronze_ref": proj["bronze_ref"],
                "replay_run_id": run_id,
            }

            envelope = adapter.build_observation_envelope(flat)
            if envelope is None:
                summary["skipped"] += 1
                metrics.increment(
                    "ingestion_replay_skipped_total", labels={"tenant_id": tenant_id}
                )
                continue

            result = validate_and_stamp(
                envelope.to_bronze_additive(),
                adapter=adapter,
                tenant_id=tenant_id,
            )
            if not result.accepted:
                summary["rejected"] += 1
                summary["rejected_event_ids"].append(event_id)
                metrics.increment(
                    "ingestion_replay_rejected_total", labels={"tenant_id": tenant_id}
                )
                continue

            summary["replayed"] += 1
            summary["replayed_event_ids"].append(event_id)
            metrics.increment(
                "ingestion_replay_replayed_total", labels={"tenant_id": tenant_id}
            )
            if dry_run:
                continue

            stamped = result.envelope or {}
            out_payload = dict(flat)
            out_payload.pop(REPLAY_CONTEXT_KEY, None)
            # Replay receipt stamps on the flat surface; timestamp stays ORIGINAL.
            out_payload["received_at"] = run_stamp
            out_payload["ingested_at"] = run_stamp
            out_payload["observation_envelope"] = stamped
            out_payload["replayed_from_event_id"] = event_id

            await producer.publish(
                Event(
                    topic=Topic.SDK_EVENTS_VALIDATED,
                    payload=out_payload,
                    tenant_id=tenant_id,
                    event_id=event_id,
                    source_service=REPLAY_SOURCE_SERVICE,
                    correlation_id=run_id,
                )
            )
            summary["published"] += 1
        except Exception as exc:  # per-row isolation: never take the run down
            summary["errors"].append(f"{event_id}: {type(exc).__name__}: {exc}")
            logger.error("replay run %s failed for event %s: %s", run_id, event_id, exc)

    if summary["published"]:
        metrics.increment(
            "ingestion_replay_published_total",
            value=summary["published"],
            labels={"tenant_id": tenant_id},
        )
    _RUN_JOURNAL[run_id] = summary
    return dict(summary)
