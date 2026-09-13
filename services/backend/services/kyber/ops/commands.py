"""The governed command plane.

A command is the only sanctioned way to change platform state from Kyber, and it
is a *wrapper*: every handler it dispatches to is a call the platform already
knows how to make. What the plane adds is uniform authority, evidence and
verification over actions that today each carry their own ad-hoc handling.

The lifecycle, in order, and every step is a refusal when it cannot be satisfied:

======  ==================================================================
 step   what it refuses
======  ==================================================================
 1      an unregistered command type
 2      a repeated ``(command_type, idempotency_key)`` — returns the first
        command rather than executing twice
 3      a caller who does not hold the spec's capability
 4      a class 4-5 command with no **live** step-up grant
 5      a blast radius that could not be computed — never an optimistic
        default, because an unmeasured reach is the whole failure this
        plane exists to prevent
 6      a spec requiring a rollback plan with none written
 7      an approval gate that is not yet satisfied
 8      a spec requiring a dry run that has not had one
 9      a target the containment plane has paused
======  ==================================================================

Then it dispatches, and — this is the part that makes the plane worth having —
the command becomes ``executed_unverified``, not ``verified``. An HTTP 200 is
not success.

Two status rules worth stating explicitly, because they are easy to get
backwards:

* ``failed`` means **the execution failed**: the handler raised, or could not be
  resolved. Nothing is known to have changed.
* ``executed_unverified`` means **the call returned but the postconditions did
  not hold or could not be checked**. Something may well have changed. Leaving a
  postcondition failure here rather than moving it to ``failed`` is deliberate:
  ``failed`` reads to an operator as "nothing happened, retry is safe", and that
  is exactly the wrong thing to believe about a command whose side effect
  already landed. The failed check is named in the verification record and
  surfaced on the command, so the state is legible rather than merely cautious.

Approval rules are not re-derived here. :mod:`services.kyber.ops.approvals`
owns them — including the refusal and audit of self-approval, unqualified
approval and the same operator approving twice — for the same reason
``services/security/break_glass`` owns them for emergency access: two
implementations of a second-actor rule is one implementation and one liability.

Two of this plane's promises are idempotency promises, and an idempotency
promise is worth exactly what it costs to break it concurrently. A double
click, a retrying client and two console tabs all produce the same shape: two
calls in flight at once, each reading state the other is about to change. Both
promises are therefore held in two layers rather than by a read-then-write:

* ``request()`` serializes on ``(command_type, idempotency_key)`` inside the
  process, and treats ``ux_kyber_command_idempotency`` refusing an insert as the
  answer it is — the row the index preserved is the winner, and it is replayed
  rather than surfaced as a 500 on the retry path the lookup exists to smooth.
* ``execute()`` serializes on the command id inside the process, and claims the
  dispatch with a conditional *executable → ``executing``* update that exactly
  one caller can win.

The in-process lock alone would be a single-worker guarantee, which is no
guarantee at all for a plane that runs behind more than one worker; the durable
half is what makes each promise true between processes. See
:meth:`CommandService._claim_for_dispatch` and
:meth:`CommandService._persist_new`.
"""
from __future__ import annotations

import asyncio
from typing import Any, Iterable, Optional

from shared.common.common import BadRequestError, ForbiddenError, NotFoundError
from shared.logger.logger import get_logger, metrics

from . import dispatch, verification
from .approvals import approval_policy
from .command_repository import (
    CommandExecutionRepository,
    CommandRepository,
    CommandVerificationRepository,
)
from .containment import (
    COMMAND_CONTROL,
    ESSENTIAL_COMMAND_TYPES,
    compute_blast_radius,
    containment_service,
    get_ops_providers,
)
from .contracts import (
    ApprovalMode,
    CommandExecution,
    CommandRequest,
    CommandSpec,
    CommandVerification,
    now_iso,
)
from .registry import COMMAND_REGISTRY, require_command_spec

logger = get_logger("aether.kyber.ops.commands")

#: Statuses from which a command may still be dispatched.
_EXECUTABLE_STATUSES: frozenset[str] = frozenset(
    {"requested", "awaiting_approval", "approved", "dry_run_complete"}
)

#: Statuses that mean the command already ran. Re-executing one of these is a
#: second side effect, so the service returns what it has instead.
_TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"executing", "executed_unverified", "verified", "failed", "rolled_back", "cancelled", "expired"}
)

