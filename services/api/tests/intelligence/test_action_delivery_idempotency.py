from __future__ import annotations

import pytest

from intelligence.intelligence import routes
from intelligence.intelligence.decision_models import ActionDispatch


@pytest.mark.asyncio
async def test_provider_idempotency_is_scoped_to_durable_dispatch(monkeypatch):
    from repositories import delivery_repos

    intents = []
    jobs = []

    class IntentRepository:
        async def insert(self, record_id, record):
            intents.append(record)
            return record

    class JobRepository:
        async def insert(self, record_id, record):
            jobs.append(record)
            return record

    monkeypatch.setattr(delivery_repos, "DeliveryIntentRepository", IntentRepository)
    monkeypatch.setattr(delivery_repos, "DeliveryJobRepository", JobRepository)
    dispatches = [
        ActionDispatch(
            dispatch_id=f"dispatch-{index}",
            tenant_id="tenant-a",
            action_id=f"action-{index}",
            decision_id=f"decision-{index}",
            recommendation_id=f"recommendation-{index}",
            target_type="webhook",
            idempotency_key="client-retry-key",
            created_at="2026-10-30T12:00:00Z",
        )
        for index in (1, 2)
    ]

    for dispatch in dispatches:
        await routes._enqueue_action_delivery(dispatch, None)

    assert [intent["idempotency_key"] for intent in intents] == [
        "dispatch-1",
        "dispatch-2",
    ]
    assert [job["idempotency_key"] for job in jobs] == ["dispatch-1", "dispatch-2"]
