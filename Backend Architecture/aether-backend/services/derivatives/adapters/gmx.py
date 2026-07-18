"""GMX read-only venue adapter (public on-chain read path via subgraph).

GMX is an on-chain perpetuals protocol: there is no private account REST API and
no account WebSocket. This adapter reads PUBLIC execution/trade events from the
GMX subgraph (a GraphQL POST, paginated by ``timestamp_lt``) and normalizes them
into canonical fill observations. Because the data is public on-chain state, the
``account`` filter is a public address, NOT a private credential — this is
clearly the public read path, distinct from private account data.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from services.integrations.connectors.base import ImplementationStatus
from services.derivatives.adapters.venue_base import StreamPlan, VenueDerivativesAdapter

_TRADES_QUERY = (
    "query Trades($account: String, $tsLt: Int!, $first: Int!) { "
    "trades(where: {account: $account, timestamp_lt: $tsLt}, first: $first, "
    "orderBy: timestamp, orderDirection: desc) { id account indexToken isLong "
    "sizeDelta price collateralDelta feeUsd timestamp } }"
)


def _sec_to_iso(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return str(value)
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()


class GmxAdapter(VenueDerivativesAdapter):
    adapter_id = "gmx"
    display_name = "GMX Perpetuals (public read-only)"
    implementation_status = ImplementationStatus.CREDENTIAL_GATED
    capabilities = ("reference_data", "markets", "fills", "position", "funding")
    supported_instrument_types = ("perpetual_future",)
    known_limitations = (
        "PUBLIC on-chain read path via the GMX subgraph only — no private "
        "account REST API and no WebSocket. On-chain execution events do not "
        "expose a centralized order lifecycle (no open/cancel order states) or "
        "maker/taker liquidity roles. Subgraph endpoint URL is credential-"
        "waiting configuration; CREDENTIAL_WAITING."
    )

    venue_id = "gmx"
    default_deployment = "arbitrum"
    rest_base_url = "https://subgraph.satsuma-prod.com/gmx/synthetics"
    has_websocket = False
    private_account_data = False
    page_first = 100

    def _account_id(self) -> str:
        return f"acct_{self._account_ref}" if self._account_ref else "public"

    def _connectivity_request(self) -> dict[str, Any]:
        return {"method": "POST", "url": self.rest_base_url,
                "json": {"query": "{ _meta { block { number } } }"}}

    def backfill_plans(self) -> list[StreamPlan]:
        return [
            StreamPlan("raw_fill", self._trades_request, self._extract_trades,
                       self._project_trade,
                       record_key=lambda r: int(r.get("timestamp", 0)), scope="public"),
        ]

    def _trades_request(self, cursor: Optional[str]) -> Optional[dict[str, Any]]:
        ts_lt = int(cursor) if cursor else 2_000_000_000  # far-future seconds
        return {
            "method": "POST",
            "url": self.rest_base_url,
            "json": {
                "query": _TRADES_QUERY,
                "variables": {
                    "account": self._account_ref,
                    "tsLt": ts_lt,
                    "first": self.page_first,
                },
            },
        }

    @staticmethod
    def _extract_trades(payload: Any) -> tuple[list[dict], Optional[str]]:
        trades = (((payload or {}).get("data") or {}).get("trades")) or []
        if not trades:
            return [], None
        earliest = min(int(t.get("timestamp", 0)) for t in trades)
        return list(trades), str(earliest)

    def _project_trade(self, r: dict[str, Any]) -> list[dict[str, Any]]:
        market = str(r.get("indexToken") or r.get("market") or "UNKNOWN")
        return [self.event(
            "derivatives_fill_observed", market,
            trading_account_id=self._account_id(),
            fill_id=str(r["id"]),
            side="buy" if r.get("isLong") else "sell",
            liquidity_role="unknown",
            price=self.amount(r.get("price") or r.get("executionPrice"), "price"),
            quantity=self.amount(r.get("sizeDelta") or r.get("sizeUsd"), "sizeDelta"),
            fee_amount=self.amount(r.get("feeUsd", "0"), "feeUsd"),
            fee_asset_id="USD",
            executed_at=_sec_to_iso(r.get("timestamp")),
        )]
