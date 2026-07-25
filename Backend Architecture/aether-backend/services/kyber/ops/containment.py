"""Containment switches and safe mode.

A containment switch is a scoped pause: stop this connector, stop this tenant's
ingestion, stop automation everywhere. Safe mode is simply the platform-wide
case of the same primitive, which is why it is not a separate mechanism with its
own state — a second emergency path is a second thing to get wrong.

Two commitments shape this module.

*Blast radius is computed before the switch flips, not after.* A global pause
whose reach nobody measured is the exact failure this plane exists to avoid: the
operator who throws it cannot tell whether they stopped a bad connector or every
customer's ingestion. The radius is therefore assessed and attached to the switch
record before it is written. When the assessor is degraded the switch still
activates — refusing to contain an incident because telemetry is down turns a
control into an outage — but it activates carrying an explicit
``available: False`` radius that no downstream gate will read as satisfied.

*Ingestion is preserved where safe.* Safe mode freezes non-essential mutations,
disables automation, pauses reward distribution and makes the Tenant Mirror
read-only. It does **not** stop ingestion: losing inbound events during an
incident converts a recoverable outage into permanent data loss, and the whole
point of the mirror going read-only is that reading stays truthful while writing
stops.

This module is the leaf of the ops plane — it imports no other ops module — so
it also hosts :class:`OpsProviders`, the provider indirection every other ops
module needs. Putting it here lets ``commands`` and ``verification`` import the
resolver at module scope without an import cycle, and keeps exactly one copy of
the "an unavailable assessor is never a passing assessor" logic.
"""
from __future__ import annotations

import importlib
import inspect
import os
from dataclasses import dataclass
from typing import Any, Optional

from repositories.repos import BaseRepository
from shared.logger.logger import get_logger, metrics

from .contracts import ContainmentScope, ContainmentSwitch, now_iso

logger = get_logger("aether.kyber.command.containment")

# ── Safe mode definition ─────────────────────────────────────────────────────

#: The marker control. Its presence at global scope *is* safe mode.
SAFE_MODE_CONTROL = "safe_mode"

#: What safe mode pauses. ``safe_mode`` leads so a partial activation is still
#: detectable: the marker is written last, so a half-applied safe mode never
#: reports itself as active.
SAFE_MODE_CONTROLS: tuple[str, ...] = (
    "non_essential_mutations",
    "automation",
    "reward_distribution",
    "tenant_mirror_writes",
    SAFE_MODE_CONTROL,
)

#: What safe mode deliberately leaves running. Documented in the switch record
#: so an operator reading it later does not assume ingestion stopped too.
SAFE_MODE_PRESERVED: tuple[str, ...] = ("ingestion",)

#: The control that gates the command plane itself.
COMMAND_CONTROL = "kyber_commands"


def current_environment() -> str:
    """The environment this process is actually running in.

    Two call sites previously hard-coded ``"local"``, so every containment
    switch — including safe mode, the broadest control the platform has —
    recorded a blast radius reading "every service, every tenant and every
    feature in **local**" while freezing production. An operator reviewing that
    record afterwards would be reading about a machine that was never involved,
    and the record is the entire point of computing the radius before flipping
    the switch.
    """
    return os.getenv("AETHER_ENV", "local")

#: Controls a paused platform must still allow, because they are how an operator
#: contains the incident. Locking these out with everything else would mean the
#: only way to widen containment is to first remove it.
ESSENTIAL_COMMAND_TYPES: frozenset[str] = frozenset(
    {"activate_kill_switch", "pause_connector", "pause_tenant_ingestion"}
)


# ── Provider indirection ─────────────────────────────────────────────────────


@dataclass
class OpsProviders:
    """The outward dependencies of the ops plane, resolved indirectly.

    Every field defaults to ``None``, and ``None`` means *the caller must fail
    closed*, never *assume success*. The indirection exists so the graph, mirror
    and exception planes can be built in parallel with this one, and so tests can
    substitute fakes without patching module globals.
    """

    #: ``services.kyber.identity.principals.principal_service``
    principals: Any = None
    #: ``services.kyber.access.scopes.access_scope_service``
    scopes: Any = None
    #: ``services.kyber.sessions.step_up.step_up_service``
    step_up: Any = None
    #: ``services.kyber.graph.blast_radius`` (module or singleton)
    blast_radius: Any = None
    #: ``services.kyber.mirror.parity`` (module or singleton)
    mirror_parity: Any = None
    #: ``services.kyber.ops.exceptions.exception_service``
    exceptions: Any = None

    def missing(self) -> list[str]:
        """Names of the providers that failed to resolve."""
        return [
            name
            for name in (
                "principals", "scopes", "step_up", "blast_radius",
                "mirror_parity", "exceptions",
            )
            if getattr(self, name) is None
        ]


