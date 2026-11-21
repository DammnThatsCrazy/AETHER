"""Tenant venue account links: ownership proof, consent, scope, revocation, erasure."""

from __future__ import annotations

import pytest

from identity.identity.hashing import encrypt_wallet_subject_binding, hash_wallet
from repositories.repos import VenueAccountLinkRepository
from value.derivatives.account_links import (
    AccountLinkError,
    LinkMethod,
    LinkStatus,
    VenueAccountLink,
    VenueAccountLinkService,
    link_id_for,
)
from value.derivatives.models import ReadOnlyCredentialError
from shared.credentials.types import ApiKeyCredential

TENANT = "tenant_links_a"
OTHER = "tenant_links_b"
WALLET = "0x52908400098527886E0F7030069857D2E4169EE7"
NAMESPACE = "eip155:137"


class FakeEvidenceRepo:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def add(self, evidence_id: str, *, tenant: str = TENANT, subject: str = "user_1",
            address: str = WALLET, namespace: str = NAMESPACE, status: str = "active",
            evidence_type: str = "wallet_ownership_verified", bind: bool = True) -> str:
        self.rows[evidence_id] = {
            "id": evidence_id,
            "tenant_id": tenant,
            "evidence_type": evidence_type,
            "identifier_type": "wallet",
            "identifier_hash": hash_wallet(address, namespace),
            "status": status,
            "subject_hint_ciphertext": encrypt_wallet_subject_binding(subject, tenant) if bind else "",
        }
        return evidence_id

    async def get_for_tenant(self, tenant_id: str, evidence_id: str):
        row = self.rows.get(evidence_id)
        return row if row and row["tenant_id"] == tenant_id else None


@pytest.fixture
def service():
    VenueAccountLinkRepository()._store.clear()
    evidence = FakeEvidenceRepo()
    return VenueAccountLinkService(evidence_repo=evidence), evidence


async def _link(svc, evidence_id, **overrides):
    args = dict(
        tenant_id=TENANT, subject_id="user_1", venue="polymarket", wallet_address=WALLET,
        chain_namespace=NAMESPACE, proof_evidence_id=evidence_id, consent_receipt_id="cr_1",
    )
    args.update(overrides)
    return await svc.link_wallet(**args)


async def test_verified_wallet_links_to_its_subject(service):
    svc, evidence = service
    link = await _link(svc, evidence.add("ev_1"))
    assert link.method is LinkMethod.WALLET_PROOF and link.status is LinkStatus.ACTIVE
    assert link.account_ref == WALLET.lower()
    assert link.link_id == link_id_for(TENANT, "user_1", "polymarket", WALLET.lower())
    assert await svc.subjects_by_account(TENANT) == {("polymarket", WALLET.lower()): "user_1"}
    record = link.to_record()
    assert record["execution_by_aether"] is False
    assert not any("secret" in k or "signature" in k for k in record)


@pytest.mark.parametrize(
    ("setup", "overrides", "reason"),
    [
        ({"subject": "someone_else"}, {}, "wallet_proof_subject_mismatch"),
        ({"bind": False}, {}, "wallet_proof_subject_unbound"),
        ({"status": "revoked"}, {}, "wallet_proof_evidence_inactive"),
        ({"evidence_type": "email_ownership_verified"}, {}, "wallet_proof_evidence_wrong_type"),
        ({"address": "0x0000000000000000000000000000000000000001"}, {}, "wallet_proof_address_mismatch"),
        ({"tenant": OTHER}, {}, "wallet_proof_evidence_not_found"),
        ({}, {"consent_receipt_id": ""}, "consent_receipt_required"),
        ({}, {"venue": "not_a_venue"}, "venue_not_registered"),
        ({}, {"chain_namespace": "eip155:1"}, "wallet_proof_address_mismatch"),
    ],
)
async def test_wallet_link_fails_closed(service, setup, overrides, reason):
    svc, evidence = service
    evidence_id = evidence.add("ev_x", **setup)
    with pytest.raises(AccountLinkError) as exc:
        await _link(svc, evidence_id, **overrides)
    assert exc.value.reason == reason
    assert await svc.list_links(TENANT) == []


