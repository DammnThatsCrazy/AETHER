"""
Profile Resolver — Canonical identity resolution across identifier types.

Given any supported identifier (user_id, wallet, email, device, session, social handle),
resolves to a canonical profile_id by querying existing identity and graph subsystems.
"""

from __future__ import annotations

from typing import Optional

from shared.graph.graph import GraphClient, VertexType, EdgeType
from shared.cache.cache import CacheClient, CacheKey, TTL
from shared.logger.logger import get_logger

logger = get_logger("aether.profile.resolver")


class ProfileResolver:
    """Resolves any identifier to a canonical profile/user ID."""

    def __init__(self, graph: GraphClient, cache: CacheClient) -> None:
        self._graph = graph
        self._cache = cache

    async def resolve(
        self,
        *,
        user_id: Optional[str] = None,
        wallet_address: Optional[str] = None,
        email: Optional[str] = None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        social_handle: Optional[str] = None,
        customer_id: Optional[str] = None,
    ) -> Optional[str]:
        """Resolve any identifier to a canonical user_id.

        Checks graph relationships: wallet→user, device→user, session→user, email→user.
        Returns the canonical user_id or None if not resolvable.
        """
        # Direct user_id
        if user_id:
            return user_id

        # Try cache first for known mappings
        for id_type, id_value in [
            ("wallet", wallet_address),
            ("email", email),
            ("device", device_id),
            ("session", session_id),
            ("social", social_handle),
            ("customer", customer_id),
        ]:
            if not id_value:
                continue

            cache_key = f"aether:profile:resolve:{id_type}:{id_value}"
            cached = await self._cache.get(cache_key)
            if cached:
                return cached

            # Graph-based resolution
            resolved = await self._resolve_via_graph(id_value, id_type)
            if resolved:
                await self._cache.set(cache_key, resolved, ttl=TTL.PROFILE)
                return resolved

        return None

    async def _resolve_via_graph(self, identifier: str, id_type: str) -> Optional[str]:
        """Traverse graph edges to find the owning User vertex."""
        edge_map = {
            "wallet": EdgeType.OWNS_WALLET,
            "email": EdgeType.HAS_EMAIL,
            "device": EdgeType.USED_DEVICE,
            "session": EdgeType.HAS_SESSION,
            "social": EdgeType.RESOLVED_AS,
        }

        # For wallets/emails/devices: find users connected via the appropriate edge
        edge_type = edge_map.get(id_type)
        if edge_type:
            neighbors = await self._graph.get_neighbors(
                identifier, edge_type=edge_type, direction="in"
            )
            for v in neighbors:
                if v.vertex_type == VertexType.USER:
                    return v.vertex_id

        # Fallback: try bidirectional search
        neighbors = await self._graph.get_neighbors(identifier, direction="both")
        for v in neighbors:
            if v.vertex_type == VertexType.USER:
                return v.vertex_id

        return None

    async def get_all_identifiers(self, user_id: str) -> dict:
        """Get all known identifiers linked to a user."""
        identifiers: dict[str, list[str]] = {
            "wallets": [],
            "emails": [],
            "phones": [],
            "devices": [],
            "sessions": [],
            "social": [],
        }

        neighbors = await self._graph.get_neighbors(user_id, direction="both")
        for v in neighbors:
            vtype = v.vertex_type
            if vtype == VertexType.WALLET:
                identifiers["wallets"].append(v.vertex_id)
            elif vtype == VertexType.EMAIL:
                identifiers["emails"].append(v.vertex_id)
            elif vtype == VertexType.PHONE:
                identifiers["phones"].append(v.vertex_id)
            elif vtype == VertexType.DEVICE or vtype == VertexType.DEVICE_FINGERPRINT:
                identifiers["devices"].append(v.vertex_id)
            elif vtype == VertexType.SESSION:
                identifiers["sessions"].append(v.vertex_id)
            elif vtype in (VertexType.USER, VertexType.IDENTITY_CLUSTER):
                if v.vertex_id != user_id:
                    identifiers["social"].append(v.vertex_id)

        return identifiers
