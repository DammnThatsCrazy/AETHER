"""Event-outbox relay worker (PR 6 / FT-6-OUTBOX-RELAY).

Drains the ``event_outbox`` table written by the /v1/batch V2 transactional
path (services/ingestion/bronze_bulk.py) and publishes each row to the event
bus, moving downstream work (Bronze→Silver projection, identity signals,
measurement) out of the request lifecycle and into replayable workers.

Claim protocol (PostgreSQL): a single UPDATE … FROM (SELECT … FOR UPDATE
SKIP LOCKED) claims up to ``batch_size`` due rows so any number of relay
processes can run concurrently without double-claiming. A claim is a LEASE:
``available_at`` is pushed ``lease_seconds`` into the future, so a relay that
crashes mid-publish simply lets its lease expire and another worker reclaims
the row. ``attempt_count`` is incremented at CLAIM time so a row that kills
its publisher still converges to ``dead_letter`` instead of looping forever.

Status machine (vocabulary owned by the FT-5 migration / bronze_bulk):

    pending      enqueued by the ingest transaction, ready at available_at
    claimed      leased by a relay worker (reclaimable once the lease lapses)
    published    terminal success — the bus accepted the event
    retry        publish failed; ready again at available_at (exp. backoff)
    dead_letter  attempt_count reached max_attempts; terminal, kept for ops

Delivery is AT-LEAST-ONCE by construction (a crash between publish and the
``published`` mark republishes on reclaim). Every downstream consumer of
``Topic.SDK_EVENTS_VALIDATED`` is idempotent (see services/ingestion/
workers.py); the Bronze writer additionally skips relay-originated events
entirely because the V2 ingest transaction already persisted the typed
Bronze row (see RELAY_SOURCE_SERVICE below).

Deliberately NOT built on shared/outbox.py: that generic worker owns the
BaseRepository ``queued/processing/…`` status machine and per-row repo
updates, while ``event_outbox`` is a typed high-volume table with its own
FT-5 status vocabulary and set-based SQL claims. Sharing the vocabulary
would have broken the shipped migration contract.

Local / test mode: when ``get_pool()`` returns ``None`` the relay operates on
the shared in-memory ``event_outbox`` store with the same state machine, so
the full claim → publish → mark lifecycle is testable without Postgres.

Supervisor wiring: ``build_event_outbox_relay_coro`` is registered as the
``event_outbox_relay`` WorkerSpec (services/runtime/specs.py), owned by the
``outbox-relay`` runtime role and gated by ``OUTBOX_RELAY_ENABLED``.
"""

from __future__ import annotations

import asyncio
import json
import socket
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence

from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.ingestion.outbox_relay")

# Events the relay publishes carry this source_service so downstream
# consumers can distinguish them from V1 in-request publishes. The Bronze
# writer consumer MUST skip these — their typed Bronze row was persisted in
# the same transaction that enqueued the outbox row.
RELAY_SOURCE_SERVICE = "ingestion.outbox_relay"

_OUTBOX_TABLE = "event_outbox"

# Statuses (kept in exact parity with services/ingestion/bronze_bulk.py and
# the 20260724_ingestion_v2 migration).
_PENDING = "pending"
_CLAIMED = "claimed"
_PUBLISHED = "published"
_RETRY = "retry"
_DEAD_LETTER = "dead_letter"

# A row is claimable when it is not terminal and its available_at has passed:
# pending/retry rows whose due time arrived, and claimed rows whose LEASE has
# expired (crashed or stalled relay).
_CLAIMABLE_STATUSES = (_PENDING, _RETRY, _CLAIMED)

DEFAULT_BACKOFF_BASE_S = 1.0
DEFAULT_BACKOFF_CAP_S = 300.0


@dataclass
class RelayStats:
    """Outcome of one ``drain_once`` pass."""

    claimed: int = 0
    published: int = 0
    retried: int = 0
    dead_lettered: int = 0
    errors: list[str] = field(default_factory=list)