async def test_links_are_tenant_exact(service):
    svc, evidence = service
    await _link(svc, evidence.add("ev_1"))
    assert await svc.list_links(OTHER) == []
    link_id = link_id_for(TENANT, "user_1", "polymarket", WALLET.lower())
    assert await svc.revoke(tenant_id=OTHER, link_id=link_id) is None


async def test_revocation_removes_account_from_active_map(service):
    svc, evidence = service
    link = await _link(svc, evidence.add("ev_1"))
    revoked = await svc.revoke(tenant_id=TENANT, link_id=link.link_id, reason="user asked")
    assert revoked.status is LinkStatus.REVOKED and revoked.revoked_at
    assert await svc.subjects_by_account(TENANT) == {}
    assert len(await svc.list_links(TENANT, active_only=False)) == 1


async def test_credential_link_rejects_mutating_scopes(service):
    svc, _ = service
    with pytest.raises(ReadOnlyCredentialError):
        await svc.link_credential(
            tenant_id=TENANT, subject_id="user_2", venue="hyperliquid", account_ref="acct",
            method=LinkMethod.READ_ONLY_API_KEY, credential=ApiKeyCredential(api_key="k"),
            scopes=["read", "trade"], consent_receipt_id="cr_2",
        )


async def test_wallet_venue_refuses_a_key_link(service):
    svc, _ = service
    with pytest.raises(AccountLinkError) as exc:
        await svc.link_credential(
            tenant_id=TENANT, subject_id="user_2", venue="hyperliquid", account_ref="acct",
            method=LinkMethod.READ_ONLY_API_KEY, credential=ApiKeyCredential(api_key="k"),
            scopes=["read"], consent_receipt_id="cr_2",
        )
    assert exc.value.reason == "venue_does_not_accept_read_only_api_key"
    assert await svc.list_links(TENANT) == []


async def test_credential_link_stores_the_secret_behind_its_connection(service, monkeypatch):
    from connectors.provider_runtime.credential_broker import credential_broker
    from value.derivatives import venue_sources

    key_venue = venue_sources.VenueSourceProfile(
        "hyperliquid", "Hyperliquid", "fills_read", (venue_sources.API_KEY_ACCESS,),
    )
    monkeypatch.setitem(venue_sources.VENUE_SOURCE_PROFILES, "hyperliquid", key_venue)
    svc, _ = service
    link = await svc.link_credential(
        tenant_id=TENANT, subject_id="user_2", venue="hyperliquid", account_ref="acct",
        method=LinkMethod.READ_ONLY_API_KEY, credential=ApiKeyCredential(api_key="sk_read_only"),
        scopes=["read"], consent_receipt_id="cr_2",
    )
    assert link.credential_ref and link.connection_id and ":connection:" in link.credential_ref
    assert "sk_read_only" not in str(link.to_record())
    stored = await credential_broker.reveal(TENANT, link.credential_ref)
    assert stored.api_key.get_secret_value() == "sk_read_only"
    assert link.source_relationship == "personal_account"

    rotated = await svc.link_credential(
        tenant_id=TENANT, subject_id="user_2", venue="hyperliquid", account_ref="acct",
        method=LinkMethod.READ_ONLY_API_KEY, credential=ApiKeyCredential(api_key="sk_rotated"),
        scopes=["read"], consent_receipt_id="cr_3",
    )
    assert (rotated.credential_ref, rotated.grant_id) == (link.credential_ref, link.grant_id)
    stored = await credential_broker.reveal(TENANT, link.credential_ref)
    assert stored.api_key.get_secret_value() == "sk_rotated"


async def test_tenant_push_and_erasure(service):
    svc, evidence = service
    await _link(svc, evidence.add("ev_1"))
    await svc.link_tenant_push(
        tenant_id=TENANT, subject_id="user_1", venue="hyperliquid", account_ref="0xabc",
        consent_receipt_id="cr_3",
    )
    assert len(await svc.list_links(TENANT, subject_id="user_1")) == 2
    erased = await svc.erase_subject(TENANT, "user_1")
    assert erased == 2
    assert await svc.list_links(TENANT, active_only=False) == []


