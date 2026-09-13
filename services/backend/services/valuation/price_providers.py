"""Price providers + deterministic CI fixtures for event-time valuation.

The event-time valuation engine (``services/valuation/engine.py``) prices
through the injected :class:`ObservationStorePort` — it never talks to a
provider or a network directly. This module therefore supplies the *vocabulary*
and *fixtures* around providers:

- canonical provider names (``provider_reported``, ``venue_exec``,
  ``primary_market``, ``fx``, ``stablecoin_peg``, ``oracle``, ``fallback``,
  ``manual``) and the provider → ``ValuationMethodExtended`` mapping;
- the ordered default provider chain and the named provider-chain policy
  registry (only ``default`` is resolvable in the pure core; unknown policy
  ids fail closed so a tenant policy is never silently ignored);
- a small :class:`PriceProvider` Protocol describing the shape a *live* source
  exposes (deterministic CI fixture providers implement it; the real adapters
  append observations through ``services/valuation/ingest.py`` in a later wave);
- deterministic, no-network, no-credential fixture builders + a
  :class:`PriceFixtures` registry so unit tests / CI can simulate provider
  conflict, staleness, outliers and missing rates.

Invariants: every price is a Decimal / decimal string (floats are rejected by
``MarketPriceObservation``), providers never fabricate an observation when one
is missing, and FX observations use the base/quote canonical asset-id shape
(``asset_id`` priced, ``quote_asset_id`` denominating).
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Protocol, Union

from services.valuation.models import MarketPriceObservation
from shared.temporal.instant import coerce_utc_lenient as _coerce_utc_lenient
from repositories.typed_repo import as_decimal

# ── Canonical provider names ────────────────────────────────────────────────
# Each name is the ``provider`` a MarketPriceObservation carries and the value
# the tenant provider-chain policy is written against.

PROVIDER_REPORTED = "provider_reported"
VENUE_EXEC = "venue_exec"
PRIMARY_MARKET = "primary_market"
FX = "fx"
STABLECOIN_PEG = "stablecoin_peg"
ORACLE = "oracle"
FALLBACK = "fallback"
MANUAL = "manual"

PROVIDERS = frozenset({
    PROVIDER_REPORTED, VENUE_EXEC, PRIMARY_MARKET, FX,
    STABLECOIN_PEG, ORACLE, FALLBACK, MANUAL,
})

# Provider -> ValuationMethodExtended. ``stablecoin_peg`` and USD-denominated
# stablecoins are refined by the engine via ``classify_peg`` (on_peg becomes
# ``stablecoin_peg_verified``; deviation stays ``stablecoin_peg``).
PROVIDER_VALUATION_METHODS: dict[str, str] = {
    PROVIDER_REPORTED: "provider_reported",
    VENUE_EXEC: "venue_exec",
    PRIMARY_MARKET: "primary_market",
    FX: "fx_rate",
    STABLECOIN_PEG: "stablecoin_peg",
    ORACLE: "oracle",
    FALLBACK: "market_price",
    MANUAL: "manual",
}

# Default provider chain, in trust order. The engine walks it left-to-right and
# stops at the first *usable* observation; independent live sources behind the
# winner are still compared so provider_conflict / outlier are surfaced rather
# than silently resolved.
DEFAULT_PROVIDER_CHAIN = (
    PROVIDER_REPORTED,
    VENUE_EXEC,
    PRIMARY_MARKET,
    FX,
    STABLECOIN_PEG,
    ORACLE,
    FALLBACK,
)

# Named provider-chain policies the pure engine can resolve. Unknown ids are
# rejected (fail closed) — a tenant policy we cannot honor must not silently
# degrade to a different chain.
POLICY_PROVIDER_CHAINS: dict[str, tuple[str, ...]] = {
    "default": DEFAULT_PROVIDER_CHAIN,
}


def provider_chain_for(policy_name: str) -> tuple[str, ...]:
    """Resolve a named provider-chain policy.

    Raises ValueError for unknown policy ids — the pure engine fails closed
    rather than silently valuing under a chain the tenant did not ask for.
    """
    chain = POLICY_PROVIDER_CHAINS.get(policy_name)
    if chain is None:
        raise ValueError(
            f"unknown provider_chain_policy {policy_name!r}; known policies: "
            + ", ".join(sorted(POLICY_PROVIDER_CHAINS))
        )
    return chain

# Fallback freshness horizon (seconds) when neither an observation nor a tenant
# policy carries one. Observations carry their own freshness_window_seconds when
# the producing source knows better; tenant_policy.stale_threshold_seconds wins
# over this global default.
DEFAULT_FRESHNESS_WINDOW_SECONDS = 86400  # 24h

# Canonical reporting asset used when the caller gives no reporting_asset_id.
USD_ASSET_ID = "fiat:USD"

# ── Small time helpers (pure; no DB / network) ──────────────────────────────


def parse_iso(value: Union[str, datetime]) -> datetime:
    """Parse an ISO-8601 timestamp to an aware UTC datetime (naive => UTC).

    Naive-assumption lives in the temporal kernel
    (``shared.temporal.instant.coerce_utc_lenient`` — the only place permitted
    to attach a timezone); this wrapper keeps the local raise-on-invalid and
    normalize-to-UTC contract.
    """
    parsed = _coerce_utc_lenient(value)
    if parsed is None:
        raise ValueError(f"invalid or empty ISO-8601 timestamp: {value!r}")
    return parsed.astimezone(timezone.utc)


def to_iso(value: Union[str, datetime]) -> str:
    return parse_iso(value).isoformat()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def seconds_before(iso: Union[str, datetime], seconds: float) -> str:
    """Return ``iso`` minus ``seconds`` as an ISO string (fixture helper)."""
    dt = parse_iso(iso)
    from datetime import timedelta

    return (dt - timedelta(seconds=seconds)).isoformat()


def minutes_before(iso: Union[str, datetime], minutes: float) -> str:
    return seconds_before(iso, minutes * 60)


def deterministic_observation_id(
    *,
    asset_id: str,
    provider: str,
    quote_asset_id: str,
    observed_at: str,
    source: str,
    deployment_id: Optional[str] = None,
    source_record_id: Optional[str] = None,
) -> str:
    """Stable observation id so ValuationSnapshots can reference observations."""
    basis = "|".join(
        str(v)
        for v in (
            asset_id, deployment_id or "", provider, quote_asset_id,
            observed_at, source, source_record_id or "",
        )
    )
    return "obs_" + hashlib.sha256(basis.encode()).hexdigest()[:32]


# ── PriceProvider seam ──────────────────────────────────────────────────────


class PriceProvider(Protocol):
    """A live price source capable of yielding one deterministic observation.

    Real adapters (exchange venues, market-data feeds, Chainlink-style oracles,
    FX rates, stablecoin-peg feeds) implement this seam and append their result
    through :func:`services.valuation.ingest.observe_price` so the observation
    store stays the single source of truth. The engine itself never calls a
    provider — it reads the store.
    """

    name: str

    async def observe(
        self,
        asset_id: str,
        *,
        quote_asset_id: str,
        deployment_id: Optional[str] = None,
        observed_at: Optional[str] = None,
    ) -> Optional[MarketPriceObservation]:
        """Return the provider's current price for ``asset_id`` quoted in
        ``quote_asset_id``, or None when the provider has no rate. Never
        fabricates an observation."""
        ...


# ── Deterministic observation builder ───────────────────────────────────────

PriceInput = Union[str, int, Decimal]


def make_observation(
    *,
    asset_id: str,
    quote_asset_id: str,
    price: PriceInput,
    provider: str,
    observed_at: str,
    source: str,
    deployment_id: Optional[str] = None,
    source_record_id: Optional[str] = None,
    freshness_window_seconds: Optional[int] = None,
    observation_id: Optional[str] = None,
) -> MarketPriceObservation:
    """Build a validated MarketPriceObservation.

    ``price`` is coerced to Decimal via ``repositories.typed_repo.as_decimal``
    — a binary float raises (floats are never legal canonical amounts). When
    ``observation_id`` is omitted a deterministic id is derived from the
    observation's natural key.
    """
    if provider not in PROVIDERS:
        raise ValueError(f"unknown price provider: {provider!r}")
    if not (asset_id and quote_asset_id and observed_at and source):
        raise ValueError("asset_id, quote_asset_id, observed_at, source are required")
    oid = observation_id or deterministic_observation_id(
        asset_id=asset_id,
        deployment_id=deployment_id,
        provider=provider,
        quote_asset_id=quote_asset_id,
        observed_at=observed_at,
        source=source,
        source_record_id=source_record_id,
    )
    freshness = (
        freshness_window_seconds
        if freshness_window_seconds is not None
        else DEFAULT_FRESHNESS_WINDOW_SECONDS
    )
    return MarketPriceObservation(
        observation_id=oid,
        asset_id=asset_id,
        deployment_id=deployment_id,
        provider=provider,
        price=as_decimal(price),  # float => TypeError (model wraps as ValueError)
        quote_asset_id=quote_asset_id,
        observed_at=observed_at,
        source=source,
        freshness_window_seconds=freshness,
        source_record_id=source_record_id,
    )


def market_observation(
    asset_id: str,
    quote_asset_id: str,
    price: PriceInput,
    provider: str,
    observed_at: str,
    *,
    source: Optional[str] = None,
    deployment_id: Optional[str] = None,
    source_record_id: Optional[str] = None,
    freshness_window_seconds: Optional[int] = None,
) -> MarketPriceObservation:
    """Convenience builder delegating to :func:`make_observation`."""
    return make_observation(
        asset_id=asset_id,
        quote_asset_id=quote_asset_id,
        price=price,
        provider=provider,
        observed_at=observed_at,
        source=source or f"{provider}:{asset_id}->{quote_asset_id}",
        deployment_id=deployment_id,
        source_record_id=source_record_id,
        freshness_window_seconds=freshness_window_seconds,
    )


# ── Deterministic CI fixture registry ───────────────────────────────────────


class PriceFixtures:
    """Deterministic, no-network fixture scenarios for pure unit tests.

    Every method takes the effective instant and returns the list of
    ``MarketPriceObservation``s an in-memory ObservationStorePort should hold so
    the engine reproduces the named price condition. Rates are fixed decimals —
    the tests pin exact amounts.
    """

    # Common fixture assets.
    ETH_USD = "crypto:ETH"
    USDC_USD = "stablecoin:USDC"
    FX_GBP_USD = "fiat:GBP"
    FX_JPY_USD = "fiat:JPY"
    FX_USD_GBP = "fiat:USD"  # asset being quoted in GBP below
    FX_USD_JPY = "fiat:USD"
    USD = "fiat:USD"
    GBP = "fiat:GBP"
    JPY = "fiat:JPY"

    MARKET_WINDOW = 3600  # 1h for crypto market observations
    FX_WINDOW = 86400  # 24h for FX snapshots
    PEG_WINDOW = 43200  # 12h for stablecoin peg observations

    def crypto_eth_in_usd(
        self,
        price: PriceInput,
        observed_at: str,
        *,
        provider: str = PROVIDER_REPORTED,
        freshness_window_seconds: Optional[int] = MARKET_WINDOW,
    ) -> MarketPriceObservation:
        return market_observation(
            self.ETH_USD, self.USD, price, provider, observed_at,
            freshness_window_seconds=freshness_window_seconds,
        )

    def provider_conflict(self, effective_at: str) -> list[MarketPriceObservation]:
        """provider_reported 100.00 vs oracle 103.00 (>1% conflict) — both live."""
        return [
            self.crypto_eth_in_usd("100.00", seconds_before(effective_at, 1),
                                   provider=PROVIDER_REPORTED),
            self.crypto_eth_in_usd("103.00", seconds_before(effective_at, 2),
                                   provider=ORACLE),
        ]

    def healthy_eth_consensus(self, effective_at: str) -> list[MarketPriceObservation]:
        """provider_reported 100.00 and oracle 100.20 (<1%) — normal, pick 100."""
        return [
            self.crypto_eth_in_usd("100.00", seconds_before(effective_at, 1),
                                   provider=PROVIDER_REPORTED),
            self.crypto_eth_in_usd("100.20", seconds_before(effective_at, 2),
                                   provider=ORACLE),
        ]

    def outlier_eth(self, effective_at: str) -> list[MarketPriceObservation]:
        """provider_reported 180.00 is an outlier vs oracle 100.50 / venue 99.80."""
        return [
            self.crypto_eth_in_usd("180.00", seconds_before(effective_at, 1),
                                   provider=PROVIDER_REPORTED),
            self.crypto_eth_in_usd("100.50", seconds_before(effective_at, 2),
                                   provider=ORACLE),
            self.crypto_eth_in_usd("99.80", seconds_before(effective_at, 3),
                                   provider=VENUE_EXEC),
        ]

    def stale_eth(self, effective_at: str) -> list[MarketPriceObservation]:
        """provider_reported 100.00 observed 2h ago with a 1h freshness window."""
        return [
            self.crypto_eth_in_usd("100.00", seconds_before(effective_at, 7200),
                                   provider=PROVIDER_REPORTED,
                                   freshness_window_seconds=3600),
        ]

    def fx_gbp_to_usd(self, effective_at: str) -> list[MarketPriceObservation]:
        """Direct FX: 1 GBP = 1.25 USD (asset fiat:GBP quoted in fiat:USD)."""
        return [market_observation(
            self.FX_GBP_USD, self.USD, "1.25", FX, seconds_before(effective_at, 60),
            source="fx:GBP:USD", freshness_window_seconds=self.FX_WINDOW,
        )]

    def fx_jpy_to_usd(self, effective_at: str) -> list[MarketPriceObservation]:
        """Direct FX: 1 JPY = 0.0100 USD."""
        return [market_observation(
            self.FX_JPY_USD, self.USD, "0.0100", FX, seconds_before(effective_at, 60),
            source="fx:JPY:USD", freshness_window_seconds=self.FX_WINDOW,
        )]

    def fx_usd_quoted_in_gbp(self, effective_at: str) -> list[MarketPriceObservation]:
        """Inverse-style FX fixture in the lane's described shape: quote from
        fiat:USD to a reporting fiat (1 USD = 0.80 GBP). Converting native GBP
        to USD must invert this observation (1 / 0.80 = 1.25)."""
        return [market_observation(
            self.FX_USD_GBP, self.GBP, "0.80", FX, seconds_before(effective_at, 60),
            source="fx:USD:GBP", freshness_window_seconds=self.FX_WINDOW,
        )]

    def usdc_in_usd(
        self,
        price: PriceInput,
        effective_at: str,
        *,
        provider: str = ORACLE,
    ) -> list[MarketPriceObservation]:
        """A stablecoin priced in USD at ``price`` (peg-aware in the engine)."""
        return [market_observation(
            self.USDC_USD, self.USD, price, provider, seconds_before(effective_at, 5),
            source=f"{provider}:USDC:USD", freshness_window_seconds=self.PEG_WINDOW,
        )]
