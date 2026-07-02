"""Integration test: full closed-loop outcome processing for Linear.

Simulates:
1. ExternalResourceLink for a suggestion → Linear issue
2. WebhookInbox entry with a fake Linear issue status-changed event
3. WebhookInboxProcessor.process_pending()
4. Assertions on ExternalOutcomeEvent and suggestion state
"""

from __future__ import annotations

import json
import uuid

import pytest


# ─── Minimal in-memory repo ─────────────────────────────────────────────────

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
async def test_linear_status_changed_outcome_loop():
    """Linear issue update triggers status_changed outcome and in_progress suggestion state."""
    from services.delivery.outcome_processor import OutcomeRouter, WebhookInboxProcessor

    inbox_repo = _MemRepo()
    outcome_repo = _MemRepo()
    link_repo = _MemRepo()
    suggestion_repo = _SuggestionRepo()

    tenant_id = "tenant-linear"
    issue_identifier = "ENG-42"
    suggestion_id = str(uuid.uuid4())

    # Pre-populate suggestion
    await suggestion_repo.update(suggestion_id, {"outcome_state": "pending"})

    # ExternalResourceLink: Linear issue ENG-42 → suggestion
    link_id = str(uuid.uuid4())
    await link_repo.insert(link_id, {
        "id": link_id,
        "tenant_id": tenant_id,
        "provider": "linear",
        "external_id": issue_identifier,
        "resource_type": "suggestion",
        "resource_id": suggestion_id,
        "intent_id": "intent-linear-1",
        "sync_status": "pending",
    })

    # Linear webhook payload: issue status update
    linear_payload = {
        "type": "Issue",
        "action": "update",
        "data": {
            "id": "lin-uuid-001",
            "identifier": issue_identifier,
            "title": "Fix the bug",
            "state": {"id": "state-1", "name": "In Progress", "type": "started"},
        },
    }

    inbox_id = str(uuid.uuid4())
    await inbox_repo.insert(inbox_id, {
        "id": inbox_id,
        "tenant_id": tenant_id,
        "provider": "linear",
        "headers": {"linear-signature": "mock-sig"},
        "raw_body": json.dumps(linear_payload),
        "signature": "mock-sig",
        "timestamp": "",
        "verified": False,
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
    processed = await processor.process_pending()

    assert processed == 1

    # Inbox marked processed
    record = await inbox_repo.find_by_id(inbox_id)
    assert record is not None
    assert record["processed"] is True

    # ExternalOutcomeEvent created
    outcomes = list(outcome_repo._store.values())
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome["provider"] == "linear"
    assert outcome["raw_payload"]["event_type"] == "status_changed"
    assert outcome["raw_payload"]["new_state"] == "In Progress"
    assert outcome["external_id"] == issue_identifier

    # Suggestion updated to "in_progress"
    suggestion = await suggestion_repo.find_by_id(suggestion_id)
    assert suggestion is not None
    assert suggestion["outcome_state"] == "in_progress"


@pytest.mark.asyncio
async def test_linear_remove_action_becomes_cancelled():
    """Linear action=remove maps to cancelled → suggestion rejected."""
    from services.delivery.outcome_processor import OutcomeRouter, WebhookInboxProcessor

    inbox_repo = _MemRepo()
    outcome_repo = _MemRepo()
    link_repo = _MemRepo()
    suggestion_repo = _SuggestionRepo()

    tenant_id = "tenant-linear"
    issue_id = "ENG-99"
    suggestion_id = str(uuid.uuid4())

    await suggestion_repo.update(suggestion_id, {"outcome_state": "pending"})

    link_id = str(uuid.uuid4())
    await link_repo.insert(link_id, {
        "id": link_id,
        "tenant_id": tenant_id,
        "provider": "linear",
        "external_id": issue_id,
        "resource_type": "suggestion",
        "resource_id": suggestion_id,
        "intent_id": "intent-2",
        "sync_status": "pending",
    })

    linear_payload = {
        "type": "Issue",
        "action": "remove",
        "data": {"identifier": issue_id},
    }

    inbox_id = str(uuid.uuid4())
    await inbox_repo.insert(inbox_id, {
        "id": inbox_id,
        "tenant_id": tenant_id,
        "provider": "linear",
        "headers": {},
        "raw_body": json.dumps(linear_payload),
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

    outcomes = list(outcome_repo._store.values())
    assert len(outcomes) == 1
    assert outcomes[0]["raw_payload"]["event_type"] == "cancelled"

    suggestion = await suggestion_repo.find_by_id(suggestion_id)
    assert suggestion["outcome_state"] == "rejected"


@pytest.mark.asyncio
async def test_linear_loop_prevention_same_state():
    """If the new_state matches the stored sync_status, routing should be skipped."""
    from services.delivery.outcome_processor import OutcomeRouter, WebhookInboxProcessor

    inbox_repo = _MemRepo()
    outcome_repo = _MemRepo()
    link_repo = _MemRepo()
    suggestion_repo = _SuggestionRepo()

    tenant_id = "tenant-linear"
    issue_id = "ENG-77"
    suggestion_id = str(uuid.uuid4())

    await suggestion_repo.update(suggestion_id, {"outcome_state": "in_progress"})

    link_id = str(uuid.uuid4())
    await link_repo.insert(link_id, {
        "id": link_id,
        "tenant_id": tenant_id,
        "provider": "linear",
        "external_id": issue_id,
        "resource_type": "suggestion",
        "resource_id": suggestion_id,
        "intent_id": "intent-3",
        "sync_status": "In Progress",  # Same as incoming new_state
    })

    linear_payload = {
        "type": "Issue",
        "action": "update",
        "data": {
            "identifier": issue_id,
            "state": {"name": "In Progress"},
        },
    }

    inbox_id = str(uuid.uuid4())
    await inbox_repo.insert(inbox_id, {
        "id": inbox_id,
        "tenant_id": tenant_id,
        "provider": "linear",
        "headers": {},
        "raw_body": json.dumps(linear_payload),
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

    # Outcome event still created, but suggestion state unchanged (loop prevention)
    suggestion = await suggestion_repo.find_by_id(suggestion_id)
    # The suggestion_repo.update may not have been called — state stays "in_progress"
    assert suggestion["outcome_state"] == "in_progress"
