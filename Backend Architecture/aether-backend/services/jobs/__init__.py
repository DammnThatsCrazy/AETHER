"""
Aether Service — Jobs Platform (durable Postgres job control plane)

Modules:
    models      JobStatus + policy vocabularies (stdlib-only)
    handlers    HANDLER_REGISTRY / register_handler / JobContext / JobOutcome
    service     JobsService + get_jobs_service()
    worker      JobWorker / LeaseSweeper + build_job_worker_coro /
                build_lease_sweeper_coro (supervisor factories)
    scheduler   JobScheduler + build_schedule_tick_coro (supervisor factory)
    routes      tenant router  (mounted by main.py, not here)
    kyber_routes  operator router (mounted by main.py, not here)

Only the dependency-light core is re-exported here; worker/scheduler/routes
are imported explicitly by their consumers (they pull croniter / the event
bus / FastAPI, which handler authors and tests do not need).
"""

from services.jobs.handlers import (
    HANDLER_REGISTRY,
    TENANT_INVOCABLE,
    JobContext,
    JobHandler,
    JobOutcome,
    register_handler,
)
from services.jobs.models import JobStatus

__all__ = [
    "HANDLER_REGISTRY",
    "TENANT_INVOCABLE",
    "JobContext",
    "JobHandler",
    "JobOutcome",
    "JobStatus",
    "JobsService",
    "get_jobs_service",
    "register_handler",
]


def __getattr__(name: str):
    # Lazy re-export: service.py imports repositories.jobs_repo, which itself
    # imports services.jobs.models — an eager import here would make loading
    # repositories.jobs_repo circular (jobs_repo → models → __init__ →
    # service → jobs_repo). PEP 562 keeps `from services.jobs import
    # get_jobs_service` working without the cycle.
    if name in ("JobsService", "get_jobs_service"):
        from services.jobs import service as _service_mod

        return getattr(_service_mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