async def test_dsr_erasure_plane_deletes_subject_links(service):
    from governance.consent.erasure_planes import (
        VENUE_ACCOUNT_LINKS_COMPONENT,
        ErasureSubject,
        erase_venue_account_links_plane,
    )

    svc, evidence = service
    await _link(svc, evidence.add("ev_1"))
    await svc.link_tenant_push(
        tenant_id=OTHER, subject_id="user_1", venue="hyperliquid", account_ref="0xabc",
        consent_receipt_id="cr_4",
    )
    receipts = await erase_venue_account_links_plane(ErasureSubject(tenant_id=TENANT, user_id="user_1"))
    assert receipts[VENUE_ACCOUNT_LINKS_COMPONENT].records_impacted == 1
    assert await svc.list_links(TENANT, active_only=False) == []
    # Another tenant's link for the same subject id is untouched.
    assert len(await svc.list_links(OTHER)) == 1


async def test_dsr_erasure_plane_honors_legal_hold(service, monkeypatch):
    from governance.consent import erasure_planes
    from shared.storage import lifecycle as lifecycle_module

    svc, evidence = service
    await _link(svc, evidence.add("ev_1"))

    async def active_hold(self, tenant_id, resource_type, subject_ref=None):
        assert resource_type == "venue_account_links"
        return {"hold_id": "hold_9", "reason": "litigation"}

    monkeypatch.setattr(lifecycle_module.StorageLifecycle, "active_hold", active_hold)
    receipts = await erasure_planes.erase_venue_account_links_plane(
        erasure_planes.ErasureSubject(tenant_id=TENANT, user_id="user_1")
    )
    receipt = receipts[erasure_planes.VENUE_ACCOUNT_LINKS_COMPONENT]
    assert receipt.status == "skipped_legal_hold"
    assert receipt.policy_decision_id == "storage_legal_hold:hold_9"
    assert len(await svc.list_links(TENANT)) == 1


async def test_capped_account_map_reports_truncation(service):
    svc, _ = service
    for i in range(3):
        await svc.link_tenant_push(
            tenant_id=TENANT, subject_id=f"user_{i}", venue="hyperliquid",
            account_ref=f"0x{i}", consent_receipt_id="cr",
        )
    mapping, truncated = await svc.subjects_by_account_bounded(TENANT, limit=2)
    assert len(mapping) == 2 and truncated is True
    mapping, truncated = await svc.subjects_by_account_bounded(TENANT, limit=3)
    assert len(mapping) == 3 and truncated is False


async def test_one_venue_account_cannot_have_two_active_owners(service):
    svc, _ = service
    await svc.link_tenant_push(tenant_id=TENANT, subject_id="alice", venue="hyperliquid",
                               account_ref="Account-X", consent_receipt_id="cr")
    with pytest.raises(AccountLinkError) as exc:
        await svc.link_tenant_push(tenant_id=TENANT, subject_id="bob", venue="hyperliquid",
                                   account_ref="Account-X", consent_receipt_id="cr")
    assert exc.value.reason == "account_already_linked_to_another_subject"
    # Re-linking the same owner is an idempotent upsert, not a conflict.
    await svc.link_tenant_push(tenant_id=TENANT, subject_id="alice", venue="hyperliquid",
                               account_ref="Account-X", consent_receipt_id="cr2")


async def test_legacy_ambiguous_accounts_are_excluded_from_the_map(service):
    from value.derivatives.account_links import LinkMethod, VenueAccountLink, link_id_for

    svc, _ = service
    for subject in ("alice", "bob"):  # rows written before the single-owner rule
        link = VenueAccountLink(
            link_id=link_id_for(TENANT, subject, "hyperliquid", "Account-X"), tenant_id=TENANT,
            subject_id=subject, venue="hyperliquid", account_ref="Account-X",
            method=LinkMethod.TENANT_PUSH, consent_receipt_id="cr",
        )
        await svc._repo.insert(link.link_id, link.to_record())
    mapping, _ = await svc.subjects_by_account_bounded(TENANT)
    assert ("hyperliquid", "Account-X") not in mapping
    assert svc.last_ambiguous_accounts == [("hyperliquid", "Account-X")]


# ── Source authority: connection + grant behind every link ───────────────────

async def _grant(grant_id, tenant=TENANT):
    from connectors.integrations.data_rights.service import data_rights_service

    return await data_rights_service.get_grant(grant_id, tenant_id=tenant)


