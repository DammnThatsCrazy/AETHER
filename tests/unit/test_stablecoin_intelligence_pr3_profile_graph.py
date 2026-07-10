import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Backend Architecture" / "aether-backend"))

from repositories.repos import reset_in_memory_stores
from repositories.stablecoin_repos import StablecoinObservationRepository
from services.stablecoins.graph_projector import StablecoinGraphProjector
from services.stablecoins.identity import StablecoinIdentityResolver, StablecoinWalletIdentityLink
from services.stablecoins.profile360 import StablecoinProfile360Composer


@pytest.fixture(autouse=True)
def reset_repos():
    reset_in_memory_stores()


@pytest.mark.asyncio
async def test_identity_resolution_is_tenant_scoped_and_unresolved_wallets_remain_visible():
    resolver = StablecoinIdentityResolver()
    await resolver.link_wallet(StablecoinWalletIdentityLink(
        tenant_id="tenant-a",
        wallet_address="0xABC",
        chain_id="8453",
        entity_id="human-1",
        entity_type="human",
        resolution_method="wallet_connection",
        deterministic=True,
        confidence=Decimal("0.99"),
        evidence_id="evt-1",
    ))

    resolved = await resolver.resolve_wallet(tenant_id="tenant-a", chain_id="8453", wallet_address="0xabc")
    unresolved = await resolver.resolve_wallet(tenant_id="tenant-b", chain_id="8453", wallet_address="0xabc")

    assert resolved["resolution_state"] == "resolved"
    assert resolved["entity_id"] == "human-1"
    assert unresolved["resolution_state"] == "unresolved"
    assert unresolved["entity_id"] == "unknown"


@pytest.mark.asyncio
async def test_graph_projection_is_tenant_scoped_idempotent_and_does_not_cross_tenants():
    projector = StablecoinGraphProjector()
    observation = {
        "tenant_id": "tenant-a",
        "observation_id": "obs-1",
        "deployment_id": "usdc:base",
        "canonical_asset_id": "usdc",
        "chain_id": "8453",
        "transaction_hash": "0xabc",
        "from_address": "0xFrom",
        "to_address": "0xTo",
        "source": "rpc",
        "evidence_id": "bronze-1",
    }
    first = await projector.enqueue_projection(observation)
    second = await projector.enqueue_projection(observation)

    assert first["projection_id"] == second["projection_id"]
    assert len(second["edges"]) == 3
    assert all(edge["tenant_id"] == "tenant-a" for edge in second["edges"])
    assert all(vertex["tenant_id"] == "tenant-a" for vertex in second["vertices"])


@pytest.mark.asyncio
async def test_profile360_composer_exposes_unresolved_and_unattributed_activity_without_cross_tenant_rows():
    repo = StablecoinObservationRepository()
    await repo.insert("obs-1", {
        "observation_id": "obs-1",
        "tenant_id": "tenant-a",
        "source": "rpc",
        "evidence_id": "bronze-1",
        "finality_status": "finalized",
        "event_type": "payment",
        "canonical_asset_id": "usdc",
        "deployment_id": "usdc:base",
        "chain_id": "8453",
        "amount_atomic": 250,
        "from_address": "0xpayer",
        "to_address": "0xmerchant",
        "to_entity_id": "merchant-1",
    })
    await repo.insert("obs-other", {
        "observation_id": "obs-other",
        "tenant_id": "tenant-b",
        "finality_status": "finalized",
        "event_type": "payment",
        "canonical_asset_id": "usdt",
        "deployment_id": "usdt:eth",
        "chain_id": "1",
        "amount_atomic": 999,
        "to_entity_id": "merchant-1",
    })

    profile = await StablecoinProfile360Composer(repo).compose(tenant_id="tenant-a", profile_id="merchant-1")

    assert profile["tenant_id"] == "tenant-a"
    assert profile["summary"]["finalized_payment_volume_atomic"] == "250"
    assert profile["summary"]["unattributed_visible"] is True
    assert profile["summary"]["unresolved_wallets_visible"] is True
    assert [item["observation_id"] for item in profile["items"]] == ["obs-1"]
