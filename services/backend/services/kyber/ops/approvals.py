"""Approval policy for governed commands.

Aether is run by one founder today and by a small team soon. Those two worlds
need different controls, and a policy that only models the second one produces
an unusable console on day one while a policy that only models the first is
unauditable on day two. So both modes are first-class:

**solo** — there is no second human, so a second signature cannot be the
control. What replaces it is *evidence and friction*: founder authority, a
fresh step-up, a completed dry run, a computed blast radius, a written rollback
plan, a verification plan, and typing the command type back. Zero second
approvers, seven things that must be true.

**small_team** — a second actor exists, so use one. Class 4 needs one qualified
approver; class 5 needs two distinct ones. The requester never satisfies their
own approval and never counts twice; both refusals are audited. That rule is
not re-invented here — it is the same second-actor rule
:mod:`services.security.break_glass` already enforces for emergency access, and
it is mirrored deliberately so the two paths cannot drift into disagreeing about
what self-approval means.

One deliberate softening. If the team does not actually contain enough qualified
operators to satisfy the requirement, the requirement falls back to solo rules
instead of standing there unsatisfiable. An approval gate nobody can pass is not
a control — it is an outage with a compliance story, and the operator's response
to it will be to work around the plane entirely. The fallback is logged and
audited so it is visible rather than convenient.
"""
from __future__ import annotations

from typing import Any, Optional

from shared.logger.logger import get_logger

from .contracts import ApprovalMode, CommandRequest, CommandSpec, now_iso

logger = get_logger("aether.kyber.command.approvals")

#: Role templates that carry founder authority. Solo mode rests on this.
FOUNDER_TEMPLATE_IDS: frozenset[str] = frozenset({"founder_operator", "emergency_root"})

#: Role templates whose holders may approve a class 4-5 command. Derived from
#: the role plane's ``max_action_class`` rather than restated: an approver must
#: be able to *take* the action they are approving.
QUALIFIED_APPROVER_TEMPLATE_IDS: frozenset[str] = frozenset(
    {"founder_operator", "emergency_root", "cto_engineering_command"}
)

#: The seven things solo mode substitutes for a second signature.
SOLO_GATES: tuple[str, ...] = (
    "founder_authority",
    "fresh_step_up",
    "dry_run",
    "blast_radius_review",
    "rollback_plan",
    "verification_plan",
    "typed_confirmation",
)

#: Action classes at which approval controls engage at all.
_APPROVAL_ACTION_CLASSES = (4, 5)


