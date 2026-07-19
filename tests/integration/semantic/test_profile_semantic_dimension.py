"""Integration: the Profile360 semantic dimension surfaces durable Gold state.

Root-suite coverage (runs under `pytest tests/`, the CI core gate) for the
/v1/profile/{id}/semantic endpoint added in Phase C·3. The durable-store fixture
lives in this package's conftest.
"""

from __future__ import annotations

from unittest.mock import MagicMock

TENANT = "tenant_profile_integration"
ENTITY = "prod_profile_integration"


def _make_request(tenant_id: str = TENANT):
    req = MagicMock()
    req.state.tenant.tenant_id = tenant_id
    req.state.tenant.require_permission = MagicMock()
    return req


async def test_profile_semantic_dimension_empty_and_populated():
    from services.profile.routes import get_semantic
    from services.semantic_intelligence.engine import classify_event, get_store

    # Empty → shaped, not 404.
    empty = await get_semantic(ENTITY, _make_request())
    assert empty["data"]["computed"] is False
    assert empty["data"]["semantic"]["semantic_summary"] == "insufficient_data"

    # Populated → weighted Gold state with reducer provenance.
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

    populated = await get_semantic(ENTITY, _make_request())
    assert populated["data"]["computed"] is True
    assert populated["data"]["semantic"]["entity_ref"] == ENTITY
    assert populated["data"]["semantic"]["semantic_delta"]["reducer_version"]
