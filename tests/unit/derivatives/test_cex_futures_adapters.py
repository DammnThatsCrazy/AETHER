"""Bybit (CEX perps) and Coinbase Financial Markets (regulated futures) read-only adapters."""

from __future__ import annotations

import hashlib
import hmac
from decimal import Decimal
from urllib.parse import urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from shared.certification.checks import run_certification
from shared.credentials.types import KeyIdSecretCredential, OAuthTokenCredential
from value.derivatives.adapters import VENUE_ADAPTERS
from value.derivatives.adapters.bybit import BybitAdapter, BybitCredentialError, bybit_signature
from value.derivatives.adapters.coinbase_futures import CoinbaseFuturesAdapter, coinbase_jwt
from value.derivatives.adapters.conformance import run_conformance

EC_KEY = ec.generate_private_key(ec.SECP256R1())
EC_PEM = EC_KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
).decode()

BYBIT_EXEC = {"retCode": 0, "result": {"list": [
    {"symbol": "BTCUSDT", "orderId": "o1", "side": "Buy", "execPrice": "97000.5", "execQty": "0.010",
     "execFee": "0.58", "feeCurrency": "USDT", "execId": "e1", "execTime": "1763650000000", "isMaker": False},
], "nextPageCursor": ""}}
BYBIT_POS = {"retCode": 0, "result": {"list": [
    {"symbol": "BTCUSDT", "side": "Buy", "size": "0.010", "avgPrice": "97000.5", "unrealisedPnl": "1.2",
     "cumRealisedPnl": "0", "positionIdx": 0},
], "nextPageCursor": ""}}
CB_FILLS = {"fills": [
    {"entry_id": "ent-1", "trade_id": "t1", "order_id": "o1", "trade_time": "2026-11-20T15:00:00Z",
     "price": "97100", "size": "2", "commission": "1.10", "product_id": "BIT-28NOV26-CDE",
     "side": "BUY", "liquidity_indicator": "MAKER"},
], "cursor": ""}
CB_POS = {"positions": [
    {"product_id": "BIT-28NOV26-CDE", "expiration_time": "2026-11-28T16:00:00Z", "side": "LONG",
     "number_of_contracts": "2", "avg_entry_price": "97100", "unrealized_pnl": "15"},
]}


async def _noop(_s):
    return None


def _bybit(seen):
    def handler(request):
        seen.append(request)
        body = BYBIT_EXEC if "/execution/" in request.url.path else BYBIT_POS
        return httpx.Response(200, json=body, request=request)

    return BybitAdapter(
        http_transport=httpx.MockTransport(handler), account_ref="uid-1", sleeper=_noop,
        credential=KeyIdSecretCredential(key_id="bybit-key", secret="bybit-secret"),
        clock=lambda: 1_763_650_000_000,
    )


def _coinbase(seen, credential):
    def handler(request):
        seen.append(request)
        body = CB_FILLS if request.url.path.endswith("/historical/fills") else CB_POS
        return httpx.Response(200, json=body, request=request)

    return CoinbaseFuturesAdapter(
        http_transport=httpx.MockTransport(handler), account_ref="cb-portfolio", sleeper=_noop,
        credential=credential, clock=lambda: 1_763_650_000,
    )


async def test_bybit_signs_each_read_and_projects_perp_fills():
    seen = []
    events, checkpoint = await _bybit(seen).pull_events()
    assert checkpoint["provider_health"] == "ok"
    for request in seen:
        query = urlsplit(str(request.url)).query
        expected = hmac.new(b"bybit-secret",
                            f"1763650000000bybit-key5000{query}".encode(), hashlib.sha256).hexdigest()
        assert request.headers["X-BAPI-SIGN"] == expected
    assert bybit_signature("s", "1", "k", "5000", "a=1") == hmac.new(
        b"s", b"1k5000a=1", hashlib.sha256).hexdigest()
    fill = next(e["payload"] for e in events if e["event_name"] == "derivatives_fill_observed")
    assert fill["canonical_market_id"] == "bybit:mainnet:BTCUSDT"
    assert Decimal(fill["price"]) == Decimal("97000.5") and fill["side"] == "buy"
    assert fill["liquidity_role"] == "taker" and fill["executed_at"].startswith("2025-11-20")
    assert all(e["execution_by_aether"] is False for e in events)


def test_bybit_refuses_incomplete_credentials():
    with pytest.raises(BybitCredentialError):
        BybitAdapter(credential=object())


