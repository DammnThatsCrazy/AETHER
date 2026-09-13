"""The registry of governed command types.

A command type must be *declared* before it can be requested. The declaration
is the contract: which capability authorises it, what risk class it carries,
which existing operational service does the work, and — the part that makes the
plane worth having — which postconditions the verifier will check afterwards.

Two registration rules are refusals rather than warnings, because both describe
a latent defect rather than a style preference:

* **A spec with no ``verification_checks`` cannot register.** A state change
  nobody can verify is precisely what this plane exists to prevent. Registering
  one would produce commands that reach ``executed_unverified`` and stay there
  forever with no way to ever learn whether they worked — or, worse, a plane
  that quietly treats "the call returned" as success.
* **A spec whose ``action_class`` disagrees with its capability's
  ``action_class`` cannot register.** The capability plane decides step-up,
  approval and role ceilings from the action class. If the spec said 2 while
  ``kyber.command.kill_switch`` says 5, a fleet-destructive command would route
  through the retry-grade gate. That is a privilege escalation with no attacker
  in it, which makes it the kind that survives review.

Handlers name work the platform already does. Nothing here reimplements a
retry, a requeue, a pause or a kill switch; the command plane adds authority,
evidence and verification over the existing call.
"""
from __future__ import annotations

from typing import Optional

from shared.logger.logger import get_logger

from ..access.capabilities import CAPABILITIES
from .contracts import CommandSpec

logger = get_logger("aether.kyber.command.registry")


class CommandSpecError(ValueError):
    """A command declaration that must not be allowed to register.

    Deliberately a :class:`ValueError`: an invalid declaration is a programming
    error found at import time, not a request the API should 4xx.
    """


#: Every registered command type, keyed by ``command_type``.
COMMAND_REGISTRY: dict[str, CommandSpec] = {}


def register_command(spec: CommandSpec, *, replace: bool = False) -> CommandSpec:
    """Register one command type, refusing declarations that cannot be governed.

    Args:
        spec: The declaration to register.
        replace: Allow overwriting an existing registration. Off by default so
            two modules cannot silently claim the same command type.

    Returns:
        The registered spec.

    Raises:
        CommandSpecError: When the declaration is unusable — no command type, no
            verification checks, an unknown capability, or an action class that
            disagrees with the capability's declared class.
    """
    command_type = (spec.command_type or "").strip()
    if not command_type:
        raise CommandSpecError("a command spec requires a non-empty command_type")

    if not spec.verification_checks:
        raise CommandSpecError(
            f"command {command_type!r} declares no verification_checks. A state "
            f"change whose postconditions cannot be checked is exactly what the "
            f"command plane exists to prevent: it would reach "
            f"'executed_unverified' and never leave."
        )

    capability = CAPABILITIES.get(spec.capability_id)
    if capability is None:
        raise CommandSpecError(
            f"command {command_type!r} names unknown capability "
            f"{spec.capability_id!r}; mint nothing new — use one of "
            f"{sorted(cid for cid in CAPABILITIES if cid.startswith('kyber.command.'))}"
        )

    if spec.action_class != capability.action_class:
        raise CommandSpecError(
            f"command {command_type!r} declares action_class="
            f"{spec.action_class} but capability {spec.capability_id!r} declares "
            f"action_class={capability.action_class}. A command whose risk and "
            f"capability disagree routes a high-impact action through a "
            f"lower-grade gate."
        )

    if not replace and command_type in COMMAND_REGISTRY:
        raise CommandSpecError(
            f"command {command_type!r} is already registered by "
            f"{COMMAND_REGISTRY[command_type].handler!r}"
        )

    COMMAND_REGISTRY[command_type] = spec
    logger.debug(
        f"kyber: registered command {command_type} "
        f"capability={spec.capability_id} ac={spec.action_class}"
    )
    return spec


def get_command_spec(command_type: str) -> Optional[CommandSpec]:
    """The spec for a command type, or ``None`` when it is not registered."""
    return COMMAND_REGISTRY.get(command_type)


def require_command_spec(command_type: str) -> CommandSpec:
    """The spec for a command type, raising when it is unknown.

    Raises:
        shared.common.common.BadRequestError: The command type is not
            registered. An unregistered command type is a client error, not a
            server one — there is no fallback path that runs unknown commands.
    """
    spec = COMMAND_REGISTRY.get(command_type)
    if spec is None:
        from shared.common.common import BadRequestError

        raise BadRequestError(
            f"unknown Kyber command type {command_type!r}",
            details={"registered": sorted(COMMAND_REGISTRY)},
        )
    return spec


def command_types() -> tuple[str, ...]:
    """Every registered command type, sorted."""
    return tuple(sorted(COMMAND_REGISTRY))


def specs_for_capability(capability_id: str) -> tuple[CommandSpec, ...]:
    """Every command type a capability authorises."""
    return tuple(
        spec for spec in COMMAND_REGISTRY.values() if spec.capability_id == capability_id
    )


# ── The canonical command catalog ────────────────────────────────────────────
#
# Ordered by action class so the risk gradient is readable. Each `handler` names
# a call that already exists; each `verification_checks` tuple names checks
# `verification.py` can actually run, because a check with no verifier keeps the
# command unverified forever (which is honest, but useless as a default).

