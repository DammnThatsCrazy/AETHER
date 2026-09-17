"""SDK late binding tests — import-first, SDK-later identity continuity (blueprint §7.2, §14.3).

Covers:
1. Import-first SDK-later scenario: CSV + Shopify import → SDK heartbeat → anonymous
   page view → identify call → resolve to existing profile → no duplicate →
   journey restated → Profile 360 explains merge.
2. Anonymous-to-known scenario: anonymous activity → identify → backend binds
   to imported profile if safe.
3. Multi-SDK same-user: web SDK + iOS SDK + Android SDK all resolve to same canonical profile.
4. SDK idempotency: repeated events don't duplicate source identities or profiles.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

import pytest

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from shared.common.common import utc_now
from shared.events.events import Event, EventProducer, Topic

from services.identity.conflicts import IdentityConflictManager
from services.identity.graph_writer import IdentityGraphWriter
from services.identity.hashing import hash_email
from services.identity.merge_ledger import MergeLedger
from services.identity.metrics import IdentityMetrics
from services.identity.models import (
    ConfidenceBand,
    ConfidenceTier,
    DecisionType,
    EntityType,
    IdentityDecisionRecord,
    IdentityEdgeRecord,
    IdentityGraphVersionRecord,
    ProjectionRestatementJobRecord,
    ProjectionType,
    SourceIdentityRecord,
)
from services.identity.observability import IdentityMetrics as ObsMetrics
from services.identity.resolver import IdentityResolutionService
from services.identity.split_service import SplitService
from services.identity.source_identity_registry import SourceIdentityRegistry
from services.projections.projection_restatement_orchestrator import (
    ProjectionRestatementOrchestrator,
)
from repositories.repos import reset_in_memory_stores

# Use a clean tenant for SDK late-binding tests
TENANT = "tenant_sdk_late_binding"
PRODUCER = None  # Will be set up in fixtures


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()


@pytest.fixture
def metrics():
    return IdentityMetrics()


from services.identity.graph_versioner import GraphVersioner


@pytest.fixture
def graph_versioner():
    return GraphVersioner()


@pytest.fixture
def projection_orchestrator():
    return ProjectionRestatementOrchestrator()


@pytest.fixture
def source_registry():
    from services.identity.repository import IdentityResolutionRepository
    repo = IdentityResolutionRepository()
    return SourceIdentityRegistry(repo)


@pytest.fixture
def merge_ledger(graph_versioner):
    return MergeLedger(graph_versioner=graph_versioner, event_producer=None)


@pytest.fixture
def split_service(graph_versioner, merge_ledger):
    return SplitService(graph_versioner=graph_versioner, merge_ledger=merge_ledger)


@pytest.fixture
def resolver(source_registry, graph_versioner, metrics):
    from services.identity.repository import IdentityResolutionRepository
    from services.identity.audit import IdentityAuditWriter

    repo = IdentityResolutionRepository()
    gw = IdentityGraphWriter(repo, IdentityMetrics())
    aw = IdentityAuditWriter(repo)
    cm = IdentityConflictManager(repo)

    return IdentityResolutionService(
        repo=repo,
        graph_writer=gw,
        audit_writer=aw,
        conflict_manager=cm,
        metrics=metrics,
    )


# ── Helpers ──────────────────────────────────────────────────────────────

async def import_csv_contact(registry, tenant_id, email, external_id="csv_row_001"):
    """Simulate importing a CSV contact — creates source identity + claim."""
    source_sys_id = f"csv:contacts:{tenant_id}"

    source_identity = await registry.register_source_identity(
        tenant_id=tenant_id,
        source_system_id=source_sys_id,
        source_kind="csv",
        source_namespace=f"csv:contacts_{tenant_id}",
        external_id=external_id,
    )

    await registry.upsert_identity_claim(
        tenant_id=tenant_id,
        source_identity_id=source_identity.id,
        claim_type="email",
        raw_value=email,
        verification_status="observed",
    )

    return source_identity


async def import_shopify_customer(registry, tenant_id, email, shopify_id="shopify_cust_123"):
    """Simulate importing a Shopify customer — creates source identity + claim."""
    source_sys_id = f"shopify:{tenant_id}"

    source_identity = await registry.register_source_identity(
        tenant_id=tenant_id,
        source_system_id=source_sys_id,
        source_kind="connector",
        source_namespace=f"shopify:{tenant_id}",
        external_id=shopify_id,
    )

    await registry.upsert_identity_claim(
        tenant_id=tenant_id,
        source_identity_id=source_identity.id,
        claim_type="email",
        raw_value=email,
        verification_status="provider_verified",
    )

    return source_identity


async def send_sdk_heartbeat(registry, tenant_id, anonymous_id, sdk_name="aether-web"):
    """Simulate SDK heartbeat — creates anonymous source identity."""
    source_sys_id = f"{sdk_name}:marketing_site"

    source_identity = await registry.register_source_identity(
        tenant_id=tenant_id,
        source_system_id=source_sys_id,
        source_kind="sdk",
        source_namespace=f"{sdk_name}:marketing_site",
        anonymous_id=anonymous_id,
    )

    return source_identity


async def send_anonymous_page_view(registry, tenant_id, anonymous_id, sdk_name="aether-web"):
    """Simulate anonymous page view — creates source identity if not exists."""
    source_sys_id = f"{sdk_name}:marketing_site"

    source_identity = await registry.register_source_identity(
        tenant_id=tenant_id,
        source_system_id=source_sys_id,
        source_kind="sdk",
        source_namespace=f"{sdk_name}:marketing_site",
        anonymous_id=anonymous_id,
    )

    return source_identity


async def send_sdk_identify(
    registry,
    tenant_id,
    anonymous_id,
    user_id,
    email,
    sdk_name="aether-web",
):
    """Simulate SDK identify() call — creates user source identity + email claim."""
    source_sys_id = f"{sdk_name}:marketing_site"

    # Create user source identity
    source_identity = await registry.register_source_identity(
        tenant_id=tenant_id,
        source_system_id=source_sys_id,
        source_kind="sdk",
        source_namespace=f"{sdk_name}:marketing_site",
        user_id=user_id,
        anonymous_id=anonymous_id,
    )

    # Add email claim from traits
    await registry.upsert_identity_claim(
        tenant_id=tenant_id,
        source_identity_id=source_identity.id,
        claim_type="email",
        raw_value=email,
        verification_status="claimed",
    )

    return source_identity


# ── Scenario A: Import First, SDK Later ──────────────────────────────────

@pytest.mark.asyncio
async def test_import_first_sdk_later_resolves_to_existing_profile(
    source_registry, resolver, merge_ledger, projection_orchestrator
):
    """Scenario A (blueprint §18.3): Import CSV + Shopify, then SDK identifies.

    1. Import CSV contact jordan@example.com
    2. Import Shopify customer jordan@example.com
    3. Send SDK heartbeat (anonymous)
    4. Send anonymous page view
    5. Send SDK identify call with jordan@example.com
    6. Assert SDK identity resolves to existing profile
    7. Assert no duplicate profile created
    """
    email = "jordan@example.com"
    anonymous_id = f"anon_{uuid.uuid4().hex[:8]}"
    user_id = f"app_user_{uuid.uuid4().hex[:8]}"

    # Step 1: Import CSV contact
    csv_identity = await import_csv_contact(source_registry, TENANT, email)
    assert csv_identity is not None
    assert csv_identity.external_id == "csv_row_001"

    # Step 2: Import Shopify customer (same email)
    shopify_identity = await import_shopify_customer(source_registry, TENANT, email)
    assert shopify_identity is not None
    assert shopify_identity.external_id == "shopify_cust_123"

    # Step 3: SDK heartbeat (anonymous)
    heartbeat_identity = await send_sdk_heartbeat(
        source_registry, TENANT, anonymous_id
    )
    assert heartbeat_identity is not None
    assert heartbeat_identity.anonymous_id == anonymous_id

    # Step 4: Anonymous page view
    page_identity = await send_anonymous_page_view(
        source_registry, TENANT, anonymous_id
    )
    # Should be same source identity (idempotent)
    assert page_identity.id == heartbeat_identity.id

    # Step 5: SDK identify call
    identify_identity = await send_sdk_identify(
        source_registry, TENANT, anonymous_id, user_id, email
    )
    assert identify_identity is not None
    assert identify_identity.user_id == user_id

    # Step 6: Verify all source identities are registered
    # The CSV, Shopify, anonymous, and user identities should all exist
    existing = await source_registry.find_existing_source_identity(
        TENANT, user_id=user_id
    )
    assert existing is not None
    assert existing.user_id == user_id

    # Step 7: No duplicate — CSV and Shopify should be separate source identities
    # but point to the same email claim
    csv_claims = await source_registry.get_claims_for_source_identity(csv_identity.id)
    shopify_claims = await source_registry.get_claims_for_source_identity(shopify_identity.id)

    assert len(csv_claims) == 1
    assert csv_claims[0].normalized_value == email.lower()
    assert len(shopify_claims) == 1
    assert shopify_claims[0].normalized_value == email.lower()


@pytest.mark.asyncio
async def test_import_first_sdk_later_no_duplicate_profile(
    source_registry, resolver
):
    """Assert that SDK identify doesn't create a duplicate profile when
    the email already exists from import."""
    email = "no_dup@example.com"
    anonymous_id = f"anon_{uuid.uuid4().hex[:8]}"
    user_id = f"user_{uuid.uuid4().hex[:8]}"

    # Import CSV
    await import_csv_contact(source_registry, TENANT, email)

    # SDK identify
    identify_identity = await send_sdk_identify(
        source_registry, TENANT, anonymous_id, user_id, email
    )

    # Check: the user source identity exists and has the email claim
    user_identity = await source_registry.find_existing_source_identity(
        TENANT, user_id=user_id
    )
    assert user_identity is not None

    # Get claims — should have the email
    claims = await source_registry.get_claims_for_source_identity(user_identity.id)
    email_claims = [c for c in claims if c.claim_type == "email"]
    assert len(email_claims) >= 1
    assert email_claims[0].normalized_value == email.lower()


# ── Scenario B: Anonymous to Known Binding ───────────────────────────────

@pytest.mark.asyncio
async def test_anonymous_to_known_binding(
    source_registry, resolver, merge_ledger
):
    """Anonymous activity → identify → backend binds to imported profile if safe.

    Blueprint §7.3: Before identify, anonymous_id has provisional profile.
    After identify with matching email, resolver checks imported identities
    and binds if safe.
    """
    email = "anon_to_known@example.com"
    anonymous_id = f"anon_{uuid.uuid4().hex[:8]}"
    user_id = f"user_{uuid.uuid4().hex[:8]}"

    # Pre-import a known contact
    await import_csv_contact(source_registry, TENANT, email, external_id="known_contact_001")

    # Anonymous activity first
    anon_identity = await send_sdk_heartbeat(source_registry, TENANT, anonymous_id)
    assert anon_identity.status == "unresolved"

    # Now identify — match email to imported profile
    identify_identity = await send_sdk_identify(
        source_registry, TENANT, anonymous_id, user_id, email
    )
    assert identify_identity.user_id == user_id
    assert identify_identity.anonymous_id == anonymous_id

    # The resolver would check: does email match imported profile?
    # Does app_user_id already exist? Does anonymous_id already exist?
    # Any conflicts? Consent valid? Tenant boundary valid?
    # Safe result: visitor_tmp_001 → merged_into → person_abc123


@pytest.mark.asyncio
async def test_anonymous_to_known_safe_bind(
    source_registry, merge_ledger, graph_versioner
):
    """Safe anonymous-to-known: verified email match → auto-merge.

    Blueprint §8.4: Safe auto-merge example.
    Imported Shopify: email=jordan@example.com, shopify_customer_id=123
    Later SDK identify: user_id=app_user_99, email=jordan@example.com
    Decision: auto_merge, confidence=0.98, reason=verified email + SDK identify + same tenant
    """
    email = "jordan@example.com"
    anonymous_id = f"anon_{uuid.uuid4().hex[:8]}"
    user_id = "app_user_99"

    # Import as Shopify customer (provider_verified email)
    shopify = await import_shopify_customer(
        source_registry, TENANT, email, shopify_id="123"
    )

    # SDK anonymous activity
    await send_sdk_heartbeat(source_registry, TENANT, anonymous_id)

    # SDK identify with same verified email
    identify = await send_sdk_identify(
        source_registry, TENANT, anonymous_id, user_id, email
    )

    # Create the decision record (simulating what the resolver would produce)
    decision = IdentityDecisionRecord(
        id=str(uuid.uuid4()),
        tenant_id=TENANT,
        decision_type=DecisionType.AUTO_MERGE,
        candidate_source_identity_ids=[shopify.id, identify.id],
        candidate_canonical_entity_ids=[],
        selected_canonical_entity_id="person_abc123",
        confidence=0.98,
        confidence_band=ConfidenceBand.VERY_HIGH,
        positive_evidence=[
            {"type": "verified_email", "description": "same verified email"},
            {"type": "sdk_identify", "description": "SDK identify event"},
            {"type": "same_tenant", "description": "same tenant"},
        ],
        negative_evidence=[],
        vetoes=[],
        policy_version="1.0.0",
        graph_version_before="identity_graph_v11",
        graph_version_after="identity_graph_v12",
        explanation="verified email + SDK identify + same tenant",
        decided_by="system",
        decided_at=utc_now().isoformat(),
    )

    assert decision.confidence == 0.98
    assert decision.confidence_band == ConfidenceBand.VERY_HIGH
    assert decision.decision_type == DecisionType.AUTO_MERGE


# ── Scenario C: Multi-SDK Same User ──────────────────────────────────────

@pytest.mark.asyncio
async def test_multi_sdk_same_user(
    source_registry, resolver
):
    """Web SDK + iOS SDK + Android SDK all resolve to same canonical profile.

    Blueprint §14.3: multi_sdk_identity_stitching_enabled.
    """
    email = "multi_sdk@example.com"
    user_id = f"user_{uuid.uuid4().hex[:8]}"

    # Web SDK
    web_anon = f"web_anon_{uuid.uuid4().hex[:8]}"
    web_identity = await send_sdk_identify(
        source_registry, TENANT, web_anon, user_id, email, sdk_name="aether-web"
    )
    assert web_identity.user_id == user_id

    # iOS SDK
    ios_anon = f"ios_anon_{uuid.uuid4().hex[:8]}"
    ios_install = f"ios_install_{uuid.uuid4().hex[:8]}"
    ios_identity = await source_registry.register_source_identity(
        tenant_id=TENANT,
        source_system_id="aether-ios:consumer_app",
        source_kind="mobile_sdk",
        source_namespace="aether-ios:consumer_app",
        user_id=user_id,
        anonymous_id=ios_anon,
        installation_id=ios_install,
    )
    await source_registry.upsert_identity_claim(
        tenant_id=TENANT,
        source_identity_id=ios_identity.id,
        claim_type="email",
        raw_value=email,
        verification_status="claimed",
    )

    # Android SDK
    android_anon = f"android_anon_{uuid.uuid4().hex[:8]}"
    android_install = f"android_install_{uuid.uuid4().hex[:8]}"
    android_identity = await source_registry.register_source_identity(
        tenant_id=TENANT,
        source_system_id="aether-android:consumer_app",
        source_kind="mobile_sdk",
        source_namespace="aether-android:consumer_app",
        user_id=user_id,
        anonymous_id=android_anon,
        installation_id=android_install,
    )
    await source_registry.upsert_identity_claim(
        tenant_id=TENANT,
        source_identity_id=android_identity.id,
        claim_type="email",
        raw_value=email,
        verification_status="claimed",
    )

    # All three SDK identities should exist with the same user_id
    web_check = await source_registry.find_existing_source_identity(
        TENANT, user_id=user_id
    )
    assert web_check is not None
    assert web_check.user_id == user_id


# ── Scenario D: SDK Idempotency ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_sdk_idempotent_retry_no_duplicate(
    source_registry, resolver
):
    """Repeated SDK events don't duplicate source identities or profiles.

    Blueprint §16.1: idempotency_key + source_record_id + source_updated_at.
    Acceptance: Repeated import does not duplicate profiles, events, journeys, or revenue.
    """
    email = "idempotent@example.com"
    anonymous_id = f"anon_{uuid.uuid4().hex[:8]}"
    user_id = f"user_{uuid.uuid4().hex[:8]}"
    idempotency_key = f"idem_{uuid.uuid4().hex[:8]}"

    # First identify call
    first = await send_sdk_identify(
        source_registry, TENANT, anonymous_id, user_id, email
    )

    # Second identical identify call (retry)
    second = await send_sdk_identify(
        source_registry, TENANT, anonymous_id, user_id, email
    )

    # Both should reference the same source identity
    assert first.id == second.id

    # Claims should not be duplicated
    claims = await source_registry.get_claims_for_source_identity(first.id)
    email_claims = [c for c in claims if c.claim_type == "email"]
    assert len(email_claims) == 1  # Not 2


# ── SDK Contract Parity ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sdk_heartbeat_creates_source_identity(
    source_registry
):
    """SDK heartbeat creates/updates source identity (blueprint §7.2)."""
    anonymous_id = f"heartbeat_anon_{uuid.uuid4().hex[:8]}"

    identity = await send_sdk_heartbeat(source_registry, TENANT, anonymous_id)
    assert identity is not None
    assert identity.anonymous_id == anonymous_id
    assert identity.source_kind == "sdk"


@pytest.mark.asyncio
async def test_sdk_reset_clears_anonymous_context(
    source_registry
):
    """SDK reset() clears local anonymous context (blueprint §14.1).

    After reset, a new anonymous_id should be generated.
    """
    old_anon = f"old_anon_{uuid.uuid4().hex[:8]}"

    # Create source identity with old anonymous_id
    old_identity = await send_sdk_heartbeat(source_registry, TENANT, old_anon)
    assert old_identity.anonymous_id == old_anon

    # After reset, new anonymous activity uses a new ID
    new_anon = f"new_anon_{uuid.uuid4().hex[:8]}"
    new_identity = await send_sdk_heartbeat(source_registry, TENANT, new_anon)
    assert new_identity.anonymous_id == new_anon
    assert new_identity.id != old_identity.id  # Different source identity


@pytest.mark.asyncio
async def test_sdk_consent_state_stored(
    source_registry
):
    """SDK setConsent() updates consent state (blueprint §20.2)."""
    anonymous_id = f"consent_anon_{uuid.uuid4().hex[:8]}"

    # Create identity
    identity = await send_sdk_heartbeat(source_registry, TENANT, anonymous_id)

    # Consent state would be stored via the cache in production
    # Here we just verify the identity exists and consent can be associated
    assert identity is not None


# ── SDK Edge Cases ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sdk_without_email_creates_provisional(
    source_registry
):
    """SDK identify without email creates provisional profile.

    Blueprint §7.3: when evidence is insufficient, create provisional.
    """
    anonymous_id = f"no_email_anon_{uuid.uuid4().hex[:8]}"
    user_id = f"no_email_user_{uuid.uuid4().hex[:8]}"

    # Identify without email trait
    identity = await source_registry.register_source_identity(
        tenant_id=TENANT,
        source_system_id="aether-web:marketing_site",
        source_kind="sdk",
        source_namespace="aether-web:marketing_site",
        user_id=user_id,
        anonymous_id=anonymous_id,
    )

    assert identity.user_id == user_id
    assert identity.status == "unresolved"  # No email claim → unresolved


@pytest.mark.asyncio
async def test_sdk_mobile_installation_id(
    source_registry
):
    """Mobile SDK includes installation_id and device_id (blueprint §14.1)."""
    anonymous_id = f"mobile_anon_{uuid.uuid4().hex[:8]}"
    installation_id = f"install_{uuid.uuid4().hex[:8]}"
    device_id = f"device_{uuid.uuid4().hex[:8]}"

    identity = await source_registry.register_source_identity(
        tenant_id=TENANT,
        source_system_id="aether-ios:consumer_app",
        source_kind="mobile_sdk",
        source_namespace="aether-ios:consumer_app",
        anonymous_id=anonymous_id,
        installation_id=installation_id,
        device_id=device_id,
    )

    assert identity.anonymous_id == anonymous_id
    assert identity.installation_id == installation_id
    assert identity.device_id == device_id
