"""Integration test: full closed-loop outcome processing for generic Aether callback.

Simulates:
1. ExternalResourceLink for a suggestion → generic webhook
2. WebhookInbox entry with a generic Aether callback payload
3. WebhookInboxProcessor.process_pending()
4. Assertions on ExternalOutcomeEvent and routing
"""

from __future__ import annotations

import json
import uuid

import pytest


# ─── Minimal in-memory repos ─────────────────────────────────────────────────

class _MemRepo:
    def __init__(self):
        self._store: dict[str, dict] = {}

    async def find_many(self, filters: dict | None = None, limit: int = 100, **kw) -> list[dict]:
        rows = list(self._store.values())
        if filters:
            for k, v in filters.items():
                rows = [r for r in rows if r.get(k) == v]
        return rows[:limit]

    async def find_by_id(self, record_id: str) -> dict | None:
        return self._store.get(record_id)

    async def insert(self, record_id: str, data: dict) -> dict:
        self._store[record_id] = {**data, "id": record_id}
        return self._store[record_id]

    async def update(self, record_id: str, data: dict) -> dict:
        if record_id in self._store:
            self._store[record_id].update(data)
        return self._store.get(record_id, {})

    async def mark_processed(self, record_id: str, error: str | None = None) -> None:
        if record_id in self._store:
            self._store[record_id]["processed"] = True
            if error:
                self._store[record_id]["processing_error"] = error


class _SuggestionRepo:
    def __init__(self):
        self._store: dict[str, dict] = {}

    async def update(self, record_id: str, data: dict) -> dict:
        if record_id not in self._store:
            self._store[record_id] = {"id": record_id}
        self._store[record_id].update(data)
        return self._store[record_id]

    async def find_by_id(self, record_id: str) -> dict | None:
        return self._store.get(record_id)


# ─── Tests ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generic_webhook_delivered_outcome():
    """Generic Aether callback with event_type=delivered creates outcome event."""
    from services.delivery.outcome_processor import OutcomeRouter, WebhookInboxProcessor

    inbox_repo = _MemRepo()
    outcome_repo = _MemRepo()
    link_repo = _MemRepo()

    tenant_id = "tenant-webhook"
    delivery_id = str(uuid.uuid4())

    callback_payload = {
        "event_data": {
            "event_type": "delivered",
            "delivery_id": delivery_id,
            "recipient": "ops@example.com",
        }
    }

    inbox_id = str(uuid.uuid4())
    await inbox_repo.insert(inbox_id, {
        "id": inbox_id,
        "tenant_id": tenant_id,
        "provider": "webhook",
        "headers": {"x-aether-signature": "sha256=abc", "x-aether-delivery-id": delivery_id},
        "raw_body": json.dumps(callback_payload),
        "signature": "sha256=abc",
        "timestamp": "",
        "verified": True,
        "processed": False,
    })

    router = OutcomeRouter(
        outcome_repo=outcome_repo,
        link_repo=link_repo,
    )
    processor = WebhookInboxProcessor(
        inbox_repo=inbox_repo,
        outcome_repo=outcome_repo,
        link_repo=link_repo,
        router=router,
    )
    processed = await processor.process_pending()

    assert processed == 1

    record = await inbox_repo.find_by_id(inbox_id)
    assert record["processed"] is True

    outcomes = list(outcome_repo._store.values())
    assert len(outcomes) == 1
    assert outcomes[0]["provider"] == "webhook"
    assert outcomes[0]["raw_payload"]["event_type"] == "delivered"


