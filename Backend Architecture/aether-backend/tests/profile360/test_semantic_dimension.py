"""Phase C·3 — Profile360 semantic dimension.

The /v1/profile/{id}/semantic endpoint surfaces the entity's durable weighted
semantic state (Gold reducer), satisfying "Profile360 contains semantic state".
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pytest

from repositories.repos import reset_in_memory_stores
from services.profile.routes import get_semantic
from services.semantic_intelligence import service as service_mod
from services.semantic_intelligence.engine import classify_event, get_store, set_store
from services.semantic_intelligence.service import SemanticIntelligenceService
from services.semantic_intelligence.store import DurableSemanticSentimentStore

TENANT = "tenant-profile-sem"
ENTITY = "prod_profile_1"


def make_request(tenant_id: str = TENANT):
    req = MagicMock()
    req.state.tenant.tenant_id = tenant_id
    req.state.tenant.require_permission = MagicMock()
    return req


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


async def test_semantic_dimension_empty_is_shaped_not_404():
    resp = await get_semantic(ENTITY, make_request())
    data = resp["data"]
    assert data["user_id"] == ENTITY
    assert data["computed"] is False
    assert data["semantic"]["semantic_summary"] == "insufficient_data"
    assert data["provenance"]["sources"] == ["semantic_gold_state"]


async def test_semantic_dimension_returns_weighted_state():
    obs, _ = classify_event(
        {
            "source_event_id": "e1",
            "source_type": "feedback",
            "actor_ref": "u1",
            "primary_subject_ref": ENTITY,
            "content": "great product, I recommend it",
        },
        TENANT,
    )
    await get_store().put_semantic(obs)

    resp = await get_semantic(ENTITY, make_request())
    data = resp["data"]
    assert data["computed"] is True
    assert data["semantic"]["entity_ref"] == ENTITY
    assert data["semantic"]["semantic_delta"]["reducer_version"]
    assert data["semantic"]["confidence"] > 0


async def test_semantic_dimension_is_tenant_scoped():
    obs, _ = classify_event(
        {"source_event_id": "e1", "source_type": "feedback", "actor_ref": "u1",
         "primary_subject_ref": ENTITY, "content": "great, recommend"},
        TENANT,
    )
    await get_store().put_semantic(obs)
    # A different tenant sees no semantic state for the same entity id.
    resp = await get_semantic(ENTITY, make_request("other-tenant"))
    assert resp["data"]["computed"] is False
