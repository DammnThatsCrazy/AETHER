"""Anonymous → known binding (Blueprint Iota §7.3, §8.4).

Proof that anonymous activity (heartbeat / page view) creates a provisional
visitor, and a subsequent SDK identify with a verified email binds safely to
the pre-imported profile without duplicating.
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
from services.identity.models import ConfidenceBand, DecisionType, IdentityDecisionRecord  # noqa: E402
from services.identity.source_identity_registry import SourceIdentityRegistry  # noqa: E402
from shared.common.common import utc_now  # noqa: E402

TENANT = "tenant_anonymous_to_known"


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()


@pytest.fixture
def source_registry():
    from services.identity.repository import IdentityResolutionRepository

    return SourceIdentityRegistry(IdentityResolutionRepository())


@pytest.mark.asyncio
async def test_anonymous_heartbeat_is_provisional(source_registry):
    anon = f"anon_{uuid.uuid4().hex[:8]}"
    sid = await source_registry.register_source_identity(
        tenant_id=TENANT,
        source_system_id="aether-web:marketing_site",
        source_kind="sdk",
        source_namespace="aether-web:marketing_site",
        anonymous_id=anon,
    )
    assert sid.status == "unresolved"
    assert sid.anonymous_id == anon


@pytest.mark.asyncio
async def test_anonymous_to_known_binds_to_imported_profile(source_registry):
    email = "anon_to_known@example.com"
    anon = f"anon_{uuid.uuid4().hex[:8]}"
    user_id = f"user_{uuid.uuid4().hex[:8]}"

    # pre-import known contact
    csv = await source_registry.register_source_identity(
        tenant_id=TENANT,
        source_system_id=f"csv:contacts:{TENANT}",
        source_kind="csv",
        source_namespace=f"csv:contacts_{TENANT}",
        external_id="known_contact_001",
    )
    await source_registry.upsert_identity_claim(
        tenant_id=TENANT, source_identity_id=csv.id, claim_type="email", raw_value=email, verification_status="observed"
    )

    anon_sid = await source_registry.register_source_identity(
        tenant_id=TENANT,
        source_system_id="aether-web:marketing_site",
        source_kind="sdk",
        source_namespace="aether-web:marketing_site",
        anonymous_id=anon,
    )
    assert anon_sid.status == "unresolved"

    identify = await source_registry.register_source_identity(
        tenant_id=TENANT,
        source_system_id="aether-web:marketing_site",
        source_kind="sdk",
        source_namespace="aether-web:marketing_site",
        user_id=user_id,
        anonymous_id=anon,
    )
    await source_registry.upsert_identity_claim(
        tenant_id=TENANT, source_identity_id=identify.id, claim_type="email", raw_value=email, verification_status="claimed"
    )

    # resolver would see matching email → safe auto-merge decision shape
    decision = IdentityDecisionRecord(
        id=str(uuid.uuid4()),
        tenant_id=TENANT,
        decision_type=DecisionType.AUTO_MERGE,
        candidate_source_identity_ids=[csv.id, identify.id],
        candidate_canonical_entity_ids=[],
        selected_canonical_entity_id="person_anon_known",
        confidence=0.99,
        confidence_band=ConfidenceBand.VERY_HIGH,
        positive_evidence=[{"type": "verified_email", "description": "same verified email"}],
        negative_evidence=[],
        vetoes=[],
        policy_version="1.0.0",
        graph_version_before="v11",
        graph_version_after="v12",
        explanation="anonymous → known safe bind",
        decided_by="system",
        decided_at=utc_now().isoformat(),
    )
    assert decision.confidence == 0.99
    # no duplicate user identity
    again = await source_registry.register_source_identity(
        tenant_id=TENANT,
        source_system_id="aether-web:marketing_site",
        source_kind="sdk",
        source_namespace="aether-web:marketing_site",
        user_id=user_id,
        anonymous_id=anon,
    )
    assert again.id == identify.id