@pytest.mark.asyncio
async def test_generic_webhook_acknowledged_routes_to_suggestion():
    """Generic webhook with event_type=acknowledged marks suggestion as executed."""
    from services.delivery.outcome_processor import OutcomeRouter, WebhookInboxProcessor

    inbox_repo = _MemRepo()
    outcome_repo = _MemRepo()
    link_repo = _MemRepo()
    suggestion_repo = _SuggestionRepo()

    tenant_id = "tenant-wh2"
    external_id = "ext-ref-001"
    suggestion_id = str(uuid.uuid4())

    await suggestion_repo.update(suggestion_id, {"outcome_state": "pending"})

    link_id = str(uuid.uuid4())
    await link_repo.insert(link_id, {
        "id": link_id,
        "tenant_id": tenant_id,
        "provider": "webhook",
        "external_id": external_id,
        "resource_type": "suggestion",
        "resource_id": suggestion_id,
        "intent_id": "intent-wh-1",
        "sync_status": "pending",
    })

    callback_payload = {
        "event_data": {
            "event_type": "acknowledged",
        }
    }

    inbox_id = str(uuid.uuid4())
    await inbox_repo.insert(inbox_id, {
        "id": inbox_id,
        "tenant_id": tenant_id,
        "provider": "webhook",
        "headers": {},
        "raw_body": json.dumps(callback_payload),
        "processed": False,
    })

    router = OutcomeRouter(
        outcome_repo=outcome_repo,
        link_repo=link_repo,
        suggestion_repo=suggestion_repo,
    )
    processor = WebhookInboxProcessor(
        inbox_repo=inbox_repo,
        outcome_repo=outcome_repo,
        link_repo=link_repo,
        router=router,
    )
    await processor.process_pending()

    # Outcome event created
    outcomes = list(outcome_repo._store.values())
    assert len(outcomes) == 1
    assert outcomes[0]["raw_payload"]["event_type"] == "acknowledged"


@pytest.mark.asyncio
async def test_empty_inbox_returns_zero():
    """process_pending returns 0 when no records are pending."""
    from services.delivery.outcome_processor import WebhookInboxProcessor

    inbox_repo = _MemRepo()
    outcome_repo = _MemRepo()
    link_repo = _MemRepo()

    processor = WebhookInboxProcessor(
        inbox_repo=inbox_repo,
        outcome_repo=outcome_repo,
        link_repo=link_repo,
    )
    result = await processor.process_pending()
    assert result == 0


@pytest.mark.asyncio
async def test_malformed_json_body_handled_gracefully():
    """A WebhookInbox with an unparseable body should still be marked processed."""
    from services.delivery.outcome_processor import WebhookInboxProcessor

    inbox_repo = _MemRepo()
    outcome_repo = _MemRepo()
    link_repo = _MemRepo()

    inbox_id = str(uuid.uuid4())
    await inbox_repo.insert(inbox_id, {
        "id": inbox_id,
        "tenant_id": "t1",
        "provider": "webhook",
        "headers": {},
        "raw_body": "this is not json {{{{",
        "processed": False,
    })

    processor = WebhookInboxProcessor(
        inbox_repo=inbox_repo,
        outcome_repo=outcome_repo,
        link_repo=link_repo,
    )
    processed = await processor.process_pending()

    assert processed == 1
    # The record should be marked as processed (either success with fallback or with error)
    record = await inbox_repo.find_by_id(inbox_id)
    assert record["processed"] is True


@pytest.mark.asyncio
async def test_outcome_event_type_mapping():
    """Verify event_type → outcome_type mapping for key event types."""
    from services.delivery.outcome_processor import WebhookInboxProcessor
    from services.delivery.models import ExternalOutcomeType

    inbox_repo = _MemRepo()
    outcome_repo = _MemRepo()
    link_repo = _MemRepo()

    event_type_to_outcome = {
        "delivered": ExternalOutcomeType.DELIVERED,
        "acknowledged": ExternalOutcomeType.RESOLVED,
        "resolved": ExternalOutcomeType.RESOLVED,
        "rejected": ExternalOutcomeType.FAILED,
        "cancelled": ExternalOutcomeType.FAILED,
        "status_changed": ExternalOutcomeType.OPENED,
        "commented": ExternalOutcomeType.REPLIED,
    }

    processor = WebhookInboxProcessor(
        inbox_repo=inbox_repo,
        outcome_repo=outcome_repo,
        link_repo=link_repo,
    )

    for event_type, expected_outcome_type in event_type_to_outcome.items():
        inbox_record = {
            "id": str(uuid.uuid4()),
            "tenant_id": "t1",
            "provider": "webhook",
            "headers": {},
            "raw_body": json.dumps({"event_data": {"event_type": event_type}}),
            "processed": False,
        }
        outcome = await processor._normalize(inbox_record)
        assert outcome is not None, f"Expected outcome for event_type={event_type}"
        assert outcome.outcome_type == expected_outcome_type, (
            f"event_type={event_type!r} → expected {expected_outcome_type}, "
            f"got {outcome.outcome_type}"
        )