class ApprovalPolicy:
    """Decides how many approvals a command needs and whether it has them."""

    # ── How many ─────────────────────────────────────────────────────────────

    def required_approvals(
        self,
        spec: CommandSpec,
        *,
        mode: ApprovalMode,
        qualified_operators: int,
    ) -> int:
        """Second approvers required before this command may execute.

        Solo mode always returns 0 — there is no second human, and pretending
        otherwise would block every command. Small-team mode returns 1 for class
        4 and 2 for class 5, *unless* the team does not hold enough qualified
        operators besides the requester, in which case it falls back to solo
        rules and says so.

        Args:
            spec: The command declaration.
            mode: ``"solo"`` or ``"small_team"``.
            qualified_operators: How many operators hold a qualified approver
                role, the requester included.

        Returns:
            The number of distinct second approvers required.
        """
        if mode != "small_team" or spec.action_class not in _APPROVAL_ACTION_CLASSES:
            return 0

        needed = 2 if spec.action_class >= 5 else 1
        # The requester cannot approve their own command, so they do not count
        # toward the pool that can satisfy it.
        available = max(0, int(qualified_operators) - 1)
        if available < needed:
            logger.warning(
                f"kyber: approval fallback to solo for {spec.command_type} — "
                f"needs {needed} qualified approver(s) besides the requester but "
                f"only {available} available; solo evidence gates apply instead "
                f"of an unsatisfiable requirement"
            )
            return 0
        return needed

    def fallback_to_solo(
        self,
        spec: CommandSpec,
        *,
        mode: ApprovalMode,
        qualified_operators: int,
    ) -> bool:
        """Whether small-team mode had to degrade to solo rules.

        Separated from :meth:`required_approvals` so the caller can audit the
        degradation; a silent fallback would be indistinguishable from a policy
        that never required a second actor at all.
        """
        if mode != "small_team" or spec.action_class not in _APPROVAL_ACTION_CLASSES:
            return False
        needed = 2 if spec.action_class >= 5 else 1
        return max(0, int(qualified_operators) - 1) < needed

    def effective_mode(
        self,
        spec: CommandSpec,
        *,
        mode: ApprovalMode,
        qualified_operators: int,
    ) -> ApprovalMode:
        """The mode whose rules actually apply after any fallback."""
        if self.fallback_to_solo(spec, mode=mode, qualified_operators=qualified_operators):
            return "solo"
        return mode

    # ── Who may approve ──────────────────────────────────────────────────────

    @staticmethod
    def is_founder(role_template_ids: Any) -> bool:
        """Whether these role templates carry founder authority."""
        return bool(FOUNDER_TEMPLATE_IDS.intersection(role_template_ids or ()))

    @staticmethod
    def is_qualified_approver(role_template_ids: Any) -> bool:
        """Whether these role templates may approve a class 4-5 command."""
        return bool(QUALIFIED_APPROVER_TEMPLATE_IDS.intersection(role_template_ids or ()))

    # ── Recording an approval ────────────────────────────────────────────────

    async def record_approval(
        self,
        command: CommandRequest,
        *,
        approver_id: str,
        role_template_ids: list[str],
        spec: CommandSpec,
    ) -> CommandRequest:
        """Attach one approval, refusing and auditing every invalid one.

        Mirrors :mod:`services.security.break_glass`: self-approval is rejected
        *and* audited, because a rejection nobody can see is not evidence. The
        same-approver-twice case is rejected on the same grounds — two
        signatures from one hand is one signature.

        The returned command is mutated in place; persistence belongs to
        :class:`~services.kyber.ops.commands.CommandService`, which owns the
        row.

        Raises:
            shared.common.common.BadRequestError: The command is not awaiting
                approval, the approver is the requester, the approver has
                already approved, or the approver is not qualified.
        """
        from shared.common.common import BadRequestError

        if command.status not in ("requested", "awaiting_approval"):
            raise BadRequestError(
                f"cannot approve a command in status {command.status!r}"
            )

        if approver_id == command.requested_by:
            await self._audit(
                command,
                actor_id=approver_id,
                event_type="kyber.command.self_approval_blocked",
                outcome="blocked",
                metadata={"reason": "approver_is_requester"},
            )
            raise BadRequestError(
                "command approval requires a different operator than the requester"
            )

        already = {str(a.get("approver_id")) for a in command.approvals}
        if approver_id in already:
            await self._audit(
                command,
                actor_id=approver_id,
                event_type="kyber.command.duplicate_approval_blocked",
                outcome="blocked",
                metadata={"reason": "approver_already_counted"},
            )
            raise BadRequestError(
                "this operator has already approved; two approvals from one "
                "operator is one approval"
            )

        if command.action_class in _APPROVAL_ACTION_CLASSES and not self.is_qualified_approver(
            role_template_ids
        ):
            await self._audit(
                command,
                actor_id=approver_id,
                event_type="kyber.command.unqualified_approval_blocked",
                outcome="blocked",
                metadata={
                    "reason": "approver_not_qualified",
                    "role_template_ids": list(role_template_ids or ()),
                },
            )
            raise BadRequestError(
                "approver does not hold a role template qualified to approve a "
                f"class {command.action_class} command"
            )

        command.approvals.append(
            {
                "approver_id": approver_id,
                "role_template_ids": list(role_template_ids or ()),
                "approved_at": now_iso(),
            }
        )
        command.updated_at = now_iso()
        if len(command.approvals) >= command.required_approvals:
            # Recomputed, never filtered. An earlier revision subtracted
            # "second_approver" from the gap list stored at request time, which
            # is a snapshot: a gap satisfied since (a dry run that has now run)
            # left the command stuck at awaiting_approval with nothing an
            # operator could do about it, and a gap that APPEARED since (a
            # step-up grant that expired while the second approver was being
            # found) was silently ignored — the dangerous direction. The gap
            # list is only meaningful as of the moment it is asked for.
            gaps = self.approval_gaps(command, spec)
            command.metadata["approval_gaps"] = gaps
            command.status = "approved" if not gaps else "awaiting_approval"

        await self._audit(
            command,
            actor_id=approver_id,
            event_type="kyber.command.approved",
            outcome="allowed",
            metadata={
                "approvals": len(command.approvals),
                "required_approvals": command.required_approvals,
                "status": command.status,
            },
        )
        return command

    # ── What is still missing ────────────────────────────────────────────────

    def approval_gaps(self, command: CommandRequest, spec: CommandSpec) -> list[str]:
        """Everything still standing between this command and execution.

        The list is the whole answer: an empty list means executable, and each
        entry names one control that has not been satisfied. Returning names
        rather than a boolean is what lets the console tell an operator *what to
        do next* instead of only that they may not proceed.
        """
        gaps: list[str] = []
        high_impact = spec.action_class in _APPROVAL_ACTION_CLASSES

        # Step-up is not a mode-specific control: class 4-5 always needs one.
        if high_impact and not command.step_up_verified:
            gaps.append("fresh_step_up")

        if spec.requires_dry_run and not self._dry_run_satisfied(command):
            gaps.append("dry_run")

        if spec.requires_rollback_plan and not (command.rollback_plan or "").strip():
            gaps.append("rollback_plan")

        if high_impact and not self._blast_radius_reviewed(command):
            gaps.append("blast_radius_review")

        if command.approval_mode == "solo":
            if high_impact:
                if not command.metadata.get("founder_authority"):
                    gaps.append("founder_authority")
                if not command.verification_plan:
                    gaps.append("verification_plan")
                if command.metadata.get("typed_confirmation") != command.command_type:
                    gaps.append("typed_confirmation")
        elif len(command.approvals) < command.required_approvals:
            gaps.append("second_approver")

        # Stable, de-duplicated order so the console never reshuffles the list.
        ordered = [*SOLO_GATES, "second_approver"]
        return sorted(set(gaps), key=lambda g: ordered.index(g) if g in ordered else 99)

    @staticmethod
    def _dry_run_satisfied(command: CommandRequest) -> bool:
        """A dry run is satisfied by being one, or by referencing a completed one."""
        if command.dry_run:
            return True
        return bool(command.metadata.get("dry_run_command_id"))

    @staticmethod
    def _blast_radius_reviewed(command: CommandRequest) -> bool:
        """A blast radius counts as reviewed only when it was actually computed.

        An attached record that says ``available: False`` is the honest output of
        a degraded assessor, and it must not read as a satisfied control.
        """
        radius = command.blast_radius or {}
        return bool(radius) and radius.get("available") is not False

    # ── Audit ────────────────────────────────────────────────────────────────

    async def _audit(
        self,
        command: CommandRequest,
        *,
        actor_id: str,
        event_type: str,
        outcome: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        try:
            from services.security.audit_ledger import audit_ledger

            await audit_ledger.record(
                actor_id=actor_id,
                actor_type="olympus_operator",
                event_type=event_type,
                resource_type="kyber_command",
                action="approve",
                outcome=outcome,  # type: ignore[arg-type]
                tenant_id=command.tenant_ids[0] if command.tenant_ids else None,
                resource_id=command.command_id,
                policy_decision_id=command.policy_decision_id,
                metadata={
                    "command_type": command.command_type,
                    "approval_mode": command.approval_mode,
                    "action_class": command.action_class,
                    **(metadata or {}),
                },
            )
        except Exception as exc:  # pragma: no cover - the ledger must not 500 a route
            logger.error(f"kyber: approval audit failed for {command.command_id}: {exc}")


#: Process-wide singleton.
approval_policy = ApprovalPolicy()

__all__ = [
    "FOUNDER_TEMPLATE_IDS",
    "QUALIFIED_APPROVER_TEMPLATE_IDS",
    "SOLO_GATES",
    "ApprovalPolicy",
    "approval_policy",
]
