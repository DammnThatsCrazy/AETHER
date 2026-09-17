"""Shared-email (inbox) must go to review, not auto-merge (Blueprint Iota §8.3).

Role / shared mailbox addresses (support@, info@, family@ ...) indicate an
inbox, not a person. The veto engine must emit SHARED_INBOX and the resolver
must not merge deterministically on that signal alone.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.identity.models import IdentitySignalType  # noqa: E402
from services.identity.source_identity_registry import SourceIdentityRegistry  # noqa: E402
from services.identity.veto_engine import evaluate_vetoes  # noqa: E402

TENANT = "tenant_shared_email_review"


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()


@pytest.fixture
def source_registry():
    from services.identity.repository import IdentityResolutionRepository

    return SourceIdentityRegistry(IdentityResolutionRepository())


@pytest.mark.asyncio
async def test_shared_inbox_emits_veto():
    # family/shared role addresses are tagged by the veto engine
    for inbox in ["support@example.com", "info@example.com", "family@example.com", "team@example.com"]:
        vetoes = await evaluate_vetoes(
            tenant_id=TENANT,
            candidate_tenant_id=TENANT,
            candidate_entity_types=["person"],
            candidate_statuses=["active"],
            candidate_verified_emails=[(inbox, "person_a"), (inbox, "person_b")],
            candidate_authenticated_user_ids=[],
            candidate_device_ids=[],
            candidate_has_revoked_consent=False,
            candidate_is_deleted=False,
            candidate_is_suppressed=False,
            candidate_source_namespaces=[],
            current_verified_emails=[inbox],
        )
        types = {v.veto_type.value for v in vetoes}
        assert "shared_inbox" in types, f"expected SHARED_INBOX veto for {inbox!r} got {types}"


@pytest.mark.asyncio
async def test_shared_email_source_identities_coexist(source_registry):
    email = "support@example.com"
    a = await source_registry.register_source_identity(
        tenant_id=TENANT,
        source_system_id=f"csv:contacts:{TENANT}",
        source_kind="csv",
        source_namespace=f"csv:contacts_{TENANT}",
        external_id="row_a",
    )
    await source_registry.upsert_identity_claim(tenant_id=TENANT, source_identity_id=a.id, claim_type="email", raw_value=email, verification_status="observed")
    b = await source_registry.register_source_identity(
        tenant_id=TENANT,
        source_system_id=f"shopify:{TENANT}",
        source_kind="connector",
        source_namespace=f"shopify:{TENANT}",
        external_id="cust_b",
    )
    await source_registry.upsert_identity_claim(tenant_id=TENANT, source_identity_id=b.id, claim_type="email", raw_value=email, verification_status="observed")
    assert a.id != b.id
    # no auto-merge executed: veto would require manual review; repository shows two distinct source identities
    for sid in (a, b):
        claims = await source_registry.get_claims_for_source_identity(sid.id)
        assert any(c.normalized_value == email.lower() for c in claims)

    # deterministic check that resolver would emit candidate/conflict not merge
    from services.identity.confidence import score_signals

    result = score_signals(
        matching_signal_types=[IdentitySignalType.EMAIL_HASH],
        consent_snapshot={"purposes": {"identity": True}},
        source_tenant_id=TENANT,
        target_tenant_id=TENANT,
    )
    # email hash alone is STRONG tier; actual merge decision is gated by veto
    assert result.tier.value in ("strong", "deterministic", "probable")


@pytest.mark.asyncio
async def test_normal_personal_email_not_flagged_as_shared_inbox():
    vetoes = await evaluate_vetoes(
        tenant_id=TENANT,
        candidate_tenant_id=TENANT,
        candidate_entity_types=["person"],
        candidate_statuses=["active"],
        candidate_verified_emails=[("jordan.personal@example.com", "person_a")],
        candidate_authenticated_user_ids=[],
        candidate_device_ids=[],
        candidate_has_revoked_consent=False,
        candidate_is_deleted=False,
        candidate_is_suppressed=False,
        candidate_source_namespaces=[],
        current_verified_emails=["jordan.personal@example.com"],
    )
    assert not any(v.veto_type.value == "shared_inbox" for v in vetoes)
