"""dYdX v4 read-only venue adapter (Indexer REST backfill + WebSocket stream).

Backfills fills / orders / positions from the dYdX Indexer REST API and
subscribes to the ``v4_subaccounts`` WebSocket channel for realtime account
updates. Read-only: only GET endpoints and the subscribe frame are used; there
is no place/cancel surface. All amounts normalize to exact ``Decimal`` strings.
"""

from __future__ import annotations

from typing import Any, Optional

from services.integrations.connectors.base import ImplementationStatus
from services.derivatives.adapters.venue_base import StreamPlan, VenueDerivativesAdapter


class DydxAdapter(VenueDerivativesAdapter):
    adapter_id = "dydx"
    display_name = "dYdX v4 Perpetuals (read-only)"
    implementation_status = ImplementationStatus.CREDENTIAL_GATED
    capabilities = (
        "reference_data", "markets", "orders", "fills", "position",
        "account_snapshot", "realtime_account_stream",
    )
    supported_instrument_types = ("perpetual_future",)
    known_limitations = (
        "Read-only observation via dYdX Indexer REST + v4_subaccounts WebSocket. "
        "Requires the account address + subaccount number (no keys, no trade "
        "surface). Live provider validation pending — CREDENTIAL_WAITING."
    )

    venue_id = "dydx"
    default_deployment = "mainnet"
    rest_base_url = "https://indexer.dydx.trade/v4"
    has_websocket = True
    private_account_data = True

    def __init__(self, *, subaccount_number: int = 0, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._subaccount = subaccount_number

    def _account_id(self) -> str:
        return f"acct_{self._account_ref}_{self._subaccount}" if self._account_ref else "public"

    def _base_params(self) -> dict[str, Any]:
        return {"address": self._account_ref, "subaccountNumber": self._subaccount}

    def _connectivity_request(self) -> dict[str, Any]:
        return {"method": "GET", "url": f"{self.rest_base_url}/height"}

    # ── backfill plans ──────────────────────────────────────────────────────
    def backfill_plans(self) -> list[StreamPlan]:
        return [
            StreamPlan("raw_fill", self._fills_request, self._extract_next("fills"),
                       self._project_fill, record_key=lambda r: str(r.get("createdAt", "")),
                       scope="private_account"),
            StreamPlan("raw_order", self._orders_request, self._extract_next("orders"),
                       self._project_order, scope="private_account"),
            StreamPlan("raw_position", self._positions_request, self._extract_next("positions"),
                       self._project_position, scope="private_account"),
        ]

    def _fills_request(self, cursor: Optional[str]) -> Optional[dict[str, Any]]:
        params = {**self._base_params(), "limit": 100}
        if cursor:
            params["pageCursor"] = cursor
        return {"method": "GET", "url": f"{self.rest_base_url}/fills", "params": params}

    def _orders_request(self, cursor: Optional[str]) -> Optional[dict[str, Any]]:
        params = {**self._base_params(), "limit": 100}
        if cursor:
            params["pageCursor"] = cursor
        return {"method": "GET", "url": f"{self.rest_base_url}/orders", "params": params}

    def _positions_request(self, cursor: Optional[str]) -> Optional[dict[str, Any]]:
        params = {**self._base_params(), "status": "OPEN"}
        if cursor:
            params["pageCursor"] = cursor
        return {
            "method": "GET",
            "url": f"{self.rest_base_url}/perpetualPositions",
            "params": params,
        }

    @staticmethod
    def _extract_next(key: str):
        def extract(payload: Any) -> tuple[list[dict], Optional[str]]:
            if not isinstance(payload, dict):
                return [], None
            return list(payload.get(key, [])), payload.get("next")
        return extract

    # ── projections ─────────────────────────────────────────────────────────
    def _project_fill(self, r: dict[str, Any]) -> list[dict[str, Any]]:
        market = str(r.get("market") or r.get("ticker") or "UNKNOWN")
        role = str(r.get("liquidity", "")).lower()
        return [self.event(
            "derivatives_fill_observed", market,
            trading_account_id=self._account_id(),
            fill_id=str(r["id"]),
            order_id=str(r["orderId"]) if r.get("orderId") is not None else None,
            side="buy" if str(r.get("side", "")).upper() == "BUY" else "sell",
            liquidity_role=role if role in {"maker", "taker"} else "unknown",
            price=self.amount(r["price"], "price"),
            quantity=self.amount(r["size"], "size"),
            fee_amount=self.amount(r.get("fee", "0"), "fee"),
            fee_asset_id=str(r.get("feeAsset", "USDC")),
            executed_at=str(r.get("createdAt", "")),
        )]

    def _project_order(self, r: dict[str, Any]) -> list[dict[str, Any]]:
        market = str(r.get("market") or r.get("ticker") or "UNKNOWN")
        status = str(r.get("status", "unknown")).lower()
        canonical_status = {
            "open": "open", "best_effort_opened": "open", "filled": "filled",
            "canceled": "cancelled", "best_effort_canceled": "cancelled",
        }.get(status, "unknown")
        return [self.event(
            "derivatives_order_observed", market,
            trading_account_id=self._account_id(),
            order_id=str(r["id"]),
            order_side="buy" if str(r.get("side", "")).upper() == "BUY" else "sell",
            order_status=canonical_status,
            order_type=str(r.get("type", "unknown")).lower(),
            quantity=self.amount(r.get("size", "0"), "size"),
            limit_price=self.amount(r["price"], "price") if r.get("price") else None,
        )]

    def _project_position(self, r: dict[str, Any]) -> list[dict[str, Any]]:
        market = str(r.get("market") or r.get("ticker") or "UNKNOWN")
        status = "open" if str(r.get("status", "")).upper() == "OPEN" else "closed"
        return [self.event(
            "derivatives_position_opened_observed" if status == "open"
            else "derivatives_position_closed_observed",
            market,
            trading_account_id=self._account_id(),
            position_id=f"{self._account_id()}:{market}",
            side="long" if str(r.get("side", "")).upper() == "LONG" else "short",
            status=status,
            size=self.amount(r.get("size", "0"), "size"),
            entry_price=self.amount(r["entryPrice"], "entryPrice") if r.get("entryPrice") else None,
            realized_pnl=self.amount(r.get("realizedPnl", "0"), "realizedPnl"),
            unrealized_pnl=self.amount(r.get("unrealizedPnl", "0"), "unrealizedPnl"),
        )]

    def normalize_stream_frame(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        contents = payload.get("contents") or payload
        events: list[dict[str, Any]] = []
        for fill in contents.get("fills", []) if isinstance(contents, dict) else []:
            events.extend(self._project_fill(fill))
        return events
