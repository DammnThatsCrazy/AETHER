"""Durable job handler registration is shared by the API and worker processes.

A dedicated worker process (``run_role lean-worker`` hosting the maintenance
role's ``job_worker``) never runs the FastAPI lifespan. Before
``services.jobs.bootstrap`` it claimed jobs with an empty handler registry, so a
DSR erasure enqueued by the API failed as ``unknown job_type 'consent.erasure'``.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("AETHER_ENV", "local")

from services.jobs.bootstrap import register_durable_job_handlers  # noqa: E402
from services.jobs.handlers import HANDLER_REGISTRY  # noqa: E402

_ALWAYS_REGISTERED = {
    "consent.erasure",
    "export.generate",
    "export.expire_sweep",
    "import.commit",
    "import.replay",
}


def test_registers_core_handlers_idempotently():
    register_durable_job_handlers()
    first = {job_type: HANDLER_REGISTRY[job_type] for job_type in _ALWAYS_REGISTERED}
    register_durable_job_handlers()  # a second call in the same process is safe
    assert {job_type: HANDLER_REGISTRY[job_type] for job_type in _ALWAYS_REGISTERED} == first


def test_worker_processes_register_handlers_before_starting_workers():
    source = (
        Path(__file__).resolve().parents[2] / "services" / "runtime" / "run_role.py"
    ).read_text(encoding="utf-8")
    body = source[source.index("async def _run_workers"):]
    assert body.index("register_durable_job_handlers(settings)") < body.index(
        "await supervisor.start_all()"
    )
