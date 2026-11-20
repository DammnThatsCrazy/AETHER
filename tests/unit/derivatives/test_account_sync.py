"""Linked venue accounts sync through provider raw admission into derivatives fills."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from identity.identity.hashing import encrypt_wallet_subject_binding, hash_wallet
from repositories.repos import VenueAccountLinkRepository
from value.derivatives.account_links import VenueAccountLinkService
from value.derivatives.account_sync import VenueAccountSync
from value.derivatives.adapters.polymarket import PolymarketAdapter

FIXTURES = (
    Path(__file__).parents[3]
    / "services" / "api" / "tests" / "fixtures" / "provider_payloads" / "derivatives"
)
PM = json.loads((FIXTURES / "polymarket_live_capture.json").read_text())
TENANT = "tenant_sync_a"
NAMESPACE = "eip155:137"


class Evidence:
    def __init__(self, address: str) -> None:
        self.row = {
            "id": "ev_sync", "tenant_id": TENANT, "evidence_type": "wallet_ownership_verified",
            "identifier_type": "wallet", "identifier_hash": hash_wallet(address, NAMESPACE),
            "status": "active",
            "subject_hint_ciphertext": encrypt_wallet_subject_binding("trader_1", TENANT),
        }

    async def get_for_tenant(self, tenant_id, evidence_id):
        return self.row if tenant_id == TENANT and evidence_id == "ev_sync" else None


class Fills:
    columns = {
        "tenant_id", "idempotency_key", "execution_by_aether", "fill_id", "trading_account_id",
        "canonical_market_id", "side", "price", "quantity", "executed_at", "source_refs",
    }

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    async def insert(self, record):
        if record["idempotency_key"] in self.rows:
            return False
        self.rows[record["idempotency_key"]] = record
        return True


async def _noop(_s):
    return None


class Markets:
    """Market reference fake: every market has its reference row unless listed."""

    def __init__(self, missing=()):
        self.missing_ids = set(missing)

    async def ensure(self, ids):
        from value.derivatives.market_reference import EnsureResult

        missing = set(ids) & self.missing_ids
        return EnsureResult(present=set(ids) - missing, missing=missing,
                            reasons={"market_reference_source_missing:polymarket"} if missing else set())


def _factory(venue, account_ref, credential=None):
    assert venue == "polymarket" and credential is None

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/v2/trades"):
            return httpx.Response(200, json=PM["trades"], request=request)
        if path.endswith("/v2/positions"):
            return httpx.Response(200, json=PM["positions"], request=request)
        return httpx.Response(200, json=[], request=request)

    return PolymarketAdapter(http_transport=httpx.MockTransport(handler), account_ref=account_ref, sleeper=_noop)


@pytest.fixture
async def linked():
    VenueAccountLinkRepository()._store.clear()
    address = PM["account_ref"]
    service = VenueAccountLinkService(evidence_repo=Evidence(address))
    link = await service.link_wallet(
        tenant_id=TENANT, subject_id="trader_1", venue="polymarket", wallet_address=address,
        chain_namespace=NAMESPACE, proof_evidence_id="ev_sync", consent_receipt_id="cr_sync",
    )
    return service, link


async def test_sync_admits_raw_records_and_writes_governed_fills(linked):
    service, link = linked
    fills = Fills()
    sync = VenueAccountSync(link_service=service, fill_repo=fills, adapter_factory=_factory,
                            market_reference=Markets())
    result = await sync.sync_link(link)
    assert result.status == "ok", result
    assert result.fills_written == len(PM["trades"]["data"])
    assert result.admitted >= result.fills_written
    for row in fills.rows.values():
        refs = dict(r.split("=", 1) for r in row["source_refs"] if "=" in r)
        assert refs["source_id"] == link.source_id
        assert refs["source_grant_ref"] == link.grant_id
        assert refs["rights_decision_ref"]
        assert row["tenant_id"] == TENANT and row["execution_by_aether"] is False
    stored = await service.get_link(TENANT, link.link_id)
    assert stored.sync_state["connection_id"] == link.connection_id
    assert stored.sync_state["checkpoint"]["provider_health"] == "ok"

    # A second sweep resumes from the checkpoint and writes no duplicates.
    again = await sync.sync_link(stored)
    assert again.status == "ok" and again.fills_written == 0


async def test_revoked_link_is_not_read(linked):
    service, link = linked
    await service.revoke(tenant_id=TENANT, link_id=link.link_id)
    revoked = await service.get_link(TENANT, link.link_id)
    result = await VenueAccountSync(
        link_service=service, fill_repo=Fills(), adapter_factory=_factory,
    ).sync_link(revoked)
    assert (result.status, result.reason) == ("skipped", "link_revoked")


async def test_grant_revoked_behind_an_active_link_denies_and_keeps_the_checkpoint(linked):
    from connectors.integrations.data_rights.models import DataRightsGrantRevoke
    from connectors.integrations.data_rights.service import data_rights_service

    service, link = linked
    await data_rights_service.revoke_grant(
        link.grant_id, DataRightsGrantRevoke(revocation_reason="t", revoked_by_user_id="t"),
        tenant_id=TENANT,
    )
    fills = Fills()
    result = await VenueAccountSync(
        link_service=service, fill_repo=fills, adapter_factory=_factory,
    ).sync_link(link)
    assert (result.status, result.reason) == ("denied", "rights_denied")
    assert fills.rows == {}
    assert (await service.get_link(TENANT, link.link_id)).sync_state is None


async def test_link_without_a_grant_is_not_read(linked):
    from dataclasses import replace

    service, link = linked
    result = await VenueAccountSync(
        link_service=service, fill_repo=Fills(), adapter_factory=_factory,
    ).sync_link(replace(link, grant_id=None))
    assert (result.status, result.reason) == ("skipped", "link_not_governed")


async def test_tenant_pushed_fill_is_admitted_under_its_link():
    from value.derivatives.account_sync import admit_pushed_fill

    VenueAccountLinkRepository()._store.clear()
    service = VenueAccountLinkService()
    link = await service.link_tenant_push(
        tenant_id=TENANT, subject_id="trader_9", venue="hyperliquid", account_ref="0xpush",
        consent_receipt_id="cr_push",
    )
    fill = {"fill_id": "pf1", "venue_id": "hyperliquid", "account_ref": "0xpush",
            "executed_at": "2026-11-20T10:00:00+00:00"}
    refs = await admit_pushed_fill(TENANT, fill, link_service=service)
    as_map = dict(r.split("=", 1) for r in refs)
    assert as_map["source_grant_ref"] == link.grant_id and as_map["rights_decision_ref"]
    # No governing link for the account: stored unadmitted, not used.
    assert await admit_pushed_fill(TENANT, {**fill, "account_ref": "0xother"}, link_service=service) is None


async def test_client_cannot_forge_governance_refs():
    from value.derivatives.account_sync import strip_governance_refs
    from value.derivatives.runtime_routes import _governed_fill_refs

    forged = ["source_grant_ref=drg_x", "rights_decision_ref=rd_x", "source_id=s", "outcome=Yes"]
    assert strip_governance_refs(forged) == ["outcome=Yes"]
    refs = await _governed_fill_refs(TENANT, {"fill_id": "f", "source_refs": forged})
    assert not any(r.startswith(("source_grant_ref", "rights_decision_ref", "source_id")) for r in refs)


async def test_fills_wait_for_their_market_reference(linked):
    service, link = linked
    fills = Fills()
    first_market = None

    def recording_factory(venue, account_ref, credential=None):
        return _factory(venue, account_ref, credential)

    events, _ = await recording_factory("polymarket", link.account_ref).pull_events()
    first_market = next(e["payload"]["canonical_market_id"] for e in events
                        if e["event_name"] == "derivatives_fill_observed")
    result = await VenueAccountSync(
        link_service=service, fill_repo=fills, adapter_factory=_factory,
        market_reference=Markets(missing={first_market}),
    ).sync_link(link)
    assert result.status == "degraded" and result.reason.startswith("market_reference_missing")
    assert all(r["canonical_market_id"] != first_market for r in fills.rows.values())
    # The checkpoint did not move, so the waiting fills are read again later.
    assert (await service.get_link(TENANT, link.link_id)).sync_state is None
