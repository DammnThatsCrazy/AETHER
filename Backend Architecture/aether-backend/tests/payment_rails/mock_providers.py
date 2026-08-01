"""Provider-shaped mock HTTP servers + fixtures for payment-rail pull tests.

TEST-TREE ONLY — never imported by production code. Each builder returns an
``httpx.MockTransport`` (injected into an adapter via ``http_transport=``) plus a
``MockServer`` recorder that captures every request so tests can assert on auth
injection, cursor progression, pagination, rate-limit/retry behaviour, and
tenant scoping. No socket is ever opened: ``httpx.MockTransport`` routes every
request to the in-process handler regardless of URL.

Response fixtures deliberately embed sensitive fields (card numbers, CVV, raw
bank account numbers) so tests can prove the adapter sanitizer strips them
before anything is normalized or stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import httpx

# ── request recorder ─────────────────────────────────────────────────────────


@dataclass
class MockServer:
    """Records requests a mock transport received, for post-hoc assertions."""

    requests: list[httpx.Request] = field(default_factory=list)
    _429_remaining: int = 0
    _timeout_remaining: int = 0

    @property
    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]

    def auth_values(self, header: str) -> list[Optional[str]]:
        return [r.headers.get(header) for r in self.requests]

    def param_values(self, name: str) -> list[Optional[str]]:
        return [r.url.params.get(name) for r in self.requests]

    def transport(self, handler: Callable[[httpx.Request], httpx.Response]) -> httpx.MockTransport:
        def _wrapped(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if self._timeout_remaining > 0:
                self._timeout_remaining -= 1
                raise httpx.ReadTimeout("mock injected timeout", request=request)
            if self._429_remaining > 0:
                self._429_remaining -= 1
                return httpx.Response(
                    429, headers={"Retry-After": "0"}, json={"error": "rate_limited"},
                    request=request,
                )
            return handler(request)

        return httpx.MockTransport(_wrapped)


# ── sensitive fixtures (must be redacted before storage) ─────────────────────

_SENSITIVE_COINBASE = {
    "card_number": "4111111111111111",
    # Sentinel carries a non-hex char ('v') on purpose: leak markers are matched
    # as substrings of the stored records' JSON, which also contains random
    # lowercase-hex UUIDs/hashes. A bare "321" spuriously matches ~3% of runs
    # (e.g. an event id like "...-4321-..."), so the sentinel must be impossible
    # to form from [0-9a-f]. Redaction strips by key name, not value, so the
    # value's shape does not affect whether the field is redacted.
    "cvv": "cvv-321",
    "ssn": "123-45-6789",
}
_SENSITIVE_BRIDGE = {
    "bank_account_number": "9876543210",
    "routing_number": "021000021",
}


# ── Coinbase: cursor pagination over /onramp/v1/buy/user/{ref}/transactions ──


def coinbase_transport(
    *,
    secret: str,
    pages: dict[Optional[str], tuple[list[dict], Optional[str]]],
    rate_limit_first: int = 0,
    timeout_first: int = 0,
) -> tuple[httpx.MockTransport, MockServer]:
    """Coinbase onramp transactions API.

    ``pages`` maps an incoming ``page_key`` (None for the first request) to
    ``(records, next_page_key)``. Requires ``Authorization: Bearer <secret>``.
    """
    server = MockServer(_429_remaining=rate_limit_first, _timeout_remaining=timeout_first)

    def handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("Authorization")
        if auth != f"Bearer {secret}":
            return httpx.Response(401, json={"error": "unauthorized"}, request=request)
        page_key = request.url.params.get("page_key")
        records, nxt = pages.get(page_key, ([], None))
        body: dict[str, Any] = {"transactions": records}
        if nxt is not None:
            body["next_page_key"] = nxt
        return httpx.Response(200, json=body, request=request)

    return server.transport(handler), server


def coinbase_tx(tx_id: str, status: str, ref: str = "user-42") -> dict:
    """A Coinbase onramp transaction record carrying sensitive fields."""
    return {
        "transaction_id": tx_id,
        "partner_user_ref": ref,
        "status": status,
        "purchase_amount": {"value": "50", "currency": "USDC"},
        "payment_total": {"value": "51.25", "currency": "USD"},
        "purchase_currency": "USDC",
        "purchase_network": "base",
        "wallet_address": "0xabc",
        "tx_hash": "0xdeadbeef",
        "updated_at": "2026-07-10T00:00:00+00:00",
        **_SENSITIVE_COINBASE,
    }


# ── MoonPay: time-window pagination over /v3/transactions ────────────────────


def moonpay_transport(
    *,
    secret: str,
    windows: dict[Optional[str], list[dict]],
    rate_limit_first: int = 0,
    timeout_first: int = 0,
) -> tuple[httpx.MockTransport, MockServer]:
    """MoonPay transactions API.

    ``windows`` maps an incoming ``startDate`` (None for first) to the records
    returned. Requires ``Authorization: Api-Key <secret>``. Returns a raw JSON
    array (MoonPay's shape).
    """
    server = MockServer(_429_remaining=rate_limit_first, _timeout_remaining=timeout_first)

    def handler(request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("Authorization")
        if auth != f"Api-Key {secret}":
            return httpx.Response(401, json={"error": "unauthorized"}, request=request)
        start = request.url.params.get("startDate")
        records = windows.get(start, [])
        return httpx.Response(200, json=records, request=request)

    return server.transport(handler), server


def moonpay_tx(tx_id: str, status: str, updated_at: str) -> dict:
    return {
        "id": tx_id,
        "status": status,
        "baseCurrencyAmount": 100,
        "quoteCurrencyAmount": 95,
        "baseCurrency": {"code": "usd"},
        "currency": {"code": "usdc"},
        "walletAddress": "0xabc",
        "cryptoTransactionId": "0xhash-" + tx_id,
        "updatedAt": updated_at,
    }


# ── Bridge: cursor pagination over /v0/customers/{id}/.../history ─────────────


def bridge_transport(
    *,
    secret: str,
    pages: dict[Optional[str], list[dict]],
    rate_limit_first: int = 0,
    timeout_first: int = 0,
) -> tuple[httpx.MockTransport, MockServer]:
    """Bridge activity-history API.

    ``pages`` maps an incoming ``starting_after`` cursor (None for first) to the
    records returned. Requires ``Api-Key: <secret>``. Shape: ``{"data": [...]}``.
    """
    server = MockServer(_429_remaining=rate_limit_first, _timeout_remaining=timeout_first)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("Api-Key") != secret:
            return httpx.Response(401, json={"error": "unauthorized"}, request=request)
        cursor = request.url.params.get("starting_after")
        records = pages.get(cursor, [])
        return httpx.Response(200, json={"data": records, "count": len(records)}, request=request)

    return server.transport(handler), server


def bridge_activity(activity_id: str, status: str) -> dict:
    """A Bridge virtual-account activity record carrying sensitive fields."""
    return {
        "id": activity_id,
        "type": "payment_processed",
        "status": status,
        "amount": "250.00",
        "currency": "usd",
        "customer_id": "cust1",
        "virtual_account_id": "va1",
        "deposit_id": "dep1",
        "source": {"payment_rail": "ach", "currency": "usd", **_SENSITIVE_BRIDGE},
        "destination": {
            "currency": "usdc", "payment_rail": "base",
            "address": "0xdest", "transaction_hash": "0xtx",
        },
        "updated_at": "2026-07-10T00:00:00+00:00",
    }


# Leak markers are searched as substrings of the stored records' JSON. Every
# marker must be impossible to form from a random lowercase-hex id/hash — the
# CVV sentinel carries a non-hex 'v' for exactly this reason (see _SENSITIVE_*).
SENSITIVE_MARKERS = ("4111111111111111", "cvv-321", "123-45-6789", "9876543210", "021000021")
