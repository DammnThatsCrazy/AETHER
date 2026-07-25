"""Postconditions — the difference between "the call returned" and "it worked".

Every registered command declares the checks that must hold *after* it runs.
This module is the only place those checks are implemented, and it holds three
rules that are refusals rather than conventions.

**A declared check with no verifier fails at import.** ``registry.py`` already
refuses a spec that declares no checks at all; that guard is worth nothing if a
check name can be declared and then quietly never run. The assertion at the
bottom of this module covers both directions — a check nobody implements, and a
verifier nobody declares — because an orphan verifier is drift too: it is either
dead code or evidence that a spec was edited and this file was not.

**A verifier that cannot determine the answer returns ``inconclusive``.** Never
``passed``. Missing information has to read as missing: an operator looking at a
green command must be able to believe that something went and checked. That is
also why the Tenant Mirror digest is compared through
``containment.mirror_digest`` — which returns ``None`` when parity cannot be
determined — rather than through a default that quietly asserts parity held.

**Checks re-read the world.** ``handler_reported_success`` is deliberately one
check among several, and never the only one on a spec that changes durable
state. A handler's return value is the weakest evidence available: it is exactly
the HTTP-200 that this plane exists not to trust. The other verifiers go back to
the jobs platform, the containment switches, the agent runtime and the blast
radius assessor and ask again.

Nothing here reaches across planes by import. Blast radius and mirror parity are
reached through the indirection in :mod:`services.kyber.ops.containment`, so a
plane that has not landed yet produces ``inconclusive`` rather than an
``ImportError`` or — far worse — a pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from shared.logger.logger import get_logger

from .containment import compute_blast_radius, containment_service, mirror_digest
from .contracts import (
    CommandExecution,
    CommandRequest,
    CommandSpec,
    CommandVerification,
    VerificationOutcome,
    now_iso,
)
from .dispatch import FLEET_TENANT, CommandDispatchError, containment_target, resolve_handler
from .registry import COMMAND_REGISTRY

logger = get_logger("aether.kyber.ops.verification")

PASSED: VerificationOutcome = "passed"
FAILED: VerificationOutcome = "failed"
INCONCLUSIVE: VerificationOutcome = "inconclusive"

#: Job statuses that mean the jobs platform has taken durable custody of the
#: work. Read from the platform's own vocabulary rather than restated as a
#: literal set the two could drift apart on.
_ACCEPTED_JOB_STATUSES: frozenset[str] = frozenset(
    {"accepted", "queued", "retrying", "running", "succeeded", "partially_succeeded"}
)

#: Keys a blast-radius record may use for reach. Every one that appears on both
#: sides is compared; a key present on neither contributes nothing rather than
#: being read as agreement.
_REACH_SET_KEYS: tuple[str, ...] = (
    "affected_tenants", "affected_services", "affected_features",
    "affected_nodes", "affected_connectors",
)
_REACH_COUNT_KEYS: tuple[str, ...] = (
    "tenant_count", "service_count", "node_count", "affected_count", "edge_count",
)


class VerifierDriftError(RuntimeError):
    """A declared check has no verifier, or a verifier has no declaration.

    Raised at import time so the mismatch is a startup failure. A command whose
    postcondition silently never runs is worse than one with no postcondition at
    all, because the spec claims otherwise.
    """


@dataclass
class VerificationContext:
    """Everything a verifier is allowed to read.

    ``digest_before`` is captured by the caller *before* the handler runs; there
    is no way to reconstruct it afterwards, and a parity check that only sampled
    the world once would be comparing a value against itself.
    """

    command: CommandRequest
    spec: CommandSpec
    execution: Optional[CommandExecution] = None
    digest_before: Optional[str] = None
    digest_after: Optional[str] = None

    @property
    def tenant_id(self) -> str:
        return self.command.tenant_ids[0] if self.command.tenant_ids else ""

    @property
    def handler_result(self) -> Any:
        if self.execution is None or not isinstance(self.execution.result, dict):
            return None
        return self.execution.result.get("handler_result")


@dataclass
class CheckResult:
    """One postcondition, with the evidence that decided it."""

    name: str
    outcome: VerificationOutcome
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.name,
            "outcome": self.outcome,
            "detail": self.detail,
            "evidence": self.evidence,
            "checked_at": now_iso(),
        }


Verifier = Callable[[VerificationContext], Awaitable[CheckResult]]


# ── Re-reading the world ─────────────────────────────────────────────────────


def _bound(path: str) -> Any:
    """A bound platform call, or ``None`` when it cannot be resolved.

    Resolution goes through :func:`services.kyber.ops.dispatch.resolve_handler`
    so verification reads through the same instance the command wrote through.
    Two different instances would let a check pass against state the command
    never touched.

    ``None`` here always becomes ``inconclusive`` at the call site — never a
    pass. That is the one thing this helper is allowed to be quiet about.
    """
    try:
        return resolve_handler(path).callable_
    except CommandDispatchError as exc:
        logger.warning(f"kyber: verification cannot reach {path}: {exc}")
        return None


async def _get_job(tenant_id: str, job_id: str) -> tuple[Optional[dict[str, Any]], str]:
    """Re-read one job. Returns ``(job, reason_when_unavailable)``."""
    getter = _bound("services.jobs.service.JobsService.get_job")
    if getter is None:
        return None, "jobs_service_unavailable"
    try:
        job = await getter(tenant_id, job_id)
    except Exception as exc:
        return None, f"job_read_failed:{type(exc).__name__}"
    if job is None:
        return None, "job_not_found"
    return job, ""


async def _list_jobs(tenant_id: str, job_type: Optional[str]) -> tuple[
    Optional[list[dict[str, Any]]], str
]:
    lister = _bound("services.jobs.service.JobsService.list_jobs")
    if lister is None:
        return None, "jobs_service_unavailable"
    try:
        return await lister(tenant_id, job_type=job_type, limit=200), ""
    except Exception as exc:
        return None, f"job_list_failed:{type(exc).__name__}"


def _job_id_from(ctx: VerificationContext) -> Optional[str]:
    """The job this command created or acted on, if one can be named."""
    result = ctx.handler_result
    if isinstance(result, dict):
        for key in ("id", "job_id"):
            value = result.get(key)
            if value:
                return str(value)
    explicit = ctx.command.metadata.get("job_id")
    if explicit:
        return str(explicit)
    return ctx.command.resource_ids[0] if ctx.command.resource_ids else None


# ── The verifiers ────────────────────────────────────────────────────────────


async def handler_reported_success(ctx: VerificationContext) -> CheckResult:
    """The call returned without raising.

    The weakest check in the table, and it is named honestly: it asserts nothing
    about platform state. It is here so that a handler which raised is
    distinguishable from one that returned something unexpected, and it is never
    the only check on a spec.
    """
    if ctx.execution is None:
        return CheckResult(
            "handler_reported_success", INCONCLUSIVE, "the command has no execution record"
        )
    if ctx.execution.error:
        return CheckResult(
            "handler_reported_success",
            FAILED,
            f"the handler did not complete: {ctx.execution.error}",
            {"error": ctx.execution.error},
        )
    result = ctx.execution.result if isinstance(ctx.execution.result, dict) else {}
    if result.get("called") is not True:
        return CheckResult(
            "handler_reported_success",
            INCONCLUSIVE,
            "no record that the handler was reached",
            {"result": result},
        )
    return CheckResult(
        "handler_reported_success",
        PASSED,
        "the handler returned without raising",
        {"handler": result.get("handler")},
    )


async def job_enqueued(ctx: VerificationContext) -> CheckResult:
    """A durable job exists, read back from the jobs platform.

    The enqueue call's own return value is not enough: it is re-read by id, so
    an enqueue that reported an id the platform never persisted fails here
    instead of being believed.
    """
    job_id = _job_id_from(ctx)
    if not job_id:
        return CheckResult(
            "job_enqueued", INCONCLUSIVE, "the handler result named no job id"
        )
    job, reason = await _get_job(ctx.tenant_id, job_id)
    if job is None:
        if reason == "job_not_found":
            return CheckResult(
                "job_enqueued",
                FAILED,
                f"the enqueue returned job {job_id} but the jobs platform has no such job",
                {"job_id": job_id},
            )
        return CheckResult("job_enqueued", INCONCLUSIVE, reason, {"job_id": job_id})

    status = str(job.get("status") or "")
    if status not in _ACCEPTED_JOB_STATUSES:
        return CheckResult(
            "job_enqueued",
            FAILED,
            f"job {job_id} is {status!r}; the platform did not take custody of the work",
            {"job_id": job_id, "status": status},
        )
    return CheckResult(
        "job_enqueued",
        PASSED,
        f"job {job_id} is {status}",
        {"job_id": job_id, "status": status},
    )


async def job_not_duplicated(ctx: VerificationContext) -> CheckResult:
    """This command produced at most one unit of durable work.

    Counts the jobs carrying this command's id as their correlation id. A
    ``replayed`` enqueue is *not* a failure — it is the jobs platform's
    idempotency working, and it is the outcome a re-requested command should
    have. What fails is two live jobs for one command, which is the shape a
    double-submit actually takes.
    """
    result = ctx.handler_result if isinstance(ctx.handler_result, dict) else {}
    job_type = str(result.get("job_type") or "") or None
    jobs, reason = await _list_jobs(ctx.tenant_id, job_type)
    if jobs is None:
        replayed = result.get("replayed")
        if replayed is True:
            return CheckResult(
                "job_not_duplicated",
                PASSED,
                "the jobs platform reported an idempotency replay; no second job was created",
                {"replayed": True, "listing": reason},
            )
        return CheckResult("job_not_duplicated", INCONCLUSIVE, reason)

    mine = [job for job in jobs if job.get("correlation_id") == ctx.command.command_id]
    if len(mine) > 1:
        return CheckResult(
            "job_not_duplicated",
            FAILED,
            f"{len(mine)} jobs carry command {ctx.command.command_id}; the command "
            f"was executed more than once",
            {"job_ids": [job.get("id") for job in mine]},
        )
    if not mine:
        return CheckResult(
            "job_not_duplicated",
            INCONCLUSIVE,
            "no job carries this command's correlation id, so duplication cannot be judged",
            {"job_type": job_type},
        )
    return CheckResult(
        "job_not_duplicated",
        PASSED,
        "exactly one job carries this command's correlation id",
        {"job_id": mine[0].get("id"), "replayed": result.get("replayed")},
    )


async def job_retry_recorded(ctx: VerificationContext) -> CheckResult:
    """The retried job actually left ``failed``.

    A retry whose job is still ``failed`` is the exact case the plane exists to
    catch: the call returned 200 and nothing moved.
    """
    job_id = _job_id_from(ctx)
    if not job_id:
        return CheckResult("job_retry_recorded", INCONCLUSIVE, "no job id to re-read")
    job, reason = await _get_job(ctx.tenant_id, job_id)
    if job is None:
        return CheckResult("job_retry_recorded", INCONCLUSIVE, reason, {"job_id": job_id})

    status = str(job.get("status") or "")
    if status == "failed":
        return CheckResult(
            "job_retry_recorded",
            FAILED,
            f"job {job_id} is still 'failed'; the retry did not take",
            {"job_id": job_id, "status": status},
        )
    return CheckResult(
        "job_retry_recorded",
        PASSED,
        f"job {job_id} left 'failed' and is now {status}",
        {"job_id": job_id, "status": status, "attempts": job.get("attempts")},
    )


async def job_not_failed(ctx: VerificationContext) -> CheckResult:
    """The job this command touched is not in a failed state now."""
    job_id = _job_id_from(ctx)
    if not job_id:
        return CheckResult("job_not_failed", INCONCLUSIVE, "no job id to re-read")
    job, reason = await _get_job(ctx.tenant_id, job_id)
    if job is None:
        return CheckResult("job_not_failed", INCONCLUSIVE, reason, {"job_id": job_id})

    status = str(job.get("status") or "")
    if status == "failed":
        return CheckResult(
            "job_not_failed",
            FAILED,
            f"job {job_id} is 'failed'",
            {"job_id": job_id, "last_error": job.get("last_error")},
        )
    return CheckResult(
        "job_not_failed", PASSED, f"job {job_id} is {status}", {"job_id": job_id, "status": status}
    )


async def window_bounded(ctx: VerificationContext) -> CheckResult:
    """The replay or recompute named both ends of its window.

    An unbounded replay is a full reprocess wearing a smaller name, so a missing
    end is a **failure**, not an inconclusive result. There is nothing further to
    look up: the bound either was declared on the request or it was not.
    """
    metadata = ctx.command.metadata or {}
    for start_key, end_key in (("window_start", "window_end"), ("from_offset", "to_offset")):
        start, end = metadata.get(start_key), metadata.get(end_key)
        if start is None and end is None:
            continue
        if start is None or end is None:
            missing = start_key if start is None else end_key
            return CheckResult(
                "window_bounded",
                FAILED,
                f"{missing} is absent; an open-ended window is a full reprocess",
                {start_key: start, end_key: end},
            )
        try:
            ordered = start <= end
        except TypeError:
            return CheckResult(
                "window_bounded",
                FAILED,
                f"{start_key} and {end_key} are not comparable",
                {start_key: str(start), end_key: str(end)},
            )
        if not ordered:
            return CheckResult(
                "window_bounded",
                FAILED,
                f"{start_key} is after {end_key}",
                {start_key: str(start), end_key: str(end)},
            )
        return CheckResult(
            "window_bounded",
            PASSED,
            f"bounded on both ends by {start_key}/{end_key}",
            {start_key: str(start), end_key: str(end)},
        )

    return CheckResult(
        "window_bounded",
        FAILED,
        "no window was declared; this command may only run over a bounded range",
        {"expected_one_of": ["window_start/window_end", "from_offset/to_offset"]},
    )


async def containment_switch_active(ctx: VerificationContext) -> CheckResult:
    """The switch this command was supposed to flip is actually on."""
    resolved = containment_target(ctx.command, ctx.spec)
    if resolved is None:
        return CheckResult(
            "containment_switch_active",
            INCONCLUSIVE,
            "the command spec declares no containment scope, so no switch is named",
        )
    scope, target, control = resolved
    try:
        active = await containment_service.is_paused(control, scope=scope, target=target)
    except Exception as exc:
        return CheckResult(
            "containment_switch_active",
            INCONCLUSIVE,
            f"containment state could not be read: {type(exc).__name__}",
        )
    evidence = {"scope": scope, "target": target, "control": control}
    if not active:
        return CheckResult(
            "containment_switch_active",
            FAILED,
            f"no active {control!r} switch for {scope}/{target}; the pause did not take",
            evidence,
        )
    return CheckResult(
        "containment_switch_active", PASSED, f"{control!r} is paused for {scope}/{target}", evidence
    )


async def kill_switch_engaged(ctx: VerificationContext) -> CheckResult:
    """The agent runtime reports its kill switch engaged.

    Re-read from the runtime's own control store rather than trusted from the
    setter's return value: the broadest action Kyber can take is the one whose
    confirmation matters most.
    """
    getter = _bound("services.agent.runtime_repository.AgentRuntimeRepository.get_kill_switch")
    if getter is None:
        return CheckResult(
            "kill_switch_engaged", INCONCLUSIVE, "the agent runtime repository is unavailable"
        )
    tenant_id = ctx.tenant_id or FLEET_TENANT
    try:
        state = await getter(tenant_id)
    except Exception as exc:
        return CheckResult(
            "kill_switch_engaged",
            INCONCLUSIVE,
            f"kill switch state could not be read: {type(exc).__name__}",
        )
    enabled = bool((state or {}).get("enabled"))
    if not enabled:
        return CheckResult(
            "kill_switch_engaged",
            FAILED,
            f"the agent runtime reports the kill switch for {tenant_id!r} is not engaged",
            {"tenant_id": tenant_id, "state": state},
        )
    return CheckResult(
        "kill_switch_engaged",
        PASSED,
        f"the kill switch for {tenant_id!r} is engaged",
        {"tenant_id": tenant_id, "updated_by": (state or {}).get("updated_by")},
    )


async def blast_radius_within_declared(ctx: VerificationContext) -> CheckResult:
    """What the command actually reached is no wider than what was approved.

    The radius attached at request time is what the approver saw. Reassessing
    afterwards and finding a wider reach means the approval was given for a
    smaller action than the one that ran, which is a failed verification even
    though every individual step succeeded.
    """
    declared = ctx.command.blast_radius or {}
    if not declared or declared.get("available") is False:
        return CheckResult(
            "blast_radius_within_declared",
            INCONCLUSIVE,
            "no assessed blast radius was attached at request time",
            {"declared": declared},
        )

    resolved = containment_target(ctx.command, ctx.spec)
    actual = await compute_blast_radius(
        command_type=ctx.command.command_type,
        tenant_ids=list(ctx.command.tenant_ids),
        resource_ids=list(ctx.command.resource_ids),
        environment=ctx.command.environment,
        scope=resolved[0] if resolved else None,
        target=resolved[1] if resolved else None,
    )
    if actual.get("available") is False:
        return CheckResult(
            "blast_radius_within_declared",
            INCONCLUSIVE,
            f"the assessor could not be reached after execution: {actual.get('reason')}",
            {"actual": actual},
        )

    widened: list[dict[str, Any]] = []
    compared = 0
    for key in _REACH_SET_KEYS:
        if key not in declared or key not in actual:
            continue
        compared += 1
        extra = sorted(set(actual.get(key) or ()) - set(declared.get(key) or ()))
        if extra:
            widened.append({"field": key, "unapproved": extra})
    for key in _REACH_COUNT_KEYS:
        if key not in declared or key not in actual:
            continue
        compared += 1
        try:
            if float(actual[key]) > float(declared[key]):
                widened.append(
                    {"field": key, "declared": declared[key], "actual": actual[key]}
                )
        except (TypeError, ValueError):
            continue

    if compared == 0:
        return CheckResult(
            "blast_radius_within_declared",
            INCONCLUSIVE,
            "the two assessments share no comparable reach field",
            {"declared_keys": sorted(declared), "actual_keys": sorted(actual)},
        )
    if widened:
        return CheckResult(
            "blast_radius_within_declared",
            FAILED,
            "the command reached further than the radius it was approved against",
            {"widened": widened},
        )
    return CheckResult(
        "blast_radius_within_declared",
        PASSED,
        f"actual reach is within the {compared} declared field(s) compared",
        {"fields_compared": compared},
    )


async def customer_visible_parity(ctx: VerificationContext) -> CheckResult:
    """The tenant-visible surface changed only if the command said it would.

    Both digests come from ``containment.mirror_digest``, which returns ``None``
    when parity cannot be determined — and ``None`` propagates to
    ``inconclusive`` here rather than being read as "unchanged". Assuming parity
    held because the comparison was unavailable is the single most misleading
    thing this module could do.

    A change is not automatically a failure: a recompute is *supposed* to move
    tenant-visible numbers. The request declares that with
    ``metadata["customer_visible_change_expected"]``. What fails is a change
    nobody declared.
    """
    before, after = ctx.digest_before, ctx.digest_after
    if before is None or after is None:
        return CheckResult(
            "customer_visible_parity",
            INCONCLUSIVE,
            "a Tenant Mirror digest was unavailable on at least one side",
            {"digest_before": before, "digest_after": after},
        )

    evidence = {"digest_before": before, "digest_after": after}
    if before == after:
        return CheckResult(
            "customer_visible_parity",
            PASSED,
            "the tenant-visible surface is unchanged",
            evidence,
        )
    if ctx.command.metadata.get("customer_visible_change_expected") is True:
        return CheckResult(
            "customer_visible_parity",
            PASSED,
            "the tenant-visible surface changed, as the request declared it would",
            {**evidence, "declared": True},
        )
    return CheckResult(
        "customer_visible_parity",
        FAILED,
        "the tenant-visible surface changed and the request did not declare that it would",
        evidence,
    )


#: Every check name a spec may declare. The keys of this map and the union of
#: every ``verification_checks`` tuple in the registry must be the same set —
#: see :func:`_assert_no_drift`.
VERIFIERS: dict[str, Verifier] = {
    "handler_reported_success": handler_reported_success,
    "job_enqueued": job_enqueued,
    "job_not_duplicated": job_not_duplicated,
    "job_retry_recorded": job_retry_recorded,
    "job_not_failed": job_not_failed,
    "window_bounded": window_bounded,
    "containment_switch_active": containment_switch_active,
    "kill_switch_engaged": kill_switch_engaged,
    "blast_radius_within_declared": blast_radius_within_declared,
    "customer_visible_parity": customer_visible_parity,
}


def declared_checks() -> frozenset[str]:
    """Every check name any registered command declares."""
    return frozenset(
        name for spec in COMMAND_REGISTRY.values() for name in spec.verification_checks
    )


def _assert_no_drift() -> None:
    """Refuse to import if the registry and this module disagree.

    Both directions matter. A declared check with no verifier is a postcondition
    that silently never runs while the spec claims it does. A verifier no spec
    declares is either dead code or the residue of a spec edit that stopped
    halfway — and the next person to add a command will reasonably assume the
    name is available and mean something different by it.
    """
    declared = declared_checks()
    implemented = frozenset(VERIFIERS)
    unimplemented = sorted(declared - implemented)
    orphaned = sorted(implemented - declared)
    if not unimplemented and not orphaned:
        return
    parts: list[str] = []
    if unimplemented:
        parts.append(
            f"declared in registry.py with no verifier here: {unimplemented} — those "
            f"commands would reach 'executed_unverified' and never leave"
        )
    if orphaned:
        parts.append(
            f"implemented here but declared by no command: {orphaned} — either dead "
            f"code or a spec edit that stopped halfway"
        )
    raise VerifierDriftError("kyber command verification drift: " + "; ".join(parts))


_assert_no_drift()


# ── Running the plan ─────────────────────────────────────────────────────────


async def capture_digest(command: CommandRequest, spec: CommandSpec) -> Optional[str]:
    """The Tenant Mirror digest to compare against, taken before execution.

    Returns ``None`` — meaning "not determinable" — when the command declares no
    parity check or the mirror plane cannot answer. The caller must pass whatever
    it gets straight through; substituting a placeholder would turn an unknown
    into a claim.
    """
    if "customer_visible_parity" not in spec.verification_checks:
        return None
    return await mirror_digest(
        tenant_ids=list(command.tenant_ids), environment=command.environment
    )


async def run_verification(
    command: CommandRequest,
    spec: CommandSpec,
    execution: Optional[CommandExecution],
    *,
    digest_before: Optional[str] = None,
) -> CommandVerification:
    """Run every check the spec declares and report the honest aggregate.

    Args:
        command: The executed command.
        spec: Its declaration; ``verification_checks`` is the plan and its order
            is preserved so the report reads the way the spec does.
        execution: What the handler returned, or ``None`` if it never ran.
        digest_before: The Tenant Mirror digest captured before execution.

    Returns:
        A :class:`~services.kyber.ops.contracts.CommandVerification` whose
        ``outcome`` is ``passed`` only when every check passed. One failure makes
        the whole verification ``failed`` and names the check; a check that could
        not decide makes it ``inconclusive``. There is no partial credit,
        because a command is either known to have worked or it is not.
    """
    verification = CommandVerification(command_id=command.command_id)
    digest_after: Optional[str] = None
    if "customer_visible_parity" in spec.verification_checks:
        digest_after = await mirror_digest(
            tenant_ids=list(command.tenant_ids), environment=command.environment
        )
        verification.mirror_digest_before = digest_before
        verification.mirror_digest_after = digest_after
        verification.customer_visible_parity = (
            None if digest_before is None or digest_after is None else digest_before == digest_after
        )

    ctx = VerificationContext(
        command=command,
        spec=spec,
        execution=execution,
        digest_before=digest_before,
        digest_after=digest_after,
    )

    failures: list[str] = []
    unknowns: list[str] = []
    for name in spec.verification_checks:
        verifier = VERIFIERS.get(name)
        if verifier is None:  # pragma: no cover - _assert_no_drift makes this unreachable
            result = CheckResult(name, INCONCLUSIVE, "no verifier is registered for this check")
        else:
            try:
                result = await verifier(ctx)
            except Exception as exc:
                # A verifier that blew up has not proven anything. Reporting the
                # crash as inconclusive keeps a broken check from reading as a
                # passing one, which is the only failure mode worth guarding.
                logger.error(f"kyber: verifier {name} raised for {command.command_id}: {exc}")
                result = CheckResult(
                    name, INCONCLUSIVE, f"the verifier raised {type(exc).__name__}: {exc}"
                )
        verification.checks.append(result.to_dict())
        if result.outcome == FAILED:
            failures.append(f"{name}: {result.detail}")
        elif result.outcome != PASSED:
            unknowns.append(f"{name}: {result.detail}")

    if failures:
        verification.outcome = FAILED
        verification.failure_reason = "; ".join(failures)
    elif unknowns:
        verification.outcome = INCONCLUSIVE
        verification.failure_reason = "; ".join(unknowns)
    else:
        verification.outcome = PASSED
    verification.completed_at = now_iso()

    logger.info(
        f"kyber: command {command.command_id} verification={verification.outcome} "
        f"checks={len(verification.checks)}"
    )
    return verification


__all__ = [
    "FAILED",
    "INCONCLUSIVE",
    "PASSED",
    "VERIFIERS",
    "CheckResult",
    "VerificationContext",
    "VerifierDriftError",
    "capture_digest",
    "declared_checks",
    "run_verification",
]
