"""Aether Runtime — supervised background worker orchestration.

Exposes the worker supervisor (generic crash/restart/backoff machinery) and
the spec builder that maps the application's long-running loop workers onto
supervised ``WorkerSpec`` entries.
"""

from services.runtime.supervisor import WorkerSpec, WorkerSupervisor
from services.runtime.specs import build_worker_specs
from services.runtime.consumer_specs import (
    CONSUMER_SPECS,
    ConsumerSpec,
    attach_consumer_specs,
    consumer_specs_for_role,
)
from services.runtime.roles import (
    ALL_ROLES,
    CONSUMER_ROLES,
    ROLE_TO_SPEC_NAMES,
    WORKER_ROLES,
    is_valid_role,
    is_worker_role,
    should_start_consumers,
    should_start_workers,
    specs_for_role,
)

__all__ = [
    "WorkerSpec",
    "WorkerSupervisor",
    "build_worker_specs",
    "ConsumerSpec",
    "CONSUMER_SPECS",
    "attach_consumer_specs",
    "consumer_specs_for_role",
    "ALL_ROLES",
    "CONSUMER_ROLES",
    "ROLE_TO_SPEC_NAMES",
    "WORKER_ROLES",
    "is_valid_role",
    "is_worker_role",
    "should_start_consumers",
    "should_start_workers",
    "specs_for_role",
]
