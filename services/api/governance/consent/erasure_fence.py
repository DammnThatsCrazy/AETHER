"""Erasure fence for asynchronous projections of subject data.

Consent is enforced when an event is accepted, but projections (the analytics
event store) run later from an at-least-once queue. An event accepted before a
DSR erasure can still be queued, or be redelivered, after the erasure job has
deleted the subject's rows — and writing it then silently undoes the erasure.

``submit_dsr`` records an **erasure marker** per erased identifier (the DSR's
``user_id`` and optional ``anonymous_id``) before it persists the request, so
every stored erasure request has its marker even if the process dies between
the two writes.
A marker is keyed by a digest of ``(tenant_id, kind, identifier)`` and stores
only the latest erasure's ``submitted_at`` — never the identifier itself — so
the fence costs one keyed query per projected event (the event's markers and
its tenant's fence together), instead of scanning consent records.

Deleting a tenant removes its subject markers but first writes a tenant-level
fence (``record_tenant_erasure_fence``) that is kept, so an event still queued
or redelivered for that tenant is never projected afterwards.

An event is fenced when a matching erasure was submitted at or after the event
was received, i.e. the erasure was meant to cover it. Activity received after
the request is new data and is not fenced.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from repositories.repos import BaseRepository, canonical_utc_timestamp
from shared.temporal.instant import coerce_utc_lenient

ERASURE_MARKERS_TABLE = "dsr_erasure_markers"
_KINDS = ("user_id", "anonymous_id")


# Durable flag: markers for erasures submitted before markers existed have
# been written (see ensure_markers_backfilled).
_BACKFILL_FLAG_ID = "dsrm_backfill_v1"
_BACKFILL_PAGE = 500
_backfilled = False


class ErasureMarkerRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__(ERASURE_MARKERS_TABLE)

    async def advance(self, marker_id: str, tenant_id: str, kind: str, submitted_at: str) -> None:
        """Create the marker, or move it forward — never back — atomically.

        ``submitted_at`` is the fixed-width canonical UTC form, so the string
        comparison inside the upsert is a chronological one and two
        overlapping erasures cannot leave the older time behind.
        """
        record = {
            "id": marker_id, "tenant_id": tenant_id, "kind": kind, "submitted_at": submitted_at,
        }
        pool = await self._ensure_pool()
        if pool is None:
            current = self._store.get(marker_id)
            if current is None or str(current.get("submitted_at") or "") < submitted_at:
                self._store[marker_id] = record
            return
        await self._ensure_table()
        await pool.execute(
            f"""INSERT INTO {self.table_name} (id, data, tenant_id, created_at, updated_at)
                VALUES ($1, $2::jsonb, $3, NOW(), NOW())
                ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, updated_at = NOW()
                WHERE COALESCE({self.table_name}.data->>'submitted_at', '')
                      < EXCLUDED.data->>'submitted_at'""",
            marker_id, json.dumps(record), tenant_id,
        )


    async def lookup(self, marker_ids: list[str]) -> dict[str, dict[str, Any]]:
        """The stored markers among ``marker_ids``, in one keyed round trip."""
        pool = await self._ensure_pool()
        if pool is None:
            return {i: self._store[i] for i in marker_ids if i in self._store}
        await self._ensure_table()
        rows = await pool.fetch(
            f"SELECT id, data FROM {self.table_name} WHERE id = ANY($1::text[])",
            list(marker_ids),
        )
        found: dict[str, dict[str, Any]] = {}
        for row in rows:
            data = row["data"]
            found[row["id"]] = json.loads(data) if isinstance(data, str) else dict(data)
        return found


def tenant_fence_id(tenant_id: str) -> str:
    digest = hashlib.sha256(f"tenant|{tenant_id}".encode("utf-8")).hexdigest()
    return f"dsrm_tenant_{digest[:48]}"


async def record_tenant_erasure_fence(tenant_id: str, *, repo: Any = None) -> None:
    """Fence every later projection for a tenant being deleted.

    Account deletion removes the tenant's subject markers, but events accepted
    before the deletion can still be queued or redelivered. This durable fence
    is written first and holds no subject data: a digest of the tenant id and
    the time. It is stored outside the tenant (``tenant_id=""``), so the
    tenant's own deletion does not remove it.
    """
    if not tenant_id:
        raise ValueError("a tenant fence needs a tenant")
    repo = repo or ErasureMarkerRepository()
    await repo.insert(tenant_fence_id(tenant_id), {
        "tenant_id": "", "kind": "tenant",
        "erased_at": canonical_utc_timestamp(coerce_utc_lenient(datetime.now(timezone.utc))),
    })


def erasure_marker_id(tenant_id: str, kind: str, identifier: str) -> str:
    digest = hashlib.sha256(f"{tenant_id}|{kind}|{identifier}".encode("utf-8")).hexdigest()
    return f"dsrm_{digest[:48]}"


async def record_erasure_markers(
    tenant_id: str,
    *,
    user_id: Optional[str],
    anonymous_id: Optional[str],
    submitted_at: Any,
    repo: Any = None,
) -> int:
    """Record (or advance) the markers for one erasure request. Returns the count."""
    repo = repo or ErasureMarkerRepository()
    submitted = coerce_utc_lenient(submitted_at)
    if not tenant_id or submitted is None:
        raise ValueError("an erasure marker needs a tenant and a submission time")
    canonical = canonical_utc_timestamp(submitted)
    written = 0
    for kind, identifier in zip(_KINDS, (user_id, anonymous_id)):
        if not identifier:
            continue
        await repo.advance(erasure_marker_id(tenant_id, kind, str(identifier)), tenant_id, kind, canonical)
        written += 1
    return written


async def ensure_markers_backfilled(*, repo: Any = None, consent_repo: Any = None) -> None:
    """Write markers for erasure requests submitted before markers existed.

    Runs once per process until the durable flag exists; afterwards it is one
    cached boolean. Idempotent under concurrency (markers only advance). A
    failure raises, so the fenced write is retried rather than let through.
    """
    global _backfilled
    if _backfilled:
        return
    repo = repo or ErasureMarkerRepository()
    if await repo.find_by_id(_BACKFILL_FLAG_ID) is not None:
        _backfilled = True
        return
    if consent_repo is None:
        from repositories.repos import ConsentRepository

        consent_repo = ConsentRepository()
    offset = 0
    while True:
        page = await consent_repo.find_many(
            filters={"request_type": "erasure"}, limit=_BACKFILL_PAGE, offset=offset,
            sort_by="created_at", sort_order="asc",
        )
        for request in page:
            if request.get("tenant_id") and request.get("submitted_at"):
                await record_erasure_markers(
                    request["tenant_id"],
                    user_id=request.get("user_id"),
                    anonymous_id=request.get("anonymous_id"),
                    submitted_at=request["submitted_at"],
                    repo=repo,
                )
        if len(page) < _BACKFILL_PAGE:
            break
        offset += _BACKFILL_PAGE
    await repo.insert(_BACKFILL_FLAG_ID, {"tenant_id": "", "kind": "backfill_flag"})
    _backfilled = True


def reset_backfill_state() -> None:
    """Forget the cached backfill flag (tests)."""
    global _backfilled
    _backfilled = False


async def erasure_fences_event(
    tenant_id: str,
    *,
    user_id: Optional[str],
    anonymous_id: Optional[str],
    received_at: Any,
    repo: Any = None,
) -> bool:
    """True when an erasure for this subject covers an event received at ``received_at``.

    Matching mirrors ``AnalyticsRepository.erase_subject``: the event's
    ``user_id`` against erased user ids, and its ``anonymous_id`` against erased
    anonymous ids. An event with no parseable receive time is fenced by any
    matching erasure (fail closed). A lookup failure raises, so the caller
    retries rather than writes.
    """
    if not tenant_id:
        return False
    repo = repo or ErasureMarkerRepository()
    await ensure_markers_backfilled(repo=repo)
    wanted = {
        kind: erasure_marker_id(tenant_id, kind, str(identifier))
        for kind, identifier in zip(_KINDS, (user_id, anonymous_id)) if identifier
    }
    # One keyed read covers the tenant fence and every subject marker.
    found = await repo.lookup([tenant_fence_id(tenant_id), *wanted.values()])
    if tenant_fence_id(tenant_id) in found:
        return True  # the tenant was deleted: nothing more is projected for it
    received: Optional[datetime] = coerce_utc_lenient(received_at)
    for marker_id in wanted.values():
        marker = found.get(marker_id)
        if marker is None or marker.get("tenant_id") != tenant_id:
            continue
        if received is None:
            return True
        submitted = coerce_utc_lenient(marker.get("submitted_at"))
        if submitted is None or submitted >= received:
            return True
    return False


__all__ = [
    "ERASURE_MARKERS_TABLE",
    "ErasureMarkerRepository",
    "ensure_markers_backfilled",
    "erasure_fences_event",
    "erasure_marker_id",
    "record_erasure_markers",
    "record_tenant_erasure_fence",
    "reset_backfill_state",
    "tenant_fence_id",
]
