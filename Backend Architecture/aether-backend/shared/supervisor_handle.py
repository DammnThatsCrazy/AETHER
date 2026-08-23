"""Process-wide WorkerSupervisor handle for observability seams.

The ``WorkerSupervisor`` (services/runtime/supervisor.py) instance lives on
``app.state.worker_supervisor`` — owned by the FastAPI lifespan. Observability
aggregators that run *outside* the request/state wiring (the Kyber fleet-health
aggregate, the reliability heartbeat bridge) need a stable way to reach the
same instance without threading an ``app`` reference through every call site.

This module is that handle: a single, deliberately dumb process-global pointer
the lifespan sets once and the seams read. It never constructs a supervisor
and it holds no lifecycle state — the supervisor remains the one-shot object
``app.state`` owns. Before the lifespan sets it, reads return ``None``, which
callers must treat as "no supervisor observed this process" (an honest unknown,
distinct from "workers are down").
"""

from __future__ import annotations

from typing import Any, Optional

_supervisor: Any = None


def set_worker_supervisor(supervisor: Any) -> None:
    """Bind the process's WorkerSupervisor instance (call once, in lifespan)."""
    global _supervisor
    _supervisor = supervisor


def get_worker_supervisor() -> Any:
    """The bound WorkerSupervisor, or None before the lifespan sets it."""
    return _supervisor


def clear_worker_supervisor() -> None:
    """Detach the handle (tests / shutdown only)."""
    global _supervisor
    _supervisor = None


__all__ = ["set_worker_supervisor", "get_worker_supervisor", "clear_worker_supervisor"]
