"""
Aether Service — Jobs Platform Handler Registry

Job handlers are async callables registered per job_type. The JobWorker
resolves the handler for a claimed job from HANDLER_REGISTRY and invokes it
with the job payload plus a JobContext (heartbeat + progress-event hooks).

Handler contract:

    @register_handler("exports.generate", tenant_invocable=True)
    async def generate_export(payload: dict, ctx: JobContext) -> JobOutcome:
        ...
        return JobOutcome(status="succeeded", result={"rows": 42})

- A handler MUST return a JobOutcome whose status is one of
  "succeeded" | "partially_succeeded" | "failed".
- A handler MAY call ``await ctx.heartbeat()`` during long work; the call
  extends the lease, returns False when the lease was lost to another
  worker, and raises JobCancelled (from services.jobs.worker) when an
  operator requested cancellation.
- ``await ctx.emit_event("my.progress", {...})`` appends a job_events row
  for timeline visibility (best-effort, never raises).

TENANT_INVOCABLE lists job types tenants may POST directly via
``POST /v1/jobs``; all other registered types can only be enqueued
internally (schedules, other services, Kyber operators).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

# Registered job handlers keyed by job_type.
HANDLER_REGISTRY: dict[str, "JobHandler"] = {}

# Job types tenants may enqueue directly through the public jobs API.
TENANT_INVOCABLE: set[str] = set()


@dataclass
class JobContext:
    """Per-execution context handed to a job handler."""

    job_id: str
    tenant_id: str
    correlation_id: str
    # The executing worker's lease-owner identity (M8-B3). Handlers pass it to
    # lease-guarded mutations (jobs_repo.update_payload) so a stale worker whose
    # lease was reaped cannot overwrite the new owner's checkpoint.
    worker_id: str
    # Extends the lease; returns False if the lease was lost, raises
    # services.jobs.worker.JobCancelled when cancellation was requested.
    heartbeat: Callable[[], Awaitable[bool]]
    # Appends a custom job_events row (event_type, payload) — best-effort.
    emit_event: Callable[[str, dict], Awaitable[None]]


@dataclass
class JobOutcome:
    """Result a handler returns to the worker."""

    status: str  # "succeeded" | "partially_succeeded" | "failed"
    result: dict
    error: str | None = None


JobHandler = Callable[[dict, JobContext], Awaitable[JobOutcome]]

# Outcome statuses a handler is allowed to return.
VALID_OUTCOME_STATUSES: set[str] = {"succeeded", "partially_succeeded", "failed"}


def register_handler(job_type: str, *, tenant_invocable: bool = False) -> Callable:
    """Decorator registering ``fn`` as the handler for ``job_type``.

    Duplicate registrations are a programming error and raise ValueError —
    silently overwriting a handler would make dispatch order-dependent.
    """
    if not job_type or not isinstance(job_type, str):
        raise ValueError("job_type must be a non-empty string")

    def decorator(fn: JobHandler) -> JobHandler:
        if job_type in HANDLER_REGISTRY:
            raise ValueError(f"Job handler already registered for job_type {job_type!r}")
        HANDLER_REGISTRY[job_type] = fn
        if tenant_invocable:
            TENANT_INVOCABLE.add(job_type)
        return fn

    return decorator


def unregister_handler(job_type: str) -> None:
    """Test helper: remove a registered handler (no-op when absent)."""
    HANDLER_REGISTRY.pop(job_type, None)
    TENANT_INVOCABLE.discard(job_type)
