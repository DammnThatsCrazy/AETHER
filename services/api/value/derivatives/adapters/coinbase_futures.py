"""Coinbase Financial Markets (CFM) read-only futures adapter (regulated US futures).

Reads one account's futures fills and open CFM positions from the Coinbase
Advanced Trade API. Two credential shapes are accepted, both read-only:

* a CDP API key (``key_id`` = key name, ``secret`` = EC private key PEM): each
  request carries a fresh ES256 JWT whose ``uri`` claim names that request
  (``"GET api.coinbase.com/api/v3/brokerage/..."``), valid for two minutes;
* an OAuth access token (``OAuthTokenCredential``) from the Aether-hosted
  Coinbase OAuth app, sent as a bearer token.

Market ids are Coinbase futures product ids (``coinbase_futures:<deployment>:<PRODUCT>``).
Observation-only: there is no order, cancel, transfer or withdrawal surface.
"""

from __future__ import annotations

import secrets
import time
from typing import Any, Optional

from connectors.integrations.connectors.base import ImplementationStatus
from value.derivatives.adapters.venue_base import StreamPlan, VenueDerivativesAdapter

COINBASE_HOST = "api.coinbase.com"
COINBASE_BROKERAGE = f"https://{COINBASE_HOST}/api/v3/brokerage"
_PAGE_LIMIT = 100


class CoinbaseCredentialError(ValueError):
    pass


def coinbase_jwt(key_name: str, private_key_pem: str, method: str, path: str, *, now: Optional[int] = None) -> str:
    import jwt

    issued = int(now if now is not None else time.time())
    return jwt.encode(
        {"sub": key_name, "iss": "cdp", "nbf": issued, "exp": issued + 120,
         "uri": f"{method.upper()} {COINBASE_HOST}{path}"},
        private_key_pem,
        algorithm="ES256",
        headers={"kid": key_name, "nonce": secrets.token_hex(16)},
    )


class CoinbaseFuturesAdapter(VenueDerivativesAdapter):
    adapter_id = "coinbase_futures"
    display_name = "Coinbase Financial Markets Futures (read-only)"
    implementation_status = ImplementationStatus.CREDENTIAL_GATED
    capabilities = ("fills", "position", "account_snapshot")
    supported_instrument_types = ("dated_future", "perpetual_future")
    authentication_model = "api_key_read_only"
    known_limitations = (
        "Read-only observation of one account's futures fills and CFM positions "
        "via the Advanced Trade API with a read-only CDP key (ES256 JWT per "
        "request) or an OAuth token from the Aether-hosted Coinbase app. No "
        "order, cancel, transfer or withdrawal surface. Live validation pending."
    )

    venue_id = "coinbase_futures"
    default_deployment = "mainnet"
    rest_base_url = COINBASE_BROKERAGE
    has_websocket = False
    private_account_data = True

    def __init__(self, *, credential: Any = None, clock: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._key_name: Optional[str] = None
        self._private_key: Optional[str] = None
        self._token: Optional[str] = None
        self._clock = clock or (lambda: int(time.time()))
        if credential is not None:
            access_token = getattr(credential, "access_token", None)
            key_id = getattr(credential, "key_id", None)
            secret = getattr(credential, "secret", None)
            if access_token is not None:
                self._token = access_token.get_secret_value()
            elif key_id and secret is not None:
                self._key_name, self._private_key = str(key_id), secret.get_secret_value()
            else:
                raise CoinbaseCredentialError("coinbase_credential_requires_cdp_key_or_oauth_token")

    @property
    def _configured(self) -> bool:
        return bool(self._token or self._key_name)

    def _account_id(self) -> str:
        return f"acct_{self._account_ref}" if self._account_ref else "public"

    def _signed(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        full_path = f"/api/v3/brokerage{path}"
        if self._token:
            auth = f"Bearer {self._token}"
        else:
            auth = "Bearer " + coinbase_jwt(
                self._key_name or "", self._private_key or "", "GET", full_path, now=self._clock(),
            )
        return {"method": "GET", "url": f"https://{COINBASE_HOST}{full_path}", "params": params,
                "headers": {"Authorization": auth}}

    def _connectivity_request(self) -> dict[str, Any]:
        return {"method": "GET", "url": f"https://{COINBASE_HOST}/api/v3/brokerage/time"}

    @staticmethod
    def _time_key(record: dict[str, Any]) -> str:
        return str(record.get("trade_time") or "")

    def backfill_plans(self) -> list[StreamPlan]:
        return [
            StreamPlan("raw_fill", self._fills_request, self._extract("fills"),
                       self._project_fill, record_key=self._time_key, scope="private_account"),
            StreamPlan("raw_account", self._positions_request, self._extract("positions"),
                       self._project_position, scope="private_account"),
        ]

    def _fills_request(self, cursor: Optional[str]) -> Optional[dict[str, Any]]:
        if not self._configured:
            return None
        params: dict[str, Any] = {"product_type": "FUTURE", "limit": _PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor
        return self._signed("/orders/historical/fills", params)

    def _positions_request(self, cursor: Optional[str]) -> Optional[dict[str, Any]]:
        if not self._configured or cursor:
            return None
        return self._signed("/cfm/positions", {})

    @staticmethod
    def _extract(key: str):
        def extract(payload: Any) -> tuple[list[dict], Optional[str]]:
            if not isinstance(payload, dict):
                return [], None
            cursor = payload.get("cursor") or None
            return list(payload.get(key) or []), (str(cursor) if cursor else None)
        return extract

    def _project_fill(self, r: dict[str, Any]) -> list[dict[str, Any]]:
        product = str(r.get("product_id") or "UNKNOWN")
        return [self.event(
            "derivatives_fill_observed", product,
            trading_account_id=self._account_id(),
            fill_id=str(r.get("entry_id") or r.get("trade_id") or ""),
            order_id=r.get("order_id"),
            side="buy" if str(r.get("side", "")).upper() == "BUY" else "sell",
            liquidity_role="maker" if str(r.get("liquidity_indicator", "")).upper() == "MAKER" else "taker",
            price=self.amount(r.get("price", "0"), "price"),
            quantity=self.amount(r.get("size", "0"), "size"),
            fee_amount=self.amount(r.get("commission", "0") or "0", "commission"),
            fee_asset_id="USD",
            executed_at=str(r.get("trade_time") or ""),
            instrument_type="dated_future",
        )]

    def _project_position(self, r: dict[str, Any]) -> list[dict[str, Any]]:
        product = str(r.get("product_id") or "UNKNOWN")
        contracts = self.amount(r.get("number_of_contracts", "0") or "0", "number_of_contracts")
        status = "open" if contracts not in ("0", "0.0") else "closed"
        return [self.event(
            "derivatives_position_opened_observed" if status == "open"
            else "derivatives_position_closed_observed",
            product,
            trading_account_id=self._account_id(),
            position_id=f"{self._account_id()}:{product}",
            side="short" if str(r.get("side", "")).upper() == "SHORT" else "long",
            status=status,
            size=contracts,
            entry_price=self.amount(r.get("avg_entry_price", "0") or "0", "avg_entry_price"),
            unrealized_pnl=self.amount(r.get("unrealized_pnl", "0") or "0", "unrealized_pnl"),
            expiry_at=r.get("expiration_time"),
            instrument_type="dated_future",
        )]


__all__ = ["COINBASE_BROKERAGE", "CoinbaseCredentialError", "CoinbaseFuturesAdapter", "coinbase_jwt"]
