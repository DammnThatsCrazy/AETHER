"""Kalshi read-only account adapter (event contracts, member read-only key).

Reads one member's fills and market positions from the Kalshi Trade API v2
portfolio endpoints with the member's *read-only* API key. Requests are signed
the way Kalshi specifies: ``KALSHI-ACCESS-KEY`` (key id),
``KALSHI-ACCESS-TIMESTAMP`` (milliseconds) and ``KALSHI-ACCESS-SIGNATURE`` =
base64 RSA-PSS (SHA-256, digest-length salt) over ``timestamp + METHOD + path``
(path without the query string). The private key arrives through the venue
account link's credential (``api_key`` = key id, ``api_secret`` = PEM key),
stored by the credential broker; this adapter never persists it.

Each market side is its own ``canonical_market_id``
(``kalshi:<deployment>:<ticker>:<yes|no>``) so the shared position engine keeps
one epoch per side, and every fill carries ``event_contract_ref``
(``kalshi:<deployment>:<ticker>``) and ``outcome`` (``yes``/``no``), the "side"
used for same-side adoption. Prices accept the current ``*_dollars`` fields and
the older integer-cent fields.

Observation-only: there is no order, cancel, transfer or withdrawal surface.
"""

from __future__ import annotations

import base64
import time
from decimal import Decimal
from typing import Any, Optional
from urllib.parse import urlparse

from connectors.integrations.connectors.base import ImplementationStatus
from value.derivatives.adapters.venue_base import StreamPlan, VenueDerivativesAdapter
from value.derivatives.event_contracts import event_contract_ref

KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
_PAGE_LIMIT = 200


class KalshiSigningError(ValueError):
    """The supplied credential cannot sign Kalshi requests."""


def kalshi_signature(private_key_pem: str, timestamp_ms: str, method: str, path: str) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    try:
        key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    except (ValueError, TypeError) as exc:
        raise KalshiSigningError("kalshi_private_key_unreadable") from exc
    if not isinstance(key, rsa.RSAPrivateKey):
        raise KalshiSigningError("kalshi_private_key_not_rsa")
    message = f"{timestamp_ms}{method.upper()}{path}".encode("utf-8")
    signature = key.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("ascii")


def _price(record: dict[str, Any], side: str) -> Decimal:
    dollars = record.get(f"{side}_price_dollars")
    if dollars not in (None, ""):
        return Decimal(str(dollars))
    cents = record.get(f"{side}_price")
    if cents in (None, ""):
        raise KeyError(f"{side}_price")
    return (Decimal(str(cents)) / Decimal(100)).quantize(Decimal("0.0001"))


def _count(record: dict[str, Any], *keys: str) -> Decimal:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return Decimal(str(value))
    return Decimal(0)