#: The control the containment plane uses to pause the command plane itself.
#: A paused plane still runs the commands that *widen* containment — locking
#: those out would mean the only way to contain further is to first uncontain.
_COMMAND_CONTROL = COMMAND_CONTROL

#: PostgreSQL's unique-violation SQLSTATE.
_UNIQUE_VIOLATION_SQLSTATE = "23505"

#: How many per-key locks to keep before evicting the idle ones. Command ids are
#: unbounded over a process's life, so an unbounded map of them is a slow leak.
_MAX_TRACKED_LOCKS = 2048

#: In-process locks, keyed by what they serialize. Recreated per event loop:
#: tests run each coroutine in a fresh ``asyncio.run()`` loop, and a lock bound
#: to a dead loop raises "is bound to a different event loop" on reuse.
_LOCKS: dict[str, asyncio.Lock] = {}
_LOCKS_LOOP: Optional[asyncio.AbstractEventLoop] = None


def _serialized_on(key: str) -> asyncio.Lock:
    """The lock serializing one key within this process.

    Callers must ``async with`` the returned lock immediately: an uncontended
    acquire does not yield, so no other coroutine can observe the map between
    the lookup and the acquire, and only idle locks are ever evicted.
    """
    global _LOCKS_LOOP
    loop = asyncio.get_running_loop()
    if _LOCKS_LOOP is not loop:
        _LOCKS.clear()
        _LOCKS_LOOP = loop
    lock = _LOCKS.get(key)
    if lock is None:
        if len(_LOCKS) >= _MAX_TRACKED_LOCKS:
            # A lock nobody holds and nobody waits on is indistinguishable from
            # a fresh one, so dropping it is safe; keeping every command id
            # forever is not.
            for idle in [k for k, held in _LOCKS.items() if not held.locked()]:
                del _LOCKS[idle]
        lock = asyncio.Lock()
        _LOCKS[key] = lock
    return lock


def _is_unique_violation(exc: BaseException) -> bool:
    """Whether a write failed because a unique index refused it.

    Matched on SQLSTATE rather than by importing ``asyncpg.exceptions``: the
    driver is an optional dependency (``repositories.repos`` imports it under a
    guard), and an ``except ImportError`` that degrades would turn a constraint
    this plane relies on into one it silently stops recognising. Nothing else is
    matched — a widened rescue around a write is how a command that did not
    persist comes to read as one that did.
    """
    return getattr(exc, "sqlstate", None) == _UNIQUE_VIOLATION_SQLSTATE


