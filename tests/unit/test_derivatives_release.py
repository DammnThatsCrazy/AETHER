from decimal import Decimal
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "services" / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from services.derivatives.models import PositionEpochState, PositionSide, PositionStatus  # noqa: E402
from services.derivatives.multi_venue import (  # noqa: E402
    CANONICAL_CONCEPTS,
    build_scaffolded_adapters,
    cross_venue_parity_report,
)


def test_structurally_distinct_venues_normalize_to_canonical_fill_facts():
    payloads = {
        "dydx": {"id": "dy-fill-1", "subaccount": "sub-7", "ticker": "BTC-USD", "side": "BUY", "price": "61000.12", "size": "0.10", "fee": "1.20", "feeAsset": "USDC", "createdAt": "2026-07-05T00:00:00Z", "liquidity": "maker"},
        "gmx": {"eventId": "gmx-fill-1", "account": "0xabc", "market": "ETH-USD", "direction": "short", "executionPrice": "3400.01", "sizeUsd": "100.00", "feeUsd": "0.40", "feeAsset": "USDC", "blockTime": "2026-07-05T00:01:00Z"},
        "drift": {"fillId": "drift-fill-1", "authority": "sol-auth", "marketName": "SOL-PERP", "direction": "long", "oraclePrice": "150.00", "baseAssetAmount": "2.5", "fee": "0.05", "feeAsset": "USDC", "slotTime": "2026-07-05T00:02:00Z", "liquidity": "taker"},
        "centralized_futures": {"tradeId": "cex-fill-1", "accountId": "acct-cex", "symbol": "BTCUSDT-PERP", "side": "SELL", "avgPrice": "60990.00", "contracts": "0.20", "commission": "1.00", "commissionAsset": "USDT", "time": "2026-07-05T00:03:00Z", "makerTaker": "taker"},
    }
    facts = []
    for venue_id, adapter in build_scaffolded_adapters().items():
        observation = adapter.bronze(
            "tenant-release",
            "unit-test",
            f"{venue_id}:fill:1",
            payloads[venue_id],
        )
        facts.append(adapter.normalize_fill(observation))
    assert {fact.provider for fact in facts} == {"dydx", "gmx", "drift", "centralized_futures"}
    assert all(fact.tenant_id == "tenant-release" for fact in facts)
    assert all(fact.execution_by_aether is False for fact in facts)
    assert all(isinstance(fact.price, Decimal) and isinstance(fact.quantity, Decimal) for fact in facts)
    assert all(fact.canonical_market_id.startswith(f"{fact.provider}:") for fact in facts)
    assert len({fact.idempotency_key for fact in facts}) == len(facts)


def test_cross_venue_parity_uses_capabilities_instead_of_fake_values():
    report = cross_venue_parity_report(build_scaffolded_adapters())
    assert report["provider_specific_api_leakage"] is False
    assert report["canonical_concepts"] == list(CANONICAL_CONCEPTS)
    assert report["venues"]["gmx"]["missing_concepts"] == ["orders"]
    assert "gmx" in report["missing_by_concept"]["orders"]
