"""Shared fixtures for x402 commerce integration tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

TENANT = "tenant-integration-test"
AGENT_ID = "agent-int-001"
PAYER_WALLET = "0xabcdef1234567890abcdef1234567890abcdef12"
RECIPIENT_WALLET = "0xfeedfeedfeedfeedfeedfeedfeedfeedfeedfeed"
RESOURCE_ID = "res-int-001"


@pytest.fixture(autouse=True)
def reset_all_stores():
    import services.x402.resources as _res_mod
    from repositories.repos import reset_in_memory_stores
    from services.x402.commerce_store import reset_commerce_store
    from services.x402.idempotency import reset_idempotency_store
    reset_in_memory_stores()
    reset_commerce_store()
    reset_idempotency_store()
    _res_mod._registry = None
    yield
    reset_in_memory_stores()
    reset_commerce_store()
    reset_idempotency_store()
    _res_mod._registry = None


@pytest_asyncio.fixture
async def seeded_resource():
    """Seed facilitators/assets and register a protected resource."""
    from services.x402.commerce_models import ProtectedResource, ResourceClass
    from services.x402.facilitators import seed_facilitators_and_assets
    from services.x402.resources import ProtectedResourceRegistry
    await seed_facilitators_and_assets(TENANT)
    registry = ProtectedResourceRegistry()
    resource = ProtectedResource(
        tenant_id=TENANT,
        resource_id=RESOURCE_ID,
        name="Integration Test API",
        resource_class=ResourceClass.API,
        path_pattern="/v1/integration/test",
        owner_service="test",
        price_usd=1.0,
        accepted_assets=["USDC"],
        accepted_chains=["eip155:8453"],
        approval_required=True,
        entitlement_ttl_seconds=900,
        active=True,
    )
    return await registry.register(resource)


@pytest_asyncio.fixture
async def cp(seeded_resource):
    """X402ControlPlane with a mocked event producer."""
    from services.x402.control_plane import X402ControlPlane
    producer = AsyncMock()
    producer.publish = AsyncMock()
    return X402ControlPlane(event_producer=producer)
