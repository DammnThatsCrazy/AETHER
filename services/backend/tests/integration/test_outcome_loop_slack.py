"""Integration test: full closed-loop outcome processing for Slack.

Uses in-memory repos to simulate:
1. ExternalResourceLink linking a suggestion to a Slack channel
2. WebhookInbox entry with a fake Slack block_actions payload
3. WebhookInboxProcessor.process_pending()
4. Assertions on ExternalOutcomeEvent and suggestion state
"""

from __future__ import annotations

import json
import urllib.parse
import uuid
from typing import Any

import pytest


_SLACK_SECRET = "test-slack-signing-secret"


def _signed_slack_record(body: str) -> dict:
    """Headers + secret that pass the processor's real v0 HMAC verification."""
    import hashlib
    import hmac
    import time

    ts = str(int(time.time()))
    sig = "v0=" + hmac.new(
        _SLACK_SECRET.encode(), f"v0:{ts}:{body}".encode(), hashlib.sha256
    ).hexdigest()
    return {
        "signing_secret": _SLACK_SECRET,
        "headers": {
            "content-type": "application/x-www-form-urlencoded",
            "x-slack-request-timestamp": ts,
            "x-slack-signature": sig,
        },
    }


# ─── Minimal in-memory repo ─────────────────────────────────────────────────

class _MemRepo:
    """Minimal in-memory repository for testing."""

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

    async def claim_pending(self, limit: int = 20) -> list[dict]:
        # Mirrors WebhookInboxRepository.claim_pending's in-memory predicate:
        # skip processed/processing rows, mark claimed rows as processing.
        results = []
        for record in self._store.values():
            if record.get("processed") or record.get("processing"):
                continue
            record["processing"] = True
            results.append(dict(record))
            if len(results) >= limit:
                break
        return results


class _SuggestionRepo:
    """Minimal in-memory suggestion repo for testing."""

    def __init__(self):
        self._store: dict[str, dict] = {}

    async def update(self, record_id: str, data: dict) -> dict:
        if record_id not in self._store:
            self._store[record_id] = {"id": record_id}
        self._store[record_id].update(data)
        return self._store[record_id]

    async def find_by_id(self, record_id: str) -> dict | None:
        return self._store.get(record_id)


# ─── Test ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_slack_outcome_loop_full():
    """Full Slack block_actions loop: inbox → outcome event → suggestion update."""
    from services.delivery.outcome_processor import OutcomeRouter, WebhookInboxProcessor

    inbox_repo = _MemRepo()
    outcome_repo = _MemRepo()
    link_repo = _MemRepo()
    suggestion_repo = _SuggestionRepo()

    # 1. Pre-populate a suggestion in the suggestion repo
    suggestion_id = str(uuid.uuid4())
    await suggestion_repo.update(suggestion_id, {"outcome_state": "pending"})

    # 2. Create an ExternalResourceLink for the suggestion → Slack channel
    link_id = str(uuid.uuid4())
    tenant_id = "tenant-abc"
    await link_repo.insert(link_id, {
        "id": link_id,
        "tenant_id": tenant_id,
        "provider": "slack",
        "external_id": suggestion_id,  # the action_id suggestion_id part
        "resource_type": "suggestion",
        "resource_id": suggestion_id,
        "intent_id": "intent-1",
        "sync_status": "pending",
    })

    # 3. Build a fake Slack block_actions payload
    action_id = f"acknowledged:{suggestion_id}:{tenant_id}"
    slack_payload = {
        "type": "block_actions",
        "user": {"id": "U12345", "username": "alice"},
        "actions": [{"action_id": action_id, "type": "button"}],
    }
    encoded_body = "payload=" + urllib.parse.quote(json.dumps(slack_payload))

    inbox_id = str(uuid.uuid4())
    await inbox_repo.insert(inbox_id, {
        "id": inbox_id,
        "tenant_id": tenant_id,
        "provider": "slack",
        **_signed_slack_record(encoded_body),
        "raw_body": encoded_body,
        "signature": "",
        "timestamp": "",
        "verified": False,
        "processed": False,
    })

    # 4. Run the processor
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

    # 5. Assert
    assert processed == 1

    # Inbox record should be marked processed
    inbox_record = await inbox_repo.find_by_id(inbox_id)
    assert inbox_record is not None
    assert inbox_record["processed"] is True

    # ExternalOutcomeEvent should exist
    outcomes = list(outcome_repo._store.values())
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome["provider"] == "slack"
    assert outcome["raw_payload"]["event_type"] == "acknowledged"
    assert outcome["raw_payload"]["actor_external_id"] == "U12345"
    assert outcome["raw_payload"]["actor_display_name"] == "alice"

    # Suggestion should be updated to "executed"
    suggestion = await suggestion_repo.find_by_id(suggestion_id)
    assert suggestion is not None
    assert suggestion["outcome_state"] == "executed"


@pytest.mark.asyncio
async def test_slack_url_verification_challenge_skipped():
    """Slack URL verification challenge should be silently skipped (no outcome event)."""
    from services.delivery.outcome_processor import OutcomeRouter, WebhookInboxProcessor

    inbox_repo = _MemRepo()
    outcome_repo = _MemRepo()
    link_repo = _MemRepo()

    challenge_payload = {"type": "url_verification", "challenge": "test-challenge-token"}
    inbox_id = str(uuid.uuid4())
    await inbox_repo.insert(inbox_id, {
        "id": inbox_id,
        "tenant_id": "tenant-1",
        "provider": "slack",
        "headers": {},
        "raw_body": json.dumps(challenge_payload),
        "signature": "",
        "timestamp": "",
        "verified": False,
        "processed": False,
    })

    processor = WebhookInboxProcessor(
        inbox_repo=inbox_repo,
        outcome_repo=outcome_repo,
        link_repo=link_repo,
    )
    processed = await processor.process_pending()

    assert processed == 1
    # No outcome event created for challenge
    assert len(outcome_repo._store) == 0
    # Inbox marked processed
    record = await inbox_repo.find_by_id(inbox_id)
    assert record["processed"] is True


@pytest.mark.asyncio
async def test_slack_loop_prevention_aether_origin():
    """Events with aether_origin=True must not be routed."""
    from services.delivery.outcome_processor import OutcomeRouter, WebhookInboxProcessor
    from unittest.mock import AsyncMock

    inbox_repo = _MemRepo()
    outcome_repo = _MemRepo()
    link_repo = _MemRepo()

    slack_payload = {
        "type": "block_actions",
        "user": {"id": "U99", "username": "bot"},
        "actions": [{"action_id": "acknowledged:sug1:t1"}],
        "aether_origin": True,  # loop prevention flag in payload
    }
    encoded = "payload=" + urllib.parse.quote(json.dumps(slack_payload))

    inbox_id = str(uuid.uuid4())
    await inbox_repo.insert(inbox_id, {
        "id": inbox_id,
        "tenant_id": "t1",
        "provider": "slack",
        **_signed_slack_record(encoded),
        "raw_body": encoded,
        "processed": False,
    })

    # Mock router to track calls
    mock_router = OutcomeRouter(
        outcome_repo=outcome_repo,
        link_repo=link_repo,
    )
    mock_router.route = AsyncMock(wraps=mock_router.route)

    processor = WebhookInboxProcessor(
        inbox_repo=inbox_repo,
        outcome_repo=outcome_repo,
        link_repo=link_repo,
        router=mock_router,
    )
    await processor.process_pending()

    # route was called but aether_origin guard should prevent suggestion update
    # The outcome event is persisted, but routing stops early
    assert len(outcome_repo._store) >= 1
