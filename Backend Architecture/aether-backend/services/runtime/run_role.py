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
- an execution group (``lean-worker``) → every logical worker role packed into
  one process. Consolidation is a *packing* decision only: each hosted role
  keeps its own queue, consumer group, DLQ, retry policy, backpressure budget,
  metrics label and independent crash/restart behaviour. Nothing runs serially.
- ``all`` → every supervised worker in one process (the single-process default;
  identical worker set to the historical lifespan).

The role is validated, exported as ``AETHER_ROLE`` for the process, and booted.
Heavy imports (uvicorn, the resource registry) are performed lazily inside the
dispatch functions so this module imports cleanly with no side effects.

Consumer-attached roles get one ``EventConsumer`` per distinct
``(role, group_id)`` via ``services/runtime/consumer_runner.py``, and each
receive loop is registered with the same :class:`WorkerSupervisor` as the loop
workers so it inherits crash → metric → backoff-restart isolation.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
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


def _stamp_owning_roles(specs: list, booted_as: str) -> list:
    """Return ``specs`` with each entry labelled with its owning logical role.

    ``build_worker_specs`` is role-agnostic, and under an execution group the
    process token (``lean-worker``) is *not* the owning role. Stamping the real
    owner here is what keeps a consolidated process per-role observable: the
    supervisor then carries it into every state entry, crash log and metric.
    Specs no role claims fall back to the booted token rather than being
    silently attributed to a role that does not own them.
    """
    from services.runtime.roles import owning_role

    return [
        dataclasses.replace(spec, role=owning_role(spec.name) or booted_as)
        for spec in specs
    ]


def _log_role_topology(role: str, specs: list, runners: list) -> None:
    """Print the per-role startup banner and emit per-spec registration metrics.

    A consolidated process must be able to answer "is measurement-worker
    running?" from its own logs, so the banner is grouped by owning role rather
    than printed as one flat list.
    """
    from shared.logger.logger import metrics

    from services.runtime.roles import roles_in

    by_role: dict[str, dict[str, list[str]]] = {
        member: {"workers": [], "consumers": []} for member in sorted(roles_in(role))
    }
    for spec in specs:
        entry = by_role.setdefault(spec.role or role, {"workers": [], "consumers": []})
        entry["workers"].append(spec.name)
        metrics.increment(
            "runtime_worker_registered",
            labels={"role": spec.role or role, "worker": spec.name, "booted_as": role},
        )
    for runner in runners:
        entry = by_role.setdefault(runner.role, {"workers": [], "consumers": []})
        entry["consumers"].append(f"{runner.group_id}[{','.join(runner.spec_names)}]")
        metrics.increment(
            "runtime_consumer_registered",
            labels={"role": runner.role, "group": runner.group_id, "booted_as": role},
        )

    consolidated = len(by_role) > 1
    print(
        f"[run_role] booted_as={role} "
        f"{'consolidated' if consolidated else 'dedicated'} "
        f"roles={len(by_role)} workers={len(specs)} consumer_pipelines={len(runners)}",
        flush=True,
    )
    for member in sorted(by_role):
        entry = by_role[member]
        print(
            f"[run_role]   role={member} "
            f"workers={', '.join(sorted(entry['workers'])) or '(none)'} "
            f"consumers={', '.join(sorted(entry['consumers'])) or '(none)'}",
            flush=True,
        )
    for runner in runners:
        status = runner.status()
        print(
            f"[run_role]   consumer role={status['role']} group={status['group_id']} "
            f"mode={status['mode']} queue={status['queue_url'] or '(none)'} "
            f"max_concurrent={status['max_concurrent']} "
            f"drain_timeout_s={runner.drain_timeout_s}",
            flush=True,
        )


async def _shutdown(role: str, registry, supervisor, runners: list) -> None:
    """Drain consumers, stop supervised workers, then close shared resources.

    Ordering is the pre-existing one and is deliberate:

    1. **Drain every consumer runner** — stop acquisition and let in-flight
       handlers finish, each against its own group's ``drain_timeout_s``. Every
       role is drained (concurrently) before anything is cancelled, so a slow
       role cannot cause a faster one to be killed mid-handler.
    2. **Stop the supervisor** — cancels the now-idle receive loops and the
       loop workers.
    3. **Close the registry** — producer/cache/graph/pool, last, because
       draining handlers still need them.
    """
    from services.runtime.consumer_runner import drain_consumer_runners

    reports: list = []
    try:
        reports = await drain_consumer_runners(runners)
    except Exception as exc:  # pragma: no cover — defensive
        print(f"[run_role] role={role} consumer drain error: {exc}", flush=True)
    for report in reports:
        print(
            f"[run_role] drain role={report['role']} group={report['group_id']} "
            f"drained={report['drained']} "
            f"in_flight_remaining={report['in_flight_remaining']}",
            flush=True,
        )

    await supervisor.stop_all()

    # Per-role exit health: a role whose worker exhausted its restarts must not
    # disappear into an otherwise clean shutdown.
    for member, health in sorted(supervisor.status_by_role().items()):
        if not health["healthy"]:
            print(
                f"[run_role] role={member} UNHEALTHY at shutdown "
                f"failed={', '.join(health['failed'])}",
                flush=True,
            )

    await registry.shutdown()


async def _run_workers(role: str) -> int:
    """Boot the supervised worker subset owned by ``role`` and run forever."""
    from config.settings import settings
    from dependencies.providers import get_registry
    from services.runtime import (
        WorkerSupervisor,
        build_worker_specs,
        consumer_specs_for_role,
        specs_for_role,
    )
    from services.runtime.consumer_runner import (
        build_consumer_runners,
        start_consumer_runners,
    )

    registry = get_registry()
    await registry.startup()

    all_specs = build_worker_specs(registry=registry, settings=settings)
    specs = _stamp_owning_roles(specs_for_role(role, all_specs), role)
    consumer_specs = consumer_specs_for_role(role, settings)

    # One EventConsumer per distinct (role, group_id): each binds its own queue,
    # pins its own consumer group, and enforces its own backpressure. A single
    # shared consumer cannot express that — see consumer_runner.py.
    runners = build_consumer_runners(registry, consumer_specs)

    supervisor = WorkerSupervisor()
    try:
        await start_consumer_runners(runners)

        for spec in specs:
            supervisor.register(spec)
        # Consumer receive loops are supervised alongside the loop workers, so
        # one logical role's crash is counted, logged with its role label, and
        # restarted with backoff without touching the other roles' tasks.
        for runner in runners:
            supervisor.register(runner.worker_spec())
        await supervisor.start_all()
    except Exception:
        # Boot failed after the registry came up (a required consumer could not
        # bind, or a required worker failed its first start under the
        # supervisor's fail-closed policy). Release what we did acquire, then
        # let the failure propagate — never come up half-started.
        await _shutdown(role, registry, supervisor, runners)
        raise

    _log_role_topology(role, specs, runners)

    stop = asyncio.Event()
    try:
        await stop.wait()  # run until cancelled / signalled
    finally:
        await _shutdown(role, registry, supervisor, runners)
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
