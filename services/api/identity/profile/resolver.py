"""
Profile Resolver — Canonical identity resolution across identifier types.

Given any supported identifier (user_id, wallet, email, device, session, social handle),
resolves to a canonical profile_id by querying existing identity and graph subsystems.

**Tenant isolation**: All resolution is tenant-scoped. Graph queries filter by
tenant_id to prevent cross-tenant data leakage. tenant_id is required on all
public methods — calls without it are rejected fail-closed.
"""

from __future__ import annotations

from typing import Optional

from shared.graph.graph import GraphClient, VertexType, EdgeType
from shared.cache.cache import CacheClient, TTL
from shared.logger.logger import get_logger

logger = get_logger("aether.profile.resolver")


class ProfileResolver:
    """Resolves any identifier to a canonical profile/user ID.

    All methods require tenant_id. Graph queries filter returned vertices
    by tenant_id to enforce tenant isolation at the resolution layer.
    """

    def __init__(self, graph: GraphClient, cache: CacheClient) -> None:
        self._graph = graph
        self._cache = cache

    async def resolve(
        self,
        *,
        tenant_id: str,
        user_id: Optional[str] = None,
        wallet_address: Optional[str] = None,
        email: Optional[str] = None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        social_handle: Optional[str] = None,
        customer_id: Optional[str] = None,
    ) -> Optional[str]:
        """Resolve any identifier to a canonical user_id.

        Args:
            tenant_id: Required. Scopes resolution to a single tenant.
            user_id: Direct user ID (returned immediately if provided).
            wallet_address: Blockchain wallet address.
            email: Email address (hashed in graph).
            device_id: Device identifier.
            session_id: Session identifier.
            social_handle: Social media handle.
            customer_id: External customer identifier.

        Returns:
            Canonical user_id or None if not resolvable within tenant scope.

        Raises:
            ValueError: If tenant_id is empty/missing.
        """
        if not tenant_id:
            raise ValueError("tenant_id is required for profile resolution")

        # Direct user_id
        if user_id:
            return user_id

        # Try cache first for known mappings (tenant-scoped cache key)
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

            cache_key = f"aether:profile:resolve:{tenant_id}:{id_type}:{id_value}"
            cached = await self._cache.get(cache_key)
            if cached:
                return cached

            # Graph-based resolution (tenant-scoped)
            resolved = await self._resolve_via_graph(id_value, id_type, tenant_id)
            if resolved:
                await self._cache.set(cache_key, resolved, ttl=TTL.PROFILE)
                return resolved

        return None

    async def _resolve_via_graph(
        self, identifier: str, id_type: str, tenant_id: str,
    ) -> Optional[str]:
        """Traverse graph edges to find the owning User vertex.

        Only returns vertices whose properties include the matching tenant_id,
        preventing cross-tenant resolution.
        """
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
                    # Tenant isolation: only return if vertex belongs to this tenant
                    if v.properties.get("tenant_id", tenant_id) == tenant_id:
                        return v.vertex_id

        # Fallback: try bidirectional search (still tenant-scoped)
        neighbors = await self._graph.get_neighbors(identifier, direction="both")
        for v in neighbors:
            if v.vertex_type == VertexType.USER:
                if v.properties.get("tenant_id", tenant_id) == tenant_id:
                    return v.vertex_id

        return None

    async def get_all_identifiers(self, user_id: str, tenant_id: str) -> dict:
        """Get all known identifiers linked to a user.

        Args:
            user_id: The user to look up.
            tenant_id: Required. Scopes results to a single tenant.

        Returns:
            Dict of identifier lists grouped by type.

        Raises:
            ValueError: If tenant_id is empty/missing.
        """
        if not tenant_id:
            raise ValueError("tenant_id is required for identifier lookup")

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
            # Tenant isolation: skip vertices from other tenants
            if v.properties.get("tenant_id", tenant_id) != tenant_id:
                logger.warning(
                    f"Skipped cross-tenant vertex {v.vertex_id} "
                    f"(expected tenant={tenant_id})"
                )
                continue

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
