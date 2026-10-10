"""
Aether Service — Protected Resource Registry
Registers all Aether-native paid resources (APIs, agent tools, priced endpoints,
service plans, internal capabilities). Seeded at startup with Day-1 GA coverage.
"""

from __future__ import annotations

from typing import Optional

from shared.logger.logger import get_logger

from .commerce_models import ProtectedResource, ResourceClass
from .commerce_store import get_commerce_store

logger = get_logger("aether.service.x402.resources")


class ProtectedResourceRegistry:
    """Unified registry of protected resources across Aether-native surfaces."""

    def __init__(self) -> None:
        self._store = get_commerce_store()

    async def register(self, resource: ProtectedResource) -> ProtectedResource:
        """Register or update a protected resource. Approval-required defaults to True."""
        if resource.price_usd < 0:
            raise ValueError("price_usd must be non-negative")
        # Day-1 GA enforcement: approval_required is True unless explicitly opted out
        # by tenant admin (still approval-required until flag changed globally).
        result = await self._store.put_resource(resource)
        logger.info(
            f"Protected resource registered: {resource.resource_id} "
            f"(tenant={resource.tenant_id}, class={resource.resource_class}, "
            f"price=${resource.price_usd})"
        )
        return result

    async def get(self, tenant_id: str, resource_id: str) -> Optional[ProtectedResource]:
        return await self._store.get_resource(tenant_id, resource_id)

    async def list(self, tenant_id: str, active_only: bool = True) -> list[ProtectedResource]:
        return await self._store.list_resources(
            tenant_id, active=True if active_only else None
        )

    async def find_by_path(self, tenant_id: str, path: str) -> Optional[ProtectedResource]:
        """Find the protected resource whose path_pattern matches the request path."""
        resources = await self._store.list_resources(tenant_id, active=True)
        # Longest matching pattern wins
        matches = [r for r in resources if r.path_pattern and path.startswith(r.path_pattern)]
        if not matches:
            return None
        return max(matches, key=lambda r: len(r.path_pattern))

    async def deactivate(self, tenant_id: str, resource_id: str) -> bool:
        resource = await self._store.get_resource(tenant_id, resource_id)
        if not resource:
            return False
        resource.active = False
        await self._store.put_resource(resource)
        return True


# Day-1 seed: Aether-native protected resources. Covers all resource classes.
AETHER_NATIVE_RESOURCE_SEEDS: list[dict] = [
    # APIs
    {
        "name": "Aether Intelligence Graph Query API",
        "resource_class": ResourceClass.API,
        "path_pattern": "/v1/intelligence/graph/query",
        "owner_service": "intelligence",
        "description": "Paid graph traversal queries",
        "price_usd": 0.05,
        "entitlement_ttl_seconds": 900,
    },
    {
        "name": "Aether ML Inference API",
        "resource_class": ResourceClass.API,
        "path_pattern": "/v1/ml/predict",
        "owner_service": "ml",
        "description": "Paid ML inference endpoint",
        "price_usd": 0.10,
        "entitlement_ttl_seconds": 900,
    },
    # Agent tools
    {
        "name": "Aether Agent — Web Search Tool",
        "resource_class": ResourceClass.AGENT_TOOL,
        "path_pattern": "/v1/agent/tools/websearch",
        "owner_service": "agent",
        "description": "Agent web search capability",
        "price_usd": 0.02,
        "entitlement_ttl_seconds": 300,
    },
    {
        "name": "Aether Agent — Code Execution Tool",
        "resource_class": ResourceClass.AGENT_TOOL,
        "path_pattern": "/v1/agent/tools/codeexec",
        "owner_service": "agent",
        "description": "Sandboxed code execution",
        "price_usd": 0.08,
        "entitlement_ttl_seconds": 300,
    },
    # Priced endpoints
    {
        "name": "Aether Analytics — Cohort Export",
        "resource_class": ResourceClass.PRICED_ENDPOINT,
        "path_pattern": "/v1/analytics/cohorts/export",
        "owner_service": "analytics",
        "description": "Cohort data export endpoint",
        "price_usd": 1.00,
        "entitlement_ttl_seconds": 86400,
    },
    # Service plans
    {
        "name": "Aether Pro Plan",
        "resource_class": ResourceClass.SERVICE_PLAN,
        "path_pattern": "/v1/plans/pro",
        "owner_service": "commerce",
        "description": "Monthly Pro service plan",
        "price_usd": 49.00,
        "entitlement_ttl_seconds": 2592000,  # 30d
    },
    # Internal capabilities
    {
        "name": "Aether Trust Score — Deep Compute",
        "resource_class": ResourceClass.INTERNAL_CAPABILITY,
        "path_pattern": "/v1/intelligence/trust/deep",
        "owner_service": "intelligence",
        "description": "Deep trust score computation",
        "price_usd": 0.20,
        "entitlement_ttl_seconds": 600,
    },
]


async def seed_aether_native_resources(tenant_id: str) -> list[ProtectedResource]:
    """Seed all Aether-native protected resources for a tenant.
    Idempotent: re-running does not duplicate."""
    registry = ProtectedResourceRegistry()
    results: list[ProtectedResource] = []
    existing = await registry.list(tenant_id, active_only=False)
    existing_paths = {r.path_pattern for r in existing}

    for seed in AETHER_NATIVE_RESOURCE_SEEDS:
        if seed["path_pattern"] in existing_paths:
            continue
        resource = ProtectedResource(
            tenant_id=tenant_id,
            name=seed["name"],
            resource_class=seed["resource_class"],
            path_pattern=seed["path_pattern"],
            owner_service=seed["owner_service"],
            description=seed["description"],
            price_usd=seed["price_usd"],
            accepted_assets=["USDC"],
            accepted_chains=["eip155:8453", "solana:mainnet"],
            approval_required=True,
            entitlement_ttl_seconds=seed["entitlement_ttl_seconds"],
            active=True,
        )
        results.append(await registry.register(resource))

    logger.info(f"Seeded {len(results)} Aether-native protected resources for tenant={tenant_id}")
    return results


_registry: Optional[ProtectedResourceRegistry] = None


def get_resource_registry() -> ProtectedResourceRegistry:
    global _registry
    if _registry is None:
        _registry = ProtectedResourceRegistry()
    return _registry
