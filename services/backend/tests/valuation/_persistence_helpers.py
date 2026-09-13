"""Shared DB-free helpers for valuation persistence tests (lane C3-W3).

Builds a minimal real UniversalAssetRegistry (no full seed) and deterministic
market observations so the canonicalize → observe → value → persist path runs
entirely on the typed-repo in-memory fallback under AETHER_ENV=local.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from services.assets.models import CanonicalAsset
from services.assets.registry import UniversalAssetRegistry
from services.valuation.models import MarketPriceObservation
from services.valuation.price_providers import (
    ORACLE,
    PROVIDER_REPORTED,
    market_observation,
    seconds_before,
)

EFFECTIVE = "2026-09-02T12:00:00+00:00"

USD = "fiat:USD"
GBP = "fiat:GBP"
ETH = "crypto:ETH"
USDC = "stablecoin:USDC"


def _kind(asset_id: str) -> str:
    return asset_id.split(":", 1)[0]


async def register_assets(registry: UniversalAssetRegistry, *asset_ids: str) -> None:
    for asset_id in asset_ids:
        await registry.register_asset(CanonicalAsset(
            id=asset_id,
            kind=_kind(asset_id),
            symbol=asset_id.split(":", 1)[-1],
            status="active",
        ))


async def make_registry(*asset_ids: str) -> UniversalAssetRegistry:
    registry = UniversalAssetRegistry()
    await register_assets(registry, *asset_ids)
    return registry


def eth_observation(
    price,
    *,
    observed_at: Optional[str] = None,
    provider: str = PROVIDER_REPORTED,
    source: Optional[str] = None,
) -> MarketPriceObservation:
    at = observed_at or seconds_before(EFFECTIVE, 60)
    return market_observation(
        ETH, USD, price, provider, at,
        source=source or f"{provider}:ETH:{price}",
        freshness_window_seconds=3600,
    )


def usd_observation(
    price,
    *,
    observed_at: Optional[str] = None,
    provider: str = PROVIDER_REPORTED,
    source: Optional[str] = None,
) -> MarketPriceObservation:
    at = observed_at or seconds_before(EFFECTIVE, 60)
    return market_observation(
        USD, USD, price, provider, at,
        source=source or f"{provider}:USD:{price}",
        freshness_window_seconds=3600,
    )


def usdc_observation(
    price,
    *,
    observed_at: Optional[str] = None,
    provider: str = ORACLE,
    source: Optional[str] = None,
) -> MarketPriceObservation:
    at = observed_at or seconds_before(EFFECTIVE, 5)
    return market_observation(
        USDC, USD, price, provider, at,
        source=source or f"{provider}:USDC:{price}",
        freshness_window_seconds=43200,
    )


def native_payload(
    amount,
    currency: str,
    *,
    canonical_asset_id: Optional[str] = None,
    economic_role: Optional[str] = None,
    deployment_id: Optional[str] = None,
) -> dict:
    payload = {"amount": str(amount), "currency": currency}
    if canonical_asset_id is not None:
        payload["canonical_asset_id"] = canonical_asset_id
    if economic_role is not None:
        payload["economic_role"] = economic_role
    if deployment_id is not None:
        payload["deployment_id"] = deployment_id
    return payload


def dec(value) -> Decimal:
    return Decimal(str(value))