def _parse_iso(value: Any) -> datetime:
    """Parse an ISO8601 string (Z or offset) into an aware UTC datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class EventOutboxRelay:
    """Claims due ``event_outbox`` rows and publishes them to the event bus."""

    def __init__(
        self,
        producer: Any = None,
        *,
        batch_size: Optional[int] = None,
        poll_interval_s: Optional[float] = None,
        lease_seconds: Optional[int] = None,
        max_attempts: Optional[int] = None,
        backoff_base_s: float = DEFAULT_BACKOFF_BASE_S,
        backoff_cap_s: float = DEFAULT_BACKOFF_CAP_S,
        claim_owner: Optional[str] = None,
    ) -> None:
        from config.settings import settings

        iv2 = settings.ingestion_v2
        self._producer = producer
        self.batch_size = int(batch_size if batch_size is not None else iv2.outbox_relay_batch_size)
        self.poll_interval_s = float(
            poll_interval_s if poll_interval_s is not None else iv2.outbox_relay_poll_interval_s
        )
        self.lease_seconds = int(
            lease_seconds if lease_seconds is not None else iv2.outbox_relay_lease_seconds
        )
        self.max_attempts = int(
            max_attempts if max_attempts is not None else iv2.outbox_relay_max_attempts
        )
        self.backoff_base_s = backoff_base_s
        self.backoff_cap_s = backoff_cap_s
        self.claim_owner = claim_owner or f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"
        self._stop = asyncio.Event()

    # ── lifecycle ─────────────────────────────────────────────────────────

    def stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        """Poll loop: drain continuously, sleeping only when the outbox is idle."""
        logger.info(
            "event_outbox relay started owner=%s batch=%d lease=%ds max_attempts=%d",
            self.claim_owner, self.batch_size, self.lease_seconds, self.max_attempts,
        )
        try:
            while not self._stop.is_set():
                try:
                    stats = await self.drain_once()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error("outbox relay drain failed: %s", exc, exc_info=True)
                    stats = RelayStats()
                if stats.claimed == 0:
                    try:
                        await asyncio.wait_for(
                            self._stop.wait(), timeout=self.poll_interval_s
                        )
                    except asyncio.TimeoutError:
                        pass
        finally:
            logger.info("event_outbox relay stopped owner=%s", self.claim_owner)

    # ── one drain pass ────────────────────────────────────────────────────

    async def drain_once(self) -> RelayStats:
        """Claim → publish → mark one batch of due outbox rows."""
        from repositories.repos import get_pool

        pool = await get_pool()
        if pool is None:
            rows = self._memory_claim()
        else:
            rows = await self._pg_claim(pool)

        stats = RelayStats(claimed=len(rows))
        if not rows:
            return stats
        metrics.increment("ingestion_outbox_relay_claimed_total", value=len(rows))

        published_ids: list[str] = []
        failed: list[tuple[dict, str]] = []
        for row in rows:
            try:
                await self._publish_row(row)
                published_ids.append(row["id"])
            except Exception as exc:  # per-row failure → retry/dead-letter
                failed.append((row, f"{type(exc).__name__}: {exc}"))

        if pool is None:
            self._memory_mark(published_ids, failed, stats)
        else:
            await self._pg_mark(pool, published_ids, failed, stats)

        stats.published = len(published_ids)
        if published_ids:
            metrics.increment(
                "ingestion_outbox_relay_published_total", value=len(published_ids)
            )
        if stats.retried:
            metrics.increment(
                "ingestion_outbox_relay_retried_total", value=stats.retried
            )
        if stats.dead_lettered:
            metrics.increment(
                "ingestion_outbox_relay_dead_lettered_total", value=stats.dead_lettered
            )
            logger.error(
                "outbox relay dead-lettered %d row(s): %s",
                stats.dead_lettered, "; ".join(stats.errors[:5]),
            )
        return stats

    # ── publish ───────────────────────────────────────────────────────────

    async def _publish_row(self, row: dict) -> None:
        """Rebuild the bus Event from an outbox row and publish it."""
        from shared.events.events import Event, Topic

        payload = row.get("payload")
        if isinstance(payload, str):
            payload = json.loads(payload)
        payload = payload or {}

        producer = self._producer
        if producer is None:
            from dependencies.providers import get_producer

            producer = get_producer()

        event = Event(
            topic=Topic(row["topic"]),  # unknown topic → ValueError → retry path
            tenant_id=row.get("tenant_id", ""),
            source_service=RELAY_SOURCE_SERVICE,
            correlation_id=str(payload.get("batch_id", "")),
            payload=payload,
        )
        await producer.publish(event)

    def _backoff_at(self, attempt_count: int) -> datetime:
        """Next-eligible time after a failed attempt (exponential, capped).

        Returns a ``datetime`` (NOT an ISO string): asyncpg requires a real
        datetime for a timestamptz parameter — a string raises DataError.
        The in-memory path serializes it with ``isoformat()``.
        """
        delay = min(self.backoff_cap_s, self.backoff_base_s * (2 ** max(attempt_count - 1, 0)))
        return utc_now() + timedelta(seconds=delay)

    # ── PostgreSQL backend ────────────────────────────────────────────────

    _PG_CLAIM_SQL = f"""
    UPDATE {_OUTBOX_TABLE} o
    SET status = '{_CLAIMED}',
        attempt_count = o.attempt_count + 1,
        claimed_at = now(),
        claim_owner = $2,
        available_at = now() + make_interval(secs => $3),
        updated_at = now()
    FROM (
        -- ORDER BY matches the claim index (status, available_at, created_at)
        -- after the status equality, so a large due backlog is claimed via
        -- index order instead of a full sort. Availability order is the relay
        -- contract; strict global FIFO is not (delivery is at-least-once and
        -- consumers are idempotent).
        SELECT id FROM {_OUTBOX_TABLE}
        WHERE status = ANY($4) AND available_at <= now()
        ORDER BY available_at, created_at
        LIMIT $1
        FOR UPDATE SKIP LOCKED
    ) due
    WHERE o.id = due.id
    RETURNING o.id, o.tenant_id, o.event_id, o.topic, o.partition_key,
              o.payload, o.attempt_count
    """

    _PG_PUBLISHED_SQL = f"""
    UPDATE {_OUTBOX_TABLE}
    SET status = '{_PUBLISHED}', published_at = now(), last_error = NULL,
        updated_at = now()
    WHERE id = ANY($1) AND claim_owner = $2
    """

    _PG_RETRY_SQL = f"""
    UPDATE {_OUTBOX_TABLE}
    SET status = '{_RETRY}', available_at = $2, last_error = $3,
        updated_at = now()
    WHERE id = $1 AND claim_owner = $4
    """

    _PG_DEAD_LETTER_SQL = f"""
    UPDATE {_OUTBOX_TABLE}
    SET status = '{_DEAD_LETTER}', last_error = $2, updated_at = now()
    WHERE id = $1 AND claim_owner = $3
    """

    async def _pg_claim(self, pool: Any) -> list[dict]:
        async with pool.acquire() as conn:
            records = await conn.fetch(
                self._PG_CLAIM_SQL,
                self.batch_size,
                self.claim_owner,
                float(self.lease_seconds),
                list(_CLAIMABLE_STATUSES),
            )
        return [dict(r) for r in records]

    async def _pg_mark(
        self,
        pool: Any,
        published_ids: Sequence[str],
        failed: Sequence[tuple[dict, str]],
        stats: RelayStats,
    ) -> None:
        async with pool.acquire() as conn:
            if published_ids:
                await conn.execute(
                    self._PG_PUBLISHED_SQL, list(published_ids), self.claim_owner
                )
            for row, error in failed:
                stats.errors.append(f"{row['id']}: {error}")
                if int(row.get("attempt_count", 0)) >= self.max_attempts:
                    await conn.execute(
                        self._PG_DEAD_LETTER_SQL, row["id"], error[:2000], self.claim_owner
                    )
                    stats.dead_lettered += 1
                else:
                    await conn.execute(
                        self._PG_RETRY_SQL,
                        row["id"],
                        self._backoff_at(int(row.get("attempt_count", 1))),
                        error[:2000],
                        self.claim_owner,
                    )
                    stats.retried += 1

    # ── in-memory backend (AETHER_ENV=local / no asyncpg) ─────────────────

    def _memory_store(self) -> dict:
        # Resolved lazily on every call so suites that evict and re-import
        # repositories.repos always see the current module generation's store.
        from repositories.repos import _IN_MEMORY_STORES

        return _IN_MEMORY_STORES.setdefault(_OUTBOX_TABLE, {})

    def _memory_claim(self) -> list[dict]:
        store = self._memory_store()
        now = utc_now()
        due = [
            row
            for row in store.values()
            if row.get("status") in _CLAIMABLE_STATUSES
            and _parse_iso(row.get("available_at")) <= now
        ]
        due.sort(key=lambda r: str(r.get("created_at", "")))
        claimed: list[dict] = []
        lease_until = (now + timedelta(seconds=self.lease_seconds)).isoformat()
        for row in due[: self.batch_size]:
            row["status"] = _CLAIMED
            row["attempt_count"] = int(row.get("attempt_count", 0)) + 1
            row["claimed_at"] = now.isoformat()
            row["claim_owner"] = self.claim_owner
            row["available_at"] = lease_until
            row["updated_at"] = now.isoformat()
            claimed.append(dict(row))
        return claimed

    def _memory_mark(
        self,
        published_ids: Sequence[str],
        failed: Sequence[tuple[dict, str]],
        stats: RelayStats,
    ) -> None:
        store = self._memory_store()
        now_iso = utc_now().isoformat()
        for oid in published_ids:
            row = store.get(oid)
            if row is None or row.get("claim_owner") != self.claim_owner:
                continue  # reclaimed by another owner — they own the mark
            row["status"] = _PUBLISHED
            row["published_at"] = now_iso
            row["last_error"] = None
            row["updated_at"] = now_iso
        for claimed_row, error in failed:
            row = store.get(claimed_row["id"])
            if row is None or row.get("claim_owner") != self.claim_owner:
                continue
            stats.errors.append(f"{claimed_row['id']}: {error}")
            if int(row.get("attempt_count", 0)) >= self.max_attempts:
                row["status"] = _DEAD_LETTER
                row["last_error"] = error[:2000]
                stats.dead_lettered += 1
            else:
                row["status"] = _RETRY
                row["available_at"] = self._backoff_at(
                    int(row.get("attempt_count", 1))
                ).isoformat()
                row["last_error"] = error[:2000]
                stats.retried += 1
            row["updated_at"] = now_iso


def build_event_outbox_relay_coro() -> Any:
    """Zero-arg coroutine factory for the ``event_outbox_relay`` WorkerSpec."""
    return EventOutboxRelay().run()
