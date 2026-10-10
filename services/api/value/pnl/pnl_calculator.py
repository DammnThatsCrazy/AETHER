"""
Aether — PNL Calculator
Computes realized + unrealized PNL per entity per time window.

Methodology:
  - Realized PNL: FIFO cost basis from silver_web3_events tx history
    + CoinGecko historical prices via CoinGecko provider.
  - Unrealized PNL: Current Moralis portfolio value - FIFO cost basis of
    remaining open positions.
  - TVL delta: (end_tvl - start_tvl) from gold_web3_daily_metrics snapshots.
  - data_confidence = 'estimated' when partial tx history prevents exact FIFO.

Time windows: 30d / 60d / 90d / lifetime (None = all history).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from shared.logger.logger import get_logger

logger = get_logger("aether.pnl.calculator")


class PNLUnavailableError(RuntimeError):
    """Raised when PNL cannot be computed because a data source is unavailable.

    Distinct from a genuinely empty dataset (which legitimately yields zero):
    a provider/store failure is LOUD so a consumer can never present an
    unavailable value as a real zero (program sec7 / sec19).
    """


@dataclass
class CostBasisLot:
    """A FIFO cost basis lot: quantity acquired at a specific price."""
    quantity: Decimal
    cost_per_unit: Decimal
    acquired_at: datetime


@dataclass
class FIFOLedger:
    """Tracks cost basis lots per token address for FIFO realized PNL."""
    lots: deque[CostBasisLot] = field(default_factory=deque)
    realized_pnl: Decimal = Decimal("0")
    # Set when a sell could not be fully matched to buy lots (missing opening
    # lots / incomplete history) — realized PNL is then an UNDER-estimate and the
    # caller must downgrade data_confidence rather than report it as exact.
    insufficient_basis: bool = False

    def buy(self, quantity: Decimal, price_per_unit: Decimal, acquired_at: datetime) -> None:
        """Add a buy lot."""
        self.lots.append(CostBasisLot(quantity, price_per_unit, acquired_at))

    def sell(self, quantity: Decimal, sale_price_per_unit: Decimal) -> Decimal:
        """
        Process a sell using FIFO matching.
        Returns realized PNL for this sale. Flags ``insufficient_basis`` if the
        sold quantity exceeds known buy lots (so confidence can be downgraded).
        """
        remaining = quantity
        realized = Decimal("0")
        while remaining > 0 and self.lots:
            lot = self.lots[0]
            matched = min(remaining, lot.quantity)
            realized += matched * (sale_price_per_unit - lot.cost_per_unit)
            lot.quantity -= matched
            remaining -= matched
            if lot.quantity == 0:
                self.lots.popleft()
        if remaining > 0:
            # Sold more than we have basis for — do NOT invent a zero-cost lot
            # (which would overstate realized PNL). Record the shortfall.
            self.insufficient_basis = True
        self.realized_pnl += realized
        return realized

    @property
    def open_cost_basis(self) -> Decimal:
        """Total cost basis of remaining open lots."""
        return sum(lot.quantity * lot.cost_per_unit for lot in self.lots)


@dataclass
class PNLResult:
    entity_id: str
    window_days: int | None
    realized_pnl_usd: Decimal
    unrealized_pnl_usd: Decimal
    # tvl_delta and best/worst "day" are BALANCE-SNAPSHOT changes (deposits +
    # withdrawals + price moves), i.e. TVL change — NOT realized P&L. They are a
    # flow/position proxy, not performance; consumers must not label them P&L.
    tvl_delta_usd: Decimal
    tvl_delta_pct: float | None   # None when opening TVL is 0 (undefined, not 0%)
    best_day_pnl_usd: Decimal | None
    best_day_date: str | None
    worst_day_pnl_usd: Decimal | None
    worst_day_date: str | None
    cost_basis_method: str
    data_confidence: str   # 'exact' | 'estimated' | 'unavailable'
    daily_series: list[dict[str, Any]]


class PNLCalculator:
    """
    Computes PNL for an entity across a time window.
    Reads from:
      - silver_web3_events (tx history with buy/sell)
      - gold_web3_daily_metrics (TVL snapshots)
      - CoinGecko provider (historical prices)
      - Moralis provider (current portfolio)
    """

    def __init__(self, clickhouse_client, coingecko_provider, moralis_provider):
        self.ch = clickhouse_client
        self.coingecko = coingecko_provider
        self.moralis = moralis_provider

    async def compute(
        self,
        entity_id: str,
        tenant_id: str,
        window_days: int | None = 30,
    ) -> PNLResult:
        """
        Compute PNL for an entity over the specified window.

        Args:
            entity_id: The entity to compute PNL for.
            tenant_id: Tenant scope.
            window_days: 30, 60, 90, or None for lifetime.

        Returns:
            PNLResult with all computed fields.
        """
        now = datetime.now(timezone.utc)
        window_start = (now - timedelta(days=window_days)) if window_days else None

        # Get TVL snapshots for delta computation
        tvl_start, tvl_end, daily_tvl = await self._get_tvl_snapshots(
            entity_id, tenant_id, window_start, now
        )
        tvl_delta_usd = tvl_end - tvl_start
        # Zero opening TVL => the percentage is UNDEFINED (None), never 0%.
        tvl_delta_pct = float(tvl_delta_usd / tvl_start * 100) if tvl_start else None

        # Compute realized PNL via FIFO
        realized_pnl, data_confidence = await self._compute_realized_pnl(
            entity_id, tenant_id, window_start, now
        )

        # Compute unrealized PNL (current portfolio value - open cost basis)
        unrealized_pnl = await self._compute_unrealized_pnl(entity_id)

        # Compute best/worst day from daily TVL series
        best_day_pnl, best_day_date, worst_day_pnl, worst_day_date = self._best_worst_day(
            daily_tvl
        )

        # Build daily series for sparkline
        daily_series = [
            {
                "date": entry["date"],
                "realized_pnl_usd": float(entry.get("realized_pnl_usd", 0)),
                "unrealized_pnl_usd": float(entry.get("unrealized_pnl_usd", 0)),
                "tvl_usd": float(entry.get("tvl_usd", 0)),
            }
            for entry in daily_tvl
        ]

        return PNLResult(
            entity_id=entity_id,
            window_days=window_days,
            realized_pnl_usd=realized_pnl,
            unrealized_pnl_usd=unrealized_pnl,
            tvl_delta_usd=tvl_delta_usd,
            tvl_delta_pct=tvl_delta_pct,
            best_day_pnl_usd=best_day_pnl,
            best_day_date=best_day_date,
            worst_day_pnl_usd=worst_day_pnl,
            worst_day_date=worst_day_date,
            cost_basis_method="FIFO",
            data_confidence=data_confidence,
            daily_series=daily_series,
        )

    async def _get_tvl_snapshots(
        self,
        entity_id: str,
        tenant_id: str,
        window_start: datetime | None,
        window_end: datetime,
    ) -> tuple[Decimal, Decimal, list[dict]]:
        """Get TVL snapshots from gold_web3_daily_metrics."""
        where_clause = "entity_id = %(entity_id)s AND tenant_id = %(tenant_id)s"
        params: dict = {"entity_id": entity_id, "tenant_id": tenant_id}
        if window_start:
            where_clause += " AND date >= %(start_date)s"
            params["start_date"] = window_start.date()

        try:
            rows = await self.ch.query(
                f"SELECT date, total_portfolio_usd FROM gold_web3_daily_metrics "
                f"WHERE {where_clause} ORDER BY date ASC",
                params=params,
            )
        except Exception as exc:
            logger.error(f"TVL snapshot query failed for {entity_id}: {exc}")
            # Store failure is NOT an empty store — raise so the caller can never
            # present a 0 TVL delta as a real value.
            raise PNLUnavailableError(
                f"TVL snapshot query unavailable for {entity_id}: {exc}"
            ) from exc

        if not rows:
            return Decimal("0"), Decimal("0"), []

        tvl_start = Decimal(str(rows[0].get("total_portfolio_usd", 0)))
        tvl_end = Decimal(str(rows[-1].get("total_portfolio_usd", 0)))
        daily_tvl = [
            {"date": str(r["date"]), "tvl_usd": Decimal(str(r.get("total_portfolio_usd", 0)))}
            for r in rows
        ]
        return tvl_start, tvl_end, daily_tvl

    async def _compute_realized_pnl(
        self,
        entity_id: str,
        tenant_id: str,
        window_start: datetime | None,
        window_end: datetime,
    ) -> tuple[Decimal, str]:
        """
        Compute realized PNL via FIFO from silver_web3_events.
        Returns (realized_pnl_usd, data_confidence).
        data_confidence = 'estimated' if full tx history is unavailable.
        """
        where_clause = (
            "wallet_address IN (SELECT address FROM wallets WHERE entity_id = %(entity_id)s) "
            "AND tx_status = 'confirmed'"
        )
        params: dict = {"entity_id": entity_id}
        if window_start:
            where_clause += " AND timestamp >= %(start)s"
            params["start"] = window_start.isoformat()

        try:
            rows = await self.ch.query(
                f"SELECT tx_type, token_symbol, token_address, token_amount, "
                f"value_usd, timestamp FROM silver_web3_events "
                f"WHERE {where_clause} ORDER BY timestamp ASC",
                params=params,
            )
        except Exception as exc:
            logger.error(f"PNL tx query failed for {entity_id}: {exc}")
            # Query failure is NOT a flat/zero P&L — raise so the caller can
            # never present 0 as a real, trustworthy value.
            raise PNLUnavailableError(
                f"Realized PNL tx history unavailable for {entity_id}: {exc}"
            ) from exc

        # FIFO ledgers keyed by token_address
        ledgers: dict[str, FIFOLedger] = {}
        data_confidence = "exact"

        for row in rows:
            token_key = row.get("token_address") or row.get("token_symbol", "UNKNOWN")
            if token_key not in ledgers:
                ledgers[token_key] = FIFOLedger()

            raw_amount = row.get("token_amount")
            raw_value = row.get("value_usd")
            # A missing cost/value must NOT become a zero-priced lot (which would
            # corrupt the cost basis). Skip it and mark the result estimated.
            if raw_amount is None or raw_value is None:
                data_confidence = "estimated"
                continue
            amount = Decimal(str(raw_amount))
            value = Decimal(str(raw_value))
            if amount == 0 or value == 0:
                continue
            price_per_unit = value / amount

            tx_type = row.get("tx_type", "")
            ts = row.get("timestamp")
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            elif not isinstance(ts, datetime):
                ts = datetime.now(timezone.utc)

            if tx_type in ("swap", "transfer") and value > 0:
                # Heuristic: positive token_amount = inflow (buy), negative = outflow (sell)
                if amount > 0:
                    ledgers[token_key].buy(amount, price_per_unit, ts)
                else:
                    ledgers[token_key].sell(abs(amount), price_per_unit)

        total_realized = sum(ledger.realized_pnl for ledger in ledgers.values())
        # If any token sold beyond its known basis (missing opening lots), the
        # realized PNL is an under-estimate — downgrade confidence.
        if any(ledger.insufficient_basis for ledger in ledgers.values()):
            data_confidence = "estimated"
        return total_realized, data_confidence

    async def _compute_unrealized_pnl(self, entity_id: str) -> Decimal:
        """
        Compute unrealized PNL.
        This is approximated as (current_portfolio_value - total_inflows) for
        the lifetime window. For windowed views, it represents the change in
        unrealized value over the window.
        """
        if self.moralis is None:
            raise PNLUnavailableError(
                f"Moralis provider is not configured for {entity_id} — "
                "unrealized PNL is unavailable, not zero"
            )
        try:
            result = await self.moralis.execute(
                "portfolio_by_address",
                {"entity_id": entity_id},
            )
        except Exception as exc:
            logger.warning(f"Moralis portfolio fetch failed for {entity_id}: {exc}")
            raise PNLUnavailableError(
                f"Unrealized PNL unavailable for {entity_id} (Moralis failed): {exc}"
            ) from exc
        # A successful response with no portfolio data is a genuinely empty
        # portfolio — zero value is correct. A provider that FAILED raised above.
        if result and result.get("data"):
            return Decimal(str(result["data"].get("unrealized_pnl_usd", 0)))
        return Decimal("0")

    @staticmethod
    def _best_worst_day(
        daily_series: list[dict],
    ) -> tuple[Decimal | None, str | None, Decimal | None, str | None]:
        """Find the best and worst day PNL from a daily TVL series."""
        if len(daily_series) < 2:
            return None, None, None, None

        daily_deltas = []
        for i in range(1, len(daily_series)):
            delta = daily_series[i]["tvl_usd"] - daily_series[i - 1]["tvl_usd"]
            daily_deltas.append((delta, daily_series[i]["date"]))

        if not daily_deltas:
            return None, None, None, None

        best = max(daily_deltas, key=lambda x: x[0])
        worst = min(daily_deltas, key=lambda x: x[0])
        return best[0], best[1], worst[0], worst[1]
