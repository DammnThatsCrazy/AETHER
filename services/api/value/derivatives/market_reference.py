"""Olympus market reference: public venue market data for the global registry.

Tenant fills and positions reference the global ``derivatives_markets`` registry
(PostgreSQL foreign key), and that registry is reference data, not tenant data.
It is filled here from each venue's *public* market endpoint, read under the
reserved ``olympus`` scope:

* A Kyber operator provisions one Olympus market source per venue
  (:class:`OlympusMarketSourceProvisioner`): a ``ProviderConnection`` for
  ``<venue>.markets.market_data`` under tenant ``olympus`` with the venue
  deployment as its account, and a ``public_reference`` grant of class
  ``olympus_provider`` for ``provider-account:<connection_id>:<deployment>``.
* :class:`MarketReferenceService` fetches missing markets from the venue's
  public API (never from a tenant payload), admits each raw market record
  through ``ProviderRawRightsAdmission`` under that grant (retention use
  ``olympus_baseline``; the provider bridge never forwards ``olympus``-scope
  records into a tenant pipeline), then writes venue, deployment, instrument
  and market rows to the global registry.

The registry rows are public market facts (ids, precisions, status, expiry).
``first_seen_at`` comes from the venue where it reports one, so a row's timing
does not reveal when a tenant first traded the market.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Awaitable, Callable, Optional

from shared.common.common import utc_now
from shared.integration_contracts.source_relationship import OLYMPUS_SOURCE_TENANT_ID

MARKET_RECORD_TYPE = "market"


class MarketReferenceError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class MarketFact:
    """One public venue market, normalized for the global registry."""

    venue: str
    deployment: str
    venue_market_id: str
    instrument_type: str
    underlying_asset_id: str
    quote_asset_id: str
    settlement_asset_id: str
    contract_type: str
    inverse_or_linear: str
    price_precision: Decimal
    size_precision: Decimal
    status: str
    raw: dict[str, Any]
    contract_multiplier: Decimal = Decimal("1")
    expiry_at: Optional[str] = None
    first_seen_at: Optional[str] = None

    @property
    def canonical_market_id(self) -> str:
        return f"{self.venue}:{self.deployment}:{self.venue_market_id}"

    @property
    def canonical_instrument_id(self) -> str:
        if self.instrument_type == "event_contract":
            return f"event_contract:{self.venue}:{self.venue_market_id}"
        return f"{self.instrument_type}:{self.underlying_asset_id}:{self.quote_asset_id}"


def _precision(decimals: Any) -> Decimal:
    return Decimal(1).scaleb(-int(decimals))


# ── Per-venue public market fetchers ─────────────────────────────────────────
# Each takes an httpx.AsyncClient and the venue market ids wanted, and returns
# the MarketFacts the venue reports for them. Only public, unauthenticated GETs
# or info POSTs are used.

async def _hyperliquid(client: Any, wanted: set[str], deployment: str) -> list[MarketFact]:
    response = await client.post("https://api.hyperliquid.xyz/info", json={"type": "meta"})
    response.raise_for_status()
    facts = []
    for asset in (response.json() or {}).get("universe") or []:
        name = str(asset.get("name") or "")
        if name not in wanted:
            continue
        size_decimals = int(asset.get("szDecimals") or 0)
        facts.append(MarketFact(
            venue="hyperliquid", deployment=deployment, venue_market_id=name,
            instrument_type="perpetual_future", underlying_asset_id=name, quote_asset_id="USD",
            settlement_asset_id="USDC", contract_type="perpetual", inverse_or_linear="linear",
            # Hyperliquid prices carry at most 6 - szDecimals decimals.
            price_precision=_precision(max(6 - size_decimals, 0)),
            size_precision=_precision(size_decimals),
            status="delisted" if asset.get("isDelisted") else "active",
            raw=dict(asset),
        ))
    return facts


async def _dydx(client: Any, wanted: set[str], deployment: str) -> list[MarketFact]:
    response = await client.get("https://indexer.dydx.trade/v4/perpetualMarkets")
    response.raise_for_status()
    facts = []
    for ticker, market in ((response.json() or {}).get("markets") or {}).items():
        if ticker not in wanted:
            continue
        base, _, quote = ticker.partition("-")
        facts.append(MarketFact(
            venue="dydx", deployment=deployment, venue_market_id=ticker,
            instrument_type="perpetual_future", underlying_asset_id=base, quote_asset_id=quote or "USD",
            settlement_asset_id="USDC", contract_type="perpetual", inverse_or_linear="linear",
            price_precision=Decimal(str(market.get("tickSize") or "0.000001")),
            size_precision=Decimal(str(market.get("stepSize") or "0.000001")),
            status=str(market.get("status") or "unknown").lower(),
            raw=dict(market),
        ))
    return facts


async def _polymarket(client: Any, wanted: set[str], deployment: str) -> list[MarketFact]:
    if not wanted:
        return []
    params = [("clob_token_ids", token) for token in sorted(wanted)]
    response = await client.get("https://gamma-api.polymarket.com/markets", params=params)
    response.raise_for_status()
    facts = []
    for market in response.json() or []:
        tokens = market.get("clobTokenIds") or []
        if isinstance(tokens, str):
            tokens = json.loads(tokens or "[]")
        condition = str(market.get("conditionId") or "")
        for token in tokens:
            token = str(token)
            if token not in wanted:
                continue
            facts.append(MarketFact(
                venue="polymarket", deployment=deployment, venue_market_id=token,
                instrument_type="event_contract", underlying_asset_id=condition or token,
                quote_asset_id="USDC", settlement_asset_id="USDC", contract_type="binary_outcome",
                inverse_or_linear="linear",
                price_precision=Decimal(str(market.get("orderPriceMinTickSize") or "0.001")),
                size_precision=Decimal("0.000001"),
                status="closed" if market.get("closed") else ("active" if market.get("active") else "inactive"),
                expiry_at=market.get("endDate") or None,
                first_seen_at=market.get("createdAt") or market.get("startDate") or None,
                raw=dict(market),
            ))
    return facts


async def _kalshi(client: Any, wanted: set[str], deployment: str) -> list[MarketFact]:
    """Kalshi markets are public; each ticker yields a ``yes`` and a ``no`` side."""
    tickers = sorted({m.rsplit(":", 1)[0] for m in wanted if ":" in m})
    if not tickers:
        return []
    response = await client.get(
        "https://api.elections.kalshi.com/trade-api/v2/markets",
        params={"tickers": ",".join(tickers), "limit": len(tickers)},
    )
    response.raise_for_status()
    facts = []
    for market in (response.json() or {}).get("markets") or []:
        ticker = str(market.get("ticker") or "")
        for side in ("yes", "no"):
            venue_market_id = f"{ticker}:{side}"
            if venue_market_id not in wanted:
                continue
            status = str(market.get("status") or "unknown").lower()
            facts.append(MarketFact(
                venue="kalshi", deployment=deployment, venue_market_id=venue_market_id,
                instrument_type="event_contract", underlying_asset_id=ticker,
                quote_asset_id="USD", settlement_asset_id="USD", contract_type="binary_outcome",
                inverse_or_linear="linear", price_precision=Decimal("0.01"),
                size_precision=Decimal("1"), status=status,
                expiry_at=market.get("close_time") or market.get("expiration_time") or None,
                first_seen_at=market.get("open_time") or None,
                raw=dict(market),
            ))
    return facts


async def _bybit(client: Any, wanted: set[str], deployment: str) -> list[MarketFact]:
    facts = []
    for symbol in sorted(wanted):
        response = await client.get(
            "https://api.bybit.com/v5/market/instruments-info",
            params={"category": "linear", "symbol": symbol},
        )
        response.raise_for_status()
        for item in ((response.json() or {}).get("result") or {}).get("list") or []:
            if str(item.get("symbol")) != symbol:
                continue
            price_filter = item.get("priceFilter") or {}
            lot = item.get("lotSizeFilter") or {}
            facts.append(MarketFact(
                venue="bybit", deployment=deployment, venue_market_id=symbol,
                instrument_type="perpetual_future",
                underlying_asset_id=str(item.get("baseCoin") or symbol),
                quote_asset_id=str(item.get("quoteCoin") or "USDT"),
                settlement_asset_id=str(item.get("settleCoin") or "USDT"),
                contract_type="perpetual", inverse_or_linear="linear",
                price_precision=Decimal(str(price_filter.get("tickSize") or "0.0001")),
                size_precision=Decimal(str(lot.get("qtyStep") or "0.001")),
                status=str(item.get("status") or "unknown").lower(),
                raw=dict(item),
            ))
    return facts


async def _coinbase_futures(client: Any, wanted: set[str], deployment: str) -> list[MarketFact]:
    facts = []
    for product in sorted(wanted):
        response = await client.get(f"https://api.coinbase.com/api/v3/brokerage/market/products/{product}")
        if response.status_code == 404:
            continue
        response.raise_for_status()
        item = response.json() or {}
        details = item.get("future_product_details") or {}
        perpetual = bool(details.get("perpetual_details")) or "PERP" in product.upper()
        facts.append(MarketFact(
            venue="coinbase_futures", deployment=deployment, venue_market_id=product,
            instrument_type="perpetual_future" if perpetual else "dated_future",
            underlying_asset_id=str(item.get("base_currency_id") or details.get("contract_root_unit") or product),
            quote_asset_id=str(item.get("quote_currency_id") or "USD"), settlement_asset_id="USD",
            contract_type="perpetual" if perpetual else "dated",
            inverse_or_linear="linear",
            contract_multiplier=Decimal(str(details.get("contract_size") or "1")),
            price_precision=Decimal(str(item.get("quote_increment") or "0.01")),
            size_precision=Decimal(str(item.get("base_increment") or "1")),
            status=str(item.get("status") or "unknown").lower(),
            expiry_at=details.get("contract_expiry") or None,
            raw=dict(item),
        ))
    return facts


MarketFetcher = Callable[[Any, set[str], str], Awaitable[list[MarketFact]]]

MARKET_FETCHERS: dict[str, MarketFetcher] = {
    "hyperliquid": _hyperliquid,
    "dydx": _dydx,
    "polymarket": _polymarket,
    "kalshi": _kalshi,
    "bybit": _bybit,
    "coinbase_futures": _coinbase_futures,
}

_VENUE_TYPES = {"polymarket": "prediction_market"}


def market_parts(canonical_market_id: str) -> tuple[str, str, str]:
    venue, deployment, market = (str(canonical_market_id).split(":", 2) + ["", ""])[:3]
    return venue, deployment, market


# ── Olympus market source provisioning (Kyber operator) ─────────────────────

class OlympusMarketSourceProvisioner:
    def __init__(self, *, orchestrator: Any = None, grant_service: Any = None) -> None:
        self._orchestrator = orchestrator
        self._grants = grant_service

    def _orch(self) -> Any:
        if self._orchestrator is None:
            from connectors.provider_runtime.connection import ConnectionOrchestrator

            self._orchestrator = ConnectionOrchestrator()
        return self._orchestrator

    def _grant_service(self) -> Any:
        if self._grants is None:
            from connectors.integrations.data_rights.service import data_rights_service

            self._grants = data_rights_service
        return self._grants

    async def find(self, venue: str, deployment: str = "mainnet") -> Optional[Any]:
        """The active Olympus market connection for a venue deployment, if any."""
        from value.derivatives.venue_sources import venue_profile

        identity = venue_profile(venue).market_identity
        rows = await self._orch().connections.list_for_tenant(OLYMPUS_SOURCE_TENANT_ID)
        for connection in rows:
            grant_id = (connection.config or {}).get("grant_id")
            if (
                connection.provider_identity == identity
                and deployment in (connection.selected_accounts or [])
                and connection.state.value == "connected"
                and grant_id
                and await self._grant_active(grant_id)
            ):
                return connection
        return None

    async def _grant_active(self, grant_id: str) -> bool:
        # A source whose grant was revoked is not a source: an operator
        # provisions a new one rather than the old one silently reviving.
        grant = await self._grant_service().get_grant(grant_id, tenant_id=OLYMPUS_SOURCE_TENANT_ID)
        status = getattr(getattr(grant, "status", None), "value", getattr(grant, "status", None))
        return bool(grant is not None and status == "active" and getattr(grant, "revoked_at", None) is None)

    async def provision(self, *, venue: str, actor: str, deployment: str = "mainnet") -> dict[str, Any]:
        from connectors.integrations.data_rights.models import DataRightsGrantCreate, LegalBasis
        from connectors.provider_runtime.rights_admission import provider_account_source_id
        from shared.integration_contracts.lifecycle import ConnectionState
        from value.derivatives.venue_sources import VenueSourceError, venue_profile

        try:
            profile = venue_profile(venue)
        except VenueSourceError as exc:
            raise MarketReferenceError(exc.reason) from exc
        if profile.market_identity is None or profile.venue not in MARKET_FETCHERS:
            raise MarketReferenceError("market_reference_not_supported")
        existing = await self.find(profile.venue, deployment)
        if existing is not None:
            return _source_record(existing)

        orchestrator = self._orch()
        connection = await orchestrator.create_connection(
            tenant_id=OLYMPUS_SOURCE_TENANT_ID,
            provider_identity=profile.market_identity,
            display_name=f"{profile.display_name} market data (Olympus reference)",
            config={"venue": profile.venue},
        )
        connection.selected_accounts = [deployment]
        source_id = provider_account_source_id(connection.connection_id, deployment)
        grant = await self._grant_service().create_grant(DataRightsGrantCreate(
            tenant_id=OLYMPUS_SOURCE_TENANT_ID,
            source_id=source_id,
            connector_id=profile.market_identity,
            connector_class="olympus_provider",
            source_manifest_id=profile.market_identity,
            data_category="derivatives_market_reference",
            data_sensitivity="public",
            raw_data_owner="public",
            source_relationship="public_reference",
            legal_basis=LegalBasis.LEGITIMATE_INTEREST.value,
        ), granted_by_user_id=actor)
        connection.config = {**connection.config, "grant_id": grant.data_rights_grant_id, "source_id": source_id}
        for state in ("verifying", "verified", "connected"):
            connection = orchestrator.transition(connection, ConnectionState(state))
        await orchestrator.connections.upsert(connection)
        return _source_record(connection)


def _source_record(connection: Any) -> dict[str, Any]:
    config = connection.config or {}
    return {
        "connection_id": connection.connection_id,
        "provider_identity": connection.provider_identity,
        "deployment": (connection.selected_accounts or [None])[0],
        "source_id": config.get("source_id"),
        "grant_id": config.get("grant_id"),
        "state": connection.state.value,
        "tenant_id": connection.tenant_id,
    }


# ── Ensuring reference rows ──────────────────────────────────────────────────

@dataclass
class EnsureResult:
    present: set[str] = field(default_factory=set)
    written: set[str] = field(default_factory=set)
    missing: set[str] = field(default_factory=set)
    reasons: set[str] = field(default_factory=set)


class MarketReferenceService:
    def __init__(
        self,
        *,
        provisioner: Any = None,
        raw_store: Any = None,
        repos: Optional[dict[str, Any]] = None,
        client_factory: Optional[Callable[[], Any]] = None,
        fetchers: Optional[dict[str, MarketFetcher]] = None,
    ) -> None:
        self._provisioner = provisioner or OlympusMarketSourceProvisioner()
        self._raw_store = raw_store
        self._repos = repos
        self._client_factory = client_factory
        self._fetchers = fetchers or MARKET_FETCHERS

    def _registry(self) -> dict[str, Any]:
        if self._repos is None:
            from repositories.derivatives_repos import (
                InstrumentRepo,
                MarketRepo,
                VenueDeploymentRepo,
                VenueRepo,
            )

            self._repos = {
                "venue": VenueRepo(), "deployment": VenueDeploymentRepo(),
                "instrument": InstrumentRepo(), "market": MarketRepo(),
            }
        return self._repos

    def _store(self) -> Any:
        if self._raw_store is None:
            from connectors.provider_runtime.raw_store import RawProviderRecordStore

            self._raw_store = RawProviderRecordStore()
        return self._raw_store

    def _client(self) -> Any:
        if self._client_factory is not None:
            return self._client_factory()
        import httpx

        return httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "aether-market-reference/1.0"})

    async def ensure(self, canonical_market_ids: set[str]) -> EnsureResult:
        """Make sure every id has a registry row; report what is still missing."""
        result = EnsureResult()
        registry = self._registry()
        wanted: dict[tuple[str, str], set[str]] = {}
        for market_id in sorted({m for m in canonical_market_ids if m}):
            if await registry["market"].find_one({"canonical_market_id": market_id}):
                result.present.add(market_id)
                continue
            venue, deployment, market = market_parts(market_id)
            wanted.setdefault((venue, deployment), set()).add(market)
        for (venue, deployment), markets in sorted(wanted.items()):
            ids = {f"{venue}:{deployment}:{m}" for m in markets}
            fetcher = self._fetchers.get(venue)
            if fetcher is None:
                result.missing |= ids
                result.reasons.add(f"market_reference_not_supported:{venue}")
                continue
            source = await self._provisioner.find(venue, deployment)
            if source is None:
                result.missing |= ids
                result.reasons.add(f"market_reference_source_missing:{venue}")
                continue
            try:
                client = self._client()
                try:
                    facts = await fetcher(client, markets, deployment)
                finally:
                    close = getattr(client, "aclose", None)
                    if close is not None:
                        await close()
            except Exception:  # noqa: BLE001 - venue outage leaves rows missing
                result.missing |= ids
                result.reasons.add(f"market_reference_fetch_failed:{venue}")
                continue
            for fact in facts:
                if await self._admit_and_write(source, fact):
                    result.written.add(fact.canonical_market_id)
            not_found = ids - result.written
            if not_found:
                result.missing |= not_found
                result.reasons.add(f"market_reference_not_found:{venue}")
        result.present |= result.written
        return result

    async def _admit_and_write(self, source: Any, fact: MarketFact) -> bool:
        from shared.integration_contracts.events import make_raw_record

        record = make_raw_record(
            provider_identity=source.provider_identity,
            tenant_id=OLYMPUS_SOURCE_TENANT_ID,
            connection_id=source.connection_id,
            account_id=fact.deployment,
            provider_record_type=MARKET_RECORD_TYPE,
            provider_record_id=fact.venue_market_id,
            payload=json.loads(json.dumps(fact.raw, default=str)),
        )
        # Raises ProviderRawRightsDenied when the Olympus grant no longer admits.
        await self._store().ingest([record], tenant_id=OLYMPUS_SOURCE_TENANT_ID)
        await self._write(fact)
        return True

    async def _write(self, fact: MarketFact) -> None:
        registry = self._registry()
        now = utc_now().isoformat()
        deployment_id = f"{fact.venue}:{fact.deployment}"
        await registry["venue"].insert({
            "venue_id": fact.venue,
            "venue_type": _VENUE_TYPES.get(fact.venue, "perpetual_dex"),
            "display_name": fact.venue,
            "global_reference": True,
        })
        await registry["deployment"].insert({
            "venue_deployment_id": deployment_id,
            "venue_id": fact.venue,
            "deployment": fact.deployment,
            "global_reference": True,
        })
        await registry["instrument"].insert({
            "canonical_instrument_id": fact.canonical_instrument_id,
            "instrument_type": fact.instrument_type,
            "underlying_asset_id": fact.underlying_asset_id,
            "quote_asset_id": fact.quote_asset_id,
            "settlement_asset_id": fact.settlement_asset_id,
            "contract_type": fact.contract_type,
            "contract_multiplier": fact.contract_multiplier,
            "inverse_or_linear": fact.inverse_or_linear,
            "expiry_at": fact.expiry_at,
            "global_reference": True,
        })
        await registry["market"].insert({
            "canonical_market_id": fact.canonical_market_id,
            "canonical_instrument_id": fact.canonical_instrument_id,
            "venue_id": fact.venue,
            "venue_deployment_id": deployment_id,
            "venue_market_id": fact.venue_market_id,
            "underlying_asset_id": fact.underlying_asset_id,
            "quote_asset_id": fact.quote_asset_id,
            "settlement_asset_id": fact.settlement_asset_id,
            "instrument_type": fact.instrument_type,
            "contract_type": fact.contract_type,
            "contract_multiplier": fact.contract_multiplier,
            "inverse_or_linear": fact.inverse_or_linear,
            "expiry_at": fact.expiry_at,
            "price_precision": fact.price_precision,
            "size_precision": fact.size_precision,
            "margin_modes": ["cross"] if fact.instrument_type == "perpetual_future" else [],
            "status": fact.status,
            "first_seen_at": fact.first_seen_at or now,
            "last_seen_at": now,
            "global_reference": True,
        })


__all__ = [
    "EnsureResult",
    "MARKET_FETCHERS",
    "MarketFact",
    "MarketReferenceError",
    "MarketReferenceService",
    "OlympusMarketSourceProvisioner",
    "market_parts",
]
