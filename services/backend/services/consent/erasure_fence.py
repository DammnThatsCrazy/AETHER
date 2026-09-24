"""Erasure fence for asynchronous projections of subject data.

Consent is enforced when an event is accepted, but projections (the analytics
event store) run later from an at-least-once queue. An event accepted before a
DSR erasure can still be queued, or be redelivered, after the erasure job has
deleted the subject's rows — and writing it then silently undoes the erasure.

The DSR record itself is the durable marker: ``submit_dsr`` stores every
erasure request (``request_type == "erasure"``) with its ``user_id``, optional
``anonymous_id`` and ``submitted_at`` in ``consent_records``. An event is fenced
when a matching erasure was submitted at or after the event was received, i.e.
the erasure was meant to cover it. Activity received after the request is new
data and is not fenced.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from shared.temporal.instant import coerce_utc_lenient

# Plenty for one subject; erasure requests for the same identity are rare.
_DSR_LOOKUP_LIMIT = 20


async def erasure_fences_event(
    tenant_id: str,
    *,
    user_id: Optional[str],
    anonymous_id: Optional[str],
    received_at: Any,
    repo: Any = None,
) -> bool:
    """True when an erasure DSR for this subject covers an event received at ``received_at``.

    Matching mirrors ``AnalyticsRepository.erase_subject``: the event's
    ``user_id`` against the request's ``user_id``, and the event's
    ``anonymous_id`` against the request's ``anonymous_id``. An event with no
    parseable receive time is fenced by any matching erasure (fail closed).
    """
    if not tenant_id or not (user_id or anonymous_id):
        return False
    if repo is None:
        from repositories.repos import ConsentRepository

        repo = ConsentRepository()

    received: Optional[datetime] = coerce_utc_lenient(received_at)
    lookups = []
    if user_id:
        lookups.append({"user_id": str(user_id)})
    if anonymous_id:
        lookups.append({"anonymous_id": str(anonymous_id)})

    for subject in lookups:
        requests = await repo.find_many(
            filters={"tenant_id": tenant_id, "request_type": "erasure", **subject},
            limit=_DSR_LOOKUP_LIMIT,
        )
        for request in requests:
            if received is None:
                return True
            submitted = coerce_utc_lenient(request.get("submitted_at"))
            if submitted is None or submitted >= received:
                return True
    return False