#: Optional planes, resolved by ``importlib`` because the ops plane must start
#: in a tree where a downstream plane has not landed yet.
#:
#: Each entry names ONE singleton. An earlier revision listed several candidate
#: names per plane and fell back to the module itself when none matched — which
#: is precisely what happened: the graph plane's singleton is
#: ``kyber_blast_radius_service``, the probe looked for ``blast_radius_service``,
#: and every assessment silently reported "assessor unavailable" forever. A
#: guessed name that misses does not fail; it degrades, and a degraded blast
#: radius refuses every class 4/5 command with a reason that reads like an
#: outage. Name it exactly, and let a rename be a loud import error instead.
_OPTIONAL_PROVIDER_SPECS: tuple[tuple[str, str, str], ...] = (
    ("blast_radius", "services.kyber.graph.blast_radius", "kyber_blast_radius_service"),
    ("mirror_parity", "services.kyber.mirror.parity", "digest_tenant_visible"),
    ("exceptions", "services.kyber.ops.exceptions", "exception_service"),
)

_providers: Optional[OpsProviders] = None


def _resolve_ops_providers() -> OpsProviders:
    resolved = OpsProviders()

    try:
        from services.kyber.access.dependencies import get_providers

        resolved.principals = get_providers().principals
    except Exception as exc:  # pragma: no cover - access plane unavailable
        logger.warning(f"kyber: ops principals provider unavailable: {exc}")

    try:
        from services.kyber.access.scopes import access_scope_service

        resolved.scopes = access_scope_service
    except Exception as exc:  # pragma: no cover - scope plane unavailable
        logger.warning(f"kyber: ops scope provider unavailable: {exc}")

    try:
        from services.kyber.sessions.step_up import step_up_service

        resolved.step_up = step_up_service
    except Exception as exc:  # pragma: no cover - session plane unavailable
        logger.warning(f"kyber: ops step-up provider unavailable: {exc}")

    for attr, module_path, singleton in _OPTIONAL_PROVIDER_SPECS:
        try:
            module = importlib.import_module(module_path)
        except ImportError:
            logger.info(f"kyber: optional ops provider {attr!r} absent ({module_path})")
            continue
        target = getattr(module, singleton, None)
        if target is None:
            # The module is here and the name is not. That is drift, not
            # absence, and it must not read like a plane that never landed —
            # the distinction is the difference between "not deployed yet" and
            # "deployed and silently broken".
            logger.error(
                f"kyber: ops provider {attr!r} — {module_path} imported but has no "
                f"{singleton!r}; this is a rename, not a missing plane"
            )
            continue
        setattr(resolved, attr, target)
    return resolved


def get_ops_providers() -> OpsProviders:
    """The resolved provider set, imported lazily and cached."""
    global _providers
    if _providers is None:
        _providers = _resolve_ops_providers()
        missing = _providers.missing()
        if missing:
            logger.warning(f"kyber: ops providers missing, callers fail closed: {missing}")
    return _providers


def set_ops_providers(providers: OpsProviders) -> None:
    """Install a provider set. Tests use this instead of patching globals."""
    global _providers
    _providers = providers


def reset_ops_providers() -> None:
    """Forget the cached provider set so the next call re-resolves."""
    global _providers
    _providers = None


# ── Blast radius and mirror parity ───────────────────────────────────────────

#: The one method the graph plane exposes for a blast-radius review. Pinned, not
#: probed: see the note on ``_OPTIONAL_PROVIDER_SPECS``.
_BLAST_RADIUS_ATTR = "for_subject"

#: A containment scope names what a command reaches; this maps it onto the
#: Kyber Graph subject type that anchors the walk. ``global`` has no single
#: anchor — a platform-wide action's reach is the whole graph, and pretending
#: one node stands for it would understate it — so it is deliberately absent and
#: produces an explicit "not assessable from one subject" record instead.
_SCOPE_SUBJECT_TYPES: dict[str, str] = {
    "environment": "Deployment",
    "region": "Deployment",
    "tenant": "Tenant",
    "feature": "FeatureSurface",
    "connector": "Service",
    "worker": "WorkerRole",
    "model": "ModelDeployment",
}


