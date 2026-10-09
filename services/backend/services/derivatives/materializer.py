"""Derivatives position, P&L and reconciliation materializer.

Raw intake (``POST /v1/derivatives/runtime/observations``) stores the venue's
orders, fills and positions as append-only facts. This worker turns those facts
into the derived tables nothing else writes:

* ``derivatives_position_epochs`` - one row per closed flat-to-flat lifecycle, from
  :func:`services.derivatives.position_engine.apply_fill` over the fill stream (a flip
  closes the epoch and opens a fresh one).
* ``derivatives_pnl_snapshots`` - realized P&L, open size, and exposure per
  ``(account, market)`` whenever the fills or the mark price change.
* ``derivatives_reconciliation_variances`` - the computed position compared with the
  position the venue reported, per market, via
  :class:`services.derivatives.runtime_reconciliation.DerivativesReconciliation`.

Observation only: nothing here places, amends or cancels anything, every row carries
``execution_by_aether = FALSE``, amounts are ``Decimal`` end to end, and each write is
idempotent on a key derived from the inputs, so a pass over unchanged data writes
nothing. Unrealized P&L and exposure need a mark price; with none observed the snapshot
says so (``evidence.mark_price_available = false``) instead of presenting a zero as a
measurement.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Awaitable, Callable, Optional

from config.settings import settings
from repositories.derivatives_repos import (
    FillRepo,
    PnlSnapshotRepo,
    PositionEpochRepo,
    PositionRepo,
    PriceObservationRepo,
    TradingAccountRepo,
)
from repositories.typed_repo import as_decimal
from services.derivatives.foundation import deterministic_id, deterministic_idempotency_key, utc_now_iso
from services.derivatives.models import (
    DerivativesValidationError,
    LiquidityRole,
    NormalizedFillFact,
    OrderSide,
    PositionEpochState,
    PositionSide,
    PositionStatus,
    SourceRef,
)
from services.derivatives.pnl import unrealized_pnl
from services.derivatives.position_engine import apply_fill
from services.derivatives.runtime_reconciliation import DerivativesReconciliation
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.derivatives.materializer")

ACCOUNTING_METHOD = "average_entry"
_PAGE = 1000
_MARK_PRICE_TYPES = ("mark", "mark_price")


@dataclass
class MarketResult:
    """What one ``(account, market)`` pass computed and wrote."""

    fills: int = 0
    skipped_fills: int = 0
    epochs_written: int = 0
    snapshot_written: bool = False
    variances_written: int = 0
    size: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")


@dataclass
class TenantResult:
    tenant_id: str
    markets: dict[tuple[str, str], MarketResult] = field(default_factory=dict)

    @property
    def totals(self) -> dict[str, int]:
        keys = ("fills", "skipped_fills", "epochs_written", "variances_written")
        out = {k: sum(getattr(m, k) for m in self.markets.values()) for k in keys}
        out["snapshots_written"] = sum(1 for m in self.markets.values() if m.snapshot_written)
        out["markets"] = len(self.markets)
        return out


async def _all_rows(repo: Any, tenant_id: str, extra: Optional[dict] = None) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        page = await repo.find_many({"tenant_id": tenant_id, **(extra or {})}, limit=_PAGE, offset=offset)
        rows.extend(page)
        if len(page) < _PAGE:
            return rows
        offset += _PAGE


def _to_fact(row: dict, account: Optional[dict]) -> NormalizedFillFact:
    """A stored fill row as the position engine's fact; raises on unusable data."""
    side = OrderSide(str(row["side"]).lower())
    role = str(row.get("liquidity_role") or "unknown").lower()
    return NormalizedFillFact(
        tenant_id=row["tenant_id"],
        provider=str((account or {}).get("venue_id") or "unknown"),
        deployment=str((account or {}).get("venue_deployment_id") or ""),
        trading_account_id=row["trading_account_id"],
        canonical_market_id=row["canonical_market_id"],
        fill_id=str(row["fill_id"]),
        side=side,
        price=as_decimal(row["price"]),
        quantity=as_decimal(row["quantity"]),
        executed_at=str(row["executed_at"]),
        liquidity_role=LiquidityRole(role) if role in {r.value for r in LiquidityRole} else LiquidityRole.UNKNOWN,
        fee_amount=as_decimal(row.get("fee_amount") or 0),
        fee_asset_id=row.get("fee_asset_id"),
        source_ref=SourceRef("derivatives_fills", str(row["fill_id"]), str(row["executed_at"])),
    )


@dataclass(frozen=True)
class ClosedEpoch:
    """A finished flat-to-flat lifecycle with the size it opened and closed at."""

    state: PositionEpochState
    open_size: Decimal
    close_size: Decimal


