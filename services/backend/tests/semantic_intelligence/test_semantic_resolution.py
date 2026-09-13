"""Phase A2 follow-up — subject/actor resolution with cross-tenant safety.

Proves the resolver walks its precedence order, rejects cross-tenant references
FAIL-CLOSED (never classifying against another tenant's entity), and routes
ambiguous / cross-tenant cases to the durable review queue.
"""

from __future__ import annotations

import pytest

from repositories.repos import EntityRepository, reset_in_memory_stores
from services.semantic_intelligence import service as service_mod
from services.semantic_intelligence.consumer import SemanticEventConsumer
from services.semantic_intelligence.engine import get_store, set_store
from services.semantic_intelligence.models import ObservationStatus, SubjectType
from services.semantic_intelligence.resolution import (
    SemanticActorResolver,
    SemanticSubjectResolver,
)
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore
from shared.events.events import Event, Topic

TENANT = "tenant_res"


@pytest.fixture(autouse=True)
def _isolate():
    reset_in_memory_stores()
    original = get_store()
    set_store(DurableSemanticSentimentStore())
    service_mod.set_semantic_service(SemanticIntelligenceService())
    yield
    set_store(original)
    service_mod.set_semantic_service(SemanticIntelligenceService())
    reset_in_memory_stores()


# ── subject resolver ─────────────────────────────────────────────────────────


async def test_explicit_ref_high_confidence():
    r = await SemanticSubjectResolver().resolve({"primary_subject_ref": "prod_1"}, TENANT)
    assert r.ref == "prod_1" and r.confidence >= 0.9 and not r.needs_review


async def test_property_extraction():
    r = await SemanticSubjectResolver().resolve(
        {"properties": {"product_id": "prod_9"}}, TENANT
    )
    assert r.ref == "prod_9" and r.type is SubjectType.PRODUCT and r.method == "property:product_id"


async def test_unresolved_enqueues_review():
    r = await SemanticSubjectResolver().resolve({"event_type": "page"}, TENANT)
    assert r.ref == "unknown_subject" and r.needs_review and r.review_queue == "ambiguous_subject"


async def test_cross_tenant_reference_rejected():
    # Seed an entity owned by ANOTHER tenant, then reference it from TENANT.
    await EntityRepository().create_entity("ent_foreign", "tenant_other", "human")
    r = await SemanticSubjectResolver().resolve({"primary_subject_ref": "ent_foreign"}, TENANT)
    assert r.ref == "unknown_subject"
    assert r.needs_review and r.review_queue == "cross_tenant_reference"


async def test_same_tenant_reference_allowed():
    await EntityRepository().create_entity("ent_ours", TENANT, "human")
    r = await SemanticSubjectResolver().resolve({"primary_subject_ref": "ent_ours"}, TENANT)
    assert r.ref == "ent_ours" and not r.needs_review


# ── actor resolver ───────────────────────────────────────────────────────────


async def test_actor_precedence():
    assert (await SemanticActorResolver().resolve({"user_id": "u1"}, TENANT)).ref == "u1"
    assert (await SemanticActorResolver().resolve({"anonymous_id": "a1"}, TENANT)).ref == "a1"
    agent = await SemanticActorResolver().resolve({"agent_id": "ag1"}, TENANT)
    assert agent.ref == "ag1" and agent.type is SubjectType.AGENT


# ── worker integration ───────────────────────────────────────────────────────


async def test_worker_quarantines_cross_tenant_subject_and_enqueues_review():
    await EntityRepository().create_entity("ent_foreign2", "tenant_other", "organization")
    ev = Event(
        topic=Topic.SDK_EVENTS_VALIDATED,
        tenant_id=TENANT,
        payload={
            "event_id": "e_xt",
            "event_type": "feedback_submitted",
            "user_id": "u1",
            "primary_subject_ref": "ent_foreign2",
            "properties": {"content": "love it"},
        },
    )
    await SemanticEventConsumer().on_validated_event(ev)

    rows = await get_store().list_semantic(TENANT)
    assert len(rows) == 1
    assert rows[0].status is ObservationStatus.QUARANTINED

    review = await service_mod.get_semantic_service().review_queue(TENANT)
    assert review["count"] == 1
    assert review["items"][0]["queue_type"] == "cross_tenant_reference"


async def test_worker_sets_resolution_confidence():
    ev = Event(
        topic=Topic.SDK_EVENTS_VALIDATED,
        tenant_id=TENANT,
        payload={
            "event_id": "e_conf",
            "event_type": "feedback_submitted",
            "user_id": "u1",
            "properties": {"content": "great", "product_id": "prod_5"},
        },
    )
    await SemanticEventConsumer().on_validated_event(ev)
    rows = await get_store().list_semantic(TENANT)
    assert rows[0].primary_subject_ref == "prod_5"
    assert rows[0].subject_resolution_confidence == pytest.approx(0.6)
