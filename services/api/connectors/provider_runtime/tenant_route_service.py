"""Governed state machine for tenant connector writer routes.

No API mounts this service. Its admission callback must be backed by the
managed-integration approval/evidence authority before traffic can change.
Without that callback every create/transition fails closed. The repository
provides durable CAS and audit; the graph gateway must still fence a mutation
atomically against ``writer_generation`` before this is a live cutover system.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from connectors.managed_integrations.repository import get_managed_integration_repository
from connectors.provider_runtime.connection import ProviderConnectionRepository
from connectors.provider_runtime.tenant_route_repository import (
    RouteAdmissionDenied,
    RouteDecision,
    RouteMode,
    RouteNotFound,
    RouteScope,
    StaleRouteRevision,
    TenantConnectorRoute,
    TenantRouteRepository,
    Writer,
)
from shared.integration_contracts.lifecycle import ConnectionState


@dataclass(frozen=True)
class RouteProposal:
    """Exact target a governance decision must approve."""

    mode: RouteMode
    legacy_connection_ref: str
    native_connection_ref: str | None
    shadow_namespace: str | None
    rollback_until: datetime | None


AdmissionCallback = Callable[
    [RouteScope, TenantConnectorRoute | None, RouteProposal, RouteDecision], Awaitable[bool]
]

_MANAGED_KINDS = frozenset(
    {
        "connector_aether_hosted",
        "connector_customer_hosted",
    }
)
_SHADOW_READY = frozenset(
    {
        ConnectionState.VERIFIED,
        ConnectionState.ACCOUNT_SELECTION_REQUIRED,
        ConnectionState.CONFIGURATION_REQUIRED,
        ConnectionState.WEBHOOK_REGISTRATION_PENDING,
        ConnectionState.INITIAL_SYNC_PENDING,
        ConnectionState.INITIAL_SYNC_RUNNING,
        ConnectionState.CONNECTED,
    }
)


class TenantRouteService:
    def __init__(
        self,
        *,
        routes: TenantRouteRepository | None = None,
        managed_integrations=None,
        connections: ProviderConnectionRepository | None = None,
        admit: AdmissionCallback | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.routes = routes if routes is not None else TenantRouteRepository()
        self.managed_integrations = (
            managed_integrations
            if managed_integrations is not None
            else get_managed_integration_repository()
        )
        self.connections = (
            connections if connections is not None else ProviderConnectionRepository()
        )
        self.admit = admit
        self.clock = clock if clock is not None else lambda: datetime.now(timezone.utc)

    async def _require_admission(
        self,
        scope: RouteScope,
        current: TenantConnectorRoute | None,
        proposal: RouteProposal,
        decision: RouteDecision,
    ) -> None:
        if self.admit is None or not await self.admit(scope, current, proposal, decision):
            raise RouteAdmissionDenied("connector route decision is not authorized")

    async def _require_managed_registration(
        self, scope: RouteScope, legacy_connection_ref: str
    ) -> None:
        row = await self.managed_integrations.get(
            scope.tenant_id, scope.environment_id, scope.managed_integration_id
        )
        if (
            row is None
            or row.get("integration_kind") not in _MANAGED_KINDS
            or row.get("source_ref") != legacy_connection_ref
        ):
            raise RouteAdmissionDenied("tenant managed integration is not eligible")

    async def _require_native_connection(
        self, scope: RouteScope, connection_ref: str, *, connected: bool
    ) -> None:
        connection = await self.connections.find(connection_ref)
        if (
            connection is None
            or connection.tenant_id != scope.tenant_id
            or connection.provider_identity != scope.provider_identity
            or (scope.account_id and scope.account_id not in connection.selected_accounts)
        ):
            raise RouteAdmissionDenied("native provider connection is not in route scope")
        if connected:
            allowed = connection.state == ConnectionState.CONNECTED
        else:
            allowed = connection.state in _SHADOW_READY
        if not allowed:
            raise RouteAdmissionDenied("native provider connection is not ready for route mode")

    async def create_legacy_route(
        self,
        scope: RouteScope,
        *,
        legacy_connection_ref: str,
        decision: RouteDecision,
    ) -> TenantConnectorRoute:
        """Register existing legacy authority; this does not migrate traffic."""
        await self._require_managed_registration(scope, legacy_connection_ref)
        await self._require_admission(
            scope,
            None,
            RouteProposal("legacy_only", legacy_connection_ref, None, None, None),
            decision,
        )
        return await self.routes.create_legacy(
            scope, legacy_connection_ref=legacy_connection_ref, decision=decision
        )

    async def start_shadow(
        self,
        scope: RouteScope,
        *,
        expected_revision: int,
        native_connection_ref: str,
        shadow_namespace: str,
        decision: RouteDecision,
    ) -> TenantConnectorRoute:
        current = await self._current(scope, expected_revision)
        if current.mode != "legacy_only":
            raise RouteAdmissionDenied("shadow may start only from legacy_only")
        if not shadow_namespace.strip():
            raise ValueError("shadow_namespace is required")
        await self._require_native_connection(scope, native_connection_ref, connected=False)
        await self._require_admission(
            scope,
            current,
            RouteProposal(
                "shadow",
                current.legacy_connection_ref,
                native_connection_ref,
                shadow_namespace,
                None,
            ),
            decision,
        )
        return await self.routes.compare_and_swap(
            scope,
            expected_revision=expected_revision,
            mode="shadow",
            native_connection_ref=native_connection_ref,
            shadow_namespace=shadow_namespace,
            rollback_until=None,
            decision=decision,
        )

    async def promote_native(
        self,
        scope: RouteScope,
        *,
        expected_revision: int,
        rollback_until: datetime,
        decision: RouteDecision,
    ) -> TenantConnectorRoute:
        current = await self._current(scope, expected_revision)
        if current.mode != "shadow" or not current.native_connection_ref:
            raise RouteAdmissionDenied("native promotion requires an active shadow route")
        if not current.shadow_namespace:
            raise RouteAdmissionDenied("native promotion requires isolated shadow evidence")
        if not decision.evidence_bundle_ref:
            raise RouteAdmissionDenied("native promotion requires an evidence bundle")
        deadline = _aware_utc(rollback_until)
        if deadline <= _aware_utc(self.clock()):
            raise RouteAdmissionDenied("rollback window must end in the future")
        await self._require_native_connection(scope, current.native_connection_ref, connected=True)
        await self._require_admission(
            scope,
            current,
            RouteProposal(
                "new_primary",
                current.legacy_connection_ref,
                current.native_connection_ref,
                current.shadow_namespace,
                deadline,
            ),
            decision,
        )
        return await self.routes.compare_and_swap(
            scope,
            expected_revision=expected_revision,
            mode="new_primary",
            native_connection_ref=current.native_connection_ref,
            shadow_namespace=current.shadow_namespace,
            rollback_until=deadline,
            decision=decision,
        )

    async def rollback_to_shadow(
        self,
        scope: RouteScope,
        *,
        expected_revision: int,
        decision: RouteDecision,
    ) -> TenantConnectorRoute:
        current = await self._current(scope, expected_revision)
        if current.mode != "new_primary" or not current.shadow_namespace:
            raise RouteAdmissionDenied("only new_primary can roll back to shadow")
        if current.rollback_until is None or _aware_utc(self.clock()) > _aware_utc(
            current.rollback_until
        ):
            raise RouteAdmissionDenied("rollback window has expired")
        if not decision.evidence_bundle_ref:
            raise RouteAdmissionDenied("rollback requires an evidence bundle")
        await self._require_admission(
            scope,
            current,
            RouteProposal(
                "shadow",
                current.legacy_connection_ref,
                current.native_connection_ref,
                current.shadow_namespace,
                None,
            ),
            decision,
        )
        return await self.routes.compare_and_swap(
            scope,
            expected_revision=expected_revision,
            mode="shadow",
            native_connection_ref=current.native_connection_ref,
            shadow_namespace=current.shadow_namespace,
            rollback_until=None,
            decision=decision,
        )

    async def stop_shadow(
        self,
        scope: RouteScope,
        *,
        expected_revision: int,
        decision: RouteDecision,
    ) -> TenantConnectorRoute:
        current = await self._current(scope, expected_revision)
        if current.mode != "shadow":
            raise RouteAdmissionDenied("only shadow may return to legacy_only")
        await self._require_admission(
            scope,
            current,
            RouteProposal(
                "legacy_only",
                current.legacy_connection_ref,
                current.native_connection_ref,
                None,
                None,
            ),
            decision,
        )
        return await self.routes.compare_and_swap(
            scope,
            expected_revision=expected_revision,
            mode="legacy_only",
            native_connection_ref=current.native_connection_ref,
            shadow_namespace=None,
            rollback_until=None,
            decision=decision,
        )

    async def disable_legacy(
        self,
        scope: RouteScope,
        *,
        expected_revision: int,
        decision: RouteDecision,
    ) -> TenantConnectorRoute:
        current = await self._current(scope, expected_revision)
        if current.mode != "new_primary":
            raise RouteAdmissionDenied("legacy disable requires new_primary")
        if current.rollback_until is None or _aware_utc(self.clock()) <= _aware_utc(
            current.rollback_until
        ):
            raise RouteAdmissionDenied("legacy disable requires an expired rollback window")
        if not decision.evidence_bundle_ref:
            raise RouteAdmissionDenied("legacy disable requires decommission evidence")
        await self._require_admission(
            scope,
            current,
            RouteProposal(
                "legacy_disabled",
                current.legacy_connection_ref,
                current.native_connection_ref,
                None,
                current.rollback_until,
            ),
            decision,
        )
        return await self.routes.compare_and_swap(
            scope,
            expected_revision=expected_revision,
            mode="legacy_disabled",
            native_connection_ref=current.native_connection_ref,
            shadow_namespace=None,
            rollback_until=current.rollback_until,
            decision=decision,
        )

    async def _current(self, scope: RouteScope, expected_revision: int) -> TenantConnectorRoute:
        current = await self.routes.get(scope)
        if current is None:
            raise RouteNotFound("tenant connector route does not exist")
        # The repository repeats this check inside its transaction; this early
        # check only avoids unnecessary external admission work on stale input.
        if current.revision != expected_revision:
            raise StaleRouteRevision("route changed since it was read")
        return current

    async def assert_writer(
        self, scope: RouteScope, *, writer: Writer, writer_generation: int
    ) -> TenantConnectorRoute:
        """Fail-closed read check for callers that will enforce it atomically.

        A caller must recheck under its graph mutation transaction/lock. This
        method alone is not sufficient to prevent a cutover race between the
        check and a downstream write.
        """
        route = await self.routes.get(scope)
        if (
            route is None
            or route.writer_generation != writer_generation
            or route.production_writer != writer
        ):
            raise RouteAdmissionDenied("connector writer route or generation is not active")
        return route

    async def assert_shadow(
        self, scope: RouteScope, *, writer_generation: int, shadow_namespace: str
    ) -> TenantConnectorRoute:
        """Authorize isolated shadow output; never a production graph write."""
        route = await self.routes.get(scope)
        if (
            route is None
            or route.mode != "shadow"
            or route.writer_generation != writer_generation
            or route.shadow_namespace != shadow_namespace
        ):
            raise RouteAdmissionDenied("isolated shadow route or generation is not active")
        return route


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("route timestamps must include a timezone")
    return value.astimezone(timezone.utc)


__all__ = ["AdmissionCallback", "RouteProposal", "TenantRouteService"]
