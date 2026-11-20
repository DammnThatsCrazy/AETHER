"""Kalshi read-only account adapter: signed reads, event-contract fills, key links."""

from __future__ import annotations

import base64
from decimal import Decimal

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from repositories.repos import VenueAccountLinkRepository
from shared.certification.checks import run_certification
from shared.credentials.types import KeyIdSecretCredential
from value.derivatives.adapters import VENUE_ADAPTERS
from value.derivatives.adapters.conformance import run_conformance
from value.derivatives.adapters.kalshi import KalshiAdapter, KalshiSigningError, kalshi_signature

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
).decode()
TENANT = "tenant_kalshi"

# Shapes follow the Trade API v2 portfolio responses (dollar fields and the
# older integer-cent fields both appear).
FILLS = {"fills": [
    {"fill_id": "f-1", "trade_id": "t-1", "order_id": "o-1", "ticker": "KXRAIN-26NOV21",
     "side": "yes", "action": "buy", "count": 10, "yes_price_dollars": "0.4200",
     "is_taker": True, "created_time": "2026-11-20T15:00:00Z"},
    {"fill_id": "f-2", "trade_id": "t-2", "order_id": "o-2", "ticker": "KXRAIN-26NOV21",
     "side": "no", "action": "buy", "count": 5, "no_price": 61,
     "is_taker": False, "created_time": "2026-11-20T15:05:00Z"},
], "cursor": ""}
POSITIONS = {"market_positions": [
    {"ticker": "KXRAIN-26NOV21", "position": 10, "realized_pnl": 0},
    {"ticker": "KXSNOW-26NOV22", "position": -3, "realized_pnl_dollars": "1.25"},
], "cursor": ""}


def _credential():
    return KeyIdSecretCredential(key_id="key-123", secret=PEM)


def _transport(seen):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/portfolio/fills"):
            return httpx.Response(200, json=FILLS, request=request)
        if request.url.path.endswith("/portfolio/positions"):
            return httpx.Response(200, json=POSITIONS, request=request)
        return httpx.Response(200, json={"exchange_active": True}, request=request)

    return httpx.MockTransport(handler)


async def _noop(_s):
    return None


def _adapter(seen=None):
    return KalshiAdapter(
        http_transport=_transport(seen if seen is not None else []), account_ref="member-9",
        credential=_credential(), clock=lambda: 1_763_650_000_000, sleeper=_noop,
    )


def test_signature_verifies_with_the_public_key():
    signature = kalshi_signature(PEM, "1763650000000", "get", "/trade-api/v2/portfolio/fills")
    KEY.public_key().verify(
        base64.b64decode(signature),
        b"1763650000000GET/trade-api/v2/portfolio/fills",
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )


def test_unreadable_or_incomplete_credentials_are_refused():
    with pytest.raises(KalshiSigningError):
        kalshi_signature("not a key", "1", "GET", "/x")
    with pytest.raises(KalshiSigningError):
        KalshiAdapter(credential=object())


async def test_signed_reads_project_event_contract_fills_and_positions():
    seen = []
    events, checkpoint = await _adapter(seen).pull_events()
    assert checkpoint["provider_health"] == "ok"
    portfolio = [r for r in seen if "/portfolio/" in r.url.path]
    assert portfolio and all(r.headers["KALSHI-ACCESS-KEY"] == "key-123" for r in portfolio)
    assert all(r.headers["KALSHI-ACCESS-SIGNATURE"] for r in portfolio)
    fills = [e["payload"] for e in events if e["event_name"] == "derivatives_fill_observed"]
    assert [f["canonical_market_id"] for f in fills] == [
        "kalshi:mainnet:KXRAIN-26NOV21:yes", "kalshi:mainnet:KXRAIN-26NOV21:no",
    ]
    assert Decimal(fills[0]["price"]) == Decimal("0.42") and Decimal(fills[1]["price"]) == Decimal("0.61")
    assert fills[0]["event_contract_ref"] == "kalshi:mainnet:KXRAIN-26NOV21"
    assert {f["outcome"] for f in fills} == {"yes", "no"}
    assert fills[0]["liquidity_role"] == "taker" and fills[1]["liquidity_role"] == "maker"
    positions = [e["payload"] for e in events if e["event_name"].startswith("derivatives_position_")]
    snow = next(p for p in positions if "KXSNOW" in p["canonical_market_id"])
    assert snow["canonical_market_id"].endswith(":no") and snow["size"] == "3"
    assert all(e["execution_by_aether"] is False for e in events)