class CommandService:
    """Request, approve, dry-run, execute and verify governed commands."""

    def __init__(
        self,
        commands: Optional[CommandRepository] = None,
        executions: Optional[CommandExecutionRepository] = None,
        verifications: Optional[CommandVerificationRepository] = None,
    ) -> None:
        self._commands = commands or CommandRepository()
        self._executions = executions or CommandExecutionRepository()
        self._verifications = verifications or CommandVerificationRepository()

    # ── Audit ────────────────────────────────────────────────────────────────

    async def _audit(
        self,
        command: CommandRequest,
        *,
        actor_id: str,
        event_type: str,
        action: str,
        outcome: str = "allowed",
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Record one command transition in the shared tamper-evident ledger.

        No privileged action without durable evidence. The write itself is
        fail-open — an operator must not be blocked from containing an incident
        because the ledger is busy — but the *module* is a declared seam, so a
        rename fails the seam gate rather than silently ending the audit trail.
        """
        try:
            from services.security.audit_ledger import audit_ledger

            await audit_ledger.record(
                actor_id=actor_id,
                actor_type="olympus_operator",
                event_type=event_type,
                resource_type="kyber_command",
                action=action,
                outcome=outcome,  # type: ignore[arg-type]
                tenant_id=command.tenant_ids[0] if command.tenant_ids else None,
                resource_id=command.command_id,
                policy_decision_id=command.policy_decision_id,
                metadata={
                    "command_type": command.command_type,
                    "status": command.status,
                    "action_class": command.action_class,
                    "approval_mode": command.approval_mode,
                    "idempotency_key": command.idempotency_key,
                    **(metadata or {}),
                },
            )
        except Exception as exc:  # pragma: no cover - the ledger must not 500 a route
            logger.error(f"kyber: command audit failed for {command.command_id}: {exc}")

    async def _persist(self, command: CommandRequest) -> CommandRequest:
        command.updated_at = now_iso()
        await self._commands.save_or_update(command.model_dump())
        return command

    # ── Gates ────────────────────────────────────────────────────────────────

    @staticmethod
    def _assert_capability(spec: CommandSpec, capabilities: Optional[Iterable[str]]) -> None:
        """The caller must hold the capability the spec names.

        ``capabilities=None`` means the caller did not supply a capability set —
        a background caller, or a test. That is allowed only because the route
        layer has already authorized through ``require_kyber_access``; when a set
        *is* supplied it is enforced, so a route that forgets to pass it degrades
        to the same guarantee rather than to none.
        """
        if capabilities is None:
            return
        if spec.capability_id not in set(capabilities):
            raise ForbiddenError(
                f"command {spec.command_type!r} requires capability "
                f"{spec.capability_id!r}",
                details={"capability_id": spec.capability_id},
            )

    @staticmethod
    async def _assert_step_up(spec: CommandSpec, session_id: Optional[str]) -> bool:
        """Class 4-5 needs a live step-up grant. No provider means no command.

        An unavailable step-up service is treated as an unsatisfied step-up, not
        as an unnecessary one. A missing verifier is never a passing verifier.
        """
        from ..access.capabilities import STEP_UP_ACTION_CLASSES

        if spec.action_class not in STEP_UP_ACTION_CLASSES:
            return False

        if not session_id:
            raise ForbiddenError(
                f"a class {spec.action_class} command requires a session with a live "
                f"step-up grant; no session was named",
                details={"denial_reason": "step_up_required"},
            )
        step_up = get_ops_providers().step_up
        if step_up is None:
            raise ForbiddenError(
                "the Kyber step-up service is unavailable; a class "
                f"{spec.action_class} command cannot be authorised without it",
                details={"denial_reason": "step_up_required"},
            )
        ok, reason = await step_up.require_fresh(session_id, capability_id=spec.capability_id)
        if not ok:
            raise ForbiddenError(
                f"a fresh step-up is required for {spec.command_type!r}",
                details={"denial_reason": reason or "step_up_required"},
            )
        return True

    async def _containment_refusal(
        self, command: CommandRequest, spec: CommandSpec
    ) -> Optional[str]:
        """Why containment forbids this command right now, or ``None``.

        Two questions, in order: is the command plane itself paused, and is the
        thing this command would act on already paused? A retry aimed at a tenant
        whose ingestion an operator deliberately stopped must say so rather than
        quietly restarting work inside the containment.
        """
        try:
            if command.command_type not in ESSENTIAL_COMMAND_TYPES and await (
                containment_service.is_paused(_COMMAND_CONTROL)
            ):
                return (
                    f"the Kyber command plane is paused ({_COMMAND_CONTROL}); only "
                    f"{sorted(ESSENTIAL_COMMAND_TYPES)} may run while it is"
                )
            # A command that *establishes* containment is not blocked by it; the
            # containment service is idempotent and returns the existing switch.
            if spec.containment_scope is not None:
                return None
            for tenant_id in command.tenant_ids:
                if await containment_service.is_paused(
                    "ingestion", scope="tenant", target=tenant_id
                ):
                    return (
                        f"tenant {tenant_id} is paused (ingestion); release the "
                        f"containment switch before running {command.command_type!r} "
                        f"against it"
                    )
        except Exception as exc:  # pragma: no cover - containment store unavailable
            logger.warning(f"kyber: containment gate could not be evaluated: {exc}")
        return None

    # ── Request ──────────────────────────────────────────────────────────────

    async def request(
        self,
        *,
        command_type: str,
        requested_by: str,
        reason: str,
        idempotency_key: str,
        tenant_ids: Optional[list[str]] = None,
        resource_ids: Optional[list[str]] = None,
        session_id: Optional[str] = None,
        device_id: Optional[str] = None,
        environment: str = "local",
        capabilities: Optional[Iterable[str]] = None,
        role_template_ids: Optional[list[str]] = None,
        approval_mode: ApprovalMode = "solo",
        qualified_operators: int = 1,
        rollback_plan: Optional[str] = None,
        typed_confirmation: Optional[str] = None,
        incident_id: Optional[str] = None,
        policy_decision_id: Optional[str] = None,
        dry_run: bool = False,
        metadata: Optional[dict[str, Any]] = None,
    ) -> CommandRequest:
        """Record one intent to change state, with everything needed to judge it.

        Returns:
            The stored command. When ``(command_type, idempotency_key)`` has been
            seen before this is the **original** command, unchanged and not
            re-executed — the same identity the operator already has a record of.

        Raises:
            shared.common.common.BadRequestError: The command type is unknown, no
                reason was given, the blast radius could not be assessed, a
                required rollback plan is missing, or containment forbids it.
            shared.common.common.ForbiddenError: The capability is not held, or a
                class 4-5 command has no live step-up.
        """
        spec = require_command_spec(command_type)

        if not (reason or "").strip():
            raise BadRequestError(
                "a command requires a reason; an unexplained state change is "
                "indistinguishable from an incident"
            )
        if not (idempotency_key or "").strip():
            raise BadRequestError(
                "a command requires an idempotency key; without one the same "
                "request twice is two state changes"
            )

        # The lookup below and the write at the bottom of this method are two
        # halves of one decision with six awaits between them. Serializing the
        # key closes that window inside this process; `_persist_new` closes it
        # between processes.
        async with _serialized_on(f"request:{command_type}:{idempotency_key}"):
            existing_row = await self._commands.find_by_idempotency(
                command_type, idempotency_key
            )
            if existing_row is not None:
                return await self._replay(
                    CommandRequest(**_strip_row(existing_row)),
                    requested_by=requested_by,
                    idempotency_key=idempotency_key,
                )

            self._assert_capability(spec, capabilities)

            command = CommandRequest(
                command_type=command_type,
                requested_by=requested_by,
                session_id=session_id,
                device_id=device_id,
                environment=environment,
                tenant_ids=list(tenant_ids or ()),
                resource_ids=list(resource_ids or ()),
                reason=reason.strip(),
                action_class=spec.action_class,
                dry_run=dry_run,
                idempotency_key=idempotency_key,
                rollback_plan=rollback_plan,
                verification_plan=list(spec.verification_checks),
                approval_mode=approval_mode,
                incident_id=incident_id,
                policy_decision_id=policy_decision_id,
                metadata=dict(metadata or {}),
            )

            stepped_up = await self._assert_step_up(spec, session_id)
            command.step_up_verified = stepped_up

            # Assessed BEFORE anything is approved, and an unavailable assessment
            # is a refusal. A command whose reach nobody measured is precisely
            # the one an approver cannot meaningfully approve.
            target = dispatch.containment_target(command, spec)
            radius = await compute_blast_radius(
                command_type=command_type,
                tenant_ids=list(command.tenant_ids),
                resource_ids=list(command.resource_ids),
                environment=environment,
                scope=target[0] if target else None,
                target=target[1] if target else None,
            )
            if radius.get("available") is False:
                await self._audit(
                    command,
                    actor_id=requested_by,
                    event_type="kyber.command.blast_radius_unavailable",
                    action="request",
                    outcome="blocked",
                    metadata={"reason": radius.get("reason")},
                )
                raise BadRequestError(
                    "the blast radius for this command could not be assessed "
                    f"({radius.get('reason')}); a command whose reach is unknown is "
                    f"refused rather than assumed small",
                    details={"blast_radius": radius},
                )
            command.blast_radius = radius

            if spec.requires_rollback_plan and not (command.rollback_plan or "").strip():
                await self._audit(
                    command,
                    actor_id=requested_by,
                    event_type="kyber.command.rollback_plan_missing",
                    action="request",
                    outcome="blocked",
                )
                raise BadRequestError(
                    f"{command_type!r} requires a written rollback plan before it may "
                    f"be requested",
                    details={"gap": "rollback_plan"},
                )

            templates = list(role_template_ids or ())
            command.metadata.setdefault("founder_authority", approval_policy.is_founder(templates))
            command.metadata.setdefault("role_template_ids", templates)
            if typed_confirmation is not None:
                command.metadata["typed_confirmation"] = typed_confirmation

            command.required_approvals = approval_policy.required_approvals(
                spec, mode=approval_mode, qualified_operators=qualified_operators
            )
            if approval_policy.fallback_to_solo(
                spec, mode=approval_mode, qualified_operators=qualified_operators
            ):
                # Visible rather than convenient: a fallback nobody can see is
                # indistinguishable from a policy that never required a second
                # actor.
                command.metadata["approval_fallback_to_solo"] = True
                command.approval_mode = "solo"

            blocked = await self._containment_refusal(command, spec)
            if blocked is not None:
                await self._audit(
                    command,
                    actor_id=requested_by,
                    event_type="kyber.command.containment_blocked",
                    action="request",
                    outcome="blocked",
                    metadata={"reason": blocked},
                )
                raise BadRequestError(blocked, details={"gap": "containment"})

            gaps = approval_policy.approval_gaps(command, spec)
            command.metadata["approval_gaps"] = gaps
            command.status = "awaiting_approval" if gaps else "approved"

            winner = await self._persist_new(command)
            if winner is not None:
                return await self._replay(
                    winner, requested_by=requested_by, idempotency_key=idempotency_key
                )

        metrics.increment(
            "kyber_command_requested_total",
            labels={"command_type": command_type, "action_class": str(spec.action_class)},
        )
        await self._audit(
            command,
            actor_id=requested_by,
            event_type="kyber.command.requested",
            action="request",
            metadata={
                "approval_gaps": gaps,
                "required_approvals": command.required_approvals,
                "verification_plan": command.verification_plan,
            },
        )
        logger.info(
            f"kyber: command {command.command_id} ({command_type}) requested by "
            f"{requested_by} status={command.status} gaps={gaps}"
        )
        return command

    async def _replay(
        self, existing: CommandRequest, *, requested_by: str, idempotency_key: str
    ) -> CommandRequest:
        """Record that a repeated key returned the first command, and return it.

        Reached from both halves of the idempotency guard — the lookup that
        found the earlier command, and the unique index that refused a
        concurrent second one — because they are the same event observed at
        different moments and must leave the same evidence.
        """
        await self._audit(
            existing,
            actor_id=requested_by,
            event_type="kyber.command.idempotent_replay",
            action="request",
            metadata={"original_command_id": existing.command_id},
        )
        metrics.increment(
            "kyber_command_idempotent_replay_total",
            labels={"command_type": existing.command_type},
        )
        logger.info(
            f"kyber: command request for {existing.command_type} idempotency_key="
            f"{idempotency_key} returned existing {existing.command_id}"
        )
        return existing

    async def _persist_new(self, command: CommandRequest) -> Optional[CommandRequest]:
        """Write a command for the first time, yielding to whoever won its key.

        Returns:
            ``None`` when this call wrote the command, or the **winning**
            command when the unique index refused the insert.

        ``ux_kyber_command_idempotency`` is unique on ``(command_type,
        idempotency_key)``, so when two workers both pass the lookup PostgreSQL
        refuses the second insert. That refusal is not a failure to surface — it
        is the index answering the same question the lookup asked, a moment
        later — and turning it into a 500 would break exactly the retry path the
        lookup exists to smooth. Only SQLSTATE 23505 is caught; see
        :func:`_is_unique_violation` for why nothing wider is.

        On the in-memory backend there is no index, and no second process either
        — the store is a dict in this one — so the lock the caller holds is the
        whole guarantee and this always returns ``None``.
        """
        try:
            await self._persist(command)
        except Exception as exc:
            if not _is_unique_violation(exc):
                raise
            row = await self._commands.find_by_idempotency(
                command.command_type, command.idempotency_key
            )
            if row is None:  # pragma: no cover - index refused an insert with no winner
                raise
            return CommandRequest(**_strip_row(row))
        return None

    # ── Reads ────────────────────────────────────────────────────────────────

    async def get(self, command_id: str) -> Optional[CommandRequest]:
        """One command, or ``None``."""
        row = await self._commands.find_by_id(command_id)
        return CommandRequest(**_strip_row(row)) if row else None

    async def require(self, command_id: str) -> CommandRequest:
        command = await self.get(command_id)
        if command is None:
            raise NotFoundError(f"kyber command {command_id}")
        return command

    async def describe(self, command_id: str) -> dict[str, Any]:
        """A command with its latest execution and verification.

        The verification is included even when it is ``None``, and the caller
        must render that as "not verified" rather than omitting it. An absent
        field reads as an absent question; the whole point of
        ``executed_unverified`` is that the question was asked and is still open.
        """
        command = await self.require(command_id)
        execution = await self._executions.latest_for_command(command_id)
        verification_row = await self._verifications.latest_for_command(command_id)
        return {
            "command": command.model_dump(),
            "spec": COMMAND_REGISTRY[command.command_type].model_dump()
            if command.command_type in COMMAND_REGISTRY
            else None,
            "execution": _strip_row(execution) if execution else None,
            "executions": [
                _strip_row(row) for row in await self._executions.list_for_command(command_id)
            ],
            "verification": _strip_row(verification_row) if verification_row else None,
            "verified": command.status == "verified",
            "generated_at": now_iso(),
        }

    async def list_commands(
        self,
        *,
        status: Optional[str] = "open",
        command_type: Optional[str] = None,
        limit: int = 100,
        tenant_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Commands by status, newest first.

        ``tenant_id`` narrows to one tenant scope (M8-D3): the mobile action
        digest binds its open-command list to the operator's resolved scope so a
        tenant-scoped operator never sees another tenant's commands. ``None``
        keeps the global list the ops ``/commands`` routes expose under
        ``kyber.audit.read``.
        """
        rows = await self._commands.list_by_status(
            status, command_type=command_type, limit=limit, tenant_id=tenant_id
        )
        return [_strip_row(row) for row in rows]

    # ── Approval ─────────────────────────────────────────────────────────────

    async def approve(
        self, command_id: str, *, approver_id: str, role_template_ids: Optional[list[str]] = None
    ) -> CommandRequest:
        """Attach one approval and re-evaluate what is still missing.

        Every refusal — self-approval, an unqualified approver, the same operator
        twice — is enforced and audited inside
        :meth:`~services.kyber.ops.approvals.ApprovalPolicy.record_approval`.
        Re-implementing any of them here would create a second second-actor rule.
        """
        command = await self.require(command_id)
        spec = require_command_spec(command.command_type)
        await approval_policy.record_approval(
            command,
            approver_id=approver_id,
            role_template_ids=list(role_template_ids or ()),
            spec=spec,
        )
        # `record_approval` recomputes the gaps against `spec` itself, so this is
        # not a second evaluation — it is the same one, read back, so that a
        # command whose approval count is still short also lands in a coherent
        # status rather than keeping whatever it had.
        gaps = approval_policy.approval_gaps(command, spec)
        command.metadata["approval_gaps"] = gaps
        command.status = "approved" if not gaps else "awaiting_approval"
        await self._persist(command)
        logger.info(
            f"kyber: command {command_id} approved by {approver_id}; remaining gaps={gaps}"
        )
        return command

    # ── Dry run ──────────────────────────────────────────────────────────────

    async def dry_run(self, command_id: str, *, actor_id: str) -> dict[str, Any]:
        """Resolve and bind the command's handler without calling it.

        A dry run that only echoed the request back would prove nothing. This one
        proves the handler exists, that the arguments bind against its real
        signature, and what containment switch (if any) the command will flip —
        the three failures that would otherwise surface mid-execution.
        """
        command = await self.require(command_id)
        if command.status in _TERMINAL_STATUSES:
            raise BadRequestError(
                f"command {command_id} is {command.status!r}; there is nothing left to dry-run"
            )
        spec = require_command_spec(command.command_type)

        plan = await dispatch.plan(command, spec)
        command.metadata["dry_run_plan"] = plan
        command.metadata["dry_run_command_id"] = command.command_id
        command.metadata["dry_run_at"] = now_iso()
        command.status = "dry_run_complete"
        command.metadata["approval_gaps"] = approval_policy.approval_gaps(command, spec)
        await self._persist(command)

        await self._audit(
            command,
            actor_id=actor_id,
            event_type="kyber.command.dry_run",
            action="dry_run",
            metadata={"handler": plan.get("handler"), "follow_up": plan.get("follow_up")},
        )
        return plan

    # ── Execution ────────────────────────────────────────────────────────────

    async def execute(self, command_id: str, *, actor_id: str) -> dict[str, Any]:
        """Dispatch a command, then go and check whether it worked.

        Returns:
            ``{"command", "execution", "verification"}``. The command's status is
            ``verified`` only when every declared postcondition passed;
            ``executed_unverified`` when one failed or could not be determined
            (with the failing check named); ``failed`` only when the handler
            itself did not complete.

        Raises:
            shared.common.common.BadRequestError: An approval gate, dry run,
                rollback plan or containment switch still stands in the way.

        Concurrent calls for one command are serialized on its id and only one
        of them dispatches; the others observe the claim and return the recorded
        outcome. The lock is held across the dispatch deliberately: a caller
        that waited gets the settled command rather than a snapshot of one
        mid-flight, and commands with different ids never wait on each other.
        """
        async with _serialized_on(f"execute:{command_id}"):
            return await self._execute_claimed(command_id, actor_id=actor_id)

    async def _execute_claimed(self, command_id: str, *, actor_id: str) -> dict[str, Any]:
        """The body of :meth:`execute`, run with the command's lock held."""
        command = await self.require(command_id)
        spec = require_command_spec(command.command_type)

        # Idempotent on the command as well as on the key: a second execute call
        # must not become a second side effect. ``executing`` counts as
        # dispatched even before an execution row exists — it is the claim
        # another worker took, and the gap between that claim and its row is
        # exactly where the duplicate dispatch used to fit.
        if command.status == "executing" or await self._executions.attempt_count(command_id) > 0:
            logger.info(
                f"kyber: command {command_id} has already been dispatched; returning "
                f"the recorded outcome instead of executing again"
            )
            return await self.describe(command_id)

        if command.status not in _EXECUTABLE_STATUSES:
            raise BadRequestError(
                f"command {command_id} is {command.status!r} and cannot be executed"
            )

        gaps = approval_policy.approval_gaps(command, spec)
        if gaps:
            command.metadata["approval_gaps"] = gaps
            await self._persist(command)
            await self._audit(
                command,
                actor_id=actor_id,
                event_type="kyber.command.execution_blocked",
                action="execute",
                outcome="blocked",
                metadata={"approval_gaps": gaps},
            )
            raise BadRequestError(
                f"command {command_id} cannot execute: {', '.join(gaps)}",
                details={"approval_gaps": gaps},
            )

        blocked = await self._containment_refusal(command, spec)
        if blocked is not None:
            await self._audit(
                command,
                actor_id=actor_id,
                event_type="kyber.command.containment_blocked",
                action="execute",
                outcome="blocked",
                metadata={"reason": blocked},
            )
            raise BadRequestError(blocked, details={"gap": "containment"})

        # Captured before anything runs. There is no way to reconstruct the
        # pre-execution tenant-visible state afterwards.
        digest_before = await verification.capture_digest(command, spec)

        if not await self._claim_for_dispatch(command):
            logger.info(
                f"kyber: command {command_id} was claimed for dispatch by another "
                f"worker; returning the recorded outcome instead of executing again"
            )
            return await self.describe(command_id)
        await self._audit(
            command, actor_id=actor_id, event_type="kyber.command.executing", action="execute"
        )

        execution = await dispatch.execute(command, spec)
        await self._executions.save(
            execution.model_dump(),
            tenant_id=command.tenant_ids[0] if command.tenant_ids else "",
        )

        if execution.error and not str(execution.error).startswith("follow_up_failed:"):
            command.status = "failed"
            command.metadata["failure_reason"] = execution.error
            await self._persist(command)
            metrics.increment(
                "kyber_command_failed_total", labels={"command_type": command.command_type}
            )
            await self._audit(
                command,
                actor_id=actor_id,
                event_type="kyber.command.failed",
                action="execute",
                outcome="failed",
                metadata={"error": execution.error},
            )
            return await self.describe(command_id)

        # The honest state between "the call returned" and "the system is in the
        # state we wanted". It is written before verification runs so a crash
        # mid-verification leaves the command here rather than at `executing`.
        command.status = "executed_unverified"
        await self._persist(command)
        await self._audit(
            command,
            actor_id=actor_id,
            event_type="kyber.command.executed_unverified",
            action="execute",
            metadata={"side_effects": execution.side_effects},
        )

        result = await verification.run_verification(
            command, spec, execution, digest_before=digest_before
        )
        await self._verifications.save(
            result.model_dump(),
            tenant_id=command.tenant_ids[0] if command.tenant_ids else "",
        )
        return await self._settle(command, result, actor_id=actor_id)

    async def _claim_for_dispatch(self, command: CommandRequest) -> bool:
        """Take the exclusive right to dispatch this command.

        Returns:
            ``True`` when this call won the claim and must dispatch, ``False``
            when someone else already holds it.

        The move from an executable status to ``executing`` is the instant a
        command becomes a side effect, so it is a compare-and-set rather than a
        write. On PostgreSQL the ``UPDATE ... WHERE data->>'status' = ANY(...)``
        matches no row for every caller but the first, whatever order their
        reads happened in; a lock would order the callers inside one worker and
        say nothing at all about the second worker.

        On the in-memory backend there is no second worker — the store is a dict
        in this process — so the per-command lock the caller already holds *is*
        the compare-and-set and the write is unconditional. Both backends end
        with exactly one caller dispatching.
        """
        pool = await self._commands._ensure_pool()
        if pool is None:
            command.status = "executing"
            await self._persist(command)
            return True

        await self._commands._ensure_table()
        result = await pool.execute(
            f"""UPDATE {self._commands.table_name}
                   SET data = jsonb_set(data, '{{status}}', '"executing"'::jsonb),
                       updated_at = NOW()
                 WHERE id = $1 AND data->>'status' = ANY($2::text[])""",
            command.command_id,
            sorted(_EXECUTABLE_STATUSES),
        )
        # asyncpg returns the command tag, e.g. "UPDATE 1" / "UPDATE 0".
        claimed = str(result).rsplit(" ", 1)[-1] == "1"
        if claimed:
            command.status = "executing"
        return claimed

    async def _settle(
        self, command: CommandRequest, result: CommandVerification, *, actor_id: str
    ) -> dict[str, Any]:
        """Move the command to its final state on the verification's verdict."""
        failed_checks = [
            check["check"] for check in result.checks if check.get("outcome") == "failed"
        ]
        unknown_checks = [
            check["check"] for check in result.checks if check.get("outcome") == "inconclusive"
        ]
        command.metadata["verification_outcome"] = result.outcome
        command.metadata["failed_checks"] = failed_checks
        command.metadata["inconclusive_checks"] = unknown_checks
        command.metadata["verification_failure_reason"] = result.failure_reason

        if result.outcome == "passed":
            command.status = "verified"
        else:
            # Stays `executed_unverified`. See the module docstring: `failed`
            # would tell an operator that nothing happened, which is the more
            # dangerous thing to believe about a command whose side effect landed.
            command.status = "executed_unverified"

        await self._persist(command)
        metrics.increment(
            "kyber_command_verification_total",
            labels={"command_type": command.command_type, "outcome": result.outcome},
        )
        await self._audit(
            command,
            actor_id=actor_id,
            event_type=f"kyber.command.{'verified' if result.outcome == 'passed' else 'unverified'}",
            action="verify",
            outcome="allowed" if result.outcome == "passed" else "failed",
            metadata={
                "verification_outcome": result.outcome,
                "failed_checks": failed_checks,
                "inconclusive_checks": unknown_checks,
                "failure_reason": result.failure_reason,
            },
        )
        logger.info(
            f"kyber: command {command.command_id} settled status={command.status} "
            f"verification={result.outcome} failed={failed_checks}"
        )
        return await self.describe(command.command_id)

    # ── Re-verification ──────────────────────────────────────────────────────

    async def verify(self, command_id: str, *, actor_id: str) -> dict[str, Any]:
        """Re-run the postconditions for a command that already executed.

        Some checks are answerable only after the platform catches up — a job
        that was queued when the first verification ran may have succeeded since.
        Re-verifying is how ``executed_unverified`` legitimately becomes
        ``verified``; there is no other path, and in particular no way for an
        operator to simply mark it verified.
        """
        command = await self.require(command_id)
        if command.status not in ("executed_unverified", "verified"):
            raise BadRequestError(
                f"command {command_id} is {command.status!r}; only an executed "
                f"command has postconditions to check"
            )
        spec = require_command_spec(command.command_type)
        row = await self._executions.latest_for_command(command_id)
        execution = CommandExecution(**_strip_row(row)) if row else None

        previous = await self._verifications.latest_for_command(command_id)
        digest_before = (previous or {}).get("mirror_digest_before")

        result = await verification.run_verification(
            command, spec, execution, digest_before=digest_before
        )
        await self._verifications.save(
            result.model_dump(),
            tenant_id=command.tenant_ids[0] if command.tenant_ids else "",
        )
        return await self._settle(command, result, actor_id=actor_id)


def _strip_row(row: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Drop the BaseRepository bookkeeping columns before model construction.

    ``insert`` stamps ``id``/``created_at``/``updated_at`` onto the payload it
    stores. ``created_at`` and ``updated_at`` are real contract fields and are
    kept; ``id`` and the mirrored ``tenant_id`` column are not, and passing them
    to a pydantic model that does not declare them is a validation error rather
    than a harmless extra.
    """
    if not row:
        return {}
    return {key: value for key, value in row.items() if key not in ("id", "tenant_id")}


#: Process-wide singleton. The routes and the ops workers both call this.
command_service = CommandService()

__all__ = ["CommandService", "command_service"]
