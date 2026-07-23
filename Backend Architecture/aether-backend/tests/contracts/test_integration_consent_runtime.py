import pytest

from repositories.repos import reset_in_memory_stores
from services.consent.authority import record_consent_receipt_envelope
from services.consent.control_plane import (
    CanonicalConsentReceiptInput,
    IntegrationPolicyManifest,
    TenantProcessingProfile,
    connector_policy_decisions,
    integration_policy_manifests,
    tenant_processing_profiles,
)
from services.consent.routes import (
    ConsentRecord,
    _canonical_receipt_hash,
    _normalize_receipt,
)
from services.integrations.consent_policy import evaluate_connector_processing
from shared.common.common import BadRequestError


@pytest.fixture(autouse=True)
def reset_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


def _receipt_payload(**overrides):
    payload = {
        "tenant_id": "tenant-1",
        "subject_id": "subject-1",
        "anonymous_id": None,
        "purposes": ["analytics", "marketing"],
        "state": "granted",
        "source": "sdk-test",
        "provider": None,
        "policy_version": "2026-07-18",
        "jurisdiction_context": None,
        "mode": None,
        "lawful_basis": None,
        "granted_at": "2026-07-18T12:00:00.000Z",
        "denied_at": None,
        "revoked_at": None,
        "expires_at": None,
        "gpc_observed": None,
        "dnt_observed": None,
        "provider_consent_id": None,
        "metadata": {},
    }
    payload.update(overrides)
    return payload


def _canonical_receipt(**overrides) -> CanonicalConsentReceiptInput:
    payload = _receipt_payload(**overrides)
    digest = _canonical_receipt_hash(payload)
    return CanonicalConsentReceiptInput(
        **payload,
        receipt_id=f"ccr_{digest[:32]}",
        integrity_hash=f"sha256:{digest}",
        idempotency_key=f"consent-receipt:{digest}",
    )


def test_canonical_receipt_hash_matches_sdk_golden_vector():
    digest = _canonical_receipt_hash(_receipt_payload())
    assert digest == "96352c9c6e59371ad054846329720b2eb1285c71bb39406ffae5b1583e1e54c0"
    assert f"ccr_{digest[:32]}" == "ccr_96352c9c6e59371ad054846329720b2e"


def test_canonical_receipt_rejects_tampered_integrity_hash():
    receipt = _canonical_receipt()
    tampered = receipt.model_copy(update={"integrity_hash": "sha256:" + "0" * 64})

    with pytest.raises(BadRequestError):
        _normalize_receipt(
            ConsentRecord(canonical_receipt=tampered),
            tenant_id="tenant-1",
            effective_mode=None,
        )


@pytest.mark.asyncio
async def test_receipt_idempotency_collision_cannot_overwrite_evidence():
    receipt = _canonical_receipt()
    await record_consent_receipt_envelope(receipt)
    collision = receipt.model_copy(update={"integrity_hash": "sha256:" + "f" * 64})

    with pytest.raises(BadRequestError):
        await record_consent_receipt_envelope(collision)


@pytest.mark.asyncio
async def test_connector_processing_decision_is_tenant_scoped_and_persisted():
    await tenant_processing_profiles.upsert_profile(
        TenantProcessingProfile(
            tenant_id="tenant-1",
            status="active",
            policy_version="2026-07-18",
            tenant_admin_approved=True,
            approved_purposes=["commerce"],
            allowed_processing_bases=["contract"],
        )
    )
    await integration_policy_manifests.upsert_manifest(
        IntegrationPolicyManifest(
            tenant_id="tenant-1",
            connector_type="stripe",
            status="approved",
            policy_version="2026-07-18",
            tenant_admin_approved=True,
            provider_admin_installed=True,
            approved_purposes=["commerce"],
            processing_basis="contract",
            allowed_fields=["event_id"],
        )
    )

    decision = await evaluate_connector_processing(
        "tenant-1",
        "stripe",
        payload_fields=["event_id"],
        purpose="commerce",
    )

    assert decision.allowed is True
    stored = await connector_policy_decisions.list_for_tenant("tenant-1")
    assert len(stored) == 1
    assert stored[0]["tenant_id"] == "tenant-1"
    assert stored[0]["decision_id"] == decision.decisionId
