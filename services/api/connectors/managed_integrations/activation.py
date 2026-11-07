"""Reconciled Control Plane — production activation authority (Programs B–C).

The §0–40 lane made the engine real but kept it inert: the plane was default
OFF, the operator surface was read-only, and "activation" meant flipping
environment variables. This module replaces that with a durable authority and
exposes the capability gate runtime consumers must honor.

Law:

* The readable sequence ``shadow -> detect -> plan -> r0 -> r1 -> r2 ->
  fully_managed`` is the only advance path. One step at a time; no skipping.
* ``emergency_frozen`` is reachable from any state and always allowed —
  safety never waits for readiness. ``resume`` restores the state that was
  frozen from (never advances).
* ``advance`` and ``resume`` require a readiness snapshot whose ``ready`` is
  true. The control plane does not decide readiness; it refuses to move
  without the readiness authority's decision.
* Environment flags are **hard kill switches**: they can only lower the
  effective state. Turning flags on never grants durable activation. The
  returned ``effective_state`` is the truth the runtime may act on.
* Every state change is compare-and-set on ``revision`` and leaves an
  append-only transition evidence row.

The service is deliberately transport-free: the read-only Kyber surface calls
``get``/``list``/``transitions``; a later operator command surface (Program E/F)
drives ``transition`` through the same governed service. Program C adds the
runtime-facing projection (:class:`RuntimeActivationResolver`) so schedulers and
actuator loops act only on the effective state they are granted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from connectors.managed_integrations import flags
from connectors.managed_integrations.activation_repository import (
    ControlPlaneActivationRepository,
    get_activation_repository,
)
from connectors.managed_integrations.contracts import (
    CONTROL_PLANE_ACTIVATION_ADVANCE_ORDER,
    CONTROL_PLANE_ACTIVATION_SCOPE_KINDS,
    CONTROL_PLANE_ACTIVATION_STATES,
    CONTROL_PLANE_ACTIVATION_TRANSITIONS,
    ControlPlaneActivationReadinessView,
    ControlPlaneActivationTransitionView,
    ControlPlaneActivationView,
    is_control_plane_activation_state,
    is_control_plane_activation_transition,
)

FROZEN_STATE = "emergency_frozen"
DEFAULT_STATE = "shadow"

# Effective-state blockers are stable tokens, not prose: operators, readiness
# records and tests can match on them.
BLOCKER_MASTER_KILL_SWITCH = "master_kill_switch_off"
BLOCKER_RECONCILER_KILL_SWITCH = "reconciler_kill_switch_off"
BLOCKER_SCHEDULER_KILL_SWITCH = "scheduler_kill_switch_off"
BLOCKER_EMERGENCY_FROZEN = "emergency_frozen"


class ActivationTransitionError(Exception):
    """A refused activation transition (fail closed, with a stable reason)."""

    def __init__(self, reason: str, detail: str) -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}")


@dataclass(frozen=True)
class ActivationScope:
    """The scope whose operational activation is tracked.

    ``global`` is the platform-wide default. ``tenant_environment`` is the
    narrowest useful production scope; a region keeps sovereign/multi-region
    deployments independently reconcilable.
    """

    scope_kind: str = "global"
    tenant_id: Optional[str] = None
    environment_id: Optional[str] = None
    region: str = "global"

    def __post_init__(self) -> None:
        if self.scope_kind not in CONTROL_PLANE_ACTIVATION_SCOPE_KINDS:
            raise ValueError(
                f"unknown activation scope {self.scope_kind!r} — expected one "
                f"of {CONTROL_PLANE_ACTIVATION_SCOPE_KINDS}"
            )
        if not self.region:
            raise ValueError("activation region must be non-empty")
        for field_name, value in (
            ("region", self.region),
            ("tenant_id", self.tenant_id),
            ("environment_id", self.environment_id),
        ):
            if value is not None and ":" in value:
                raise ValueError(
                    f"activation {field_name} must not contain ':' because it "
                    "is part of the scoped activation id"
                )
        if self.scope_kind == "global":
            if self.tenant_id is not None or self.environment_id is not None:
                raise ValueError(
                    "global activation scope cannot name a tenant/environment"
                )
        else:
            if not self.tenant_id or not self.environment_id:
                raise ValueError(
                    "tenant_environment activation scope requires both "
                    "tenant_id and environment_id"
                )

    @property
    def activation_id(self) -> str:
        return (
            f"rcpa:{self.scope_kind}:{self.region}:"
            f"{self.tenant_id or '-'}:{self.environment_id or '-'}"
        )


# ── state law ───────────────────────────────────────────────────────────────

_ADVANCE_INDEX: dict[str, int] = {
    state: index for index, state in enumerate(CONTROL_PLANE_ACTIVATION_ADVANCE_ORDER)
}


def activation_state_rank(state: str) -> int:
    """Rank on the ordered advance path (``emergency_frozen`` is out of band)."""
    if state == FROZEN_STATE:
        raise ValueError("emergency_frozen is an override state, not a rank")
    try:
        return _ADVANCE_INDEX[state]
    except KeyError:
        raise ValueError(
            f"unknown control-plane activation state {state!r} — expected one "
            f"of {CONTROL_PLANE_ACTIVATION_STATES}"
        ) from None


def next_activation_state(state: str) -> Optional[str]:
    """The single legal advance from ``state`` (``None`` at ``fully_managed``)."""
    index = activation_state_rank(state)
    if index + 1 >= len(CONTROL_PLANE_ACTIVATION_ADVANCE_ORDER):
        return None
    return CONTROL_PLANE_ACTIVATION_ADVANCE_ORDER[index + 1]


def effective_state(
    durable_state: str,
    *,
    enabled: bool,
    reconciler_enabled: bool,
    scheduler_enabled: bool,
) -> tuple[str, list[str]]:
    """Apply hard kill switches to a durable state.

    Returns ``(effective_state, blockers)``. Kill switches only lower; the
    master switch is inclusive (``disabled``). A frozen durable state stays
    frozen while the reconciler/scheduler flags are off — freeze is an
    authority, not a capability — but the master switch still yields
    ``disabled``; the durable freeze survives and returns when the plane is
    re-enabled.
    """
    if not is_control_plane_activation_state(durable_state):
        raise ValueError(
            f"unknown control-plane activation state {durable_state!r}"
        )
    if not enabled:
        return "disabled", [BLOCKER_MASTER_KILL_SWITCH]
    if durable_state == FROZEN_STATE:
        return FROZEN_STATE, [BLOCKER_EMERGENCY_FROZEN]

    blockers: list[str] = []
    ceiling = CONTROL_PLANE_ACTIVATION_ADVANCE_ORDER[-1]
    if not reconciler_enabled:
        ceiling = "shadow"
        blockers.append(BLOCKER_RECONCILER_KILL_SWITCH)
    if not scheduler_enabled:
        if _ADVANCE_INDEX["plan"] < _ADVANCE_INDEX[ceiling]:
            ceiling = "plan"
        blockers.append(BLOCKER_SCHEDULER_KILL_SWITCH)

    durable_rank = _ADVANCE_INDEX[durable_state]
    ceiling_rank = _ADVANCE_INDEX[ceiling]
    if durable_rank > ceiling_rank:
        return ceiling, blockers
    return durable_state, blockers


def readiness_from_controls(
    controls: dict[str, bool],
    *,
    evidence_ref: Optional[str] = None,
) -> ControlPlaneActivationReadinessView:
    """Build a readiness snapshot from per-control booleans.

    ``ready`` is true only when at least one control was evaluated and every
    named control is satisfied. This helper is for readiness adapters and
    tests; the real readiness authority supplies its own snapshot.
    """
    blockers = sorted(name for name, satisfied in controls.items() if not satisfied)
    ready = bool(controls) and not blockers
    return ControlPlaneActivationReadinessView(
        ready=ready,
        controls=dict(controls),
        blockers=blockers,
        evidence_ref=evidence_ref,
    )


def _flags() -> tuple[bool, bool, bool]:
    return flags.enabled(), flags.reconciler_enabled(), flags.scheduler_enabled()


def _empty_row(scope: ActivationScope) -> dict:
    """The synthetic no-row view (durable default ``shadow``)."""
    return {
        "activation_id": scope.activation_id,
        "scope_kind": scope.scope_kind,
        "tenant_id": scope.tenant_id,
        "environment_id": scope.environment_id,
        "region": scope.region,
        "state": DEFAULT_STATE,
        "previous_state": None,
        "frozen_from_state": None,
        "revision": 0,
        "readiness_ref": None,
        "readiness_ready": False,
        "reason": None,
        "updated_by": None,
        "created_at": None,
        "updated_at": None,
    }


def _view(row: dict) -> ControlPlaneActivationView:
    enabled, reconciler, scheduler = _flags()
    effective, blockers = effective_state(
        row["state"],
        enabled=enabled,
        reconciler_enabled=reconciler,
        scheduler_enabled=scheduler,
    )
    return ControlPlaneActivationView(
        **{
            key: row.get(key)
            for key in (
                "activation_id",
                "scope_kind",
                "tenant_id",
                "environment_id",
                "region",
                "state",
                "previous_state",
                "frozen_from_state",
                "revision",
                "readiness_ref",
                "readiness_ready",
                "reason",
                "updated_by",
                "created_at",
                "updated_at",
            )
        },
        effective_state=effective,
        effective_blockers=blockers,
    )


class ControlPlaneActivationService:
    """The durable activation authority (read + governed transitions)."""

    def __init__(
        self,
        repository: Optional[ControlPlaneActivationRepository] = None,
    ) -> None:
        self._repository = repository or get_activation_repository()

    async def get(self, scope: ActivationScope) -> ControlPlaneActivationView:
        recorded = await self.get_recorded(scope)
        if recorded is not None:
            return recorded
        return _view(_empty_row(scope))

    async def get_recorded(
        self, scope: ActivationScope
    ) -> Optional[ControlPlaneActivationView]:
        """Return the durable activation row for ``scope``, or ``None``.

        Unlike :meth:`get` this does not synthesize the default ``shadow``
        row. Runtime consumers use the distinction to inherit a parent
        (global) activation instead of treating an absent tenant row as an
        explicit shadow cap.
        """
        row = await self._repository.get(scope.activation_id)
        return _view(row) if row is not None else None

    async def list(
        self,
        *,
        scope_kind: Optional[str] = None,
        tenant_id: Optional[str] = None,
        environment_id: Optional[str] = None,
        region: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ControlPlaneActivationView]:
        rows = await self._repository.list(
            scope_kind=scope_kind,
            tenant_id=tenant_id,
            environment_id=environment_id,
            region=region,
            limit=limit,
            offset=offset,
        )
        return [_view(row) for row in rows]

    async def transitions(
        self,
        scope: ActivationScope,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        rows = await self._repository.list_transitions(
            activation_id=scope.activation_id, limit=limit, offset=offset
        )
        return [
            ControlPlaneActivationTransitionView(**row).model_dump(mode="json")
            for row in rows
        ]

    async def transition(
        self,
        scope: ActivationScope,
        transition: str,
        *,
        readiness: Optional[ControlPlaneActivationReadinessView] = None,
        actor: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> ControlPlaneActivationView:
        """Apply one governed activation transition.

        ``advance`` moves one ordered step; ``freeze`` enters
        ``emergency_frozen`` and requires a reason; ``resume`` restores the
        pre-freeze state. Advance/resume require ``readiness.ready``. A
        compare-and-set loss raises ``concurrent_transition`` so a caller never
        believes an overwritten write succeeded.
        """
        if not is_control_plane_activation_transition(transition):
            raise ActivationTransitionError(
                "unknown_transition",
                f"{transition!r} is not one of "
                f"{CONTROL_PLANE_ACTIVATION_TRANSITIONS}",
            )

        current_row = await self._repository.get(scope.activation_id)
        current = _view(current_row or _empty_row(scope))
        current_state = current.state
        reason = reason.strip() if reason else None

        if transition == "freeze":
            if current_state == FROZEN_STATE:
                raise ActivationTransitionError(
                    "already_frozen", "control plane is already emergency frozen"
                )
            if not reason:
                raise ActivationTransitionError(
                    "reason_required", "freeze requires an operator-visible reason"
                )
            next_state = FROZEN_STATE
            frozen_from_state = current_state
        elif transition == "resume":
            if current_state != FROZEN_STATE:
                raise ActivationTransitionError(
                    "not_frozen", "resume is only legal from emergency_frozen"
                )
            self._require_readiness(readiness, "resume")
            next_state = current.frozen_from_state or DEFAULT_STATE
            frozen_from_state = None
        else:  # advance
            if current_state == FROZEN_STATE:
                raise ActivationTransitionError(
                    "frozen", "resume the control plane before advancing"
                )
            self._require_readiness(readiness, "advance")
            following = next_activation_state(current_state)
            if following is None:
                raise ActivationTransitionError(
                    "terminal", "fully_managed has no further advance"
                )
            next_state = following
            frozen_from_state = None

        readiness_ready = bool(
            readiness is not None
            and readiness.controls
            and readiness.ready
            and not readiness.blockers
        )
        readiness_ref = readiness.evidence_ref if readiness is not None else None

        updated = await self._repository.apply_transition(
            activation_id=scope.activation_id,
            scope_kind=scope.scope_kind,
            tenant_id=scope.tenant_id,
            environment_id=scope.environment_id,
            region=scope.region,
            expected_revision=current.revision,
            state=next_state,
            previous_state=current_state,
            frozen_from_state=frozen_from_state,
            readiness_ref=readiness_ref,
            readiness_ready=readiness_ready,
            reason=reason,
            updated_by=actor,
            transition=transition,
        )
        if updated is None:
            raise ActivationTransitionError(
                "concurrent_transition",
                "activation revision changed while planning the transition; "
                "re-read before retrying",
            )
        return _view(updated)

    @staticmethod
    def _require_readiness(
        readiness: Optional[ControlPlaneActivationReadinessView], transition: str
    ) -> None:
        if readiness is None:
            raise ActivationTransitionError(
                "readiness_snapshot_missing",
                f"{transition} requires a readiness-authority snapshot",
            )
        if not readiness.controls:
            raise ActivationTransitionError(
                "readiness_snapshot_empty",
                f"{transition} requires a readiness snapshot with evaluated controls",
            )
        if not readiness.ready or readiness.blockers:
            blockers = ", ".join(readiness.blockers) or "ready=false"
            raise ActivationTransitionError(
                "readiness_not_ready",
                f"readiness authority denied {transition}: {blockers}",
            )


# Runtime capability vocabulary. Capabilities are monotone over the advance
# path; ``emergency_frozen`` and ``disabled`` are stops, not capability levels.
RUNTIME_CAPABILITY_OBSERVE = "observe"
RUNTIME_CAPABILITY_DETECT = "detect"
RUNTIME_CAPABILITY_PLAN = "plan"
RUNTIME_CAPABILITY_EXECUTE = "execute"
RUNTIME_CAPABILITIES: tuple[str, ...] = (
    RUNTIME_CAPABILITY_OBSERVE,
    RUNTIME_CAPABILITY_DETECT,
    RUNTIME_CAPABILITY_PLAN,
    RUNTIME_CAPABILITY_EXECUTE,
)

_RUNTIME_CAPS_BY_STATE: dict[str, frozenset[str]] = {
    "disabled": frozenset(),
    FROZEN_STATE: frozenset(),
    "shadow": frozenset({RUNTIME_CAPABILITY_OBSERVE}),
    "detect": frozenset(
        {RUNTIME_CAPABILITY_OBSERVE, RUNTIME_CAPABILITY_DETECT}
    ),
    "plan": frozenset(
        {
            RUNTIME_CAPABILITY_OBSERVE,
            RUNTIME_CAPABILITY_DETECT,
            RUNTIME_CAPABILITY_PLAN,
        }
    ),
    "r0": frozenset(RUNTIME_CAPABILITIES),
    "r1": frozenset(RUNTIME_CAPABILITIES),
    "r2": frozenset(RUNTIME_CAPABILITIES),
    "fully_managed": frozenset(RUNTIME_CAPABILITIES),
}


def runtime_capabilities(state: str) -> frozenset[str]:
    """Runtime capabilities granted by an effective activation state.

    ``shadow`` observes only; ``detect`` reconciles; ``plan`` may persist
    ChangeSets; ``r0`` and above may execute them. ``disabled`` and
    ``emergency_frozen`` grant nothing (a freeze stops the runtime loop).
    """
    try:
        return _RUNTIME_CAPS_BY_STATE[state]
    except KeyError:
        raise ValueError(
            f"unknown control-plane activation state {state!r}"
        ) from None


def combine_runtime_states(global_state: str, scoped_state: str) -> str:
    """Most restrictive of the global and tenant/environment states.

    ``disabled`` wins over everything, then ``emergency_frozen``. Otherwise
    the lower state on the ordered advance path wins: a tenant scope can
    narrow the global authority but can never exceed it.
    """
    if "disabled" in (global_state, scoped_state):
        return "disabled"
    if FROZEN_STATE in (global_state, scoped_state):
        return FROZEN_STATE
    return (
        global_state
        if activation_state_rank(global_state)
        <= activation_state_rank(scoped_state)
        else scoped_state
    )


@dataclass(frozen=True)
class RuntimeActivationDecision:
    """The activation gate one runtime sweep may act on.

    ``state`` is the combined effective state; ``global_state`` and
    ``tenant_state`` expose the inputs for observability. ``tenant_state`` is
    ``None`` when no tenant/environment row exists and the scope inherits the
    global authority.
    """

    state: str
    capabilities: frozenset[str]
    blockers: tuple[str, ...]
    global_state: str
    tenant_state: Optional[str] = None

    def can(self, capability: str) -> bool:
        return capability in self.capabilities


class RuntimeActivationResolver:
    """Resolve the effective activation decision for a runtime scope.

    The global scope is the platform authority; a tenant/environment row may
    narrow it. Missing tenant rows inherit the global state rather than
    synthesizing a shadow cap. Resolutions are cached for the lifetime of the
    resolver (one scheduler pass) so a mid-pass transition cannot make one
    sweep act at two different authority levels.
    """

    def __init__(
        self, service: Optional[ControlPlaneActivationService] = None
    ) -> None:
        self._service = service or get_activation_service()
        self._global: Optional[ControlPlaneActivationView] = None
        self._cache: dict[tuple[str, str], RuntimeActivationDecision] = {}

    async def resolve(
        self, *, tenant_id: str, environment_id: str
    ) -> RuntimeActivationDecision:
        key = (tenant_id, environment_id)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        if self._global is None:
            self._global = await self._service.get(ActivationScope())
        scoped = await self._service.get_recorded(
            ActivationScope(
                scope_kind="tenant_environment",
                tenant_id=tenant_id,
                environment_id=environment_id,
            )
        )

        tenant_state = scoped.effective_state if scoped is not None else None
        combined = combine_runtime_states(
            self._global.effective_state,
            tenant_state if tenant_state is not None else self._global.effective_state,
        )
        blockers = list(self._global.effective_blockers)
        if scoped is not None:
            for blocker in scoped.effective_blockers:
                if blocker not in blockers:
                    blockers.append(blocker)

        decision = RuntimeActivationDecision(
            state=combined,
            capabilities=runtime_capabilities(combined),
            blockers=tuple(blockers),
            global_state=self._global.effective_state,
            tenant_state=tenant_state,
        )
        self._cache[key] = decision
        return decision


_SERVICE: Optional[ControlPlaneActivationService] = None


def get_activation_service() -> ControlPlaneActivationService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = ControlPlaneActivationService()
    return _SERVICE


__all__ = [
    "ActivationScope",
    "ActivationTransitionError",
    "ControlPlaneActivationService",
    "RUNTIME_CAPABILITIES",
    "RUNTIME_CAPABILITY_DETECT",
    "RUNTIME_CAPABILITY_EXECUTE",
    "RUNTIME_CAPABILITY_OBSERVE",
    "RUNTIME_CAPABILITY_PLAN",
    "RuntimeActivationDecision",
    "RuntimeActivationResolver",
    "activation_state_rank",
    "combine_runtime_states",
    "effective_state",
    "get_activation_service",
    "next_activation_state",
    "readiness_from_controls",
    "runtime_capabilities",
]