async def _connection(connection_id):
    from connectors.provider_runtime.connection import ProviderConnectionRepository

    return await ProviderConnectionRepository().find(connection_id)


async def test_wallet_link_is_a_personal_account_source(service):
    svc, evidence = service
    link = await _link(svc, evidence.add("ev_1"), actor="admin_1")
    grant = await _grant(link.grant_id)
    assert link.source_id == f"provider-account:{link.connection_id}:{WALLET.lower()}"
    assert grant.source_id == link.source_id
    assert grant.connector_id == "polymarket.account.activity_read"
    assert grant.connector_class == "tenant_byod_data"
    assert grant.source_relationship == "personal_account"
    assert grant.raw_data_owner == "subject" and grant.subject_ref == "user_1"
    assert grant.consent_basis == "cr_1" and grant.granted_by_user_id == "admin_1"
    assert not grant.olympus_baseline_allowed and not grant.model_training_allowed
    connection = await _connection(link.connection_id)
    assert connection.state.value == "connected"
    assert connection.selected_accounts == [WALLET.lower()] and connection.credential_ref == ""


async def test_tenant_push_is_an_organization_system_source(service):
    svc, _ = service
    link = await svc.link_tenant_push(
        tenant_id=TENANT, subject_id="user_1", venue="hyperliquid", account_ref="0xabc",
        consent_receipt_id="cr_3",
    )
    grant = await _grant(link.grant_id)
    assert grant.source_relationship == "organization_system"
    assert grant.raw_data_owner == "tenant" and grant.subject_ref is None
    assert (await _connection(link.connection_id)).state.value == "available"


async def test_olympus_scope_cannot_hold_a_venue_link(service):
    svc, _ = service
    with pytest.raises(AccountLinkError) as exc:
        await svc.link_tenant_push(
            tenant_id="olympus", subject_id="u", venue="hyperliquid", account_ref="0xabc",
            consent_receipt_id="cr",
        )
    assert exc.value.reason == "olympus_scope_not_linkable"


def _raw(link, record_id="fill_1"):
    from shared.integration_contracts.events import make_raw_record

    return make_raw_record(
        provider_identity="polymarket.account.activity_read", tenant_id=link.tenant_id,
        connection_id=link.connection_id, account_id=link.account_ref,
        provider_record_type="trade", provider_record_id=record_id, payload={"id": record_id},
    )


async def test_linked_account_raw_records_are_admitted_until_revoked(service):
    from connectors.provider_runtime.rights_admission import (
        ProviderRawRightsAdmission,
        ProviderRawRightsDenied,
    )

    svc, evidence = service
    link = await _link(svc, evidence.add("ev_1"))
    admission = ProviderRawRightsAdmission()
    evidence_row = await admission.admit(_raw(link))
    assert evidence_row.source_grant_ref == link.grant_id
    assert evidence_row.source_relationship == "personal_account"
    assert evidence_row.requested_use == "tenant_lake"

    await svc.revoke(tenant_id=TENANT, link_id=link.link_id, reason="user asked")
    assert (await _grant(link.grant_id)).revoked_at
    assert (await _connection(link.connection_id)).state.value in ("revoked", "disabled")
    with pytest.raises(ProviderRawRightsDenied):
        await admission.admit(_raw(link, "fill_2"))


async def test_unlinked_account_on_the_same_connection_is_not_admitted(service):
    from connectors.provider_runtime.rights_admission import (
        ProviderRawRightsAdmission,
        ProviderRawRightsDenied,
    )

    svc, evidence = service
    link = await _link(svc, evidence.add("ev_1"))
    other = _raw(link).model_copy(update={"account_id": "0x0000000000000000000000000000000000000009"})
    with pytest.raises(ProviderRawRightsDenied):
        await ProviderRawRightsAdmission().admit(other)


async def test_relink_keeps_the_governing_source(service):
    svc, evidence = service
    first = await _link(svc, evidence.add("ev_1"))
    second = await _link(svc, evidence.add("ev_2"), proof_evidence_id="ev_2", consent_receipt_id="cr_9")
    assert second.link_id == first.link_id
    assert (second.grant_id, second.connection_id) == (first.grant_id, first.connection_id)
    assert second.consent_receipt_id == "cr_9"
    assert (await _grant(first.grant_id)).revoked_at is None