async def test_without_a_credential_nothing_is_read():
    seen = []
    events, _ = await KalshiAdapter(http_transport=_transport(seen), account_ref="m", sleeper=_noop).pull_events()
    assert events == [] and not [r for r in seen if "/portfolio/" in r.url.path]


async def test_kalshi_passes_conformance_and_certification():
    assert isinstance(VENUE_ADAPTERS.get("kalshi"), KalshiAdapter)
    report = await run_conformance(_adapter())
    assert report["passed"], [c for c in report["checks"] if not c["passed"]]
    failures = [r.name for r in run_certification(_adapter()) if not r.passed]
    assert not failures, failures
    assert _adapter().certification_descriptor().required_credentials == ["read_only_api_key"]


async def test_key_link_then_signed_sync_writes_admitted_fills():
    from value.derivatives.account_links import LinkMethod, VenueAccountLinkService
    from value.derivatives.account_sync import VenueAccountSync

    VenueAccountLinkRepository()._store.clear()
    service = VenueAccountLinkService()
    link = await service.link_credential(
        tenant_id=TENANT, subject_id="trader", venue="kalshi", account_ref="member-9",
        method=LinkMethod.READ_ONLY_API_KEY, credential=_credential(), scopes=["read"],
        consent_receipt_id="cr_k",
    )
    assert link.source_relationship == "personal_account" and link.credential_ref
    from value.derivatives.venue_sources import VenueSourceError, VenueSourceProvisioner

    with pytest.raises(VenueSourceError) as refused:  # a key venue never takes a wallet link
        await VenueSourceProvisioner().provision(
            tenant_id=TENANT, subject_id="trader", venue="kalshi", account_ref="0xabc",
            method="wallet_proof", consent_receipt_id="cr", actor="t",
        )
    assert refused.value.reason == "venue_does_not_accept_public_wallet_address"

    class Fills:
        columns = {"tenant_id", "idempotency_key", "execution_by_aether", "fill_id",
                   "canonical_market_id", "source_refs", "price"}
        rows = []

        async def insert(self, record):
            self.rows.append(record)
            return True

    class Markets:
        async def ensure(self, ids):
            from value.derivatives.market_reference import EnsureResult

            return EnsureResult(present=set(ids))

    def factory(venue, account_ref, credential=None):
        assert venue == "kalshi" and credential.key_id == "key-123"
        return KalshiAdapter(http_transport=_transport([]), account_ref=account_ref,
                             credential=credential, sleeper=_noop)

    fills = Fills()
    result = await VenueAccountSync(
        link_service=service, fill_repo=fills, adapter_factory=factory, market_reference=Markets(),
    ).sync_link(link)
    assert result.status == "ok" and result.fills_written == 2
    assert all(any(r.startswith("source_grant_ref=") for r in row["source_refs"]) for row in fills.rows)


async def test_kalshi_market_reference_yields_both_sides():
    from value.derivatives.market_reference import _kalshi

    def handler(request):
        assert request.url.params["tickers"] == "KXRAIN-26NOV21"
        return httpx.Response(200, json={"markets": [
            {"ticker": "KXRAIN-26NOV21", "status": "active", "close_time": "2026-11-21T23:00:00Z"},
        ]}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        facts = await _kalshi(client, {"KXRAIN-26NOV21:yes", "KXRAIN-26NOV21:no"}, "mainnet")
    assert {f.canonical_market_id for f in facts} == {
        "kalshi:mainnet:KXRAIN-26NOV21:yes", "kalshi:mainnet:KXRAIN-26NOV21:no",
    }
