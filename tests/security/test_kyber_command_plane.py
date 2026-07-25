"""The governed command plane, one falsifiable claim per test.

The plane's whole reason to exist is that an HTTP 200 is not success. These
tests pin the refusals that make that true — a command that cannot be verified,
approved, stepped-up or blast-radius-assessed does not run, and a command whose
postconditions fail does not report itself as verified.

Every test names a claim rather than a code path:

* three approval refusals, because a second-actor rule with a hole in it is one
  signature wearing two names;
* one idempotency claim, because the unique index on
  ``(command_type, idempotency_key)`` is worthless if the read path never
  consults it;
* one postcondition claim, because ``executed_unverified`` is the honest state
  between "the call returned" and "the system is in the state we wanted";
* one step-up claim and one blast-radius claim, because both gates fail closed
  or they are not gates;
* one drift claim, in both directions, because a declared check with no verifier
  is a postcondition that silently never runs while the spec says otherwise;
* two evidence claims — dry run and rollback plan — because a spec that demands
  them and then executes without them demands nothing.

Nothing here needs a database: the repositories fall back to shared in-memory
dicts under ``AETHER_ENV=local``. Nothing here patches a module global either;
the ops plane's own provider indirection and the dispatch instance seam are used
instead, so a test that misses its target fails rather than silently exercising
the real handler.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores  # noqa: E402
from shared.common.common import BadRequestError, ForbiddenError  # noqa: E402

from services.kyber.ops import dispatch, verification  # noqa: E402
from services.kyber.ops.command_repository import (  # noqa: E402
    command_execution_repository,
    command_repository,
)
from services.kyber.ops.commands import CommandService  # noqa: E402
from services.kyber.ops.containment import (  # noqa: E402
    OpsProviders,
    reset_ops_providers,
    set_ops_providers,
)
from services.kyber.ops.contracts import CommandRequest, CommandSpec  # noqa: E402
from services.kyber.ops.registry import COMMAND_REGISTRY, register_command  # noqa: E402

JOBS_CLASS = "services.jobs.service.JobsService"

REQUESTER = "op_requester"
APPROVER_A = "op_approver_a"
APPROVER_B = "op_approver_b"
FOUNDER_TEMPLATES = ["founder_operator"]
UNQUALIFIED_TEMPLATES = ["support_readonly"]
SESSION = "sess_kyber_1"
TENANT = "tenant_alpha"


# ── Fakes ────────────────────────────────────────────────────────────────────


class FakeBlastRadius:
    """A blast-radius assessor that answers, so the gate can be reached.

    ``containment.compute_blast_radius`` pins one entrypoint — ``for_subject`` —
    rather than probing candidate names, so this fake exposes exactly that. The
    reach it reports is what the ``blast_radius_within_declared`` verifier later
    compares the post-execution assessment against.
    """

    def __init__(self, *, node_count: int = 3) -> None:
        self.node_count = node_count
        self.calls: list[dict[str, Any]] = []

    async def for_subject(
        self,
        *,
        subject_type: str,
        subject_id: str,
        environment: Optional[str] = None,
        tenant_id: Optional[str] = None,
        **_ignored: Any,
    ) -> dict[str, Any]:
        self.calls.append({"subject_type": subject_type, "subject_id": subject_id})
        return {
            "affected_tenants": [tenant_id] if tenant_id else [],
            "affected_services": ["jobs"],
            "node_count": self.node_count,
        }


async def fake_mirror_digest(
    *, tenant_ids: Optional[list[str]] = None, environment: str = "local"
) -> str:
    """A stable Tenant Mirror digest.

    ``mirror_parity`` is now the callable itself rather than an object, so the
    fake is a plain function. A *stable* digest is the right default: a command
    that is not supposed to move tenant-visible numbers should see parity hold.
    """
    return f"digest::{','.join(sorted(tenant_ids or ()))}::{environment}"


class FakeStepUp:
    """A step-up service with a fixed verdict."""

    def __init__(self, *, fresh: bool) -> None:
        self.fresh = fresh
        self.calls: list[tuple[str, Optional[str]]] = []

    async def require_fresh(
        self, session_id: str, *, capability_id: Optional[str] = None
    ) -> tuple[bool, Optional[str]]:
        self.calls.append((session_id, capability_id))
        return (True, None) if self.fresh else (False, "step_up_required")


class FakeJobs:
    """A stand-in for ``JobsService``, recording what the plane asked it to do."""

    def __init__(self, *, status_after_retry: str = "queued") -> None:
        self.retry_calls: list[tuple[str, str]] = []
        self.enqueue_calls: list[dict[str, Any]] = []
        self.status_after_retry = status_after_retry
        self._jobs: dict[str, dict[str, Any]] = {}

    async def retry(self, tenant_id: str, job_id: str) -> dict[str, Any]:
        self.retry_calls.append((tenant_id, job_id))
        job = {
            "id": job_id,
            "tenant_id": tenant_id,
            "job_type": "import.commit",
            "status": self.status_after_retry,
            "attempts": 0,
        }
        self._jobs[job_id] = job
        return job

    async def enqueue(
        self,
        tenant_id: str,
        job_type: str,
        payload: dict,
        *,
        idempotency_key: Optional[str] = None,
        correlation_id: Optional[str] = None,
        requested_by: Optional[str] = None,
        priority: int = 100,
        max_attempts: int = 5,
        scheduled_for: Any = None,
    ) -> dict[str, Any]:
        self.enqueue_calls.append(
            {
                "tenant_id": tenant_id,
                "job_type": job_type,
                "payload": payload,
                "idempotency_key": idempotency_key,
                "correlation_id": correlation_id,
            }
        )
        job = {
            "id": f"job_{len(self.enqueue_calls)}",
            "tenant_id": tenant_id,
            "job_type": job_type,
            "status": "queued",
            "correlation_id": correlation_id,
            "replayed": False,
        }
        self._jobs[job["id"]] = job
        return job

    async def get_job(self, tenant_id: str, job_id: str) -> Optional[dict[str, Any]]:
        return self._jobs.get(job_id)

    async def list_jobs(self, tenant_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        return list(self._jobs.values())


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def jobs() -> FakeJobs:
    return FakeJobs()


@pytest.fixture(autouse=True)
def clean_state():
    """Empty stores, a fresh dispatch cache and no cached providers."""
    reset_in_memory_stores()
    dispatch.reset_handler_instances()
    reset_ops_providers()
    yield
    reset_in_memory_stores()
    dispatch.reset_handler_instances()
    reset_ops_providers()


def install(
    *,
    blast_radius: Any = "default",
    step_up_fresh: bool = True,
    jobs: Optional[FakeJobs] = None,
) -> FakeStepUp:
    """Wire the ops plane's outward dependencies to fakes.

    ``blast_radius=None`` is a real configuration, not a missing fixture: it is
    how the "assessor unavailable" case is produced.
    """
    assessor = FakeBlastRadius() if blast_radius == "default" else blast_radius
    step_up = FakeStepUp(fresh=step_up_fresh)
    set_ops_providers(
        OpsProviders(
            blast_radius=assessor, step_up=step_up, mirror_parity=fake_mirror_digest
        )
    )
    if jobs is not None:
        dispatch.set_handler_instance(JOBS_CLASS, jobs)
    return step_up


def service() -> CommandService:
    return CommandService()


async def request_kill_switch(svc: CommandService, **overrides: Any) -> CommandRequest:
    kwargs: dict[str, Any] = dict(
        command_type="activate_kill_switch",
        requested_by=REQUESTER,
        reason="runaway agent loop across the fleet",
        idempotency_key="ks-1",
        session_id=SESSION,
        rollback_plan="deactivate the switch and resume the runtime",
        approval_mode="small_team",
        qualified_operators=3,
        role_template_ids=FOUNDER_TEMPLATES,
    )
    kwargs.update(overrides)
    return await svc.request(**kwargs)


# ── Approval refusals ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_self_approval_is_refused():
    """The requester cannot be the second actor. One hand, one signature."""
    install()
    svc = service()
    command = await request_kill_switch(svc)

    with pytest.raises(BadRequestError) as excinfo:
        await svc.approve(
            command.command_id, approver_id=REQUESTER, role_template_ids=FOUNDER_TEMPLATES
        )

    assert "different operator" in str(excinfo.value)
    stored = await svc.get(command.command_id)
    assert stored is not None and stored.approvals == []
    assert stored.status == "awaiting_approval"


@pytest.mark.asyncio
async def test_unqualified_approver_is_refused():
    """An approver must be able to take the action they are approving."""
    install()
    svc = service()
    command = await request_kill_switch(svc, idempotency_key="ks-unqualified")

    with pytest.raises(BadRequestError) as excinfo:
        await svc.approve(
            command.command_id,
            approver_id=APPROVER_A,
            role_template_ids=UNQUALIFIED_TEMPLATES,
        )

    assert "qualified" in str(excinfo.value)
    stored = await svc.get(command.command_id)
    assert stored is not None and stored.approvals == []


@pytest.mark.asyncio
async def test_the_same_approver_cannot_approve_twice():
    """Two approvals from one operator is one approval."""
    install()
    svc = service()
    command = await request_kill_switch(svc, idempotency_key="ks-duplicate")
    assert command.required_approvals == 2

    await svc.approve(
        command.command_id, approver_id=APPROVER_A, role_template_ids=FOUNDER_TEMPLATES
    )

    with pytest.raises(BadRequestError) as excinfo:
        await svc.approve(
            command.command_id, approver_id=APPROVER_A, role_template_ids=FOUNDER_TEMPLATES
        )

    assert "already approved" in str(excinfo.value)
    stored = await svc.get(command.command_id)
    assert stored is not None
    assert [entry["approver_id"] for entry in stored.approvals] == [APPROVER_A]

    # A *different* qualified operator still counts, which is what makes the
    # refusal above a duplicate check rather than an approval ceiling.
    await svc.approve(
        command.command_id, approver_id=APPROVER_B, role_template_ids=FOUNDER_TEMPLATES
    )
    stored = await svc.get(command.command_id)
    assert stored is not None and len(stored.approvals) == 2


# ── Idempotency ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_same_idempotency_key_executes_once(jobs: FakeJobs):
    """Same key, same command type: one command, one execution, one side effect."""
    install(jobs=jobs)
    svc = service()

    first = await svc.request(
        command_type="retry_job",
        requested_by=REQUESTER,
        reason="transient connector timeout",
        idempotency_key="retry-key-1",
        tenant_ids=[TENANT],
        resource_ids=["job_77"],
        session_id=SESSION,
    )
    second = await svc.request(
        command_type="retry_job",
        requested_by=REQUESTER,
        reason="transient connector timeout",
        idempotency_key="retry-key-1",
        tenant_ids=[TENANT],
        resource_ids=["job_77"],
        session_id=SESSION,
    )

    assert second.command_id == first.command_id
    rows = await command_repository.list_by_status(None, limit=100)
    assert len([row for row in rows if row["idempotency_key"] == "retry-key-1"]) == 1

    await svc.execute(first.command_id, actor_id=REQUESTER)
    await svc.execute(second.command_id, actor_id=REQUESTER)

    assert jobs.retry_calls == [(TENANT, "job_77")]
    assert await command_execution_repository.attempt_count(first.command_id) == 1


# ── Postconditions ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_failed_postcondition_leaves_the_command_unverified_and_names_the_check():
    """A retry whose job is still failed is not a success, whatever the call returned.

    The handler returns cleanly; the job did not move. The command must not read
    as ``verified``, and the operator must be told *which* postcondition failed
    rather than being handed a bare status.
    """
    jobs = FakeJobs(status_after_retry="failed")
    install(jobs=jobs)
    svc = service()

    command = await svc.request(
        command_type="retry_job",
        requested_by=REQUESTER,
        reason="retry after connector fix",
        idempotency_key="retry-unverified",
        tenant_ids=[TENANT],
        resource_ids=["job_88"],
        session_id=SESSION,
    )
    result = await svc.execute(command.command_id, actor_id=REQUESTER)

    assert jobs.retry_calls == [(TENANT, "job_88")]
    assert result["command"]["status"] == "executed_unverified"
    assert result["command"]["status"] != "verified"
    assert result["execution"]["error"] is None

    verification_row = result["verification"]
    assert verification_row["outcome"] == "failed"
    assert "job_retry_recorded" in verification_row["failure_reason"]
    assert "job_retry_recorded" in result["command"]["metadata"]["failed_checks"]
    failed = [c for c in verification_row["checks"] if c["outcome"] == "failed"]
    assert {c["check"] for c in failed} == {"job_retry_recorded", "job_not_failed"}


# ── Fail-closed gates ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_class_five_command_without_live_step_up_is_denied():
    """No live elevation, no fleet-destructive command."""
    step_up = install(step_up_fresh=False)
    svc = service()

    with pytest.raises(ForbiddenError) as excinfo:
        await request_kill_switch(svc, idempotency_key="ks-no-step-up")

    assert step_up.calls, "the step-up service must actually have been consulted"
    assert excinfo.value.details.get("denial_reason") == "step_up_required"
    assert await command_repository.list_by_status(None, limit=10) == []


@pytest.mark.asyncio
async def test_unavailable_blast_radius_refuses_rather_than_assuming_a_small_one():
    """An unmeasured reach is refused, never defaulted to something optimistic."""
    install(blast_radius=None)
    svc = service()

    with pytest.raises(BadRequestError) as excinfo:
        await svc.request(
            command_type="retry_job",
            requested_by=REQUESTER,
            reason="retry after connector fix",
            idempotency_key="retry-no-radius",
            tenant_ids=[TENANT],
            resource_ids=["job_99"],
            session_id=SESSION,
        )

    message = str(excinfo.value)
    assert "blast radius" in message and "could not be assessed" in message
    assert excinfo.value.details["blast_radius"]["available"] is False
    assert await command_repository.list_by_status(None, limit=10) == []


# ── Registry / verifier drift ────────────────────────────────────────────────


def test_every_declared_check_has_a_verifier_and_every_verifier_is_declared():
    """Drift in either direction is a defect, and both are checked."""
    declared = verification.declared_checks()
    implemented = frozenset(verification.VERIFIERS)

    assert declared - implemented == frozenset(), (
        "checks declared in registry.py with no verifier: those commands would "
        "reach 'executed_unverified' and never leave"
    )
    assert implemented - declared == frozenset(), (
        "verifiers implemented for checks no command declares: dead code, or a "
        "spec edit that stopped halfway"
    )
    assert declared, "the registry declares no checks at all"


def test_a_declared_check_with_no_verifier_fails_the_drift_assertion():
    """The guard fires — proved by declaring a check nothing implements."""
    spec = CommandSpec(
        command_type="_drift_probe",
        title="drift probe",
        capability_id="kyber.command.retry",
        action_class=2,
        handler="services.jobs.service.JobsService.retry",
        verification_checks=("a_check_nobody_implements",),
    )
    register_command(spec)
    try:
        with pytest.raises(verification.VerifierDriftError) as excinfo:
            verification._assert_no_drift()
        assert "a_check_nobody_implements" in str(excinfo.value)
    finally:
        COMMAND_REGISTRY.pop("_drift_probe", None)
    verification._assert_no_drift()


def test_a_verifier_no_command_declares_fails_the_drift_assertion():
    """The other direction: an orphan verifier is drift too."""
    async def _orphan(ctx: Any) -> Any:  # pragma: no cover - never invoked
        raise AssertionError("orphan verifier must never run")

    verification.VERIFIERS["_orphan_check"] = _orphan
    try:
        with pytest.raises(verification.VerifierDriftError) as excinfo:
            verification._assert_no_drift()
        assert "_orphan_check" in str(excinfo.value)
    finally:
        verification.VERIFIERS.pop("_orphan_check", None)
    verification._assert_no_drift()


# ── Evidence gates ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_spec_requiring_a_dry_run_cannot_execute_without_one(jobs: FakeJobs):
    """``requires_dry_run`` is a gate, not documentation."""
    install(jobs=jobs)
    svc = service()

    command = await svc.request(
        command_type="replay_event_range",
        requested_by=REQUESTER,
        reason="replay the dropped window after the connector fix",
        idempotency_key="replay-1",
        tenant_ids=[TENANT],
        session_id=SESSION,
        metadata={"window_start": "2026-07-01T00:00:00+00:00",
                  "window_end": "2026-07-01T06:00:00+00:00"},
    )
    assert "dry_run" in command.metadata["approval_gaps"]

    with pytest.raises(BadRequestError) as excinfo:
        await svc.execute(command.command_id, actor_id=REQUESTER)
    assert "dry_run" in str(excinfo.value)
    assert jobs.enqueue_calls == [], "a blocked command must not reach its handler"

    plan = await svc.dry_run(command.command_id, actor_id=REQUESTER)
    assert plan["handler"] == "services.jobs.service.JobsService.enqueue"
    assert jobs.enqueue_calls == [], "a dry run must not call the handler either"

    await svc.execute(command.command_id, actor_id=REQUESTER)
    assert len(jobs.enqueue_calls) == 1


@pytest.mark.asyncio
async def test_a_spec_requiring_a_rollback_plan_cannot_execute_without_one(jobs: FakeJobs):
    """``requires_rollback_plan`` is refused at request *and* at execution."""
    install(jobs=jobs)
    svc = service()

    with pytest.raises(BadRequestError) as excinfo:
        await svc.request(
            command_type="pause_connector",
            requested_by=REQUESTER,
            reason="connector is flooding the queue",
            idempotency_key="pause-no-rollback",
            tenant_ids=[TENANT],
            resource_ids=["connector_hubspot"],
            session_id=SESSION,
        )
    assert excinfo.value.details.get("gap") == "rollback_plan"

    # And the execution gate holds independently: a command persisted without a
    # rollback plan — by any path that bypassed the request gate — still cannot
    # run. One gate is a check; two is a control.
    smuggled = CommandRequest(
        command_type="pause_connector",
        requested_by=REQUESTER,
        reason="connector is flooding the queue",
        idempotency_key="pause-smuggled",
        tenant_ids=[TENANT],
        resource_ids=["connector_hubspot"],
        action_class=4,
        status="approved",
        step_up_verified=True,
        blast_radius={"available": True, "affected_tenants": [TENANT]},
        verification_plan=list(COMMAND_REGISTRY["pause_connector"].verification_checks),
        metadata={"dry_run_command_id": "prior", "founder_authority": True,
                  "typed_confirmation": "pause_connector"},
    )
    await command_repository.save(smuggled.model_dump())

    with pytest.raises(BadRequestError) as excinfo:
        await svc.execute(smuggled.command_id, actor_id=REQUESTER)
    assert "rollback_plan" in str(excinfo.value)
    assert await command_execution_repository.attempt_count(smuggled.command_id) == 0


# ── Handler resolution ───────────────────────────────────────────────────────


def test_every_registered_handler_resolves_to_a_real_callable():
    """A registered command with an unresolvable handler is a gate with no door.

    Resolution is deliberately loud — ``services/kyber/seams.py`` records two
    production defects caused by a wrong module path reading as an absent one —
    so this walks the whole catalog against the real modules, with no fakes
    installed.
    """
    dispatch.reset_handler_instances()
    for command_type, spec in sorted(COMMAND_REGISTRY.items()):
        resolved = dispatch.resolve_handler(spec.handler)
        assert callable(resolved.callable_), command_type
        assert resolved.path == spec.handler


def test_an_unresolvable_handler_raises_instead_of_degrading():
    """No silent ``try/except ImportError``: a bad path is an error, not a no-op."""
    with pytest.raises(dispatch.CommandDispatchError) as excinfo:
        dispatch.resolve_handler("services.jobs.service.JobsService.no_such_method")
    assert "no_such_method" in str(excinfo.value)

    with pytest.raises(dispatch.CommandDispatchError):
        dispatch.resolve_handler("services.nowhere.at.all.Thing.method")


async def test_record_approval_recomputes_gaps_instead_of_filtering_a_snapshot():
    """A gap that reappears after the request must still block the command.

    `ApprovalPolicy.record_approval` used to subtract "second_approver" from the
    gap list stored in `command.metadata` at request time. That list is a
    snapshot, and a snapshot is wrong in both directions: a gap satisfied since
    (a dry run that has now run) left a command stuck at `awaiting_approval`
    with nothing an operator could do about it, and a gap that REAPPEARED since
    — a step-up grant lapsing while the second approver was being found — was
    silently dropped. The second direction is the one that matters.

    This test drives `approval_policy` directly rather than through
    `CommandService.approve`, because the service recomputes the gaps itself
    immediately afterwards and so masks the defect. Every other caller of the
    policy inherits the stale verdict, which is exactly why the rule has to live
    in the policy rather than in one of its callers.
    """
    from services.kyber.ops.approvals import ApprovalPolicy

    spec = COMMAND_REGISTRY["activate_kill_switch"]
    policy = ApprovalPolicy()
    command = CommandRequest(
        command_type=spec.command_type,
        requested_by="operator_requester",
        reason="containment drill",
        action_class=spec.action_class,
        idempotency_key="ks-policy-stale-gaps",
        status="awaiting_approval",
        required_approvals=1,
        approval_mode="small_team",
        # Fresh at request time, lapsed by the time the approval lands.
        step_up_verified=False,
        rollback_plan="deactivate the switch",
        verification_plan=list(spec.verification_checks),
        blast_radius={"available": True, "exposure_known": True},
        metadata={
            # The stale snapshot: written when step-up WAS fresh, so it names
            # only the missing second approver.
            "approval_gaps": ["second_approver"],
            "dry_run": {"ok": True},
            "founder_authority": True,
            "typed_confirmation": spec.command_type,
        },
    )

    await policy.record_approval(
        command,
        approver_id="operator_approver",
        role_template_ids=["founder_operator"],
        spec=spec,
    )

    assert len(command.approvals) == 1, "the approval itself should still be recorded"
    assert "fresh_step_up" in command.metadata["approval_gaps"], (
        "step-up had lapsed since the request; recording the final approval must "
        f"surface it as a live gap, got {command.metadata['approval_gaps']}"
    )
    assert command.status == "awaiting_approval", (
        "the approval count was met but a real gap remains, so the command must "
        f"not be marked approved — status was {command.status!r}"
    )
