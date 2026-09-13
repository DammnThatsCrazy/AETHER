"""Hyperliquid read-only venue adapter (REST backfill + WebSocket stream).

Hyperliquid exposes a single POST ``/info`` endpoint keyed by a ``type`` field
for reads, and a WebSocket for realtime account updates. This adapter constructs
those read requests over the injectable REST client, backfills fills / funding /
positions / margin, and normalizes them into canonical observation events with
exact ``Decimal`` amounts. It never signs or submits anything — ``/info`` and the
public ``meta``/``userFills`` reads are the only surfaces touched.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from services.integrations.connectors.base import ImplementationStatus
from services.derivatives.adapters.venue_base import StreamPlan, VenueDerivativesAdapter
from services.derivatives.models import decimal_from_provider


def _ms_to_iso(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        millis = int(value)
    except (TypeError, ValueError):
        return str(value)
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).isoformat()


class HyperliquidAdapter(VenueDerivativesAdapter):
    adapter_id = "hyperliquid"
    display_name = "Hyperliquid Perpetuals (read-only)"
    implementation_status = ImplementationStatus.CREDENTIAL_GATED
    capabilities = (
        "reference_data", "markets", "fills", "funding", "position",
        "margin_snapshot", "account_snapshot", "realtime_account_stream",
    )
    supported_instrument_types = ("perpetual_future",)
    known_limitations = (
        "Read-only observation via POST /info + account WebSocket. Requires a "
        "read-only API wallet reference; no order/transfer/withdraw surface. "
        "Live provider validation pending — CREDENTIAL_WAITING."
    )

    venue_id = "hyperliquid"
    default_deployment = "mainnet"
    rest_base_url = "https://api.hyperliquid.xyz"
    has_websocket = True
    private_account_data = True

    def _account_id(self) -> str:
        return f"acct_{self._account_ref}" if self._account_ref else "public"

    def _info_request(self, body: dict[str, Any]) -> dict[str, Any]:
        return {"method": "POST", "url": f"{self.rest_base_url}/info", "json": body}

    def _connectivity_request(self) -> dict[str, Any]:
        return self._info_request({"type": "meta"})

    # ── backfill plans ──────────────────────────────────────────────────────
    @staticmethod
    def _time_key(record: dict[str, Any]) -> int:
        return int(record.get("time", 0))

    def backfill_plans(self) -> list[StreamPlan]:
        return [
            StreamPlan("raw_fill", self._fills_request, self._extract_time_list,
                       self._project_fill, record_key=self._time_key, scope="private_account"),
            StreamPlan("raw_funding", self._funding_request, self._extract_time_list,
                       self._project_funding, record_key=self._time_key, scope="private_account"),
            StreamPlan("raw_account", self._clearinghouse_request, self._extract_snapshot,
                       self._project_clearinghouse, scope="private_account"),
        ]

    def _start_time(self, cursor: Optional[str], record_type: str) -> int:
        # First page of a sweep resumes from the stored high-water mark
        # (INCLUSIVE, so boundary-ms fills are re-fetched and deduped downstream
        # rather than lost); later pages advance via the intra-sweep window token.
        if cursor:
            return int(cursor)
        resume = self._resume.get(record_type)
        return int(resume) if resume else 0

    def _fills_request(self, cursor: Optional[str]) -> Optional[dict[str, Any]]:
        return self._info_request({
            "type": "userFillsByTime",
            "user": self._account_ref,
            "startTime": self._start_time(cursor, "raw_fill"),
        })

    def _funding_request(self, cursor: Optional[str]) -> Optional[dict[str, Any]]:
        return self._info_request({
            "type": "userFunding",
            "user": self._account_ref,
            "startTime": self._start_time(cursor, "raw_funding"),
        })

    def _clearinghouse_request(self, cursor: Optional[str]) -> Optional[dict[str, Any]]:
        if cursor is not None:  # snapshot: one fetch per pull
            return None
        return self._info_request({"type": "clearinghouseState", "user": self._account_ref})

    @staticmethod
    def _extract_time_list(payload: Any) -> tuple[list[dict], Optional[str]]:
        records = payload if isinstance(payload, list) else payload.get("records", [])
        if not records:
            return [], None
        latest = max(int(r.get("time", 0)) for r in records)
        return list(records), str(latest + 1)

    @staticmethod
    def _extract_snapshot(payload: Any) -> tuple[list[dict], Optional[str]]:
        return ([payload], None) if isinstance(payload, dict) else ([], None)

    # ── projections ─────────────────────────────────────────────────────────
    def _project_fill(self, r: dict[str, Any]) -> list[dict[str, Any]]:
        side = "buy" if str(r.get("side", "")).upper() in {"B", "BUY"} else "sell"
        role = "taker" if r.get("crossed") else "maker"
        market = str(r.get("coin", "UNKNOWN"))
        return [self.event(
            "derivatives_fill_observed", market,
            trading_account_id=self._account_id(),
            fill_id=str(r.get("tid") or r.get("hash")),
            order_id=str(r["oid"]) if r.get("oid") is not None else None,
            side=side,
            liquidity_role=role,
            price=self.amount(r["px"], "px"),
            quantity=self.amount(r["sz"], "sz"),
            fee_amount=self.amount(r.get("fee", "0"), "fee"),
            fee_asset_id=str(r.get("feeToken", "USDC")),
            executed_at=_ms_to_iso(r.get("time")),
        )]

    def _project_funding(self, r: dict[str, Any]) -> list[dict[str, Any]]:
        delta = r.get("delta", r)
        market = str(delta.get("coin", "UNKNOWN"))
        return [self.event(
            "derivatives_funding_payment_observed", market,
            trading_account_id=self._account_id(),
            funding_payment_id=f"{market}:{r.get('time')}",
            position_id=f"{self._account_id()}:{market}",
            amount=self.amount(delta.get("usdc", "0"), "usdc"),
            asset_id="USDC",
            settled_at=_ms_to_iso(r.get("time")),
        )]

    def _project_clearinghouse(self, r: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        observed_at = _ms_to_iso(r.get("time"))
        for asset_position in r.get("assetPositions", []):
            pos = asset_position.get("position", {})
            size = decimal_from_provider(pos.get("szi", "0"), "szi")
            if size == 0:
                continue
            market = str(pos.get("coin", "UNKNOWN"))
            events.append(self.event(
                "derivatives_position_opened_observed", market,
                trading_account_id=self._account_id(),
                position_id=f"{self._account_id()}:{market}",
                side="long" if size > 0 else "short",
                status="open",
                size=self.amount(abs(size), "szi"),
                entry_price=self.amount(pos.get("entryPx", "0"), "entryPx"),
                unrealized_pnl=self.amount(pos.get("unrealizedPnl", "0"), "unrealizedPnl"),
            ))
        margin = r.get("marginSummary", {})
        used = margin.get("totalMarginUsed", "0")
        events.append(self.event(
            "derivatives_margin_snapshot_observed", "account",
            trading_account_id=self._account_id(),
            margin_snapshot_id=f"{self._account_id()}:margin:{r.get('time', '')}",
            margin_mode="cross",
            maintenance_margin=self.amount(used, "totalMarginUsed"),
            initial_margin=self.amount(used, "totalMarginUsed"),
            margin_utilization=self.amount(margin.get("marginUtilization", "0"), "marginUtilization"),
            observed_at=observed_at,
        ))
        return events

    # ── WS frame → canonical fill (used by stream normalization) ────────────
    def normalize_stream_frame(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if payload.get("channel") == "userFills" or "fills" in payload:
            fills = payload.get("fills") or (payload.get("data") or {}).get("fills") or []
            events: list[dict[str, Any]] = []
            for fill in fills:
                events.extend(self._project_fill(fill))
            return events
        return []
