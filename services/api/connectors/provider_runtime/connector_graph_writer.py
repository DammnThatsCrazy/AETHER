"""Opt-in graph writer protected by a tenant connector route row lock.

This is the integration seam for legacy and native connector writers. It
checks the exact route scope, connection, and generation under a PostgreSQL
row lock, then holds that lock until GraphMutationGateway.apply returns. Route
transitions use the same lock and cannot pass an in-flight cooperating write.

No live connector path calls this wrapper yet. Cutover must remain disabled
until both legacy and native graph writers submit every affected fact through
it, with a reviewed mapping from each source event to route stream/fact family.
The graph gateway's ledger/projection are not one transaction with the route
table, so a timeout or connection loss still requires reconciliation.
"""

from __future__ import annotations

import asyncio

from connectors.provider_runtime.tenant_route_repository import (
    RouteAdmissionDenied,
    RouteScope,
    TenantRouteRepository,
    Writer,
)
from shared.graph.mutation_gateway import (
    GraphMutationGateway,
    MutationIntent,
    MutationOutcome,
    get_mutation_gateway,
)


class ConnectorGraphWriter:
    """Route-fenced GraphMutationGateway adapter for connector facts."""

    def __init__(
        self,
        *,
        routes: TenantRouteRepository | None = None,
        gateway: GraphMutationGateway | None = None,
        mutation_timeout_seconds: float = 45,
    ) -> None:
        if not 0 < mutation_timeout_seconds <= 45:
            raise ValueError("connector mutation timeout must be within (0, 45] seconds")
        self.routes = routes if routes is not None else TenantRouteRepository()
        self.gateway = gateway if gateway is not None else get_mutation_gateway()
        self.mutation_timeout_seconds = mutation_timeout_seconds

    async def apply(
        self,
        intent: MutationIntent,
        *,
        scope: RouteScope,
        writer: Writer,
        writer_generation: int,
        connection_ref: str,
    ) -> MutationOutcome:
        """Apply one connector mutation while its route generation is locked.

        ``source_event_id`` is required for fact lineage. Edge and vertex
        properties must carry the same tenant, since a writer-set graph property
        can override the gateway's canonical edge defaults. The caller must
        derive ``scope.stream_id`` and ``scope.fact_family`` from reviewed
        source metadata, never from an untrusted client hint. The gateway runs
        in enforce mode so validation and ledger idempotency cannot be bypassed.
        """
        if intent.tenant_id != scope.tenant_id:
            raise RouteAdmissionDenied("connector mutation tenant differs from route")
        if not (intent.source_event_id or "").strip():
            raise RouteAdmissionDenied("connector mutation requires source_event_id")
        target = intent.edge if intent.edge is not None else intent.vertex
        if target is not None:
            properties = target.properties or {}
            if properties.get("tenant_id") != scope.tenant_id or (
                "tenantId" in properties and properties["tenantId"] != scope.tenant_id
            ):
                raise RouteAdmissionDenied("connector graph fact tenant differs from route")
            if (
                "source_event_id" in properties
                and properties["source_event_id"] != intent.source_event_id
            ):
                raise RouteAdmissionDenied("connector graph fact lineage differs from intent")
        # Bound queueing for the row lock and pool connection as well as the
        # downstream graph mutation. Otherwise a stuck transaction holder can
        # leave an ingestion worker waiting indefinitely before this timeout
        # even begins.
        async with asyncio.timeout(self.mutation_timeout_seconds):
            async with self.routes.writer_fence(
                scope,
                writer=writer,
                writer_generation=writer_generation,
                connection_ref=connection_ref,
            ):
                return await self.gateway.apply(intent, mode_override="enforce")


__all__ = ["ConnectorGraphWriter"]
