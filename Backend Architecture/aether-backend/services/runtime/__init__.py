"""Aether Runtime — supervised background worker orchestration.

Exposes the worker supervisor (generic crash/restart/backoff machinery) and
the spec builder that maps the application's long-running loop workers onto
supervised ``WorkerSpec`` entries.
"""

from services.runtime.supervisor import WorkerSpec, WorkerSupervisor
from services.runtime.specs import build_worker_specs

__all__ = ["WorkerSpec", "WorkerSupervisor", "build_worker_specs"]