def replay_epochs(facts: list[NormalizedFillFact]) -> tuple[list[ClosedEpoch], PositionEpochState | None]:
    """Fold a chronological fill stream into ``(closed epochs, open epoch or None)``.

    Every zero -> non-zero lifecycle gets its own epoch: a closed state is retired and the
    next fill starts a fresh one; a flip closes the epoch and opens another for the
    remainder.
    """
    closed: list[ClosedEpoch] = []
    open_sizes: dict[str, Decimal] = {}
    current: PositionEpochState | None = None
    for fact in facts:
        if current is not None and current.status is PositionStatus.CLOSED:
            current = None
        prior = current
        produced = apply_fill(current, fact)
        if len(produced) == 2:  # flip: the first state is the closed epoch
            closed.append(ClosedEpoch(produced[0], open_sizes[produced[0].epoch_id], prior.size if prior else Decimal("0")))
            current = produced[1]
        else:
            current = produced[0]
            if current.status is PositionStatus.CLOSED:
                closed.append(ClosedEpoch(current, open_sizes.get(current.epoch_id, fact.quantity), prior.size if prior else fact.quantity))
        open_sizes.setdefault(current.epoch_id, current.size)
    if current is not None and current.status is PositionStatus.CLOSED:
        current = None
    return closed, current


def _ts(value: Any) -> Any:
    """An ISO timestamp string as a datetime for TIMESTAMPTZ columns; anything else as is."""
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return value


def _signed_size(state: PositionEpochState | None) -> Decimal:
    if state is None or state.size == 0:
        return Decimal("0")
    return state.size if state.side is PositionSide.LONG else -state.size


async def _latest_mark(prices: PriceObservationRepo, tenant_id: str, market_id: str) -> Optional[dict]:
    rows = await prices.find_many({"tenant_id": tenant_id, "canonical_market_id": market_id}, limit=500)
    marks = [r for r in rows if str(r.get("price_type") or "").lower() in _MARK_PRICE_TYPES]
    if not marks:
        return None
    return max(marks, key=lambda r: str(r.get("observed_at") or ""))


async def _venue_position(positions: PositionRepo, tenant_id: str, account_id: str, market_id: str) -> Optional[dict]:
    rows = await positions.find_many(
        {"tenant_id": tenant_id, "trading_account_id": account_id, "canonical_market_id": market_id}, limit=500,
    )
    if not rows:
        return None
    return max(rows, key=lambda r: str(r.get("updated_at") or ""))