async def test_coinbase_cdp_key_reads_carry_a_verifiable_es256_jwt():
    seen = []
    adapter = _coinbase(seen, KeyIdSecretCredential(key_id="organizations/o/apiKeys/k", secret=EC_PEM))
    events, _ = await adapter.pull_events()
    portfolio = [r for r in seen if "/brokerage/" in r.url.path]
    assert portfolio
    for request in portfolio:
        token = request.headers["Authorization"].removeprefix("Bearer ")
        claims = jwt.decode(token, EC_KEY.public_key(), algorithms=["ES256"],
                            options={"verify_exp": False, "verify_nbf": False})
        assert claims["iss"] == "cdp" and claims["uri"] == f"GET api.coinbase.com{request.url.path}"
        assert jwt.get_unverified_header(token)["kid"] == "organizations/o/apiKeys/k"
    fills = [e["payload"] for e in events if e["event_name"] == "derivatives_fill_observed"]
    assert fills[0]["canonical_market_id"] == "coinbase_futures:mainnet:BIT-28NOV26-CDE"
    assert fills[0]["liquidity_role"] == "maker"
    position = next(e["payload"] for e in events if e["event_name"].startswith("derivatives_position_"))
    assert position["size"] == "2" and position["expiry_at"] == "2026-11-28T16:00:00Z"


async def test_coinbase_oauth_token_is_sent_as_bearer():
    seen = []
    adapter = _coinbase(seen, OAuthTokenCredential(access_token="oauth-access", scope=["wallet:user:read"]))
    await adapter.pull_events()
    assert {r.headers["Authorization"] for r in seen if "/brokerage/" in r.url.path} == {"Bearer oauth-access"}


def test_coinbase_jwt_names_the_exact_request():
    token = coinbase_jwt("k", EC_PEM, "get", "/api/v3/brokerage/cfm/positions", now=100)
    claims = jwt.decode(token, EC_KEY.public_key(), algorithms=["ES256"],
                        options={"verify_exp": False, "verify_nbf": False})
    assert claims == {"sub": "k", "iss": "cdp", "nbf": 100, "exp": 220,
                      "uri": "GET api.coinbase.com/api/v3/brokerage/cfm/positions"}


@pytest.mark.parametrize("adapter_id", ["bybit", "coinbase_futures"])
async def test_new_venues_pass_conformance_and_certification(adapter_id):
    adapter = VENUE_ADAPTERS[adapter_id]
    report = await run_conformance(adapter)
    assert report["passed"], [c for c in report["checks"] if not c["passed"]]
    assert not [r.name for r in run_certification(adapter) if not r.passed]
    assert adapter.certification_descriptor().required_credentials == ["read_only_api_key"]


async def test_unconfigured_adapters_read_nothing():
    for cls in (BybitAdapter, CoinbaseFuturesAdapter):
        seen = []

        def handler(request, seen=seen):
            seen.append(request)
            return httpx.Response(200, json={}, request=request)

        events, _ = await cls(http_transport=httpx.MockTransport(handler), account_ref="a",
                              sleeper=_noop).pull_events()
        assert events == [] and seen == []


async def test_coinbase_accepts_oauth_and_key_links_bybit_only_keys():
    from value.derivatives.venue_sources import API_KEY_ACCESS, OAUTH_ACCESS, venue_profile

    assert venue_profile("coinbase_futures").account_access == (API_KEY_ACCESS, OAUTH_ACCESS)
    assert venue_profile("bybit").account_access == (API_KEY_ACCESS,)


async def test_transport_keeps_a_pre_signed_query_string():
    from value.derivatives.connectors.transport import RestBackfillClient

    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json={}, request=request)

    client = RestBackfillClient(http_transport=httpx.MockTransport(handler), base_url="", sleeper=_noop)
    await client.request_json({"method": "GET", "url": "https://x.test/a?b=1&c=2"}, health={})
    await client.request_json({"method": "GET", "url": "https://x.test/a", "params": {"d": "3"}}, health={})
    assert seen == ["https://x.test/a?b=1&c=2", "https://x.test/a?d=3"]


@pytest.mark.parametrize(
    "ret_code,health",
    [(10003, "auth_error"), (10005, "auth_error"), (10006, "rate_limited"), (110001, "client_error")],
)
async def test_bybit_http_200_application_errors_are_failed_reads(ret_code, health):
    """A rejected key arrives as HTTP 200 + retCode; it must not read as a healthy empty account."""
    def handler(request):
        return httpx.Response(200, json={"retCode": ret_code, "retMsg": "nope", "result": {}}, request=request)

    adapter = BybitAdapter(
        http_transport=httpx.MockTransport(handler), account_ref="uid-1", sleeper=_noop,
        credential=KeyIdSecretCredential(key_id="bybit-key", secret="bybit-secret"),
        clock=lambda: 1_763_650_000_000,
    )
    events, checkpoint = await adapter.pull_events()
    assert events == []
    assert checkpoint["provider_health"] == health