async def test_relink_after_revocation_provisions_a_new_source(service):
    svc, evidence = service
    first = await _link(svc, evidence.add("ev_1"))
    await svc.revoke(tenant_id=TENANT, link_id=first.link_id)
    second = await _link(svc, evidence.add("ev_2"), proof_evidence_id="ev_2")
    assert second.grant_id != first.grant_id and second.status is LinkStatus.ACTIVE
    assert (await _grant(first.grant_id)).revoked_at


async def test_erasure_revokes_every_grant_and_credential(service):
    svc, evidence = service
    link = await _link(svc, evidence.add("ev_1"))
    assert await svc.erase_subject(TENANT, "user_1") == 1
    assert (await _grant(link.grant_id)).revoked_at


async def test_backfill_governs_links_created_before_sources(service):
    svc, _ = service
    legacy = VenueAccountLink(
        link_id=link_id_for(TENANT, "user_7", "hyperliquid", "0xfeed"), tenant_id=TENANT,
        subject_id="user_7", venue="hyperliquid", account_ref="0xfeed",
        method=LinkMethod.TENANT_PUSH, consent_receipt_id="cr_old",
    )
    keyless = VenueAccountLink(
        link_id=link_id_for(TENANT, "user_8", "hyperliquid", "acct8"), tenant_id=TENANT,
        subject_id="user_8", venue="hyperliquid", account_ref="acct8",
        method=LinkMethod.READ_ONLY_API_KEY, consent_receipt_id="cr_old",
    )
    for row in (legacy, keyless):
        await svc._repo.insert(row.link_id, row.to_record())
    counts = await svc.backfill_sources(TENANT, actor="op")
    assert counts == {"provisioned": 1, "already_governed": 0, "refused": 1}
    (governed,) = [link for link in await svc.list_links(TENANT) if link.subject_id == "user_7"]
    assert (await _grant(governed.grant_id)).consent_basis == "cr_old"
    assert (await svc.backfill_sources(TENANT))["already_governed"] == 1


async def test_disconnect_stops_reading_but_keeps_the_grant(service):
    from connectors.provider_runtime.rights_admission import ProviderRawRightsAdmission

    svc, evidence = service
    link = await _link(svc, evidence.add("ev_1"))
    disconnected = await svc.disconnect(tenant_id=TENANT, link_id=link.link_id)
    assert disconnected.status is LinkStatus.DISCONNECTED and disconnected.disconnected_at
    assert (await _grant(link.grant_id)).revoked_at is None
    assert (await _connection(link.connection_id)).state.value in ("revoked", "disabled")
    # Admitted history stays attributed to its subject.
    assert await svc.subjects_by_account(TENANT) == {("polymarket", WALLET.lower()): "user_1"}
    # The grant still governs; the sync simply no longer reads (status gate).
    assert (await ProviderRawRightsAdmission().admit(_raw(link))).source_grant_ref == link.grant_id


async def test_reconnect_reuses_the_grant_and_reopens_the_connection(service):
    svc, evidence = service
    link = await _link(svc, evidence.add("ev_1"))
    await svc.disconnect(tenant_id=TENANT, link_id=link.link_id)
    again = await _link(svc, evidence.add("ev_2"), proof_evidence_id="ev_2")
    assert again.status is LinkStatus.ACTIVE
    assert (again.grant_id, again.connection_id) == (link.grant_id, link.connection_id)
    assert (await _connection(link.connection_id)).state.value == "connected"


async def test_disconnected_account_still_blocks_another_owner(service):
    svc, _ = service
    link = await svc.link_tenant_push(tenant_id=TENANT, subject_id="alice", venue="hyperliquid",
                                      account_ref="Account-Y", consent_receipt_id="cr")
    await svc.disconnect(tenant_id=TENANT, link_id=link.link_id)
    with pytest.raises(AccountLinkError) as exc:
        await svc.link_tenant_push(tenant_id=TENANT, subject_id="bob", venue="hyperliquid",
                                   account_ref="Account-Y", consent_receipt_id="cr")
    assert exc.value.reason == "account_already_linked_to_another_subject"
