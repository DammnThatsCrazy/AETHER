"""Erasure fence for asynchronous projections of subject data.

Consent is enforced when an event is accepted, but projections (the analytics
event store) run later from an at-least-once queue. An event accepted before a
DSR erasure can still be queued, or be redelivered, after the erasure job has
deleted the subject's rows — and writing it then silently undoes the erasure.

``submit_dsr`` records an **erasure marker** per erased identifier (the DSR's
``user_id`` and optional ``anonymous_id``) before it enqueues the erasure job.
A marker is keyed by a digest of ``(tenant_id, kind, identifier)`` and stores
only the latest erasure's ``submitted_at`` — never the identifier itself — so
the fence costs one primary-key read per identifier on the event, instead of
scanning consent records for every projected event.

An event is fenced when a matching erasure was submitted at or after the event
was received, i.e. the erasure was meant to cover it. Activity received after
the request is new data and is not fenced.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Optional

from repositories.repos import BaseRepository
from shared.temporal.instant import coerce_utc_lenient, to_iso_utc

ERASURE_MARKERS_TABLE = "dsr_erasure_markers"
_KINDS = ("user_id", "anonymous_id")


class ErasureMarkerRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__(ERASURE_MARKERS_TABLE)


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
    written = 0
    for kind, identifier in zip(_KINDS, (user_id, anonymous_id)):
        if not identifier:
            continue
        marker_id = erasure_marker_id(tenant_id, kind, str(identifier))
        existing = await repo.find_by_id(marker_id)
        if existing is None:
            await repo.insert(marker_id, {
                "tenant_id": tenant_id,
                "kind": kind,
                "submitted_at": to_iso_utc(submitted),
            })
        else:
            previous = coerce_utc_lenient(existing.get("submitted_at"))
            if previous is None or submitted > previous:
                await repo.update(marker_id, {"submitted_at": to_iso_utc(submitted)})
        written += 1
    return written


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
    if not tenant_id or not (user_id or anonymous_id):
        return False
    repo = repo or ErasureMarkerRepository()
    received: Optional[datetime] = coerce_utc_lenient(received_at)
    for kind, identifier in zip(_KINDS, (user_id, anonymous_id)):
        if not identifier:
            continue
        marker = await repo.find_by_id(erasure_marker_id(tenant_id, kind, str(identifier)))
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
    "erasure_fences_event",
    "erasure_marker_id",
    "record_erasure_markers",
]
