"""Hyperliquid derivatives connector normalization.

The adapter is production-shaped but network calls are deliberately injected via
fixtures/transport in PR2 tests. Raw provider payloads land in Bronze first and
``normalize`` projects supported records to Silver facts.
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from services.derivatives.connectors.base import (
    DerivativesConnector,
    DerivativesConnectorCheckpoint,
    DerivativesConnectorHealth,
    enforce_read_only_credentials,
)
from services.derivatives.models import (
    BronzeObservation,
    LiquidityRole,
    NormalizedFillFact,
    OrderSide,
    SourceRef,
    decimal_from_provider,
)


class HyperliquidConnector(DerivativesConnector):
    provider = "hyperliquid"

    def __init__(self, *, tenant_id: str, deployment: str = "mainnet", connector_id: str = "hyperliquid") -> None:
        self.tenant_id = tenant_id
        self.deployment = deployment
        self.connector_id = connector_id

    async def describe_venue(self) -> Mapping[str, Any]:
        return {
            "venue_id": "hyperliquid",
            "venue_type": "decentralized_exchange",
            "deployments": [self.deployment],
            "capabilities": ["markets", "account_snapshot", "fills", "funding", "realtime_account_stream"],
        }

    async def test_connection(self, scopes: Iterable[str]) -> DerivativesConnectorHealth:
        enforce_read_only_credentials(scopes)
        return DerivativesConnectorHealth(connector_id=self.connector_id, state="ok")

    async def fetch_markets(self, *, checkpoint: DerivativesConnectorCheckpoint | None = None) -> list[BronzeObservation]:
        return []

    async def fetch_account_snapshot(self, *, account_ref: str, checkpoint: DerivativesConnectorCheckpoint | None = None) -> list[BronzeObservation]:
        return []

    async def fetch_fills(self, *, account_ref: str, checkpoint: DerivativesConnectorCheckpoint | None = None) -> list[BronzeObservation]:
        return []

    async def subscribe_account_stream(self, *, account_ref: str, checkpoint: DerivativesConnectorCheckpoint | None = None) -> AsyncIterator[BronzeObservation]:
        if False:  # pragma: no cover - keeps method an async iterator without a live socket in PR2 foundation tests.
            yield self._bronze("websocket_message", account_ref, "noop", {})
        return

    def normalize(self, observation: BronzeObservation) -> list[NormalizedFillFact]:
        if observation.record_type != "raw_fill":
            return []
        payload = observation.raw_payload
        side = OrderSide.BUY if str(payload.get("side", "")).upper() in {"B", "BUY"} else OrderSide.SELL
        role = str(payload.get("liquidity", payload.get("liquidity_role", "unknown"))).lower()
        liquidity_role = LiquidityRole.MAKER if role == "maker" else LiquidityRole.TAKER if role == "taker" else LiquidityRole.UNKNOWN
        fill_id = str(payload.get("hash") or payload.get("tid") or observation.source_record_id)
        account_ref = str(payload.get("account") or payload.get("user") or "unknown_account")
        market = str(payload.get("coin") or payload.get("market") or "UNKNOWN")
        return [
            NormalizedFillFact(
                tenant_id=observation.tenant_id,
                provider=self.provider,
                deployment=observation.deployment,
                trading_account_id=f"acct_{account_ref}",
                canonical_market_id=f"hyperliquid:{self.deployment}:{market}",
                fill_id=fill_id,
                side=side,
                price=decimal_from_provider(payload["px"], "px"),
                quantity=decimal_from_provider(payload["sz"], "sz"),
                fee_amount=decimal_from_provider(payload.get("fee", "0"), "fee"),
                fee_asset_id=str(payload.get("feeToken", "USDC")),
                liquidity_role=liquidity_role,
                executed_at=str(payload.get("time") or observation.observed_at),
                source_ref=SourceRef(provider=self.provider, source_record_id=observation.source_record_id, observed_at=observation.observed_at),
            )
        ]

    def checkpoint(self, observations: list[BronzeObservation]) -> DerivativesConnectorCheckpoint | None:
        if not observations:
            return None
        latest = max(observations, key=lambda obs: obs.observed_at)
        return DerivativesConnectorCheckpoint(
            tenant_id=latest.tenant_id,
            connector_id=self.connector_id,
            checkpoint_value=f"{latest.record_type}:{latest.source_record_id}:{latest.observed_at}",
            advanced_at=datetime.now(timezone.utc).isoformat(),
        )

    def _bronze(self, record_type: str, account_ref: str, source_record_id: str, payload: Mapping[str, Any]) -> BronzeObservation:
        return BronzeObservation(
            tenant_id=self.tenant_id,
            provider=self.provider,
            deployment=self.deployment,
            record_type=record_type,
            source_record_id=source_record_id,
            raw_payload=payload,
            observed_at=datetime.now(timezone.utc).isoformat(),
            idempotency_key=":".join([self.tenant_id, self.provider, self.deployment, account_ref, source_record_id]),
        )
