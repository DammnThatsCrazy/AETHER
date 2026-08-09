"""Scan-to-projection wiring for Interoperability graph mutations.

Wires the graph_mutations builders (previously dead code) into the scan
pipeline: one scan cycle's observations feed ``build_topology_mutations``
(provider/gateway/path topology, public scope) and the cycle's correlated
messages feed ``build_message_mutations`` (SENT_VIA_PATH / SECURED_BY_POLICY
edges). Mutations persist through ``foundation.persist_mutations`` — the
canonical graph outbox path.

Gated on ``settings.interop.graph_enabled``; a disabled projector is a no-op
that never constructs a GraphClient, so the disabled path has zero runtime
cost (mirrors the fail-closed interop rollout flags).
"""

from __future__ import annotations

from typing import Any, Optional

from repositories.interop_repos import InteropMessageRepo
from services.interop.foundation import GraphProjectionResult, persist_mutations
from services.interop.graph_mutations import (
    build_message_mutations,
    build_topology_mutations,
)


def _extract_topology(
    observations: list[dict[str, Any]], provider: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Derive the provider's gateways and paths from one cycle's observations.

    Deterministic and idempotent: gateways/paths are keyed by stable ids
    derived from the observation refs, so re-projecting a replayed cycle
    produces identical mutations (the graph outbox dedups on those ids).
    """
    gateways: dict[str, dict[str, Any]] = {}
    paths: dict[str, dict[str, Any]] = {}
    for observation in observations:
        endpoint = observation.get("endpoint_ref") or {}
        gateway_id = endpoint.get("gateway_id")
        if gateway_id:
            gateways[gateway_id] = {
                "gateway_id": gateway_id,
                "network_id": endpoint.get("network_id", ""),
                "native_chain_id": endpoint.get("native_chain_id", ""),
                "gateway_role": observation.get("phase", "unknown"),
            }
        source = observation.get("source_network_id")
        destination = observation.get("destination_network_id")
        if source and destination:
            path_id = observation.get(
                "path_id",
                f"{provider.get('provider_id', 'interop')}:{source}->{destination}",
            )
            paths[path_id] = {
                "path_id": path_id,
                "source_network_id": source,
                "destination_network_id": destination,
                "source_gateway_id": endpoint.get("gateway_id"),
                "destination_gateway_id": None,
            }
    return list(gateways.values()), list(paths.values())


class InteropGraphProjector:
    """Projects one scan cycle into the graph; no-op when disabled."""

    def __init__(self, enabled: bool, message_repo: Optional[InteropMessageRepo] = None) -> None:
        self.enabled = enabled
        self.messages = message_repo or InteropMessageRepo()

    async def project(
        self,
        tenant_id: str,
        observations: list[dict[str, Any]],
        correlation_results: list[dict[str, Any]],
        *,
        provider: dict[str, Any],
        trace_id: str = "",
    ) -> GraphProjectionResult:
        """Persist topology + message mutations for one scan cycle."""
        if not self.enabled:
            return GraphProjectionResult(graph_mutations_built=0)

        gateways, paths = _extract_topology(observations, provider)
        mutations = []
        vertices, edges = build_topology_mutations(provider, gateways, paths)
        mutations.extend(vertices)
        mutations.extend(edges)

        seen: set[str] = set()
        for result in correlation_results:
            message_id = result.get("interop_message_id")
            if not message_id or message_id in seen:
                continue
            seen.add(message_id)
            message = await self.messages.find_one({
                "tenant_id": tenant_id,
                "interop_message_id": message_id,
            })
            if not message:
                continue
            vertices, edges = build_message_mutations(message)
            mutations.extend(vertices)
            mutations.extend(edges)

        return await persist_mutations(mutations, tenant_id=tenant_id, trace_id=trace_id)
