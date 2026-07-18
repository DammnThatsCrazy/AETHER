"""Hyperliquid derivatives connector — Bronze ingestion + Silver normalization.

This is the ``DerivativesConnector`` view of Hyperliquid: it fetches raw provider
records into Bronze over the INJECTABLE REST client and normalizes fills to
Silver ``NormalizedFillFact``. It converges with the canonical
:class:`~services.derivatives.adapters.hyperliquid.HyperliquidAdapter` (which
projects the same reads to canonical observation events); this connector is the
lower-level Bronze/Silver ingestion path used by replay + the ingestion pipeline.

Import-safe + offline by default: ``httpx`` is only touched inside the injected
transport; with no ``http_transport`` / ``rest_client`` supplied the fetch
methods return nothing (credential-waiting) rather than performing IO.
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Mapping
from typing import Any, Optional

from shared.common.common import utc_now
from services.derivatives.connectors.base import (
    DerivativesConnector,
    DerivativesConnectorCheckpoint,
    DerivativesConnectorHealth,
    enforce_read_only_credentials,
)
from services.derivatives.connectors.stream import FrameSourceFactory
from services.derivatives.connectors.transport import (
    PROVIDER_HEALTH_OK,
    ProviderRequestError,
    RestBackfillClient,
)
from services.derivatives.models import (
    BronzeObservation,
    LiquidityRole,
    NormalizedFillFact,
    OrderSide,
    SourceRef,
    decimal_from_provider,
)

_REST_BASE_URL = "https://api.hyperliquid.xyz"


class HyperliquidConnector(DerivativesConnector):
    provider = "hyperliquid"

    def __init__(
        self,
        *,
        tenant_id: str,
        deployment: str = "mainnet",
        connector_id: str = "hyperliquid",
        rest_client: Optional[RestBackfillClient] = None,
        http_transport: Any = None,
        stream_factory: Optional[FrameSourceFactory] = None,
        sleeper: Any = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.deployment = deployment
        self.connector_id = connector_id
        if rest_client is not None:
            self._rest: Optional[RestBackfillClient] = rest_client
        elif http_transport is not None:
            self._rest = RestBackfillClient(
                http_transport=http_transport, base_url=_REST_BASE_URL, sleeper=sleeper,
            )
        else:
            self._rest = None
        self._stream_factory = stream_factory

    async def describe_venue(self) -> Mapping[str, Any]:
        return {
            "venue_id": "hyperliquid",
            "venue_type": "decentralized_exchange",
            "deployments": [self.deployment],
            "capabilities": ["markets", "account_snapshot", "fills", "funding", "realtime_account_stream"],
        }

    async def test_connection(self, scopes: Iterable[str]) -> DerivativesConnectorHealth:
        enforce_read_only_credentials(scopes)
        if self._rest is None:
            return DerivativesConnectorHealth(connector_id=self.connector_id, state="credential_waiting")
        health = {"health": PROVIDER_HEALTH_OK}
        try:
            await self._rest.request_json(
                {"method": "POST", "url": f"{_REST_BASE_URL}/info", "json": {"type": "meta"}},
                health=health,
            )
        except ProviderRequestError as exc:
            return DerivativesConnectorHealth(
                connector_id=self.connector_id, state=exc.classification, last_error=str(exc),
            )
        return DerivativesConnectorHealth(connector_id=self.connector_id, state="ok")

    async def fetch_markets(self, *, checkpoint: DerivativesConnectorCheckpoint | None = None) -> list[BronzeObservation]:
        if self._rest is None:
            return []
        payload = await self._rest.request_json(
            {"method": "POST", "url": f"{_REST_BASE_URL}/info", "json": {"type": "meta"}}
        )
        universe = payload.get("universe", []) if isinstance(payload, Mapping) else []
        return [
            self._bronze("raw_market", "public", str(entry.get("name", "")), dict(entry))
            for entry in universe
        ]

    async def fetch_account_snapshot(self, *, account_ref: str, checkpoint: DerivativesConnectorCheckpoint | None = None) -> list[BronzeObservation]:
        if self._rest is None:
            return []
        payload = await self._rest.request_json({
            "method": "POST", "url": f"{_REST_BASE_URL}/info",
            "json": {"type": "clearinghouseState", "user": account_ref},
        })
        if not isinstance(payload, Mapping):
            return []
        return [self._bronze("raw_account", account_ref, account_ref, dict(payload))]

    async def fetch_fills(self, *, account_ref: str, checkpoint: DerivativesConnectorCheckpoint | None = None) -> list[BronzeObservation]:
        if self._rest is None:
            return []

        def build_request(cursor: Optional[str]) -> dict[str, Any]:
            return {
                "method": "POST", "url": f"{_REST_BASE_URL}/info",
                "json": {"type": "userFillsByTime", "user": account_ref, "startTime": int(cursor or 0)},
            }

        def extract_page(payload: Any) -> tuple[list[dict], Optional[str]]:
            records = payload if isinstance(payload, list) else []
            if not records:
                return [], None
            latest = max(int(r.get("time", 0)) for r in records)
            return records, str(latest + 1)

        start = checkpoint.checkpoint_value if checkpoint else None
        records, _ = await self._rest.paginate(build_request, extract_page, start_cursor=start)
        return [
            self._bronze("raw_fill", account_ref, str(r.get("tid") or r.get("hash")), dict(r))
            for r in records
        ]

    async def subscribe_account_stream(self, *, account_ref: str, checkpoint: DerivativesConnectorCheckpoint | None = None) -> AsyncIterator[BronzeObservation]:
        if self._stream_factory is None:
            return
        source = self._stream_factory(None)
        async for frame in source:
            payload = frame.get("payload") if isinstance(frame, Mapping) else None
            body = dict(payload) if isinstance(payload, Mapping) else dict(frame)
            yield self._bronze(
                "websocket_message", account_ref,
                str(body.get("tid") or body.get("hash") or utc_now().isoformat()), body,
            )

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
            advanced_at=utc_now().isoformat(),
        )

    def _bronze(self, record_type: str, account_ref: str, source_record_id: str, payload: Mapping[str, Any]) -> BronzeObservation:
        return BronzeObservation(
            tenant_id=self.tenant_id,
            provider=self.provider,
            deployment=self.deployment,
            record_type=record_type,
            source_record_id=source_record_id,
            raw_payload=dict(payload),
            observed_at=str(payload.get("time") or utc_now().isoformat()),
            idempotency_key=":".join([self.tenant_id, self.provider, self.deployment, account_ref, source_record_id]),
        )
