"""Shared fixtures for x402 commerce integration tests."""

from __future__ import annotations

import asyncio
import functools
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

try:
    import pytest_asyncio
except ImportError:  # pragma: no cover - fallback for constrained local sandboxes
    class _PytestAsyncioFallback:
        @staticmethod
        def fixture(func=None, **kwargs):
            def decorate(inner):
                @functools.wraps(inner)
                def wrapper(*args, **fixture_kwargs):
                    return asyncio.run(inner(*args, **fixture_kwargs))

                return pytest.fixture(**kwargs)(wrapper)

            if func is None:
                return decorate
            return decorate(func)

    pytest_asyncio = _PytestAsyncioFallback()

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


def _reset_all():
    import services.x402.approvals as _approvals_mod
    import services.x402.entitlements as _entitlements_mod
    import services.x402.facilitators as _facilitators_mod
    import services.x402.policies as _policies_mod
    import services.x402.resources as _res_mod
    import services.x402.settlement as _settlement_mod
    import services.x402.verification as _verification_mod
    from repositories.repos import reset_in_memory_stores
    from services.x402.commerce_store import reset_commerce_store
    from services.x402.control_plane import reset_control_plane
    from services.x402.idempotency import reset_idempotency_store

    reset_in_memory_stores()
    reset_commerce_store()
    reset_idempotency_store()
    reset_control_plane()
    # Null out service singletons so they re-bind to the new store on next use.
    _res_mod._registry = None
    _approvals_mod._service = None
    _policies_mod._engine = None
    _settlement_mod._tracker = None
    _entitlements_mod._service = None
    _facilitators_mod._facilitator_registry = None
    _facilitators_mod._asset_registry = None
    _verification_mod._engine = None


@pytest.fixture(autouse=True)
def reset_all_stores():
    _reset_all()
    yield
    _reset_all()


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
