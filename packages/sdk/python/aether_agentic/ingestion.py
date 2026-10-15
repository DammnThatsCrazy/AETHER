"""Aether Agentic Python SDK — ingestion batch-health parsing (Truth Kernel §2.8).

The Python SDK is an observation-envelope builder rather than a batching HTTP
client, so it does not maintain a local queue. It can, however, parse the
per-batch health counters returned by ``POST /v1/batch`` (the backend
BatchResponse, mirrored in ``packages/shared/ingestion-contract.ts``) into a
uniform :class:`BatchHealth`, matching the ``accepted`` / ``duplicate`` /
``rejected`` / ``dropped_by_consent`` / ``queue_depth`` shape surfaced by the
web, server, and native SDKs.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class BatchHealth:
    """Per-batch ingestion health counters.

    ``accepted`` / ``duplicate`` / ``rejected`` are parsed from the backend
    BatchResponse. ``dropped_by_consent`` and ``queue_depth`` are caller-supplied
    SDK-side truths (a consent gate ahead of ingestion, and the local backlog).
    """

    accepted: int = 0
    duplicate: int = 0
    rejected: int = 0
    dropped_by_consent: int = 0
    queue_depth: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):  # bool is an int subclass — reject it explicitly
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def parse_batch_health(
    response: Mapping[str, Any] | None,
    *,
    dropped_by_consent: int = 0,
    queue_depth: int = 0,
) -> BatchHealth:
    """Parse a ``/v1/batch`` response body into a :class:`BatchHealth`.

    The backend BatchResponse uses ``accepted`` / ``duplicates`` / ``rejected``;
    the singular ``duplicate`` is also accepted. Missing counters default to 0.
    ``dropped_by_consent`` and ``queue_depth`` are passed through from the caller
    (the Python SDK does not consent-gate or queue locally).
    """
    body: Mapping[str, Any] = response if isinstance(response, Mapping) else {}
    accepted = _as_int(body.get("accepted")) or 0
    duplicate = _as_int(body.get("duplicate"))
    if duplicate is None:
        duplicate = _as_int(body.get("duplicates")) or 0
    rejected = _as_int(body.get("rejected")) or 0
    return BatchHealth(
        accepted=accepted,
        duplicate=duplicate,
        rejected=rejected,
        dropped_by_consent=max(0, int(dropped_by_consent)),
        queue_depth=max(0, int(queue_depth)),
    )
