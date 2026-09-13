"""In-memory fakes of RegistryPort / ObservationStorePort for pure unit tests.

No database, no network, no registry lane dependency — the engine only ever
sees these two ports, so these fakes pin the seam's behavior deterministically.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, List, Mapping, Optional, Set

from services.assets.models import CanonicalAsset
from services.valuation.ingest import observation_natural_key
from services.valuation.models import (
    CanonicalNativeValue,
    MarketPriceObservation,
)
from services.valuation.price_providers import parse_iso


def payload_field(native: Any, name: str) -> Any:
    if isinstance(native, Mapping):
        return native.get(name)
    return getattr(native, name, None)


class FakeObservationStore:
    """In-memory ObservationStorePort."""

    def __init__(self) -> None:
        self.rows: List[MarketPriceObservation] = []
        self.record_calls = 0

    def add_observations(self, observations: List[MarketPriceObservation]) -> None:
        self.rows.extend(observations)

    async def observations_for(
        self,
        asset_id: str,
        deployment_id: Optional[str],
        provider: str,
        effective_at: str,
        freshness_window_seconds: Optional[int] = None,
    ) -> List[MarketPriceObservation]:
        effective_dt = parse_iso(effective_at)
        matched = [
            obs for obs in self.rows
            if obs.asset_id == asset_id
            and obs.deployment_id == deployment_id
            and obs.provider == provider
            and parse_iso(obs.observed_at) <= effective_dt
        ]
        matched.sort(key=lambda obs: parse_iso(obs.observed_at), reverse=True)
        return matched

    async def record_observation(
        self, observation: MarketPriceObservation,
    ) -> bool:
        self.record_calls += 1
        key = observation_natural_key(observation)
        if any(observation_natural_key(row) == key for row in self.rows):
            return False
        self.rows.append(observation)
        return True


class FakeRegistry:
    """In-memory RegistryPort over a set of known canonical asset ids."""

    def __init__(
        self,
        known_ids: Optional[Set[str]] = None,
        *,
        registry_version: Optional[str] = None,
    ) -> None:
        self.known_ids: Set[str] = set(known_ids or ())
        self.registry_version = registry_version
        self.unresolved: List[dict] = []

    async def canonicalize(
        self, native: Any,
    ) -> Optional[CanonicalNativeValue]:
        asset_id = payload_field(native, "canonical_asset_id")
        if not asset_id or asset_id not in self.known_ids:
            return None
        amount = payload_field(native, "amount")
        currency = payload_field(native, "currency")
        if amount is None or currency is None:
            return None
        return CanonicalNativeValue(
            amount=Decimal(str(amount)),
            currency=str(currency),
            canonical_asset_id=str(asset_id),
            deployment_id=payload_field(native, "deployment_id"),
            economic_role=payload_field(native, "economic_role") or "unknown",
            asset_symbol=payload_field(native, "asset_symbol")
            or payload_field(native, "symbol"),
        )

    async def asset_for(self, asset_id: str) -> Optional[CanonicalAsset]:
        if asset_id not in self.known_ids:
            return None
        return CanonicalAsset(id=asset_id, kind="token", symbol=asset_id.split(":", 1)[-1])

    async def resolve_deployment(
        self,
        asset_id: str,
        *,
        deployment_id: Optional[str] = None,
        chain: Optional[str] = None,
        contract_or_mint: Optional[str] = None,
    ) -> Any:
        return None

    async def record_unresolved(
        self,
        *,
        raw_reference: str,
        tenant_id: Optional[str] = None,
        reason: str = "no_registry_entry",
        observed_at: Optional[str] = None,
    ) -> None:
        self.unresolved.append({
            "raw_reference": raw_reference,
            "tenant_id": tenant_id,
            "reason": reason,
            "observed_at": observed_at,
        })


def native_payload(
    amount: Any,
    currency: str,
    *,
    canonical_asset_id: Optional[str] = None,
    economic_role: Optional[str] = None,
    deployment_id: Optional[str] = None,
    symbol: Optional[str] = None,
) -> dict:
    payload: dict = {"amount": str(amount), "currency": currency}
    if canonical_asset_id is not None:
        payload["canonical_asset_id"] = canonical_asset_id
    if economic_role is not None:
        payload["economic_role"] = economic_role
    if deployment_id is not None:
        payload["deployment_id"] = deployment_id
    if symbol is not None:
        payload["symbol"] = symbol
    return payload
