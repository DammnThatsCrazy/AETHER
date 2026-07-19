"""Phase B·3 — actor-scoped erasure + consent-revocation propagation.

A DSR subject is also an actor: erasing / restricting them must reach the
observations they authored (actor_ref), not only those about them (subject_ref).
And a CONSENT_UPDATED revocation must automatically restrict their semantic data.
"""

from __future__ import annotations

import pytest

from repositories.repos import reset_in_memory_stores
from services.semantic_intelligence import service as service_mod
from services.semantic_intelligence.consumer import SemanticEventConsumer
from services.semantic_intelligence.engine import get_store, set_store
from services.semantic_intelligence.models import ObservationStatus
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore
from shared.events.events import Event, Topic

TENANT = "tenant_consent_prop"
USER = "user_actor_1"


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


# The user is the ACTOR; the subject is a product.
_PAYLOAD = {
    "source_event_id": "e1",
    "source_type": "feedback",
    "actor_ref": USER,
    "primary_subject_ref": "prod_1",
    "target_type": "product",
    "content": "great product, I recommend it",
}


async def test_erasure_reaches_actor_authored_observations():
    svc = service_mod.get_semantic_service()
    await svc.classify_and_persist(_PAYLOAD, TENANT)
    # Subject is prod_1, so a subject-only erase would miss it — actor erase catches it.
    result = await svc.erase_subject(TENANT, USER)
    assert result["deleted_total"] >= 1
    assert await get_store().list_semantic(TENANT) == []


async def test_restriction_reaches_actor_authored_observations():
    svc = service_mod.get_semantic_service()
    await svc.classify_and_persist(_PAYLOAD, TENANT)
    await svc.restrict_subject(TENANT, USER)
    rows = await get_store().list_semantic(TENANT)
    assert rows and rows[0].status is ObservationStatus.CONSENT_RESTRICTED


async def test_consent_revocation_event_restricts_subject():
    svc = service_mod.get_semantic_service()
    await svc.classify_and_persist(_PAYLOAD, TENANT)

    consumer = SemanticEventConsumer()
    await consumer.on_consent_updated(
        Event(
            topic=Topic.CONSENT_UPDATED,
            tenant_id=TENANT,
            payload={"user_id": USER, "granted": False, "purposes": ["analytics"]},
        )
    )
    rows = await get_store().list_semantic(TENANT)
    assert rows and rows[0].status is ObservationStatus.CONSENT_RESTRICTED


async def test_consent_grant_event_does_not_restrict():
    svc = service_mod.get_semantic_service()
    await svc.classify_and_persist(_PAYLOAD, TENANT)

    consumer = SemanticEventConsumer()
    await consumer.on_consent_updated(
        Event(
            topic=Topic.CONSENT_UPDATED,
            tenant_id=TENANT,
            payload={"user_id": USER, "granted": True, "purposes": ["analytics"]},
        )
    )
    rows = await get_store().list_semantic(TENANT)
    assert rows and rows[0].status is ObservationStatus.CLASSIFIED
