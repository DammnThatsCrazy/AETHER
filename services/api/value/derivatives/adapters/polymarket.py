"""Polymarket read-only event-contract adapter (Data API v2 + Gamma markets).

Polymarket account activity is public on-chain and served per wallet by the
Data API v2 (``/v2/trades?user=``, ``/v2/positions?user=``, cursor-only
pagination via ``pagination.next_cursor``). Market metadata (outcomes and
outcome token ids) comes from the Gamma ``/markets`` endpoint. No key is needed
for any of these reads; the account reference is the user's proxy wallet,
linked to a tenant subject through a verified venue account link.

Each outcome token is its own ``canonical_market_id``
(``polymarket:<deployment>:<token_id>``) so the shared position engine
reconstructs one epoch per outcome. Every fill and position also carries the
``event_contract_ref`` (``polymarket:<deployment>:<condition_id>``) and the
``outcome`` label, which is the "side" used for same-side adoption.

Observation-only: there is no order, transfer, or redemption surface.
JSON floats are parsed as ``Decimal`` by the shared REST client.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from connectors.integrations.connectors.base import ImplementationStatus
from value.derivatives.adapters.venue_base import StreamPlan, VenueDerivativesAdapter
from value.derivatives.event_contracts import event_contract_ref

DATA_API_BASE_URL = "https://data-api.polymarket.com"
GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
_PAGE_LIMIT = 500


def _seconds_to_iso(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return str(value)
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()


def polymarket_fill_id(record: dict[str, Any]) -> str:
    """Stable fill identity: one transaction can carry several token fills."""
    return ":".join(
        str(record.get(key) or "")
        for key in ("transaction_hash", "token_id", "side", "size", "price")
    )


class PolymarketAdapter(VenueDerivativesAdapter):
    adapter_id = "polymarket"
    display_name = "Polymarket Event Contracts (read-only)"
    implementation_status = ImplementationStatus.CREDENTIAL_GATED
    capabilities = (
        "reference_data", "markets", "fills", "position", "account_snapshot",
    )
    supported_instrument_types = ("event_contract",)
    authentication_model = "public_wallet_address"
    known_limitations = (
        "Read-only observation of public wallet activity via Data API v2 "
        "(trades, positions) and Gamma market metadata. No order, transfer, or "
        "redemption surface. Live tenant-linked validation pending."
    )

    venue_id = "polymarket"
    default_deployment = "mainnet"
    rest_base_url = DATA_API_BASE_URL
    has_websocket = False
    private_account_data = True

    def _account_id(self) -> str:
        return f"acct_{self._account_ref}" if self._account_ref else "public"

    def _connectivity_request(self) -> dict[str, Any]:
        return {"method": "GET", "url": f"{GAMMA_BASE_URL}/markets", "params": {"limit": 1}}

    @staticmethod
    def _time_key(record: dict[str, Any]) -> int:
        return int(record.get("timestamp") or 0)

    def backfill_plans(self) -> list[StreamPlan]:
        return [
            StreamPlan("raw_fill", self._trades_request, self._extract_page,
                       self._project_trade, record_key=self._time_key,
                       scope="private_account"),
            StreamPlan("raw_account", self._positions_request, self._extract_page,
                       self._project_position, scope="private_account"),
        ]

    def _trades_request(self, cursor: Optional[str]) -> Optional[dict[str, Any]]:
        params: dict[str, Any] = {"user": self._account_ref, "limit": _PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor
        return {"method": "GET", "url": f"{DATA_API_BASE_URL}/v2/trades", "params": params}

    def _positions_request(self, cursor: Optional[str]) -> Optional[dict[str, Any]]:
        params: dict[str, Any] = {"user": self._account_ref, "limit": _PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor
        return {"method": "GET", "url": f"{DATA_API_BASE_URL}/v2/positions", "params": params}

    @staticmethod
    def _extract_page(payload: Any) -> tuple[list[dict], Optional[str]]:
        if isinstance(payload, list):
            return list(payload), None
        if not isinstance(payload, dict):
            return [], None
        records = payload.get("data") or []
        pagination = payload.get("pagination") or {}
        next_cursor = pagination.get("next_cursor") if pagination.get("has_more") else None
        return list(records), (str(next_cursor) if next_cursor else None)

    def _contract_fields(self, record: dict[str, Any]) -> dict[str, Any]:
        condition = str(record.get("condition_id") or "")
        return {
            "instrument_type": "event_contract",
            "event_contract_ref": (
                event_contract_ref(self.venue_id, self._deployment, condition) if condition else None
            ),
            "outcome": str(record.get("outcome") or ""),
            "outcome_index": record.get("outcome_index"),
        }

    def _project_trade(self, r: dict[str, Any]) -> list[dict[str, Any]]:
        side = "buy" if str(r.get("side", "")).upper() == "BUY" else "sell"
        token = str(r.get("token_id") or "UNKNOWN")
        return [self.event(
            "derivatives_fill_observed", token,
            trading_account_id=self._account_id(),
            fill_id=polymarket_fill_id(r),
            order_id=None,
            side=side,
            liquidity_role="unknown",
            price=self.amount(r["price"], "price"),
            quantity=self.amount(r["size"], "size"),
            fee_amount="0",
            fee_asset_id="USDC",
            executed_at=_seconds_to_iso(r.get("timestamp")),
            **self._contract_fields(r),
        )]

    def _project_position(self, r: dict[str, Any]) -> list[dict[str, Any]]:
        token = str(r.get("token_id") or "UNKNOWN")
        size = self.amount(r.get("current_size", "0"), "current_size")
        status = "open" if str(r.get("status", "")).upper() == "OPEN" else "closed"
        return [self.event(
            "derivatives_position_opened_observed" if status == "open"
            else "derivatives_position_closed_observed",
            token,
            trading_account_id=self._account_id(),
            position_id=f"{self._account_id()}:{token}",
            side="long",
            status=status,
            size=size,
            entry_price=self.amount(r.get("avg_price", "0"), "avg_price"),
            unrealized_pnl=self.amount(r.get("unrealized_pnl", "0"), "unrealized_pnl"),
            realized_pnl=self.amount(r.get("realized_pnl", "0"), "realized_pnl"),
            first_entry_at=_seconds_to_iso(r.get("first_entry_at")),
            **self._contract_fields(r),
        )]


__all__ = ["DATA_API_BASE_URL", "GAMMA_BASE_URL", "PolymarketAdapter", "polymarket_fill_id"]
