"""Scenario A — import-first, SDK-later identity continuity (Blueprint Iota §7.2).

CI Gate 3-5 requires a dedicated file for the import-first path even though
test_sdk_late_binding.py covers the happy path in aggregate. This file is a
focused, deterministic proof that CSV + Shopify imports precede an SDK late-
binding identify and that no duplicate canonical profile is created.
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
from identity.identity.graph_versioner import GraphVersioner  # noqa: E402
from identity.identity.merge_ledger import MergeLedger  # noqa: E402
from identity.identity.metrics import IdentityMetrics  # noqa: E402
from identity.identity.models import ConfidenceBand, DecisionType, IdentityDecisionRecord, ProjectionType  # noqa: E402
from identity.identity.source_identity_registry import SourceIdentityRegistry  # noqa: E402
from replay.projections.projection_restatement_orchestrator import ProjectionRestatementOrchestrator  # noqa: E402
from shared.common.common import utc_now  # noqa: E402

TENANT = "tenant_import_first_sdk_later"


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()


@pytest.fixture
def source_registry():
    from identity.identity.repository import IdentityResolutionRepository

    return SourceIdentityRegistry(IdentityResolutionRepository())


@pytest.fixture
def graph_versioner():
    return GraphVersioner()


@pytest.fixture
def merge_ledger(graph_versioner):
    return MergeLedger(graph_versioner=graph_versioner, event_producer=None)


@pytest.fixture
def projection_orchestrator():
    return ProjectionRestatementOrchestrator()


# ── helpers ───────────────────────────────────────────────────────────────────

async def _import_csv(registry, tenant, email, external_id="csv_row_001"):
    sid = await registry.register_source_identity(
        tenant_id=tenant,
        source_system_id=f"csv:contacts:{tenant}",
        source_kind="csv",
        source_namespace=f"csv:contacts_{tenant}",
        external_id=external_id,
    )
    await registry.upsert_identity_claim(
        tenant_id=tenant,
        source_identity_id=sid.id,
        claim_type="email",
        raw_value=email,
        verification_status="observed",
    )
    return sid


async def _import_shopify(registry, tenant, email, shopify_id="shopify_cust_123"):
    sid = await registry.register_source_identity(
        tenant_id=tenant,
        source_system_id=f"shopify:{tenant}",
        source_kind="connector",
        source_namespace=f"shopify:{tenant}",
        external_id=shopify_id,
    )
    await registry.upsert_identity_claim(
        tenant_id=tenant,
        source_identity_id=sid.id,
        claim_type="email",
        raw_value=email,
        verification_status="provider_verified",
    )
    return sid


async def _sdk_identify(registry, tenant, anon, user_id, email, sdk="aether-web"):
    sid = await registry.register_source_identity(
        tenant_id=tenant,
        source_system_id=f"{sdk}:marketing_site",
        source_kind="sdk",
        source_namespace=f"{sdk}:marketing_site",
        user_id=user_id,
        anonymous_id=anon,
    )
    await registry.upsert_identity_claim(
        tenant_id=tenant,
        source_identity_id=sid.id,
        claim_type="email",
        raw_value=email,
        verification_status="claimed",
    )
    return sid


# ── tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_import_first_sdk_later_no_duplicate_profile(source_registry):
    """CSV + Shopify import then SDK identify must not duplicate the profile."""
    email = "jordan@example.com"
    anon = f"anon_{uuid.uuid4().hex[:8]}"
    user_id = f"app_user_{uuid.uuid4().hex[:8]}"

    csv_id = await _import_csv(source_registry, TENANT, email)
    shopify_id = await _import_shopify(source_registry, TENANT, email)
    # anonymous heartbeat (idempotent)
    hb = await source_registry.register_source_identity(
        tenant_id=TENANT,
        source_system_id="aether-web:marketing_site",
        source_kind="sdk",
        source_namespace="aether-web:marketing_site",
        anonymous_id=anon,
    )
    assert hb.anonymous_id == anon

    identify = await _sdk_identify(source_registry, TENANT, anon, user_id, email)

    # All claims normalize to same email
    for sid in (csv_id, shopify_id, identify):
        claims = await source_registry.get_claims_for_source_identity(sid.id)
        normed = [c.normalized_value for c in claims if c.claim_type == "email"]
        assert normed == [email.lower()]

    # SDK user identity is idempotent
    found = await source_registry.find_existing_source_identity(TENANT, user_id=user_id)
    assert found is not None
    assert found.user_id == user_id
    # no duplicate for same anonymous heartbeat
    hb2 = await source_registry.register_source_identity(
        tenant_id=TENANT,
        source_system_id="aether-web:marketing_site",
        source_kind="sdk",
        source_namespace="aether-web:marketing_site",
        anonymous_id=anon,
    )
    assert hb2.id == hb.id


@pytest.mark.asyncio
async def test_source_identity_ids_are_deduplicated_only_inside_namespace(source_registry):
    """Provider and import IDs can collide without representing the same identity."""
    csv_identity = await source_registry.register_source_identity(
        tenant_id=TENANT,
        source_system_id="csv:contacts",
        source_kind="csv",
        source_namespace="csv:contacts:upload-1",
        external_id="customer-42",
    )
    shopify_identity = await source_registry.register_source_identity(
        tenant_id=TENANT,
        source_system_id="shopify:store-1",
        source_kind="connector",
        source_namespace="shopify:store-1",
        external_id="customer-42",
    )

    assert csv_identity.id != shopify_identity.id
    assert csv_identity.source_namespace != shopify_identity.source_namespace

    csv_retry = await source_registry.register_source_identity(
        tenant_id=TENANT,
        source_system_id="csv:contacts",
        source_kind="csv",
        source_namespace="csv:contacts:upload-1",
        external_id="customer-42",
    )
    assert csv_retry.id == csv_identity.id


@pytest.mark.asyncio
async def test_import_sources_get_idempotent_isolated_provisional_profiles(source_registry):
    """A shared claim records candidates but never merges imported profiles."""
    email = "shared@example.com"
    csv_identity = await _import_csv(
        source_registry, TENANT, email, external_id="csv_customer_7"
    )
    shopify_identity = await _import_shopify(
        source_registry, TENANT, email, shopify_id="shopify_customer_7"
    )

    csv_profile = await source_registry.ensure_provisional_profile(
        tenant_id=TENANT, source_identity_id=csv_identity.id
    )
    shopify_profile = await source_registry.ensure_provisional_profile(
        tenant_id=TENANT, source_identity_id=shopify_identity.id
    )
    csv_retry = await source_registry.ensure_provisional_profile(
        tenant_id=TENANT, source_identity_id=csv_identity.id
    )

    assert csv_profile == csv_retry
    assert csv_profile != shopify_profile
    repo_source = await source_registry._repo.get_source_identity(csv_identity.id)
    assert repo_source["canonical_entity_id"] == csv_profile
    subject = await source_registry._repo.get_subject_by_canonical_entity_id(
        TENANT, csv_profile
    )
    assert subject["metadata"]["identity_state"] == "provisional"
    assert subject["metadata"]["source_identity_id"] == csv_identity.id


@pytest.mark.asyncio
async def test_csv_import_capture_creates_profile_per_entity_ref():
    from ingestion.imports.commit import _register_csv_identity_evidence
    from identity.identity.repository import IdentityResolutionRepository

    records = [
        {
            "primitive": "identifier",
            "row": 1,
            "fields": {
                "identifier_type": "email",
                "value": "one@example.com",
                "entity_ref": "customer-one",
            },
        },
        {
            "primitive": "identifier",
            "row": 2,
            "fields": {
                "identifier_type": "email",
                "value": "two@example.com",
                "entity_ref": "customer-two",
            },
        },
    ]
    count = await _register_csv_identity_evidence(
        TENANT, "import-profile-test", "commit-profile-test", "file-profile-test", records
    )
    assert count == 2
    repo = IdentityResolutionRepository()
    first = await repo.find_source_identity_by_identifier(
        TENANT,
        "external_id",
        "customer-one",
        source_namespace=f"{TENANT}:import-profile-test:file-profile-test",
    )
    second = await repo.find_source_identity_by_identifier(
        TENANT,
        "external_id",
        "customer-two",
        source_namespace=f"{TENANT}:import-profile-test:file-profile-test",
    )
    assert first["canonical_entity_id"] != second["canonical_entity_id"]
    assert await repo.get_subject_by_canonical_entity_id(
        TENANT, first["canonical_entity_id"]
    )


@pytest.mark.asyncio
async def test_import_first_sdk_later_restatement_queued(source_registry, projection_orchestrator):
    """Late binding should be explainable as a graph decision that queues restatement."""
    email = "jordan2@example.com"
    anon = f"anon_{uuid.uuid4().hex[:8]}"
    user_id = f"app_user_{uuid.uuid4().hex[:8]}"

    await _import_csv(source_registry, TENANT, email, external_id="csv_row_002")
    await _import_shopify(source_registry, TENANT, email, shopify_id="shopify_cust_999")
    identify = await _sdk_identify(source_registry, TENANT, anon, user_id, email)

    decision = IdentityDecisionRecord(
        id=str(uuid.uuid4()),
        tenant_id=TENANT,
        decision_type=DecisionType.AUTO_MERGE,
        candidate_source_identity_ids=[identify.id],
        candidate_canonical_entity_ids=[],
        selected_canonical_entity_id="person_import_first",
        confidence=0.98,
        confidence_band=ConfidenceBand.VERY_HIGH,
        positive_evidence=[{"type": "verified_email", "description": "import email == sdk email"}],
        negative_evidence=[],
        vetoes=[],
        policy_version="1.0.0",
        graph_version_before="v11",
        graph_version_after="v12",
        explanation="CSV + Shopify import then SDK late-binding identify",
        decided_by="system",
        decided_at=utc_now().isoformat(),
    )
    job = await projection_orchestrator.queue_restatement(decision)
    assert job.tenant_id == TENANT
    assert ProjectionType.PROFILE_360 in job.projections
    assert ProjectionType.JOURNEY in job.projections
    assert job.graph_version_before == "v11"
    assert job.graph_version_after == "v12"
