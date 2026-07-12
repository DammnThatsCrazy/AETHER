"""Aether Runtime — role entrypoint (PR 4 / FT-4).

    python -m services.runtime.run_role <role>

Boots exactly one runtime role:

- ``api``  → the FastAPI HTTP server (``uvicorn main:app``). With
  ``WORKER_ROLES_ENABLED`` on, the API lifespan starts no supervised workers or
  stream consumers (see ``main.py``); this process is the pure request server.
- a worker role (``stream-worker``, ``outbox-relay``, ``materializer``,
  ``maintenance``, …) → the supervised :class:`WorkerSupervisor` filtered to the
  :class:`WorkerSpec` subset that role owns (see
  ``services/runtime/roles.py::ROLE_TO_SPEC_NAMES``).
- ``all`` → every supervised worker in one process (the single-process default;
  identical worker set to the historical lifespan).

The role is validated, exported as ``AETHER_ROLE`` for the process, and booted.
Heavy imports (uvicorn, the resource registry) are performed lazily inside the
dispatch functions so this module imports cleanly with no side effects.

Deferred (see ledger FT-4): dedicated supervised loops + consumer attachment for
the identity/graph/measurement worker roles — those currently ride the shared
stream consumer. This entrypoint's fully-wired path today is ``api`` and the
supervised-spec worker roles; consumer-only roles start an (empty) supervisor.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from services.runtime.roles import ALL_ROLES, is_valid_role


def _run_api() -> int:
    """Boot the FastAPI HTTP server (mirrors main.py's __main__ block)."""
    import uvicorn

    from config.settings import settings

    uvicorn.run(
        "main:app",
        host=os.environ.get("AETHER_API_HOST", "0.0.0.0"),
        port=int(os.environ.get("AETHER_API_PORT", "8000")),
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
    return 0


async def _run_workers(role: str) -> int:
    """Boot the supervised worker subset owned by ``role`` and run forever."""
    from config.settings import settings
    from dependencies.providers import get_registry
    from services.runtime import (
        WorkerSupervisor,
        build_worker_specs,
        specs_for_role,
    )

    registry = get_registry()
    await registry.startup()

    all_specs = build_worker_specs(registry=registry, settings=settings)
    specs = specs_for_role(role, all_specs)

    supervisor = WorkerSupervisor()
    for spec in specs:
        supervisor.register(spec)
    await supervisor.start_all()

    print(
        f"[run_role] role={role} started {len(specs)} supervised worker(s): "
        f"{', '.join(s.name for s in specs) or '(none — deferred/consumer-only)'}",
        flush=True,
    )

    stop = asyncio.Event()
    try:
        await stop.wait()  # run until cancelled / signalled
    finally:
        await supervisor.stop_all()
        await registry.shutdown()
    return 0


def run(role: str) -> int:
    """Validate ``role``, export it, and dispatch to the matching boot path.

    Returns a process exit code. Raises ``SystemExit`` via the CLI wrapper on an
    invalid role; ``run`` itself returns non-zero so it stays unit-testable.
    """
    if not is_valid_role(role):
        print(
            f"[run_role] invalid role {role!r}. Valid roles: "
            f"{', '.join(sorted(ALL_ROLES))}",
            file=sys.stderr,
            flush=True,
        )
        return 2

    os.environ["AETHER_ROLE"] = role

    if role == "api":
        return _run_api()
    return asyncio.run(_run_workers(role))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m services.runtime.run_role",
        description="Boot a single Aether runtime role.",
    )
    parser.add_argument(
        "role",
        choices=sorted(ALL_ROLES),
        help="Which runtime role to boot (api | all | a worker role).",
    )
    args = parser.parse_args(argv)
    return run(args.role)


if __name__ == "__main__":  # pragma: no cover — process entrypoint
    raise SystemExit(main())
