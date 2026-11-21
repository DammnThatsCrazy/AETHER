"""Bybit read-only account adapter (CEX perpetuals, member read-only key).

Reads one account's linear (USDT/USDC-margined) perpetual executions and open
positions from the Bybit v5 API with the member's *read-only* API key. Each
request is signed as Bybit specifies: ``X-BAPI-SIGN`` = hex HMAC-SHA256 over
``timestamp + api_key + recv_window + query_string`` with the API secret. The
key pair arrives through the venue account link's credential (``api_key`` =
key, ``api_secret`` = secret) and is never persisted here.

Market ids are Bybit symbols (``bybit:<deployment>:<SYMBOL>``).
Observation-only: there is no order, cancel, transfer or withdrawal surface.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlencode

from connectors.integrations.connectors.base import ImplementationStatus
from value.derivatives.adapters.venue_base import StreamPlan, VenueDerivativesAdapter
from value.derivatives.connectors.transport import (
    PROVIDER_HEALTH_AUTH_ERROR,
    PROVIDER_HEALTH_BAD_RESPONSE,
    PROVIDER_HEALTH_CLIENT_ERROR,
    PROVIDER_HEALTH_RATE_LIMITED,
    ProviderRequestError,
)

BYBIT_BASE_URL = "https://api.bybit.com"
_PAGE_LIMIT = 100
# Bybit v5 retCodes for a rejected credential (invalid/expired key, bad
# signature, missing permission) and for rate limiting.
_BYBIT_AUTH_CODES = frozenset({10003, 10004, 10005, 10007, 33004})
_BYBIT_RATE_LIMIT_CODES = frozenset({10006, 10018})
_RECV_WINDOW = "5000"


class BybitCredentialError(ValueError):
    pass


def bybit_signature(secret: str, timestamp_ms: str, api_key: str, recv_window: str, query: str) -> str:
    message = f"{timestamp_ms}{api_key}{recv_window}{query}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _ms_to_iso(value: Any) -> str:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return str(value or "")


class BybitAdapter(VenueDerivativesAdapter):
    adapter_id = "bybit"
    display_name = "Bybit Perpetuals (read-only)"
    implementation_status = ImplementationStatus.CREDENTIAL_GATED
    capabilities = ("fills", "position", "account_snapshot")
    supported_instrument_types = ("perpetual_future",)
    authentication_model = "api_key_read_only"
    known_limitations = (
        "Read-only observation of one account's linear perpetual executions and "
        "positions via the v5 REST API with a read-only key (HMAC-signed). No "
        "order, cancel, transfer or withdrawal surface; inverse and option "
        "categories are not read. Live tenant-linked validation pending."
    )

    venue_id = "bybit"
    default_deployment = "mainnet"
    rest_base_url = BYBIT_BASE_URL
    has_websocket = False
    private_account_data = True

    def __init__(self, *, credential: Any = None, clock: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._api_key, self._secret = self._credential_parts(credential)
        self._clock = clock or (lambda: int(time.time() * 1000))

    @staticmethod
    def _credential_parts(credential: Any) -> tuple[Optional[str], Optional[str]]:
        if credential is None:
            return None, None
        key_id = getattr(credential, "key_id", None)
        secret = getattr(credential, "secret", None)
        if key_id and secret is not None:
            return str(key_id), secret.get_secret_value()
        raise BybitCredentialError("bybit_credential_requires_key_and_secret")

    def _account_id(self) -> str:
        return f"acct_{self._account_ref}" if self._account_ref else "public"

    def _signed(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = urlencode(sorted(params.items()))
        timestamp = str(self._clock())
        return {
            "method": "GET",
            "url": f"{BYBIT_BASE_URL}{path}?{query}",
            "headers": {
                "X-BAPI-API-KEY": self._api_key or "",
                "X-BAPI-TIMESTAMP": timestamp,
                "X-BAPI-RECV-WINDOW": _RECV_WINDOW,
                "X-BAPI-SIGN": bybit_signature(self._secret or "", timestamp, self._api_key or "",
                                               _RECV_WINDOW, query),
            },
        }

    def _connectivity_request(self) -> dict[str, Any]:
        return {"method": "GET", "url": f"{BYBIT_BASE_URL}/v5/market/time"}

    @staticmethod
    def _time_key(record: dict[str, Any]) -> int:
        return int(record.get("execTime") or 0)

    def backfill_plans(self) -> list[StreamPlan]:
        return [
            StreamPlan("raw_fill", self._executions_request, self._extract,
                       self._project_fill, record_key=self._time_key, scope="private_account"),
            StreamPlan("raw_account", self._positions_request, self._extract,
                       self._project_position, scope="private_account"),
        ]

    def _executions_request(self, cursor: Optional[str]) -> Optional[dict[str, Any]]:
        if not self._api_key:
            return None
        params: dict[str, Any] = {"category": "linear", "limit": _PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor
        return self._signed("/v5/execution/list", params)

    def _positions_request(self, cursor: Optional[str]) -> Optional[dict[str, Any]]:
        if not self._api_key:
            return None
        params: dict[str, Any] = {"category": "linear", "settleCoin": "USDT", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        return self._signed("/v5/position/list", params)

    @staticmethod
    def _extract(payload: Any) -> tuple[list[dict], Optional[str]]:
        # Bybit reports application errors (rejected key, missing permission,
        # rate limit) inside an HTTP 200 body. They are failed reads, never an
        # empty page: an empty page would mark a rejected credential healthy.
        if not isinstance(payload, dict):
            raise ProviderRequestError(PROVIDER_HEALTH_BAD_RESPONSE, "bybit: non-object response")
        try:
            code = int(payload.get("retCode", 0) or 0)
        except (TypeError, ValueError):
            raise ProviderRequestError(PROVIDER_HEALTH_BAD_RESPONSE, "bybit: unreadable retCode")
        if code != 0:
            if code in _BYBIT_AUTH_CODES:
                classification = PROVIDER_HEALTH_AUTH_ERROR
            elif code in _BYBIT_RATE_LIMIT_CODES:
                classification = PROVIDER_HEALTH_RATE_LIMITED
            else:
                classification = PROVIDER_HEALTH_CLIENT_ERROR
            raise ProviderRequestError(classification, f"bybit retCode {code}")
        result = payload.get("result") or {}
        cursor = result.get("nextPageCursor") or None
        return list(result.get("list") or []), (str(cursor) if cursor else None)

    def _project_fill(self, r: dict[str, Any]) -> list[dict[str, Any]]:
        symbol = str(r.get("symbol") or "UNKNOWN")
        return [self.event(
            "derivatives_fill_observed", symbol,
            trading_account_id=self._account_id(),
            fill_id=str(r.get("execId") or ""),
            order_id=r.get("orderId"),
            side="buy" if str(r.get("side", "")).lower() == "buy" else "sell",
            liquidity_role="maker" if r.get("isMaker") else "taker",
            price=self.amount(r.get("execPrice", "0"), "execPrice"),
            quantity=self.amount(r.get("execQty", "0"), "execQty"),
            fee_amount=self.amount(r.get("execFee", "0"), "execFee"),
            fee_asset_id=str(r.get("feeCurrency") or "USDT"),
            executed_at=_ms_to_iso(r.get("execTime")),
            instrument_type="perpetual_future",
        )]

    def _project_position(self, r: dict[str, Any]) -> list[dict[str, Any]]:
        symbol = str(r.get("symbol") or "UNKNOWN")
        size = self.amount(r.get("size", "0"), "size")
        side = str(r.get("side", "")).lower()
        status = "open" if side in ("buy", "sell") and size not in ("0", "0.0") else "closed"
        return [self.event(
            "derivatives_position_opened_observed" if status == "open"
            else "derivatives_position_closed_observed",
            symbol,
            trading_account_id=self._account_id(),
            position_id=f"{self._account_id()}:{symbol}:{r.get('positionIdx', 0)}",
            side="long" if side == "buy" else "short",
            status=status,
            size=size,
            entry_price=self.amount(r.get("avgPrice", "0") or "0", "avgPrice"),
            unrealized_pnl=self.amount(r.get("unrealisedPnl", "0") or "0", "unrealisedPnl"),
            realized_pnl=self.amount(r.get("cumRealisedPnl", "0") or "0", "cumRealisedPnl"),
            instrument_type="perpetual_future",
        )]


__all__ = ["BYBIT_BASE_URL", "BybitAdapter", "BybitCredentialError", "bybit_signature"]
