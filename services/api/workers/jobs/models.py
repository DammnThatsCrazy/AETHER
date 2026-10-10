"""
Aether Service — Jobs Platform Models

Status vocabulary and policy constants for the durable Postgres job control
plane (tables: jobs / job_events / job_schedules, see alembic migration
20260713_platform_control_plane).

This module is intentionally dependency-light (stdlib only) so unit tests and
workers can import it without FastAPI/pydantic installed.
"""

from __future__ import annotations

from enum import Enum


class JobStatus(str, Enum):
    """Lifecycle states for a durable job row."""

    ACCEPTED = "accepted"
    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    PARTIALLY_SUCCEEDED = "partially_succeeded"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


# Terminal states: no further transitions are legal from these.
TERMINAL_STATUSES: set[str] = {
    JobStatus.SUCCEEDED.value,
    JobStatus.PARTIALLY_SUCCEEDED.value,
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
    JobStatus.EXPIRED.value,
}

# States that still occupy the pipeline (used for schedule overlap checks).
ACTIVE_STATUSES: set[str] = {
    JobStatus.ACCEPTED.value,
    JobStatus.QUEUED.value,
    JobStatus.RUNNING.value,
    JobStatus.RETRYING.value,
    JobStatus.CANCEL_REQUESTED.value,
}

# States a worker can claim from.
CLAIMABLE_STATUSES: set[str] = {
    JobStatus.QUEUED.value,
    JobStatus.RETRYING.value,
}


class MisfirePolicy(str, Enum):
    """What to do when a schedule is more than one interval behind."""

    FIRE_ONCE = "fire_once"  # coalesce all missed fires into a single run
    SKIP = "skip"            # drop the missed fires and advance


class OverlapPolicy(str, Enum):
    """What to do when a schedule fires while a previous run is still active."""

    SKIP = "skip"    # do not enqueue while an active job for the schedule exists
    ALLOW = "allow"  # enqueue regardless of in-flight jobs


MISFIRE_POLICIES: set[str] = {p.value for p in MisfirePolicy}
OVERLAP_POLICIES: set[str] = {p.value for p in OverlapPolicy}

# A schedule is auto-disabled after this many consecutive tick failures.
MAX_SCHEDULE_CONSECUTIVE_FAILURES = 10
