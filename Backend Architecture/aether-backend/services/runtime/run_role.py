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

Consumer-only roles attach their canonical ``ConsumerSpec`` entries and start
the broker consumer even when they own no loop-style ``WorkerSpec`` entries.
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
        attach_consumer_specs,
        build_worker_specs,
        consumer_specs_for_role,
        specs_for_role,
    )

    registry = get_registry()
    await registry.startup()

    all_specs = build_worker_specs(registry=registry, settings=settings)
    specs = specs_for_role(role, all_specs)
    consumer_specs = consumer_specs_for_role(role, settings)
    attach_consumer_specs(registry, consumer_specs)
    if consumer_specs:
        await registry.consumer.start()

    supervisor = WorkerSupervisor()
    for spec in specs:
        supervisor.register(spec)
    await supervisor.start_all()

    print(
        f"[run_role] role={role} started {len(specs)} supervised worker(s) and "
        f"{len(consumer_specs)} consumer pipeline(s): "
        f"{', '.join(s.name for s in specs + consumer_specs) or '(none)'}",
        flush=True,
    )

    stop = asyncio.Event()
    try:
        await stop.wait()  # run until cancelled / signalled
    finally:
        # Stop acquisition first; EventConsumer completes the currently
        # awaited handler before its loop observes shutdown.
        await registry.consumer.stop()
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
        nargs="?",
        default=None,
        choices=sorted(ALL_ROLES),
        help=(
            "Which runtime role to boot (api | all | a worker role). "
            "When omitted, falls back to the AETHER_ROLE environment variable."
        ),
    )
    args = parser.parse_args(argv)
    # Explicit positional wins; AETHER_ROLE is the deployment-env fallback so
    # task/compose definitions that only export the variable still boot the
    # role they declare. run() re-validates either source.
    role = args.role or os.environ.get("AETHER_ROLE", "")
    if not role:
        parser.error("role argument required (or set AETHER_ROLE)")
    return run(role)


if __name__ == "__main__":  # pragma: no cover — process entrypoint
    raise SystemExit(main())