async def _call_filtered(fn: Any, kwargs: dict[str, Any]) -> Any:
    """Call ``fn`` with only the keywords its signature accepts.

    The assessor is built by another worker; passing a keyword it does not take
    would raise ``TypeError`` and read, to a ``try/except``, exactly like the
    plane being unavailable. Filtering makes a real answer reachable and keeps a
    genuine absence distinguishable from a signature mismatch.
    """
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):  # pragma: no cover - C callables
        sig = None
    if sig is not None and not any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    ):
        kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}
    result = fn(**kwargs)
    if inspect.isawaitable(result):
        result = await result
    return result


def unavailable_blast_radius(reason: str, *, module: str) -> dict[str, Any]:
    """The explicit record of an assessment that could not be made.

    Returning this rather than ``None`` or ``{}`` is deliberate: every gate that
    consults a blast radius checks ``available``, so a degraded assessor produces
    a value that refuses rather than a falsy value that might be skipped.
    """
    return {
        "available": False,
        "reason": reason,
        "missing_inputs": [module],
        "computed_at": now_iso(),
    }


async def compute_blast_radius(
    *,
    command_type: Optional[str] = None,
    tenant_ids: Optional[list[str]] = None,
    resource_ids: Optional[list[str]] = None,
    environment: str = "local",
    scope: Optional[str] = None,
    target: Optional[str] = None,
) -> dict[str, Any]:
    """Assess what an action would reach, always returning a record.

    Returns:
        A dict with ``available: True`` and whatever the assessor reported, or
        an :func:`unavailable_blast_radius` record. Never ``None`` — a caller
        must be able to attach *something* that says what is known.
    """
    provider = get_ops_providers().blast_radius
    if provider is None:
        return unavailable_blast_radius(
            "blast_radius_assessor_unavailable", module="services.kyber.graph.blast_radius"
        )

    fn = getattr(provider, _BLAST_RADIUS_ATTR, None)
    if not callable(fn):
        return unavailable_blast_radius(
            f"blast_radius_assessor_has_no_{_BLAST_RADIUS_ATTR}",
            module="services.kyber.graph.blast_radius",
        )

    if (scope or "").strip().lower() == "global":
        return _platform_wide_blast_radius(command_type=command_type, environment=environment)

    subject_type, subject_id, subject_tenant = _command_subject(
        scope=scope, target=target, tenant_ids=tenant_ids, resource_ids=resource_ids
    )
    if subject_type is None:
        # No single node anchors this action. Saying so beats assessing an
        # arbitrary one and presenting a narrow answer as the whole reach.
        return unavailable_blast_radius(
            f"no_single_subject_for_scope:{scope or 'unscoped'}",
            module="services.kyber.graph.blast_radius",
        )

    try:
        raw = await _call_filtered(
            fn,
            {
                "subject_type": subject_type,
                "subject_id": subject_id,
                "environment": environment,
                "tenant_id": subject_tenant,
            },
        )
    except Exception as exc:
        logger.warning(f"kyber: blast radius assessment failed for {command_type}: {exc}")
        return unavailable_blast_radius(
            f"blast_radius_assessment_failed:{exc}",
            module="services.kyber.graph.blast_radius",
        )

    if raw is None:
        return unavailable_blast_radius(
            "blast_radius_assessor_returned_none",
            module="services.kyber.graph.blast_radius",
        )
    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    if not isinstance(raw, dict):
        raw = {"summary": str(raw)}
    return {
        **raw,
        "available": True,
        "source": f"services.kyber.graph.blast_radius.{_BLAST_RADIUS_ATTR}",
        "subject_type": subject_type,
        "subject_id": subject_id,
        "computed_at": now_iso(),
    }


def _platform_wide_blast_radius(
    *, command_type: Optional[str], environment: str
) -> dict[str, Any]:
    """The reach of a platform-wide action, which is known rather than unknown.

    A global kill switch has no anchor node, but that is not the same as an
    unassessable reach: the answer is *everything*, and it is certain. Returning
    an ``unavailable`` record here would be the worst of both worlds — the
    command plane refuses on an unavailable blast radius, so the single most
    important emergency control would be permanently unusable, and the reason
    shown to the operator would read like a broken dependency rather than the
    deliberate breadth of what they asked for.
    """
    return {
        "available": True,
        "source": "services.kyber.ops.containment._platform_wide_blast_radius",
        "subject_type": "OlympusPlatform",
        "subject_id": environment,
        "environment": environment,
        "exposure_known": True,
        "missing_inputs": [],
        "scope": "global",
        "customer_visible": True,
        "confidence": 1.0,
        "summary": (
            f"{command_type or 'action'} is platform-wide: every service, every "
            f"tenant and every feature in {environment} is in reach"
        ),
        "computed_at": now_iso(),
    }


