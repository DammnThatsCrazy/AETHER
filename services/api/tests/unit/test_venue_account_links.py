"""Tenant venue account links: ownership proof, consent, scope, revocation, erasure."""

from __future__ import annotations

import pytest

from identity.identity.hashing import encrypt_wallet_subject_binding, hash_wallet
from repositories.repos import VenueAccountLinkRepository
from value.derivatives.account_links import (
    AccountLinkError,
    LinkMethod,
    LinkStatus,
    VenueAccountLinkService,
    link_id_for,
)
from value.derivatives.models import ReadOnlyCredentialError

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
            method=LinkMethod.READ_ONLY_API_KEY, credential_ref="cred_1",
            scopes=["read", "trade"], consent_receipt_id="cr_2",
        )
    link = await svc.link_credential(
        tenant_id=TENANT, subject_id="user_2", venue="hyperliquid", account_ref="acct",
        method=LinkMethod.READ_ONLY_API_KEY, credential_ref="cred_1",
        scopes=["read"], consent_receipt_id="cr_2",
    )
    assert link.credential_ref == "cred_1" and link.method is LinkMethod.READ_ONLY_API_KEY


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
