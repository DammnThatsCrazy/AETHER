"""Drift read-only venue adapter (Drift Data API read path).

Drift is a Solana perpetuals protocol. This adapter reads trade/fill and
settled-funding records from the Drift Data REST API (paginated by an opaque
``next`` cursor) for an authority (wallet) reference and normalizes them into
canonical observations with exact ``Decimal`` amounts. The authority-scoped
trade history is the available read path; a realtime account WebSocket is not
wired here yet and that deferral is declared honestly (``has_websocket=False``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from services.integrations.connectors.base import ImplementationStatus
from services.derivatives.adapters.venue_base import StreamPlan, VenueDerivativesAdapter


def _sec_to_iso(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return str(value)
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()


class DriftAdapter(VenueDerivativesAdapter):
    adapter_id = "drift"
    display_name = "Drift Perpetuals (read-only)"
    implementation_status = ImplementationStatus.CREDENTIAL_GATED
    capabilities = ("reference_data", "markets", "fills", "funding", "position")
    supported_instrument_types = ("perpetual_future",)
    known_limitations = (
        "Read-only observation via the Drift Data REST API, scoped by wallet "
        "authority. Realtime account WebSocket is not wired yet (deferred, "
        "declared has_websocket=False) — REST read path only. Live provider "
        "validation pending; CREDENTIAL_WAITING."
    )

    venue_id = "drift"
    default_deployment = "mainnet-beta"
    rest_base_url = "https://data.api.drift.trade"
    has_websocket = False
    private_account_data = True

    def _account_id(self) -> str:
        return f"acct_{self._account_ref}" if self._account_ref else "public"

    def _connectivity_request(self) -> dict[str, Any]:
        return {"method": "GET", "url": f"{self.rest_base_url}/status"}

    def backfill_plans(self) -> list[StreamPlan]:
        return [
            StreamPlan("raw_fill", self._trades_request, self._extract_records,
                       self._project_fill, record_key=lambda r: int(r.get("ts", 0)),
                       scope="private_account"),
            StreamPlan("raw_funding", self._funding_request, self._extract_records,
                       self._project_funding, record_key=lambda r: int(r.get("ts", 0)),
                       scope="private_account"),
        ]

    def _trades_request(self, cursor: Optional[str]) -> Optional[dict[str, Any]]:
        params: dict[str, Any] = {"authority": self._account_ref, "pageSize": 100}
        if cursor:
            params["page"] = cursor
        return {"method": "GET", "url": f"{self.rest_base_url}/trades", "params": params}

    def _funding_request(self, cursor: Optional[str]) -> Optional[dict[str, Any]]:
        params: dict[str, Any] = {"authority": self._account_ref, "pageSize": 100}
        if cursor:
            params["page"] = cursor
        return {
            "method": "GET",
            "url": f"{self.rest_base_url}/fundingPayments",
            "params": params,
        }

    @staticmethod
    def _extract_records(payload: Any) -> tuple[list[dict], Optional[str]]:
        if not isinstance(payload, dict):
            return [], None
        return list(payload.get("records", [])), payload.get("next")

    def _project_fill(self, r: dict[str, Any]) -> list[dict[str, Any]]:
        market = str(r.get("marketName") or r.get("market") or "UNKNOWN")
        role = str(r.get("liquidity", "")).lower()
        return [self.event(
            "derivatives_fill_observed", market,
            trading_account_id=self._account_id(),
            fill_id=str(r["fillId"]),
            order_id=str(r["takerOrderId"]) if r.get("takerOrderId") is not None else None,
            side="buy" if str(r.get("direction", "")).lower() in {"long", "buy"} else "sell",
            liquidity_role=role if role in {"maker", "taker"} else "unknown",
            price=self.amount(r.get("price") or r.get("oraclePrice"), "price"),
            quantity=self.amount(r.get("baseAssetAmount") or r.get("baseAssetAmountFilled"), "baseAssetAmount"),
            fee_amount=self.amount(r.get("fee", "0"), "fee"),
            fee_asset_id=str(r.get("feeAsset", "USDC")),
            executed_at=_sec_to_iso(r.get("ts") or r.get("slotTime")),
        )]

    def _project_funding(self, r: dict[str, Any]) -> list[dict[str, Any]]:
        market = str(r.get("marketName") or r.get("market") or "UNKNOWN")
        return [self.event(
            "derivatives_funding_payment_observed", market,
            trading_account_id=self._account_id(),
            funding_payment_id=str(r.get("recordId") or f"{market}:{r.get('ts')}"),
            position_id=f"{self._account_id()}:{market}",
            amount=self.amount(r.get("amount") or r.get("fundingPayment"), "amount"),
            asset_id="USDC",
            settled_at=_sec_to_iso(r.get("ts")),
        )]
