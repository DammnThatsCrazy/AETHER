"""GET /v1/ready must grade worker failures instead of ignoring them.

The readiness probe used to mark every worker check ``advisory: True`` and drop
advisory checks from the aggregate, so a process whose entire worker fleet had
exhausted its restart budget still answered 200 — and ``deploy.yml`` gates an
ECS rollout on exactly that response. These tests pin the replacement contract:

- a **release-critical** role failure (``roles.py::RELEASE_CRITICAL_ROLES``)
  fails the whole probe;
- a **non-critical** role failure leaves the probe ready and marks only its own
  capability unavailable;
- a role this process is supposed to supervise but cannot see is a failure, not
  a pass — including the case where the supervisor itself is missing;
- the historical "every worker failed → 200" outcome can no longer occur.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from config.settings import Environment
from services.gateway.readiness import expected_worker_roles, readiness_report
from services.runtime.roles import RELEASE_CRITICAL_ROLES, WORKER_ROLES
from services.runtime.supervisor import WorkerSpec, WorkerSupervisor

# One representative worker name per role, taken from ROLE_TO_SPEC_NAMES so the
# owning-role fallback resolves them exactly as it does for the real specs the
# FastAPI lifespan registers (which carry no explicit role).
CRITICAL_WORKER = "event_outbox_relay"        # outbox-relay   — release-critical
CRITICAL_ROLE = "outbox-relay"
NONCRITICAL_WORKER = "retention_sweep"        # maintenance    — not critical
NONCRITICAL_ROLE = "maintenance"


class _StubResource:
    """Healthy cache/producer stand-in: readiness must fail on workers alone."""

    mode = "stub"

    async def health_check(self) -> bool:
        return True


def _registry() -> SimpleNamespace:
    return SimpleNamespace(cache=_StubResource(), producer=_StubResource())


def _settings(role: str = "all") -> SimpleNamespace:
    """Local settings so only the worker checks can move the verdict.

    Local skips migrations and auth_config, and in-memory repositories make the
    database check pass, which isolates the behaviour under test.
    """
    return SimpleNamespace(
        env=Environment.LOCAL,
        auth=SimpleNamespace(jwt_secret=""),
        runtime=SimpleNamespace(aether_role=role, worker_roles_enabled=True),
    )


async def _healthy_forever() -> None:
    await asyncio.Event().wait()


async def _crashes() -> None:
    raise RuntimeError("worker is dead")


async def _supervisor_with(failed: tuple[str, ...], healthy: tuple[str, ...] = ()):
    """Start a supervisor where ``failed`` exhaust their restarts immediately."""
    supervisor = WorkerSupervisor(environment=Environment.LOCAL)
    for name in failed:
        supervisor.register(
            WorkerSpec(name=name, factory=_crashes, max_restarts=0, backoff_base_s=0.001)
        )
    for name in healthy:
        supervisor.register(WorkerSpec(name=name, factory=_healthy_forever))
    await supervisor.start_all()
    # Guard tasks are created by start_all but have not been scheduled yet, so
    # settle every worker into its steady state before probing. A probe issued
    # in that window legitimately sees "stopped" and fails closed.
    for _ in range(400):
        states = {n: i["state"] for n, i in supervisor.status().items()}
        if all(states[n] == "failed" for n in failed) and all(
            states[n] == "running" for n in healthy
        ):
            break
        await asyncio.sleep(0.005)
    return supervisor


def _status_code(ready: bool) -> int:
    """The status routes.py derives from the report (200 ready / 503 not)."""
    return 200 if ready else 503


# ── the defect: all workers failed used to be a 200 ───────────────────────────


@pytest.mark.asyncio
async def test_every_worker_failed_can_no_longer_return_200():
    """The exact pre-existing behaviour this change removes."""
    supervisor = await _supervisor_with(
        failed=(CRITICAL_WORKER, "event_replay", "kyber_graph_projector",
                NONCRITICAL_WORKER),
    )
    try:
        ready, report = await readiness_report(_registry(), supervisor, _settings())
    finally:
        await supervisor.stop_all()

    assert all(
        info["state"] == "failed" for info in supervisor.status().values()
    ), "precondition: every registered worker must have failed"
    assert ready is False
    assert _status_code(ready) == 503
    workers = report["checks"]["workers"]
    assert workers["status"] == "failed"
    # The mechanism that made this a 200 is gone, not merely inverted.
    assert "advisory" not in workers
    assert not any(check.get("advisory") for check in report["checks"].values())


# ── release-critical failure fails the whole probe ────────────────────────────


@pytest.mark.asyncio
async def test_failed_critical_worker_makes_ready_non_200():
    supervisor = await _supervisor_with(
        failed=(CRITICAL_WORKER,), healthy=(NONCRITICAL_WORKER,),
    )
    try:
        ready, report = await readiness_report(
            _registry(), supervisor, _settings(role=CRITICAL_ROLE),
        )
    finally:
        await supervisor.stop_all()

    assert ready is False
    assert _status_code(ready) == 503
    workers = report["checks"]["workers"]
    assert workers["status"] == "failed"
    assert workers["critical_failures"] == [CRITICAL_ROLE]
    assert workers["roles"][CRITICAL_ROLE]["state"] == "failed"
    assert workers["roles"][CRITICAL_ROLE]["available"] is False

    capability = workers["roles"][CRITICAL_ROLE]["capability"]
    assert report["capabilities"][capability]["available"] is False
    assert report["capabilities"][capability]["release_critical"] is True


# ── non-critical failure degrades one capability only ─────────────────────────


@pytest.mark.asyncio
async def test_failed_non_critical_worker_keeps_200_but_marks_capability_down():
    supervisor = await _supervisor_with(
        failed=(NONCRITICAL_WORKER,), healthy=(CRITICAL_WORKER,),
    )
    try:
        ready, report = await readiness_report(
            _registry(), supervisor, _settings(role=NONCRITICAL_ROLE),
        )
    finally:
        await supervisor.stop_all()

    assert ready is True
    assert _status_code(ready) == 200
    workers = report["checks"]["workers"]
    assert workers["status"] == "degraded"
    assert workers["critical_failures"] == []
    assert workers["degraded_roles"] == [NONCRITICAL_ROLE]

    capability = workers["roles"][NONCRITICAL_ROLE]["capability"]
    assert report["capabilities"][capability]["available"] is False
    assert report["capabilities"][capability]["release_critical"] is False
    assert report["capabilities"][capability]["state"] == "failed"
    # The healthy critical role is still reported as serving its capability.
    assert report["capabilities"][
        workers["roles"][CRITICAL_ROLE]["capability"]
    ]["available"] is True


# ── absence of signal is not health ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_supervisor_fails_when_worker_roles_are_expected():
    ready, report = await readiness_report(_registry(), None, _settings(role="all"))

    assert ready is False
    workers = report["checks"]["workers"]
    assert workers["status"] == "failed"
    assert set(workers["critical_failures"]) & RELEASE_CRITICAL_ROLES
    for role in workers["critical_failures"]:
        assert workers["roles"][role]["state"] == "unknown"


@pytest.mark.asyncio
async def test_expected_critical_role_with_no_registered_worker_is_unknown():
    """A hosted role the supervisor cannot see must not read as healthy."""
    supervisor = await _supervisor_with(failed=(), healthy=(NONCRITICAL_WORKER,))
    try:
        ready, report = await readiness_report(_registry(), supervisor, _settings())
    finally:
        await supervisor.stop_all()

    workers = report["checks"]["workers"]
    assert ready is False
    assert CRITICAL_ROLE in workers["critical_failures"]
    assert workers["roles"][CRITICAL_ROLE]["state"] == "unknown"
    # The one role that IS supervised and running stays available.
    assert workers["roles"][NONCRITICAL_ROLE]["available"] is True


@pytest.mark.asyncio
async def test_pure_api_process_claims_nothing_about_workers():
    """An api-only task supervises no role, so it asserts no worker health."""
    ready, report = await readiness_report(_registry(), None, _settings(role="api"))

    assert ready is True
    assert report["checks"]["workers"]["status"] == "skipped"
    assert report["capabilities"] == {}
    assert expected_worker_roles(_settings(role="api")) == frozenset()


# ── criticality declaration ───────────────────────────────────────────────────


def test_criticality_is_declared_against_real_worker_roles():
    assert RELEASE_CRITICAL_ROLES <= WORKER_ROLES
    # Both halves must be non-empty, or the graded contract collapses back into
    # "everything blocks a release" or "nothing does".
    assert RELEASE_CRITICAL_ROLES
    assert WORKER_ROLES - RELEASE_CRITICAL_ROLES


def test_expected_roles_follow_the_booted_role():
    assert expected_worker_roles(_settings(role=NONCRITICAL_ROLE)) == frozenset(
        {NONCRITICAL_ROLE}
    )
    # An execution group is responsible for every role it packs.
    assert CRITICAL_ROLE in expected_worker_roles(_settings(role="lean-worker"))
