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
    apply_consumer_limits,
    attach_consumer_specs,
    consumer_specs_for_role,
    drain_timeout_for,
)
from services.runtime.consumer_runner import (
    ConsumerRunner,
    build_consumer_runners,
    consumer_runner_status,
    drain_consumer_runners,
    resolve_queue_url,
    role_queue_urls,
    start_consumer_runners,
)
from services.runtime.roles import (
    ALL_ROLES,
    CONSUMER_ROLES,
    EXECUTION_GROUPS,
    ROLE_TO_SPEC_NAMES,
    WORKER_ROLES,
    is_execution_group,
    is_valid_role,
    is_worker_role,
    owning_role,
    roles_in,
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
    "apply_consumer_limits",
    "attach_consumer_specs",
    "consumer_specs_for_role",
    "drain_timeout_for",
    "ConsumerRunner",
    "build_consumer_runners",
    "consumer_runner_status",
    "drain_consumer_runners",
    "resolve_queue_url",
    "role_queue_urls",
    "start_consumer_runners",
    "ALL_ROLES",
    "CONSUMER_ROLES",
    "EXECUTION_GROUPS",
    "ROLE_TO_SPEC_NAMES",
    "WORKER_ROLES",
    "is_execution_group",
    "is_valid_role",
    "is_worker_role",
    "owning_role",
    "roles_in",
    "should_start_consumers",
    "should_start_workers",
    "specs_for_role",
]