def _command_subject(
    *,
    scope: Optional[str],
    target: Optional[str],
    tenant_ids: Optional[list[str]],
    resource_ids: Optional[list[str]],
) -> tuple[Optional[str], str, Optional[str]]:
    """The one graph subject a command's reach is anchored to.

    Returns ``(subject_type, subject_id, tenant_id)``, or ``(None, "", None)``
    when no single subject stands for the action.

    A command naming several tenants is anchored on the first, and the caller
    is told which via ``subject_id`` on the result. Summing reach across tenants
    is deliberately not done here: ``services/agent_access_intelligence/
    kyber_ops_routes.py`` records why — a cross-tenant total hides exactly the
    tenants whose inputs were missing, so it reads confident precisely where it
    is least reliable.
    """
    tenants = [t for t in (tenant_ids or ()) if t]
    resources = [r for r in (resource_ids or ()) if r]
    tenant_id = tenants[0] if tenants else None
    normalized_scope = (scope or "").strip().lower()

    if normalized_scope == "global":
        return None, "", None

    subject_type = _SCOPE_SUBJECT_TYPES.get(normalized_scope)
    if subject_type is not None:
        if subject_type == "Tenant":
            anchor = target or tenant_id
            return ("Tenant", anchor, anchor) if anchor else (None, "", None)
        anchor = target or (resources[0] if resources else None)
        return (subject_type, anchor, tenant_id) if anchor else (None, "", None)

    # Unscoped commands (retry, requeue, replay, recompute, rebuild) act inside
    # one tenant, so the tenant node is the honest anchor.
    if tenant_id:
        return "Tenant", tenant_id, tenant_id
    return None, "", None


async def mirror_digest(
    *, tenant_ids: Optional[list[str]] = None, environment: str = "local"
) -> Optional[str]:
    """A Tenant Mirror digest, or ``None`` when parity cannot be determined.

    ``None`` is a real answer here and must be propagated as ``None``: assuming
    parity held because the comparison was unavailable is the single most
    misleading thing verification could do.
    """
    fn = get_ops_providers().mirror_parity
    if not callable(fn):
        return None
    try:
        raw = await _call_filtered(
            fn, {"tenant_ids": list(tenant_ids or ()), "environment": environment}
        )
    except Exception as exc:
        logger.warning(f"kyber: mirror digest failed: {exc}")
        return None
    if raw is None:
        return None
    # ``digest_tenant_visible`` returns a ParityDigest; the verifier only ever
    # compares digests for equality, so the digest string is the whole answer.
    return str(getattr(raw, "digest", raw))


# ── Storage ──────────────────────────────────────────────────────────────────


class ContainmentSwitchRepository(BaseRepository):
    """JSONB store for ``kyber_containment_switches``.

    Uniqueness of ``(scope, target, control)`` among *active* rows is enforced by
    the partial unique index ``ux_kyber_containment_active``; this class reads
    through the same expressions so the constraint guards the path that is
    actually used.
    """

    def __init__(self) -> None:
        super().__init__("kyber_containment_switches")


# ── The service ──────────────────────────────────────────────────────────────