async def materialize_market(
    tenant_id: str,
    account_id: str,
    market_id: str,
    fill_rows: list[dict],
    account: Optional[dict],
    *,
    epochs: PositionEpochRepo,
    snapshots: PnlSnapshotRepo,
    positions: PositionRepo,
    prices: PriceObservationRepo,
    reconciliation: DerivativesReconciliation,
    write_pnl: bool = True,
    write_variances: bool = True,
    as_of: Optional[str] = None,
) -> MarketResult:
    """Recompute one ``(account, market)`` from its fills and persist what changed."""
    result = MarketResult()
    ordered = sorted(fill_rows, key=lambda r: (str(r.get("executed_at")), str(r.get("fill_id"))))
    facts: list[NormalizedFillFact] = []
    for row in ordered:
        try:
            facts.append(_to_fact(row, account))
        except (DerivativesValidationError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
            result.skipped_fills += 1
            logger.warning("derivatives fill %s skipped: %s", row.get("fill_id"), exc)
    result.fills = len(facts)
    if not facts:
        return result

    closed, open_state = replay_epochs(facts)
    fee_total = sum((e.state.fees for e in closed), Decimal("0")) + (open_state.fees if open_state else Decimal("0"))
    realized = sum((e.state.realized_pnl for e in closed), Decimal("0")) + (
        open_state.realized_pnl if open_state else Decimal("0")
    )
    result.size = _signed_size(open_state)
    result.realized_pnl = realized

    position_id = deterministic_id("dposn_", f"{tenant_id}|{account_id}|{market_id}")
    for item in closed:
        epoch = item.state
        inserted = await epochs.insert({
            "tenant_id": tenant_id,
            "position_epoch_id": epoch.epoch_id,
            "position_id": position_id,
            "opened_at": _ts(epoch.opened_at),
            "closed_at": _ts(epoch.closed_at),
            "open_size": item.open_size,
            "close_size": item.close_size,
            "idempotency_key": deterministic_idempotency_key(f"{tenant_id}|epoch|{epoch.epoch_id}|closed"),
            "execution_by_aether": False,
        })
        result.epochs_written += 1 if inserted else 0

    mark = await _latest_mark(prices, tenant_id, market_id)
    mark_price = as_decimal(mark["price"]) if mark and mark.get("price") is not None else None
    last_fill_id = facts[-1].fill_id

    if write_pnl:
        entry_price = open_state.entry_price if open_state else None
        if open_state is not None and mark_price is not None and entry_price is not None:
            unrealized = unrealized_pnl(_signed_size(open_state), entry_price, mark_price)
            net_exposure = _signed_size(open_state) * mark_price
        else:
            unrealized = Decimal("0")
            net_exposure = Decimal("0")
        key = deterministic_idempotency_key(
            f"{tenant_id}|pnl|{account_id}|{market_id}|{last_fill_id}|{(mark or {}).get('price_observation_id')}|{result.size}"
        )
        snapshot_at = as_of or utc_now_iso()
        result.snapshot_written = await snapshots.insert({
            "tenant_id": tenant_id,
            "pnl_snapshot_id": deterministic_id("dpnl_", key),
            "trading_account_id": account_id,
            "canonical_market_id": market_id,
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "gross_exposure": abs(net_exposure),
            "net_exposure": net_exposure,
            "accounting_method": ACCOUNTING_METHOD,
            "as_of": _ts(snapshot_at),
            "idempotency_key": key,
            "evidence": {
                "fills": result.fills,
                "last_fill_id": last_fill_id,
                "open_size": str(result.size),
                "fees": str(fee_total),
                "closed_epochs": len(closed),
                "mark_price_available": mark_price is not None,
                "mark_price_observation_id": (mark or {}).get("price_observation_id"),
            },
            "execution_by_aether": False,
        })

    if write_variances:
        observed = await _venue_position(positions, tenant_id, account_id, market_id)
        if observed is not None:
            venue_size = as_decimal(observed.get("size") or 0)
            if str(observed.get("side") or "").lower() == "short":
                venue_size = -venue_size
            venue: dict[str, Any] = {"size": venue_size}
            projected: dict[str, Any] = {"size": result.size}
            if observed.get("realized_pnl") is not None:
                venue["realized_pnl"] = as_decimal(observed["realized_pnl"])
                projected["realized_pnl"] = realized
            outcome = await reconciliation.reconcile_account(
                tenant_id, account_id, venue, projected, scope=market_id,
            )
            result.variances_written = outcome["variance_count"]
    return result


async def materialize_tenant(
    tenant_id: str,
    *,
    fills: Optional[FillRepo] = None,
    accounts: Optional[TradingAccountRepo] = None,
    epochs: Optional[PositionEpochRepo] = None,
    snapshots: Optional[PnlSnapshotRepo] = None,
    positions: Optional[PositionRepo] = None,
    prices: Optional[PriceObservationRepo] = None,
    reconciliation: Optional[DerivativesReconciliation] = None,
    write_pnl: bool = True,
    write_variances: bool = True,
) -> TenantResult:
    """Materialize every ``(account, market)`` the tenant has fills for."""
    fills = fills or FillRepo()
    accounts_by_id = {a["trading_account_id"]: a for a in await _all_rows(accounts or TradingAccountRepo(), tenant_id)}
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in await _all_rows(fills, tenant_id):
        grouped.setdefault((row["trading_account_id"], row["canonical_market_id"]), []).append(row)

    outcome = TenantResult(tenant_id)
    for (account_id, market_id), rows in sorted(grouped.items()):
        outcome.markets[(account_id, market_id)] = await materialize_market(
            tenant_id, account_id, market_id, rows, accounts_by_id.get(account_id),
            epochs=epochs or PositionEpochRepo(),
            snapshots=snapshots or PnlSnapshotRepo(),
            positions=positions or PositionRepo(),
            prices=prices or PriceObservationRepo(),
            reconciliation=reconciliation or DerivativesReconciliation(),
            write_pnl=write_pnl,
            write_variances=write_variances,
        )
    return outcome


async def materialize_all() -> list[TenantResult]:
    """One pass over every tenant with fills. A failing tenant is logged, never fatal."""
    d = settings.derivatives
    write_pnl = bool(d.pnl_enabled)
    write_variances = bool(d.reconciliation_enabled)
    results: list[TenantResult] = []
    for tenant_id in await FillRepo().distinct_tenant_ids():
        try:
            results.append(await materialize_tenant(tenant_id, write_pnl=write_pnl, write_variances=write_variances))
        except Exception as exc:  # noqa: BLE001 - one tenant must not stop the pass
            logger.error("derivatives materialization failed tenant=%s: %s", tenant_id, exc)
    metrics.increment("derivatives_materializer_passes")
    return results


async def materializer_loop(interval_s: float = 60.0) -> None:
    """The supervised loop (``derivatives_position_materializer`` worker)."""
    logger.info("derivatives_position_materializer started interval=%ss", interval_s)
    while True:
        try:
            await materialize_all()
        except Exception as exc:  # noqa: BLE001 - the loop survives
            logger.error("derivatives materializer pass failed: %s", exc)
        await asyncio.sleep(interval_s)


def build_materializer_coro(interval_s: float = 60.0) -> Any:
    """Zero-arg coroutine factory for the runtime WorkerSpec."""
    return materializer_loop(interval_s)


__all__ = [
    "ACCOUNTING_METHOD",
    "MarketResult",
    "TenantResult",
    "build_materializer_coro",
    "materialize_all",
    "materialize_market",
    "materialize_tenant",
    "replay_epochs",
]