_CATALOG: tuple[CommandSpec, ...] = (
    # ── class 2: retry / requeue ─────────────────────────────────────────────
    CommandSpec(
        command_type="retry_job",
        title="Retry a failed job",
        capability_id="kyber.command.retry",
        action_class=2,
        handler="services.jobs.service.JobsService.retry",
        verification_checks=("handler_reported_success", "job_retry_recorded", "job_not_failed"),
        tenant_scoped=True,
        description="Re-run one failed durable job through the jobs platform's "
                    "own retry path, so attempt accounting and max_attempts "
                    "still apply.",
    ),
    CommandSpec(
        command_type="requeue_import",
        title="Requeue a failed import",
        capability_id="kyber.command.requeue",
        action_class=2,
        handler="services.jobs.service.JobsService.enqueue",
        verification_checks=("handler_reported_success", "job_enqueued", "job_not_duplicated"),
        tenant_scoped=True,
        description="Reset a failed import session to 'approved' and re-enqueue "
                    "its durable commit job — the same recovery the Kyber "
                    "imports route performs, now audited and verified.",
    ),
    # ── class 3: replay / recompute / rebuild over a bounded window ───────────
    CommandSpec(
        command_type="replay_event_range",
        title="Replay a bounded event range",
        capability_id="kyber.command.replay",
        action_class=3,
        handler="services.jobs.service.JobsService.enqueue",
        verification_checks=("handler_reported_success", "window_bounded", "job_enqueued"),
        requires_dry_run=True,
        tenant_scoped=True,
        description="Replay events between two offsets. The window must be "
                    "bounded on both ends: an unbounded replay is a full "
                    "reprocess wearing a smaller name.",
    ),
    CommandSpec(
        command_type="recompute_measurement",
        title="Recompute a measurement window",
        capability_id="kyber.command.recompute",
        action_class=3,
        handler="services.jobs.service.JobsService.enqueue",
        verification_checks=("window_bounded", "job_enqueued", "customer_visible_parity"),
        requires_dry_run=True,
        tenant_scoped=True,
        description="Recompute a measurement over a bounded window. Tenant-"
                    "visible numbers move, so Tenant Mirror parity is part of "
                    "verification rather than an afterthought.",
    ),
    CommandSpec(
        command_type="rebuild_graph_projection",
        title="Rebuild a graph projection",
        capability_id="kyber.command.rebuild",
        action_class=3,
        handler="services.jobs.service.JobsService.enqueue",
        verification_checks=(
            "handler_reported_success", "job_enqueued", "blast_radius_within_declared",
        ),
        requires_dry_run=True,
        tenant_scoped=True,
        description="Rebuild one Kyber graph projection from its offset.",
    ),
    # ── class 4: pause / rollback ────────────────────────────────────────────
    CommandSpec(
        command_type="pause_connector",
        title="Pause a connector",
        capability_id="kyber.command.pause",
        action_class=4,
        handler="services.kyber.ops.containment.ContainmentService.activate",
        verification_checks=(
            "containment_switch_active", "blast_radius_within_declared",
            "handler_reported_success",
        ),
        requires_dry_run=True,
        requires_rollback_plan=True,
        tenant_scoped=True,
        containment_scope="connector",
        description="Stop one connector from ingesting. Reversible by "
                    "deactivating the switch, which is why the rollback plan is "
                    "mandatory and short.",
    ),
    CommandSpec(
        command_type="pause_tenant_ingestion",
        title="Pause a tenant's ingestion",
        capability_id="kyber.command.pause",
        action_class=4,
        handler="services.kyber.ops.containment.ContainmentService.activate",
        verification_checks=(
            "containment_switch_active", "blast_radius_within_declared",
            "customer_visible_parity",
        ),
        requires_dry_run=True,
        requires_rollback_plan=True,
        tenant_scoped=True,
        containment_scope="tenant",
        description="Stop all ingestion for one tenant. Immediately visible to "
                    "that tenant, so parity is verified rather than assumed.",
    ),
    CommandSpec(
        command_type="rollback_model",
        title="Roll back a model version",
        capability_id="kyber.command.rollback",
        action_class=4,
        handler="services.jobs.service.JobsService.enqueue",
        verification_checks=(
            "handler_reported_success", "job_enqueued", "blast_radius_within_declared",
        ),
        requires_dry_run=True,
        requires_rollback_plan=True,
        tenant_scoped=False,
        containment_scope="model",
        description="Pin a model back to a previous version across the fleet.",
    ),
    CommandSpec(
        command_type="rollback_release",
        title="Roll back a release",
        capability_id="kyber.command.rollback",
        action_class=4,
        handler="services.jobs.service.JobsService.enqueue",
        verification_checks=(
            "handler_reported_success", "job_enqueued", "blast_radius_within_declared",
        ),
        requires_dry_run=True,
        requires_rollback_plan=True,
        tenant_scoped=False,
        containment_scope="environment",
        description="Roll a deployment back to the previous release.",
    ),
    # ── class 5: fleet destructive ───────────────────────────────────────────
    CommandSpec(
        command_type="activate_kill_switch",
        title="Activate a kill switch",
        capability_id="kyber.command.kill_switch",
        action_class=5,
        handler="services.agent.runtime_repository.AgentRuntimeRepository.set_kill_switch",
        verification_checks=(
            "kill_switch_engaged", "containment_switch_active",
            "blast_radius_within_declared",
        ),
        requires_dry_run=True,
        requires_rollback_plan=True,
        tenant_scoped=False,
        containment_scope="global",
        description="Engage the agent-runtime kill switch and record the "
                    "matching containment switch. The broadest action Kyber can "
                    "take, and therefore the most heavily gated.",
    ),
)

for _spec in _CATALOG:
    register_command(_spec)


__all__ = [
    "COMMAND_REGISTRY",
    "CommandSpecError",
    "command_types",
    "get_command_spec",
    "register_command",
    "require_command_spec",
    "specs_for_capability",
]
