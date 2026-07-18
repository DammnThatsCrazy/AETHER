"""Chainlink-compatible on-chain price-feed connector + honest peg classification.

Reads a Chainlink ``AggregatorV3`` feed over the injectable read-only RPC seam
(``eth_call`` → ``latestRoundData`` / ``decimals``) and produces a timestamped,
source-attributed peg snapshot. It reuses the depeg thresholds from
``services/stablecoin/valuation.py`` (singular) so classification stays canonical.

HONEST VALUE is the whole point:

* an unavailable / reverted / non-positive answer stays UNAVAILABLE — the price
  is ``None``, never ``0`` and never silently ``1 USD``;
* a stale answer (older than the configured staleness window, or an incomplete
  round) is not trusted for peg classification (``peg_status = "unknown"``);
* every price is a ``Decimal`` derived from the integer feed answer + feed
  decimals — NEVER a float;
* the snapshot always attributes the value to its feed address, round id, and
  ``updatedAt``.

Observation-only: no signing, execution, or write calls.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping, Optional

from services.stablecoin.valuation import classify_peg
from shared.common.common import utc_now
from shared.logger.logger import get_logger
from shared.temporal import to_iso_utc

from .connector_base import (
    ConnectorCertificationMixin,
    StablecoinConnectorError,
    StablecoinRpcClient,
    atomic_from_answer,
    guarded_rpc,
    iso_from_unix,
)
from .models import StablecoinDeployment

logger = get_logger("aether.stablecoins.price_feed")

# AggregatorV3Interface selectors (first 4 bytes of the function signature hash).
LATEST_ROUND_DATA_SELECTOR = "0xfeaf968c"  # latestRoundData()
DECIMALS_SELECTOR = "0x313ce567"           # decimals()

# Confidence tokens (source-attributed, honest).
CONFIDENCE_HIGH = "high"
CONFIDENCE_DEGRADED = "degraded"
CONFIDENCE_STALE = "stale"
CONFIDENCE_UNAVAILABLE = "unavailable"

# Peg status returned when the price cannot be trusted — a stablecoin is NEVER
# assumed on-peg (or worth 1 USD) in the absence of a fresh, valid answer.
PEG_UNKNOWN = "unknown"

_BPS = Decimal("10000")
_PAR = Decimal("1")


@dataclass(frozen=True)
class StablecoinPriceObservation:
    """A timestamped, source-attributed peg snapshot with honest availability."""

    deployment_id: str
    chain_id: str
    canonical_asset_id: str
    available: bool
    price_usd: Optional[Decimal]
    peg_status: str
    peg_deviation_bps: Optional[Decimal]
    confidence: str
    stale: bool
    observed_at: str
    reason: str = ""
    source: Mapping[str, Any] = field(default_factory=dict)


class StablecoinChainlinkPriceConnector(ConnectorCertificationMixin):
    """Read-only Chainlink price-feed connector for one stablecoin deployment."""

    domain = "stablecoin_price"
    adapter_version = "1.0.0"
    cert_supported_operations = (
        "connection_test",
        "latest_round_data",
        "feed_decimals",
        "staleness_check",
        "peg_classification",
    )
    cert_unsupported_operations = (
        "historical_round_retrieval",
        "price_push_subscription",
        "off_chain_aggregation",
    )
    cert_required_endpoints = ("evm_json_rpc",)
    cert_pagination_model = "none"
    cert_rate_limit_behavior = (
        "HTTP 429 classified as rate_limited via RPCGateway; a rate-limited or "
        "failed read yields an UNAVAILABLE snapshot (never a fabricated price)"
    )
    cert_retry_policy = (
        "single latestRoundData read per snapshot; classified failures return an "
        "unavailable snapshot for the caller to retry on the next cycle"
    )

    def __init__(
        self,
        *,
        deployment: StablecoinDeployment,
        feed_address: str,
        rpc: Optional[StablecoinRpcClient] = None,
        provider: str = "chainlink_price_feed",
        feed_decimals: int = 8,
        staleness_threshold_seconds: int = 3600,
        source_manifest_id: str = "",
    ) -> None:
        if not feed_address:
            raise ValueError("feed_address is required for the price-feed connector")
        if staleness_threshold_seconds < 1:
            raise ValueError("staleness_threshold_seconds must be positive")
        self.deployment = deployment
        self.chain_id = str(deployment.chain_id)
        self.canonical_asset_id = deployment.canonical_asset_id
        self.feed_address = feed_address
        self.provider = provider
        self.default_feed_decimals = int(feed_decimals)
        self.staleness_threshold_seconds = int(staleness_threshold_seconds)
        self.source_manifest_id = source_manifest_id or f"chainlink:{deployment.deployment_id}"
        self.rpc: StablecoinRpcClient = rpc if rpc is not None else _default_rpc()
        self._feed_decimals: Optional[int] = None

    # ── public surface ───────────────────────────────────────────────────────

    async def test_connection(self) -> dict[str, Any]:
        """Prove the feed answers ``decimals()`` over the RPC seam."""
        decimals = await self._decimals()
        return {"ok": True, "feed_address": self.feed_address, "feed_decimals": decimals}

    async def get_price_observation(self) -> StablecoinPriceObservation:
        """Fetch ``latestRoundData`` and classify the peg honestly.

        Any failure (revert, empty result, rate limit, non-positive answer)
        yields an UNAVAILABLE snapshot — the price is ``None``, never 0/1 USD.
        """
        observed_at = to_iso_utc(utc_now())
        try:
            decimals = await self._decimals()
            round_data = await self._latest_round_data()
        except StablecoinConnectorError as exc:
            return self._unavailable(observed_at, reason=exc.classification)

        if round_data is None:
            return self._unavailable(observed_at, reason="empty_round_data")

        round_id, answer, _started_at, updated_at, answered_in_round = round_data
        if answer <= 0:
            # A zero/negative feed answer is NOT a price. Never emit 0.
            return self._unavailable(
                observed_at,
                reason="non_positive_answer",
                source=self._source(round_id, updated_at, answered_in_round, None),
            )

        price_usd = atomic_from_answer(answer, decimals)  # Decimal, never float
        now_ts = int(utc_now().timestamp())
        age_seconds = max(0, now_ts - int(updated_at)) if updated_at else None
        stale = updated_at == 0 or (age_seconds is not None and age_seconds > self.staleness_threshold_seconds)
        incomplete = int(answered_in_round) < int(round_id)

        source = self._source(round_id, updated_at, answered_in_round, price_usd)

        if stale:
            # A stale price is real evidence but untrusted for peg — do NOT
            # assume on-peg / 1 USD. Surface the value with stale confidence.
            return StablecoinPriceObservation(
                deployment_id=self.deployment.deployment_id,
                chain_id=self.chain_id,
                canonical_asset_id=self.canonical_asset_id,
                available=True,
                price_usd=price_usd,
                peg_status=PEG_UNKNOWN,
                peg_deviation_bps=None,
                confidence=CONFIDENCE_STALE,
                stale=True,
                observed_at=observed_at,
                reason="stale_round",
                source=source,
            )

        deviation_bps = (price_usd - _PAR) * _BPS
        peg_status = classify_peg(deviation_bps)  # reuse singular depeg thresholds
        confidence = CONFIDENCE_DEGRADED if incomplete else CONFIDENCE_HIGH
        return StablecoinPriceObservation(
            deployment_id=self.deployment.deployment_id,
            chain_id=self.chain_id,
            canonical_asset_id=self.canonical_asset_id,
            available=True,
            price_usd=price_usd,
            peg_status=peg_status,
            peg_deviation_bps=deviation_bps,
            confidence=confidence,
            stale=False,
            observed_at=observed_at,
            reason="" if not incomplete else "incomplete_round",
            source=source,
        )

    # ── RPC + ABI decoding ───────────────────────────────────────────────────

    async def _decimals(self) -> int:
        if self._feed_decimals is not None:
            return self._feed_decimals
        try:
            raw = await self._eth_call(DECIMALS_SELECTOR)
            words = _words(raw)
            self._feed_decimals = int(words[0]) if words else self.default_feed_decimals
        except (StablecoinConnectorError, ValueError):
            self._feed_decimals = self.default_feed_decimals
        return self._feed_decimals

    async def _latest_round_data(self) -> Optional[tuple[int, int, int, int, int]]:
        raw = await self._eth_call(LATEST_ROUND_DATA_SELECTOR)
        words = _words(raw)
        if len(words) < 5:
            return None
        round_id = words[0]
        answer = _to_signed(words[1])
        started_at = words[2]
        updated_at = words[3]
        answered_in_round = words[4]
        return round_id, answer, started_at, updated_at, answered_in_round

    async def _eth_call(self, selector: str) -> str:
        response = await guarded_rpc(
            self.rpc,
            self.chain_id,
            "eth_call",
            [{"to": self.feed_address, "data": selector}, "latest"],
        )
        result = response.get("result")
        return result if isinstance(result, str) else ""

    def _source(self, round_id: int, updated_at: int, answered_in_round: int, price: Optional[Decimal]) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "feed_address": self.feed_address,
            "chain_id": self.chain_id,
            "round_id": str(round_id),
            "answered_in_round": str(answered_in_round),
            "updated_at": iso_from_unix(updated_at) if updated_at else "",
            "price_usd": str(price) if price is not None else "",
            "source_manifest_id": self.source_manifest_id,
        }

    def _unavailable(
        self, observed_at: str, *, reason: str, source: Optional[Mapping[str, Any]] = None
    ) -> StablecoinPriceObservation:
        return StablecoinPriceObservation(
            deployment_id=self.deployment.deployment_id,
            chain_id=self.chain_id,
            canonical_asset_id=self.canonical_asset_id,
            available=False,
            price_usd=None,  # NEVER 0, NEVER assumed 1 USD
            peg_status=PEG_UNKNOWN,
            peg_deviation_bps=None,
            confidence=CONFIDENCE_UNAVAILABLE,
            stale=False,
            observed_at=observed_at,
            reason=reason,
            source=dict(source) if source else {"provider": self.provider, "feed_address": self.feed_address},
        )

    # ── certification duck-typed hooks ───────────────────────────────────────

    def normalize(self, payload: Any) -> Optional[dict[str, Any]]:
        """Canonicalize a raw round-data mapping; drift/malformed tolerant."""
        if not isinstance(payload, dict):
            return None
        answer = payload.get("answer")
        decimals = payload.get("decimals", self.default_feed_decimals)
        if answer is None:
            return None
        try:
            answer_int = int(answer)
            price = atomic_from_answer(answer_int, int(decimals))
        except (ValueError, TypeError):
            return None
        if answer_int <= 0:
            return {"available": "false", "price_usd": "", "peg_status": PEG_UNKNOWN}
        return {"available": "true", "price_usd": str(price), "feed_address": self.feed_address}


def _words(raw: str) -> list[int]:
    """Split an ``eth_call`` hex result into 32-byte words as unsigned ints."""
    if not isinstance(raw, str):
        return []
    body = raw[2:] if raw.lower().startswith("0x") else raw
    if not body:
        return []
    return [int(body[i:i + 64], 16) for i in range(0, len(body) - len(body) % 64, 64)]


def _to_signed(value: int, bits: int = 256) -> int:
    """Interpret an unsigned word as a two's-complement signed integer."""
    if value >= 1 << (bits - 1):
        return value - (1 << bits)
    return value


def _default_rpc() -> StablecoinRpcClient:
    from services.onchain.rpc_gateway import RPCGateway

    return RPCGateway()


__all__ = [
    "StablecoinChainlinkPriceConnector",
    "StablecoinPriceObservation",
    "LATEST_ROUND_DATA_SELECTOR",
    "DECIMALS_SELECTOR",
    "PEG_UNKNOWN",
    "CONFIDENCE_HIGH",
    "CONFIDENCE_DEGRADED",
    "CONFIDENCE_STALE",
    "CONFIDENCE_UNAVAILABLE",
]