class ContainmentService:
    """Activate, deactivate and query scoped pauses, including safe mode."""

    def __init__(self, repo: Optional[ContainmentSwitchRepository] = None) -> None:
        self._repo = repo or ContainmentSwitchRepository()

    # ── Activation ───────────────────────────────────────────────────────────

    async def activate(
        self,
        *,
        scope: ContainmentScope,
        target: Optional[str],
        control: str,
        actor_id: str,
        reason: str,
        blast_radius: Optional[dict[str, Any]] = None,
    ) -> ContainmentSwitch:
        """Flip a scoped pause on, with its reach assessed first.

        Idempotent: an already-active switch for the same
        ``(scope, target, control)`` is returned unchanged rather than
        duplicated, matching the partial unique index.

        Raises:
            shared.common.common.BadRequestError: No reason, or no control.
        """
        from shared.common.common import BadRequestError

        control = (control or "").strip()
        if not control:
            raise BadRequestError("a containment switch requires a control")
        if not (reason or "").strip():
            raise BadRequestError(
                "a containment switch requires a reason; an unexplained pause is "
                "indistinguishable from an outage"
            )

        existing = await self._find_active(scope, target, control)
        if existing is not None:
            logger.info(
                f"kyber: containment already active scope={scope} target={target} "
                f"control={control}"
            )
            return existing

        # Computed BEFORE the switch exists. A pause whose reach was measured
        # afterwards is a pause nobody chose.
        radius = blast_radius or await compute_blast_radius(
            command_type=f"containment:{control}",
            tenant_ids=[target] if scope == "tenant" and target else [],
            environment=current_environment(),
            scope=scope,
            target=target,
        )
        unknown = radius.get("available") is False
        if unknown and scope in ("global", "environment"):
            logger.error(
                f"kyber: activating {scope} containment control={control} with an "
                f"UNKNOWN blast radius ({radius.get('reason')}). Containment is "
                f"not blocked on telemetry, but the switch records that its reach "
                f"was never measured."
            )

        switch = ContainmentSwitch(
            scope=scope,
            target=target,
            control=control,
            active=True,
            reason=reason.strip(),
            activated_by=actor_id,
            activated_at=now_iso(),
            blast_radius=radius,
            metadata={
                "blast_radius_unknown": unknown,
                "preserves": list(SAFE_MODE_PRESERVED) if control in SAFE_MODE_CONTROLS else [],
            },
        )
        await self._repo.insert(switch.switch_id, switch.model_dump())

        metrics.gauge(
            "kyber_containment_active", 1, labels={"scope": scope, "control": control}
        )
        await self._audit(
            switch,
            actor_id=actor_id,
            event_type="kyber.containment.activated",
            action="activate",
            outcome="allowed",
        )
        logger.warning(
            f"kyber: containment ACTIVATED scope={scope} target={target} "
            f"control={control} by={actor_id}"
        )
        return switch

    async def deactivate(
        self,
        *,
        scope: ContainmentScope,
        target: Optional[str],
        control: str,
        actor_id: str,
        reason: str = "",
    ) -> Optional[ContainmentSwitch]:
        """Flip a scoped pause off. Returns ``None`` when none was active."""
        switch = await self._find_active(scope, target, control)
        if switch is None:
            return None
        switch.active = False
        switch.deactivated_by = actor_id
        switch.deactivated_at = now_iso()
        switch.metadata = {**switch.metadata, "deactivation_reason": reason}
        await self._repo.update(switch.switch_id, switch.model_dump())

        metrics.gauge(
            "kyber_containment_active", 0, labels={"scope": scope, "control": control}
        )
        await self._audit(
            switch,
            actor_id=actor_id,
            event_type="kyber.containment.deactivated",
            action="deactivate",
            outcome="allowed",
        )
        logger.warning(
            f"kyber: containment released scope={scope} target={target} "
            f"control={control} by={actor_id}"
        )
        return switch

    # ── Queries ──────────────────────────────────────────────────────────────

    async def active_switches(
        self,
        *,
        scope: Optional[str] = None,
        control: Optional[str] = None,
        target: Optional[str] = None,
        limit: int = 200,
    ) -> list[ContainmentSwitch]:
        """Every currently-active switch, optionally filtered."""
        rows = await self._repo.find_many({"active": True}, limit=max(limit, 1) * 4)
        switches = [ContainmentSwitch(**row) for row in rows]
        out = [
            s
            for s in switches
            if s.active
            and (scope is None or s.scope == scope)
            and (control is None or s.control == control)
            and (target is None or s.target == target)
        ]
        return out[:limit]

    async def is_paused(
        self,
        control: str,
        *,
        scope: Optional[str] = None,
        target: Optional[str] = None,
    ) -> bool:
        """Whether a control is currently paused for this scope and target.

        A broader switch covers a narrower target: a ``global`` switch, or a
        switch with no ``target``, pauses every target under it. Asking about a
        specific tenant must not miss the global pause that already stopped it.
        """
        for switch in await self.active_switches(control=control, limit=200):
            if scope is not None and switch.scope not in (scope, "global"):
                continue
            if target is not None and switch.target not in (None, "", target):
                continue
            return True
        return False

    async def describe(self) -> dict[str, Any]:
        """Body-safe containment state for the console."""
        switches = await self.active_switches(limit=200)
        return {
            "safe_mode": await self.safe_mode_active(),
            "active_count": len(switches),
            "switches": [s.model_dump() for s in switches],
            "preserved_in_safe_mode": list(SAFE_MODE_PRESERVED),
        }

    # ── Safe mode ────────────────────────────────────────────────────────────

    async def safe_mode_active(self) -> bool:
        """Whether the platform is in safe mode."""
        return await self.is_paused(SAFE_MODE_CONTROL, scope="global")

    async def activate_safe_mode(
        self, *, actor_id: str, reason: str
    ) -> list[ContainmentSwitch]:
        """Freeze the platform to the smallest safe surface.

        One blast-radius assessment is computed up front and shared by every
        switch: they are one decision, and recording six different radii for one
        act would suggest six independent choices were made.

        The ``safe_mode`` marker is written last (it is last in
        :data:`SAFE_MODE_CONTROLS`), so a partial activation never reports itself
        as a complete safe mode.
        """
        from shared.common.common import BadRequestError

        if not (reason or "").strip():
            raise BadRequestError("safe mode requires a reason")

        radius = await compute_blast_radius(
            command_type="containment:safe_mode",
            environment=current_environment(),
            scope="global",
        )
        switches: list[ContainmentSwitch] = []
        for control in SAFE_MODE_CONTROLS:
            switches.append(
                await self.activate(
                    scope="global",
                    target=None,
                    control=control,
                    actor_id=actor_id,
                    reason=reason,
                    blast_radius=radius,
                )
            )
        logger.error(
            f"kyber: SAFE MODE activated by {actor_id}: {reason} "
            f"(ingestion preserved: {list(SAFE_MODE_PRESERVED)})"
        )
        return switches

    async def deactivate_safe_mode(
        self, *, actor_id: str, reason: str = ""
    ) -> list[ContainmentSwitch]:
        """Release safe mode.

        The marker is cleared first, so a partially released safe mode reports
        itself inactive rather than trapping the platform in a state that looks
        frozen but is not.
        """
        released: list[ContainmentSwitch] = []
        for control in reversed(SAFE_MODE_CONTROLS):
            switch = await self.deactivate(
                scope="global",
                target=None,
                control=control,
                actor_id=actor_id,
                reason=reason,
            )
            if switch is not None:
                released.append(switch)
        logger.warning(f"kyber: safe mode released by {actor_id}: {reason}")
        return released

    # ── Internals ────────────────────────────────────────────────────────────

    async def _find_active(
        self, scope: str, target: Optional[str], control: str
    ) -> Optional[ContainmentSwitch]:
        for switch in await self.active_switches(control=control, limit=200):
            if switch.scope == scope and (switch.target or None) == (target or None):
                return switch
        return None

    async def _audit(
        self,
        switch: ContainmentSwitch,
        *,
        actor_id: str,
        event_type: str,
        action: str,
        outcome: str,
    ) -> None:
        try:
            from services.security.audit_ledger import audit_ledger

            await audit_ledger.record(
                actor_id=actor_id,
                actor_type="olympus_operator",
                event_type=event_type,
                resource_type="kyber_containment_switch",
                action=action,
                outcome=outcome,  # type: ignore[arg-type]
                tenant_id=switch.target if switch.scope == "tenant" else None,
                resource_id=switch.switch_id,
                metadata={
                    "scope": switch.scope,
                    "target": switch.target,
                    "control": switch.control,
                    "reason": switch.reason,
                    "blast_radius": switch.blast_radius,
                },
            )
        except Exception as exc:  # pragma: no cover - the ledger must not 500 a route
            logger.error(f"kyber: containment audit failed for {switch.switch_id}: {exc}")


#: Process-wide singleton.
containment_service = ContainmentService()

__all__ = [
    "COMMAND_CONTROL",
    "ESSENTIAL_COMMAND_TYPES",
    "SAFE_MODE_CONTROL",
    "SAFE_MODE_CONTROLS",
    "SAFE_MODE_PRESERVED",
    "ContainmentService",
    "ContainmentSwitchRepository",
    "OpsProviders",
    "compute_blast_radius",
    "containment_service",
    "get_ops_providers",
    "mirror_digest",
    "reset_ops_providers",
    "set_ops_providers",
    "unavailable_blast_radius",
]