class KalshiAdapter(VenueDerivativesAdapter):
    adapter_id = "kalshi"
    display_name = "Kalshi Event Contracts (read-only)"
    implementation_status = ImplementationStatus.CREDENTIAL_GATED
    capabilities = ("fills", "position", "account_snapshot")
    supported_instrument_types = ("event_contract",)
    authentication_model = "api_key_read_only"
    known_limitations = (
        "Read-only observation of one member's fills and market positions via "
        "the Trade API v2 portfolio endpoints with the member's read-only key "
        "(RSA-PSS signed requests). No order, cancel, transfer or withdrawal "
        "surface. Live tenant-linked validation pending."
    )

    venue_id = "kalshi"
    default_deployment = "mainnet"
    rest_base_url = KALSHI_BASE_URL
    has_websocket = False
    private_account_data = True

    def __init__(self, *, credential: Any = None, clock: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._key_id, self._private_key = self._credential_parts(credential)
        self._clock = clock or (lambda: int(time.time() * 1000))

    @staticmethod
    def _credential_parts(credential: Any) -> tuple[Optional[str], Optional[str]]:
        if credential is None:
            return None, None
        key_id = getattr(credential, "key_id", None)
        secret = getattr(credential, "secret", None)
        if key_id and secret is not None:
            return str(key_id), secret.get_secret_value()
        raise KalshiSigningError("kalshi_credential_requires_key_id_and_private_key")

    def _account_id(self) -> str:
        return f"acct_{self._account_ref}" if self._account_ref else "public"

    def _signed(self, method: str, url: str, params: dict[str, Any]) -> dict[str, Any]:
        headers: dict[str, str] = {}
        if self._key_id and self._private_key:
            timestamp = str(self._clock())
            path = urlparse(url).path
            headers = {
                "KALSHI-ACCESS-KEY": self._key_id,
                "KALSHI-ACCESS-TIMESTAMP": timestamp,
                "KALSHI-ACCESS-SIGNATURE": kalshi_signature(self._private_key, timestamp, method, path),
            }
        return {"method": method, "url": url, "params": params, "headers": headers}

    def _connectivity_request(self) -> dict[str, Any]:
        return {"method": "GET", "url": f"{KALSHI_BASE_URL}/exchange/status"}

    @staticmethod
    def _time_key(record: dict[str, Any]) -> str:
        return str(record.get("created_time") or "")

    def backfill_plans(self) -> list[StreamPlan]:
        return [
            StreamPlan("raw_fill", self._fills_request, self._extract("fills"),
                       self._project_fill, record_key=self._time_key, scope="private_account"),
            StreamPlan("raw_account", self._positions_request, self._extract("market_positions"),
                       self._project_position, scope="private_account"),
        ]

    def _fills_request(self, cursor: Optional[str]) -> Optional[dict[str, Any]]:
        if not self._key_id:
            return None
        params: dict[str, Any] = {"limit": _PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor
        return self._signed("GET", f"{KALSHI_BASE_URL}/portfolio/fills", params)

    def _positions_request(self, cursor: Optional[str]) -> Optional[dict[str, Any]]:
        if not self._key_id:
            return None
        params: dict[str, Any] = {"limit": _PAGE_LIMIT, "count_filter": "position"}
        if cursor:
            params["cursor"] = cursor
        return self._signed("GET", f"{KALSHI_BASE_URL}/portfolio/positions", params)

    @staticmethod
    def _extract(key: str):
        def extract(payload: Any) -> tuple[list[dict], Optional[str]]:
            if not isinstance(payload, dict):
                return [], None
            cursor = payload.get("cursor") or None
            return list(payload.get(key) or []), (str(cursor) if cursor else None)
        return extract

    def _contract(self, ticker: str, outcome: str) -> dict[str, Any]:
        return {
            "instrument_type": "event_contract",
            "event_contract_ref": event_contract_ref(self.venue_id, self._deployment, ticker),
            "outcome": outcome,
        }

    def _project_fill(self, r: dict[str, Any]) -> list[dict[str, Any]]:
        ticker = str(r.get("ticker") or r.get("market_ticker") or "UNKNOWN")
        outcome = "no" if str(r.get("side", "")).lower() == "no" else "yes"
        action = "sell" if str(r.get("action", "")).lower() == "sell" else "buy"
        return [self.event(
            "derivatives_fill_observed", f"{ticker}:{outcome}",
            trading_account_id=self._account_id(),
            fill_id=str(r.get("fill_id") or r.get("trade_id") or ""),
            order_id=r.get("order_id"),
            side=action,
            liquidity_role="taker" if r.get("is_taker") else "maker",
            price=str(_price(r, outcome)),
            quantity=str(_count(r, "count_fp", "count")),
            fee_amount="0",
            fee_asset_id="USD",
            executed_at=str(r.get("created_time") or ""),
            **self._contract(ticker, outcome),
        )]

    def _project_position(self, r: dict[str, Any]) -> list[dict[str, Any]]:
        ticker = str(r.get("ticker") or "UNKNOWN")
        signed = _count(r, "position_fp", "position")
        outcome = "no" if signed < 0 else "yes"
        size = abs(signed)
        status = "open" if size > 0 else "closed"
        return [self.event(
            "derivatives_position_opened_observed" if status == "open"
            else "derivatives_position_closed_observed",
            f"{ticker}:{outcome}",
            trading_account_id=self._account_id(),
            position_id=f"{self._account_id()}:{ticker}:{outcome}",
            side="long",
            status=status,
            size=str(size),
            realized_pnl=str(_count(r, "realized_pnl_dollars") or (_count(r, "realized_pnl") / 100)),
            **self._contract(ticker, outcome),
        )]


__all__ = ["KALSHI_BASE_URL", "KalshiAdapter", "KalshiSigningError", "kalshi_signature"]
