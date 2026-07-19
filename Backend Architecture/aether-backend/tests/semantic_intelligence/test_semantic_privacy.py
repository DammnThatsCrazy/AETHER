"""Phase B — semantic DSR deletion / consent restriction propagation.

Proves a revoked/erased subject's semantic data does not persist: erasure
hard-deletes across the semantic silver/gold tables + review queue and returns a
verification result; restriction marks observations CONSENT_RESTRICTED; and the
semantic components are part of the DSR propagation record.
"""

from __future__ import annotations

import pytest

from repositories.repos import reset_in_memory_stores
from services.dsr_propagation.models import DSR_COMPONENTS
from services.semantic_intelligence import service as service_mod
from services.semantic_intelligence.engine import get_store, set_store
from services.semantic_intelligence.models import ObservationStatus
from services.semantic_intelligence.repositories.review_queue_repo import (
    SemanticReviewQueueRepository,
)
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore

TENANT = "tenant_privacy"
SUBJECT = "prod_target"


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


_PAYLOAD = {
    "source_event_id": "e1",
    "source_type": "feedback",
    "actor_ref": "u1",
    "primary_subject_ref": SUBJECT,
    "target_type": "product",
    "content": "great product, I recommend it",
}


def test_semantic_components_registered_in_dsr():
    for component in (
        "semantic_observations",
        "sentiment_observations",
        "semantic_gold_state",
        "semantic_review_queue",
    ):
        assert component in DSR_COMPONENTS


async def test_erasure_deletes_semantic_data_and_reports():
    svc = service_mod.get_semantic_service()
    await svc.classify_and_persist(_PAYLOAD, TENANT)
    await SemanticReviewQueueRepository().enqueue(
        TENANT, "ambiguous_subject", subject_ref=SUBJECT
    )
    assert len(await get_store().list_semantic(TENANT)) == 1

    result = await svc.erase_subject(TENANT, SUBJECT)
    assert result["completed"] is True
    assert result["deleted"]["silver_semantic_observations"] == 1
    assert result["deleted"]["semantic_review_queue"] == 1
    assert result["deleted_total"] >= 2

    # Nothing remains for the subject.
    assert await get_store().list_semantic(TENANT, SUBJECT) == []
    assert await SemanticReviewQueueRepository().list_open(TENANT) == []


async def test_erasure_is_tenant_scoped():
    svc = service_mod.get_semantic_service()
    await svc.classify_and_persist(_PAYLOAD, TENANT)
    await svc.classify_and_persist(_PAYLOAD, "other_tenant")

    await svc.erase_subject(TENANT, SUBJECT)
    # The other tenant's observation is untouched.
    assert len(await get_store().list_semantic("other_tenant", SUBJECT)) == 1


async def test_restriction_marks_consent_restricted():
    svc = service_mod.get_semantic_service()
    await svc.classify_and_persist(_PAYLOAD, TENANT)

    result = await svc.restrict_subject(TENANT, SUBJECT)
    assert result["completed"] is True
    assert result["restricted"]["silver_semantic_observations"] == 1

    rows = await get_store().list_semantic(TENANT, SUBJECT)
    assert rows and rows[0].status is ObservationStatus.CONSENT_RESTRICTED
