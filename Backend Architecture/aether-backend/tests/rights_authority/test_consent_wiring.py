"""Consent wiring — the resolver's consent seam wired to the server authority.

Covers:
* ``default_consent_evaluator`` (services.rights_authority.consent) maps the
  server ``evaluate_consent`` result (allowed + each relevant fail-closed reason
  code) to a ``ConsentPolicyDecision`` correctly.
* A resolver wired with the adapter records ``consent_decision_refs`` and honors
  allow vs deny (server consent is authoritative).
* Bare ``EffectiveRightsResolver()`` stays fail-closed (``consent_required``)
  exactly as before wiring.
* ``configure_consent_evaluator`` installs/clears the seam on a resolver.
* The module singleton is wired to the server authority by default.
"""
from __future__ import annotations

import uuid
from typing import Optional

import pytest

from repositories.repos import reset_in_memory_stores

from services.consent.authority import (
    CONSENT_DENIED,
    CONSENT_EXPIRED,
    CONSENT_RECEIPT_MISSING,
    CONSENT_REVOKED,
    CONSENT_UNKNOWN,
    PURPOSE_NOT_AUTHORIZED,
    record_consent_receipt_envelope,
)
from services.consent.control_plane import CanonicalConsentReceiptInput
from services.integrations.data_rights.models import (
    DataRightsGrant,
    GrantStatus,
)
from services.integrations.data_rights.service import default_generated_output_rights
from services.policy.repositories import ConsentPolicyDecisionRepository
from services.rights_authority.consent import default_consent_evaluator
from services.rights_authority.contracts import RightsDecisionRequest
from services.rights_authority.resolver import (
    EffectiveRightsResolver,
    configure_consent_evaluator,
    effective_rights_resolver,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def reset_stores():
    reset_in_memory_stores()
    yield
    reset_in_memory_stores()


# ── builders ────────────────────────────────────────────────────────────────


def _grant(**overrides) -> DataRightsGrant:
    base = {
        "data_rights_grant_id": "drg_consent_001",
        "tenant_id": "tenant_abc",
        "contract_id": None,
        "source_id": "src_001",
        "connector_id": "dune_api",
        "connector_class": "tenant_byod_data",
        "source_manifest_id": None,
        "data_category": "onchain",
        "data_sensitivity": "unclassified",
        "raw_data_owner": "olympus_labs",
        "tenant_lake_allowed": True,
        "tenant_graph_allowed": True,
        "tenant_insights_allowed": True,
        "olympus_baseline_allowed": False,
        "cross_tenant_aggregate_allowed": False,
        "model_training_allowed": False,
        "commercial_reuse_allowed": False,
        "legal_basis": "operator_policy",
        "consent_basis": None,
        "granted_by_user_id": "user_1",
        "granted_at": "2026-09-01T00:00:00+00:00",
        "expires_at": None,
        "revoked_at": None,
        "revocation_reason": None,
        "status": GrantStatus.ACTIVE,
        "audit_event_id": "audit_1",
    }
    base.update(overrides)
    return DataRightsGrant(**base)


def _consent_grant(**overrides) -> DataRightsGrant:
    defaults = {
        "legal_basis": "consent",
        "consent_basis": "explicit_consent",
        "subject_ref": "subject-1",
    }
    defaults.update(overrides)
    if "subject_ref" not in overrides and "consent_basis" in overrides and overrides["consent_basis"] is None:
        defaults["subject_ref"] = None
    return _grant(**defaults)


def _request(**overrides) -> RightsDecisionRequest:
    base = {
        "tenant_id": "tenant_abc",
        "source_id": "src_001",
        "artifact_ref": None,
        "artifact_class": None,
        "actor": "actor_1",
        "actor_role": None,
        "requested_use": "export",
        "purpose": "analytics",
        "destination": "tenant",
        "as_of": None,
    }
    base.update(overrides)
    return RightsDecisionRequest(**base)


def _loader(*grants: DataRightsGrant):
    async def _load(tenant_id: str, source_id: str) -> Optional[DataRightsGrant]:
        for grant in grants:
            if grant.tenant_id == tenant_id and grant.source_id == source_id:
                return grant
        return None

    return _load


async def _seed_receipt(
    *,
    tenant_id: str,
    subject_id: Optional[str],
    state: str = "granted",
    purpose: str = "analytics",
) -> None:
    """Persist one authoritative server consent receipt via the public path."""
    nonce = uuid.uuid4().hex
    receipt = CanonicalConsentReceiptInput(
        receipt_id=f"ccr_{nonce[:24]}",
        tenant_id=tenant_id,
        subject_id=subject_id,
        anonymous_id=None,
        purposes=[purpose],
        state=state,
        source="test",
        provider=None,
        policy_version="2026-07-18",
        jurisdiction_context=None,
        mode=None,
        lawful_basis=None,
        granted_at="2026-09-01T00:00:00+00:00" if state == "granted" else None,
        denied_at=None,
        revoked_at="2026-09-02T00:00:00+00:00" if state == "revoked" else None,
        expires_at="2020-01-01T00:00:00+00:00" if state == "expired" else None,
        gpc_observed=None,
        dnt_observed=None,
        provider_consent_id=None,
        integrity_hash="sha256:" + nonce,
        idempotency_key=f"consent-receipt:{nonce}",
        metadata={},
    )
    await record_consent_receipt_envelope(receipt)


async def _adapter_decision(**grant_overrides) -> tuple[RightsDecisionRequest, DataRightsGrant, object]:
    request = _request()
    grant = _consent_grant(**grant_overrides)
    return request, grant, await default_consent_evaluator(request, grant)


# ── adapter mapping: server evaluate_consent → ConsentPolicyDecision ────────


async def test_adapter_allows_granted_registry_purpose():
    """A granted analytics receipt for the grant's subject → allowed decision."""
    await _seed_receipt(tenant_id="tenant_abc", subject_id="subject-1")
    _req, _grant_obj, decision = await _adapter_decision()
    assert decision is not None
    assert decision.allowed is True
    assert decision.denied_reason is None
    assert decision.tenant_id == "tenant_abc"
    assert decision.subject_ref == "subject-1"
    assert decision.resource_id == _grant_obj.data_rights_grant_id
    assert "analytics" in decision.granted_purposes


async def test_request_subject_reference_overrides_grant_default():
    """A request may bind one subject without overloading consent_basis."""
    await _seed_receipt(tenant_id="tenant_abc", subject_id="subject-2")
    request = _request(subject_ref="subject-2")
    decision = await default_consent_evaluator(request, _consent_grant())
    assert decision is not None
    assert decision.allowed is True
    assert decision.subject_ref == "subject-2"


async def test_adapter_denies_missing_receipt():
    """No server receipt → authoritative consent_receipt_missing denial."""
    await _seed_receipt(tenant_id="tenant_abc", subject_id="other-subject")
    _req, _grant_obj, decision = await _adapter_decision()
    assert decision is not None
    assert decision.allowed is False
    assert decision.denied_reason == CONSENT_RECEIPT_MISSING
    assert "analytics" in decision.missing_purposes


async def test_adapter_denies_no_subject_resolvable():
    """A consent grant with no subject is not fail-open — absence is denial."""
    _req, _grant_obj, decision = await _adapter_decision(consent_basis=None)
    assert decision is not None
    assert decision.allowed is False
    assert decision.denied_reason == CONSENT_RECEIPT_MISSING
    assert decision.subject_ref is None


async def test_adapter_denies_revoked_receipt():
    await _seed_receipt(tenant_id="tenant_abc", subject_id="subject-1", state="revoked")
    _req, _grant_obj, decision = await _adapter_decision()
    assert decision is not None
    assert decision.allowed is False
    assert decision.denied_reason == CONSENT_REVOKED


async def test_adapter_denies_denied_receipt():
    await _seed_receipt(tenant_id="tenant_abc", subject_id="subject-1", state="denied")
    _req, _grant_obj, decision = await _adapter_decision()
    assert decision is not None
    assert decision.allowed is False
    assert decision.denied_reason == CONSENT_DENIED


async def test_adapter_denies_expired_receipt():
    await _seed_receipt(tenant_id="tenant_abc", subject_id="subject-1", state="expired")
    _req, _grant_obj, decision = await _adapter_decision()
    assert decision is not None
    assert decision.allowed is False
    assert decision.denied_reason == CONSENT_EXPIRED


async def test_adapter_denies_unknown_non_registry_purpose():
    """A purpose outside the consent registry cannot have a lawful basis."""
    _req = _request(purpose="model_training")
    grant = _consent_grant()
    decision = await default_consent_evaluator(_req, grant)
    assert decision is not None
    assert decision.allowed is False
    assert decision.denied_reason == CONSENT_UNKNOWN


async def test_adapter_denies_empty_purpose():
    """No purpose → purpose_not_authorized (authority fail-closed)."""
    _req = _request(purpose="")
    grant = _consent_grant()
    decision = await default_consent_evaluator(_req, grant)
    assert decision is not None
    assert decision.allowed is False
    assert decision.denied_reason == PURPOSE_NOT_AUTHORIZED


async def test_adapter_returns_none_for_non_consent_grant():
    """Non-consent grants are governed by structured rights, not this seam."""
    request = _request()
    grant = _grant(legal_basis="contract")
    assert await default_consent_evaluator(request, grant) is None


# ── resolver wiring honors allow vs deny + records consent_decision_refs ─────


async def test_wired_resolver_allows_verified_consent_export():
    """Consent verified against the server authority → export allowed with refs."""
    await _seed_receipt(tenant_id="tenant_abc", subject_id="subject-1")
    grant = _consent_grant(
        generated_output_rights=default_generated_output_rights(),
    )
    resolver = EffectiveRightsResolver(
        grant_loader=_loader(grant),
        consent_evaluator=default_consent_evaluator,
    )
    decision = await resolver.resolve(
        grant.tenant_id, grant.source_id, "artifact_1", "actor_1",
        "export", "analytics", "tenant",
    )
    assert decision.allowed is True
    assert decision.reason_codes == []
    assert len(decision.consent_decision_refs) == 1
    assert decision.consent_decision_refs[0].startswith("cpd_")

    # The recorded consent_decision_ref resolves to a persisted evidence row.
    repo = ConsentPolicyDecisionRepository()
    row = await repo.find_by_id(decision.consent_decision_refs[0])
    assert row is not None
    assert row.get("allowed") is True
    assert row.get("tenant_id") == "tenant_abc"


async def test_wired_resolver_denies_when_server_consent_missing():
    """No server receipt → the durable decision is denied (consent_denied)."""
    grant = _consent_grant(generated_output_rights=default_generated_output_rights())
    resolver = EffectiveRightsResolver(
        grant_loader=_loader(grant),
        consent_evaluator=default_consent_evaluator,
    )
    decision = await resolver.resolve(
        grant.tenant_id, grant.source_id, "artifact_1", "actor_1",
        "export", "analytics", "tenant",
    )
    assert decision.allowed is False
    assert "consent_denied" in decision.reason_codes
    assert len(decision.consent_decision_refs) == 1


async def test_wired_resolver_leaves_non_consent_grants_untouched():
    """operator_policy grants never consult the consent seam (None → skip)."""
    grant = _grant(
        legal_basis="operator_policy",
        generated_output_rights=default_generated_output_rights(),
    )
    resolver = EffectiveRightsResolver(
        grant_loader=_loader(grant),
        consent_evaluator=default_consent_evaluator,
    )
    decision = await resolver.resolve(
        grant.tenant_id, grant.source_id, "artifact_1", "actor_1",
        "export", "analytics", "tenant",
    )
    assert decision.allowed is True
    assert decision.consent_decision_refs == []


# ── bare construction stays fail-closed (no regression) ─────────────────────


async def test_bare_resolver_consent_grant_fails_closed_consent_required():
    """A bare EffectiveRightsResolver() has no evaluator → consent_required."""
    grant = _consent_grant()
    resolver = EffectiveRightsResolver(grant_loader=_loader(grant))
    decision = await resolver.resolve(
        grant.tenant_id, grant.source_id, None, "actor_1",
        "export", "analytics", "tenant",
    )
    assert decision.allowed is False
    assert "consent_required" in decision.reason_codes
    assert decision.consent_decision_refs == []


# ── configure_consent_evaluator seam ────────────────────────────────────────


async def test_configure_consent_evaluator_installs_and_clears_seam():
    """The module-level seam can install/clear an evaluator on a resolver."""
    grant = _consent_grant(generated_output_rights=default_generated_output_rights())
    resolver = EffectiveRightsResolver(grant_loader=_loader(grant))

    # Cleared → bare fail-closed consent_required.
    configure_consent_evaluator(None, resolver=resolver)
    decision = await resolver.resolve(
        grant.tenant_id, grant.source_id, None, "actor_1",
        "export", "analytics", "tenant",
    )
    assert decision.allowed is False
    assert "consent_required" in decision.reason_codes

    # Wired → server authority allow. A different artifact yields a distinct §17
    # identity so the recorded consent_required decision is not replayed.
    await _seed_receipt(tenant_id="tenant_abc", subject_id="subject-1")
    configure_consent_evaluator(default_consent_evaluator, resolver=resolver)
    decision = await resolver.resolve(
        grant.tenant_id, grant.source_id, "artifact_2", "actor_1",
        "export", "analytics", "tenant",
    )
    assert decision.allowed is True
    assert len(decision.consent_decision_refs) == 1


async def test_module_singleton_is_wired_to_server_authority(monkeypatch):
    """effective_rights_resolver consults the server authority (no unverified)."""
    grant = _consent_grant(generated_output_rights=default_generated_output_rights())
    loader = _loader(grant)
    monkeypatch.setattr(effective_rights_resolver, "_grant_loader", loader)
    decision = await effective_rights_resolver.resolve(
        grant.tenant_id, grant.source_id, "artifact_1", "actor_1",
        "export", "analytics", "tenant",
    )
    assert decision.allowed is False
    # The singleton verifies against the server authority: an absent receipt is
    # an authoritative denial (consent_denied), not a local "unverified".
    assert "consent_denied" in decision.reason_codes
    assert len(decision.consent_decision_refs) == 1
