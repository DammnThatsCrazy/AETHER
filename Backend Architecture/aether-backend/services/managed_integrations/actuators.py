"""Reconciled Control Plane — typed actuator architecture (§36, Phase 2).

``The Reconciler does not directly mutate arbitrary systems`` (blueprint §36).
Each ChangeActionKind is handled by one registered ``Actuator`` exposing the
§36 lifecycle — ``plan/preflight/apply/verify/rollback`` where rollback is
applicable. An actuator is *decisioning plus a declared authority*: it never
fabricates a mutation. Its ``authority_ref`` names the real repo substrate that
owns the change (from the Phase-2 substrate survey); when no authority is
admitted for the current execution context, ``apply``/``rollback`` return
``not_applied`` and the executor surfaces the change as ActionRequired rather
than claiming success.

Day-1 vocabulary (§36): every kind has a registered actuator below. Where the
substrate survey found a real, reversible authority the actuator declares it;
``reversible=False`` marks changes that are themselves rollback/consequence
moves (quarantine, notification, rollback) whose *effect* is not further
undoable by this plane.

Phase-2 boundary: nothing here is triggerable in production. Executors run only
when a caller drives a ChangeSet through the governed path; no autonomous
trigger exists yet (ledger Phase-2 boundary).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel

from services.managed_integrations.contracts import (
    ChangeActionKind,
    CHANGE_ACTION_KINDS,
    ChangeSpec,
    VerifyOutcome,
)

# ── §36 typed views ───────────────────────────────────────────────────────────


class ActuatorPreflight(BaseModel):
    """§36 ``preflight(change)``: can this change run through this actuator?

    Fail-closed: an actuator without an admitted authority or with an unmet
    precondition returns ``ok=False`` with issues, never a silent success.
    """

    ok: bool
    issues: list[str] = []
    note: Optional[str] = None


class ActuatorApplyResult(BaseModel):
    """§36 ``apply(change)`` outcome.

    ``applied`` claims a real mutation with before/after state refs. Any other
    value means the change was **not** applied — the executor must surface it,
    not treat it as done.
    """

    outcome: str  # applied | not_applied
    before_state_ref: Optional[str] = None
    after_state_ref: Optional[str] = None
    detail: Optional[str] = None


class ActuatorVerifyResult(BaseModel):
    """§36 ``verify(change)`` — technical + semantic health (§32 step 19).

    An actuator that applied a change returns the health dimensions it can
    attest; an actuator that could not apply returns ``failed`` so the executor
    never commits a change that did not happen.
    """

    technical: VerifyOutcome = "passed"
    semantic: VerifyOutcome = "passed"
    note: Optional[str] = None


@dataclass(frozen=True)
class ActuatorAuthority:
    """Admitted mutation authority for one actuator kind.

    ``target_ref`` names the repo substrate function (survey-derived). A real
    authority object implementing ``apply/verify/rollback`` is supplied by the
    driving layer (tests today; the Phase-3 governed surface later); None means
    the actuator resolves to ``not_applied`` in this deployment.
    """

    kind: ChangeActionKind
    target_ref: str
    reversible: bool
    handler: Optional[object] = None


# ── §36 actuator registry ─────────────────────────────────────────────────────


class Actuator:
    """Base typed actuator. Subclasses fix ``kind`` + §36 policy methods."""

    kind: ChangeActionKind
    reversible: bool = False
    authority: Optional[ActuatorAuthority] = None

    def __init__(self, authority: Optional[ActuatorAuthority] = None) -> None:
        if authority is not None:
            assert authority.kind == self.kind, (
                f"authority kind {authority.kind} does not match actuator "
                f"kind {self.kind}"
            )
        self.authority = authority

    # §36 lifecycle
    def preflight(self, change: ChangeSpec) -> ActuatorPreflight:
        if self.authority is None or self.authority.handler is None:
            return ActuatorPreflight(
                ok=False,
                issues=[
                    "no admitted authority for "
                    f"{self.kind} in this deployment — change cannot run"
                ],
            )
        return ActuatorPreflight(ok=True, note="authority admitted")

    async def apply(self, change: ChangeSpec) -> ActuatorApplyResult:
        if self.authority is None or self.authority.handler is None:
            return ActuatorApplyResult(
                outcome="not_applied",
                detail=(
                    f"{self.kind} has no admitted authority here; "
                    "surface as ActionRequired, do not claim applied"
                ),
            )
        return await self.authority.handler.apply(change, self)

    async def verify(self, change: ChangeSpec) -> ActuatorVerifyResult:
        if self.authority is None or self.authority.handler is None:
            # Nothing could have been applied through a closed actuator, so
            # nothing is attestable — fail closed rather than claim passed.
            return ActuatorVerifyResult(
                technical="failed",
                semantic="failed",
                note=(
                    f"{self.kind} has no admitted authority here; nothing "
                    "can be verified"
                ),
            )
        handler_verify = getattr(self.authority.handler, "verify", None)
        if handler_verify is None:
            # A real apply authority admitted without an explicit verify
            # attestation; the actuator defaults stay passed (§32 step 19).
            return ActuatorVerifyResult()
        return await handler_verify(change, self)

    async def rollback(self, change: ChangeSpec) -> ActuatorApplyResult:
        if not self.reversible or self.authority is None or self.authority.handler is None:
            return ActuatorApplyResult(
                outcome="not_applied",
                detail=f"{self.kind} rollback not available",
            )
        return await self.authority.handler.rollback(change, self)


class RemoteManifestActuator(Actuator):
    """Publish/revise the desired remote-manifest an SDK observes."""

    kind = "remote_manifest_change"
    reversible = True

    def __init__(self, authority: Optional[ActuatorAuthority] = None) -> None:
        super().__init__(
            authority
            or ActuatorAuthority(
                kind=self.kind,
                target_ref="services.sdk_config.service:SDKConfigService."
                "publish_manifest / rollback_manifest",
                reversible=True,
            )
        )


class ManagedConnectorActuator(Actuator):
    """Configure/enable/disable a managed connector (§36)."""

    kind = "managed_connector_change"
    reversible = True

    def __init__(self, authority: Optional[ActuatorAuthority] = None) -> None:
        super().__init__(
            authority
            or ActuatorAuthority(
                kind=self.kind,
                target_ref="services.integrations.connectors.service:"
                "ConnectorService.configure",
                reversible=True,
            )
        )


class ProviderRuntimeActuator(Actuator):
    """Create/update/disable a provider connection via the runtime."""

    kind = "provider_runtime_change"
    reversible = True

    def __init__(self, authority: Optional[ActuatorAuthority] = None) -> None:
        super().__init__(
            authority
            or ActuatorAuthority(
                kind=self.kind,
                target_ref="services.provider_runtime.connection:"
                "ConnectionOrchestrator (create/update/delete_connection)",
                reversible=True,
            )
        )


class MappingActuator(Actuator):
    """Apply an import/semantic mapping revision."""

    kind = "mapping_change"
    reversible = True

    def __init__(self, authority: Optional[ActuatorAuthority] = None) -> None:
        super().__init__(
            authority
            or ActuatorAuthority(
                kind=self.kind,
                target_ref="services.imports.service:set_mapping "
                "(import_mappings; no semantic-mapping publish substrate yet)",
                reversible=True,
            )
        )


class CompatibilityProjectionActuator(Actuator):
    """Project a compatibility revision — expressed via the desired manifest."""

    kind = "compatibility_projection_change"
    reversible = True

    def __init__(self, authority: Optional[ActuatorAuthority] = None) -> None:
        super().__init__(
            authority
            or ActuatorAuthority(
                kind=self.kind,
                target_ref="services.sdk_config.service:SDKConfigService."
                "publish_manifest (min_sdk_version/schema_version fields)",
                reversible=True,
            )
        )


class RepositoryUpgradeActuator(Actuator):
    """Advance a managed artifact's desired revision (version upgrades ride the
    desired remote-manifest; the tenant SDK self-adapts, CP-28/30)."""

    kind = "repository_upgrade"
    reversible = True

    def __init__(self, authority: Optional[ActuatorAuthority] = None) -> None:
        super().__init__(
            authority
            or ActuatorAuthority(
                kind=self.kind,
                target_ref="services.sdk_config.service:SDKConfigService."
                "publish_manifest / rollback_manifest",
                reversible=True,
            )
        )


class AuthorizationActuator(Actuator):
    """Grant/revoke a processing authority or platform permission."""

    kind = "authorization_change"
    reversible = True

    def __init__(self, authority: Optional[ActuatorAuthority] = None) -> None:
        super().__init__(
            authority
            or ActuatorAuthority(
                kind=self.kind,
                target_ref="services.agent_access_intelligence.authority:"
                "CapabilityAuthorityService.grant / revoke",
                reversible=True,
            )
        )


class QuarantineActuator(Actuator):
    """Quarantine an integration/connector from active processing."""

    kind = "quarantine"
    reversible = False  # the *effect* (isolation) is not further undoable here

    def __init__(self, authority: Optional[ActuatorAuthority] = None) -> None:
        super().__init__(
            authority
            or ActuatorAuthority(
                kind=self.kind,
                target_ref="services.integrations.webhook_quarantine:"
                "WebhookQuarantineRepository.quarantine",
                reversible=False,
            )
        )


class ReplayActuator(Actuator):
    """Trigger a replay job over a source range."""

    kind = "replay"
    reversible = True  # a replay job is cancellable

    def __init__(self, authority: Optional[ActuatorAuthority] = None) -> None:
        super().__init__(
            authority
            or ActuatorAuthority(
                kind=self.kind,
                target_ref="services.events.routes:submit_replay / "
                "services.events.worker:start_replay_worker",
                reversible=True,
            )
        )


class BackfillActuator(Actuator):
    """Trigger a backfill over a tenant/source range."""

    kind = "backfill"
    reversible = False  # forced/repair backfill is not cleanly undoable

    def __init__(self, authority: Optional[ActuatorAuthority] = None) -> None:
        super().__init__(
            authority
            or ActuatorAuthority(
                kind=self.kind,
                target_ref="services.measurement.engine.gold_materializer:"
                "backfill_tenant",
                reversible=False,
            )
        )


class RollbackActuator(Actuator):
    """Execute the rollback moves for a prior change (§32 step 20)."""

    kind = "rollback"
    reversible = False  # rollback is itself the reversal

    def __init__(self, authority: Optional[ActuatorAuthority] = None) -> None:
        super().__init__(
            authority
            or ActuatorAuthority(
                kind=self.kind,
                target_ref="services.agent.mutation_commit:rollback_mutation "
                "(+ sdk_config.rollback_manifest / import_rollbacks)",
                reversible=False,
            )
        )


class NotificationActionActuator(Actuator):
    """Emit an operational notification (no further mutation to reverse)."""

    kind = "notification_action"
    reversible = False

    def __init__(self, authority: Optional[ActuatorAuthority] = None) -> None:
        super().__init__(
            authority
            or ActuatorAuthority(
                kind=self.kind,
                target_ref="services.notification_intelligence.routes:"
                "emit_notification",
                reversible=False,
            )
        )


class _ActuatorRegistry:
    """Explicit §36 registry: exactly one actuator per Day-1 action kind."""

    def __init__(self) -> None:
        self._actuators: dict[ChangeActionKind, Actuator] = {}

    def register(self, actuator: Actuator) -> Actuator:
        if actuator.kind in self._actuators:
            raise ValueError(f"duplicate actuator for kind {actuator.kind!r}")
        self._actuators[actuator.kind] = actuator
        return actuator

    def get(self, kind: str) -> Optional[Actuator]:
        return self._actuators.get(kind)  # type: ignore[arg-type]

    def has(self, kind: str) -> bool:
        return kind in self._actuators

    def all(self) -> list[Actuator]:
        return list(self._actuators.values())


def _default_registry() -> _ActuatorRegistry:
    registry = _ActuatorRegistry()
    for actuator in (
        RemoteManifestActuator(),
        ManagedConnectorActuator(),
        ProviderRuntimeActuator(),
        MappingActuator(),
        CompatibilityProjectionActuator(),
        RepositoryUpgradeActuator(),
        AuthorizationActuator(),
        QuarantineActuator(),
        ReplayActuator(),
        BackfillActuator(),
        RollbackActuator(),
        NotificationActionActuator(),
    ):
        registry.register(actuator)
    return registry


def registry_with_authorities(
    handlers: dict[str, object],
) -> _ActuatorRegistry:
    """Build a registry whose listed kinds carry an admitted authority handler.

    Tests (and later the governed operator surface) inject handlers that
    implement the real substrate contract (``apply(change, actuator)`` /
    ``verify(change, actuator)`` / ``rollback(change, actuator)``). Kinds not
    listed keep their default un-admitted state and fail closed.
    """
    registry = _default_registry()
    for actuator in registry.all():
        handler = handlers.get(actuator.kind)
        if handler is None:
            continue
        authority = actuator.authority
        if authority is None:
            raise ValueError(
                f"actuator {actuator.kind!r} has no authority to admit"
            )
        registry._actuators[actuator.kind] = type(actuator)(
            authority=ActuatorAuthority(
                kind=authority.kind,
                target_ref=authority.target_ref,
                reversible=authority.reversible,
                handler=handler,
            )
        )
    return registry


_registry: Optional[_ActuatorRegistry] = None


def get_actuator_registry() -> _ActuatorRegistry:
    """Module singleton registry covering all 12 Day-1 action kinds."""
    global _registry
    if _registry is None:
        _registry = _default_registry()
    return _registry


@dataclass(frozen=True)
class ActuatorCapabilitySummary:
    """Registry snapshot for the operator read surface / tests."""

    kinds: list[str] = field(default_factory=list)
    reversible: dict[str, bool] = field(default_factory=dict)
    authority_refs: dict[str, Optional[str]] = field(default_factory=dict)
    authority_admitted: dict[str, bool] = field(default_factory=dict)


def registry_capabilities() -> ActuatorCapabilitySummary:
    """Coverage summary: every §36 Day-1 kind present; which are reversible;
    which declare (but may not yet admit) a real substrate authority."""
    registry = get_actuator_registry()
    kinds = sorted({str(a.kind) for a in registry.all()})
    return ActuatorCapabilitySummary(
        kinds=[str(k) for k in kinds],
        reversible={str(a.kind): a.reversible for a in registry.all()},
        authority_refs={
            str(a.kind): (a.authority.target_ref if a.authority else None)
            for a in registry.all()
        },
        authority_admitted={
            str(a.kind): bool(a.authority and a.authority.handler)
            for a in registry.all()
        },
    )


def registry_covers_all_day1_kinds() -> bool:
    """Every ChangeActionKind in the §36 Day-1 vocabulary has an actuator."""
    registered = {a.kind for a in get_actuator_registry().all()}
    return set(CHANGE_ACTION_KINDS) == registered
