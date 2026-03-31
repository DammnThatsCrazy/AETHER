"""
Aether Shared — Extraction Graph Helpers

Graph-based extraction defense queries:
    - Cluster-neighbor feature fetchers
    - Graph-deviation helpers
    - Linked-identity aggregation queries

Uses the existing GraphClient and graph model without replacement.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.graph.graph import GraphClient, Vertex, VertexType
from shared.logger.logger import get_logger

logger = get_logger("aether.graph.extraction")


class ExtractionGraphHelper:
    """
    Graph-based helpers for extraction defense scoring.

    Queries the identity graph to discover related actors, cluster
    behavior, and cross-key correlation for multi-identity evasion
    detection.
    """

    def __init__(self, graph: GraphClient) -> None:
        self._graph = graph

    async def get_identity_cluster_members(
        self, cluster_id: str, limit: int = 50,
    ) -> list[str]:
        """Get all member vertex IDs in an identity cluster."""
        try:
            neighbors = await self._graph.get_neighbors(
                cluster_id, edge_type="MEMBER_OF_CLUSTER", direction="in"
            )
            return [n.vertex_id for n in neighbors[:limit]]
        except Exception as e:
            logger.debug(f"Cluster member query error: {e}")
            return []

    async def get_linked_api_keys(
        self, entity_id: str,
    ) -> list[str]:
        """
        Find API keys linked to the same identity through graph relationships.

        Traverses: entity → cluster → other members → their API keys
        """
        try:
            # Get clusters this entity belongs to
            clusters = await self._graph.get_neighbors(
                entity_id, edge_type="MEMBER_OF_CLUSTER", direction="out"
            )
            linked_keys: set[str] = set()
            for cluster in clusters[:5]:
                members = await self._graph.get_neighbors(
                    cluster.vertex_id, edge_type="MEMBER_OF_CLUSTER", direction="in"
                )
                for member in members[:20]:
                    if member.vertex_id != entity_id:
                        api_key = member.properties.get("api_key_id", "")
                        if api_key:
                            linked_keys.add(api_key)
            return list(linked_keys)
        except Exception as e:
            logger.debug(f"Linked API key query error: {e}")
            return []

    async def get_wallet_linked_actors(
        self, wallet_id: str,
    ) -> list[str]:
        """Find actors linked through shared wallet ownership."""
        try:
            neighbors = await self._graph.get_neighbors(
                wallet_id, edge_type="OWNS_WALLET", direction="in"
            )
            return [n.vertex_id for n in neighbors[:20]]
        except Exception as e:
            logger.debug(f"Wallet-linked actor query error: {e}")
            return []

    async def get_device_linked_actors(
        self, device_fingerprint: str,
    ) -> list[str]:
        """Find actors seen from the same device fingerprint."""
        try:
            neighbors = await self._graph.get_neighbors(
                device_fingerprint, edge_type="HAS_FINGERPRINT", direction="in"
            )
            return [n.vertex_id for n in neighbors[:20]]
        except Exception as e:
            logger.debug(f"Device-linked actor query error: {e}")
            return []

    async def get_ip_linked_actors(
        self, ip_address: str,
    ) -> list[str]:
        """Find actors seen from the same IP address."""
        try:
            neighbors = await self._graph.get_neighbors(
                ip_address, edge_type="SEEN_FROM_IP", direction="in"
            )
            return [n.vertex_id for n in neighbors[:30]]
        except Exception as e:
            logger.debug(f"IP-linked actor query error: {e}")
            return []

    async def compute_cluster_features(
        self, cluster_id: str,
    ) -> dict[str, Any]:
        """
        Compute aggregate features for an identity cluster.

        Returns metrics useful for extraction detection:
        member count, device diversity, IP diversity, key rotation indicators.
        """
        members = await self.get_identity_cluster_members(cluster_id)
        if not members:
            return {"cluster_size": 0}

        devices: set[str] = set()
        ips: set[str] = set()
        api_keys: set[str] = set()

        for member_id in members[:30]:
            vertex = await self._graph.get_vertex(member_id)
            if vertex:
                if vertex.properties.get("device_fingerprint"):
                    devices.add(vertex.properties["device_fingerprint"])
                if vertex.properties.get("source_ip"):
                    ips.add(vertex.properties["source_ip"])
                if vertex.properties.get("api_key_id"):
                    api_keys.add(vertex.properties["api_key_id"])

        return {
            "cluster_size": len(members),
            "unique_devices": len(devices),
            "unique_ips": len(ips),
            "unique_api_keys": len(api_keys),
            "key_to_member_ratio": len(api_keys) / max(len(members), 1),
            "device_to_member_ratio": len(devices) / max(len(members), 1),
        }
