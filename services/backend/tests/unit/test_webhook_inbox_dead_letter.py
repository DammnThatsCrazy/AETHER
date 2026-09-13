"""WebhookInboxProcessor: a persist/routing failure must NEVER mark a record
processed (Zero Silent Failure, program sec7).

A hand-off failure is RETRYABLE: the claim is released (``processing=False``,
``processed=False``) so the next tick re-queues the record instead of silently
dropping the delivery. Only terminal dispositions (signature unverified,
nothing to normalise) are marked processed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid

import pytest

from services.delivery.outcome_processor import WebhookInboxProcessor

_WEBHOOK_SECRET = "test-aether-callback-secret"


def _signed_webhook_record(body: str, sig_secret: str | None = None) -> dict:
    """Headers + secret that pass the processor's real HMAC verification."""
    secret = sig_secret or _WEBHOOK_SECRET
    ts = str(int(time.time()))
    sig = "sha256=" + hmac.new(
        secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256
    ).hexdigest()
    return {
        "signing_secret": secret,
        "headers": {"x-aether-signature": sig, "x-aether-timestamp": ts},
    }


def _callback_payload() -> dict:
    return {
        "event_data": {
            "event_type": "delivered",
            "delivery_id": str(uuid.uuid4()),
            "recipient": "ops@example.com",
        }
    }


class _MemInboxRepo:
    def __init__(self):
        self._store: dict[str, dict] = {}

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
        results = []
        for record in self._store.values():
            if record.get("processed") or record.get("processing"):
                continue
            record["processing"] = True
            results.append(dict(record))
            if len(results) >= limit:
                break
        return results

    def get(self, record_id: str) -> dict | None:
        return self._store.get(record_id)


class _MemOutcomeRepo:
    def __init__(self, fail: bool = False):
        self._fail = fail
        self._store: dict[str, dict] = {}

    async def insert(self, record_id: str, data: dict) -> None:
        if self._fail:
            raise RuntimeError("outcome persist down")
        self._store[record_id] = data

    async def update(self, record_id: str, data: dict) -> None:
        if record_id in self._store:
            self._store[record_id].update(data)


class _RaisingRouter:
    async def route(self, outcome) -> None:
        raise RuntimeError("downstream router unavailable")


class _OkRouter:
    async def route(self, outcome) -> None:
        return None


async def _seed_processed_webhook(inbox_repo: _MemInboxRepo) -> str:
    record_id = str(uuid.uuid4())
    body = json.dumps(_callback_payload())
    await inbox_repo.insert(record_id, {
        "id": record_id,
        "tenant_id": "t-dl",
        "provider": "webhook",
        **_signed_webhook_record(body),
        "raw_body": body,
    })
    return record_id


class TestRoutingFailureIsRetryable:
    async def test_router_failure_releases_claim_never_marks_processed(self):
        inbox_repo = _MemInboxRepo()
        outcome_repo = _MemOutcomeRepo()
        record_id = await _seed_processed_webhook(inbox_repo)

        processor = WebhookInboxProcessor(
            inbox_repo=inbox_repo,
            outcome_repo=outcome_repo,
            link_repo=_MemInboxRepo(),
            router=_RaisingRouter(),
        )
        count = await processor.process_pending()

        assert count == 1
        record = inbox_repo.get(record_id)
        # Hand-off failed → claim released, NOT marked processed → next tick
        # re-queues the record. The delivery is not silently dropped.
        assert record["processed"] is False
        assert record["processing"] is False
        assert "processing_error" not in record

    async def test_router_failure_is_retried_on_next_tick(self):
        """The released record is claimed again on the next tick."""
        inbox_repo = _MemInboxRepo()
        outcome_repo = _MemOutcomeRepo()
        record_id = await _seed_processed_webhook(inbox_repo)

        processor = WebhookInboxProcessor(
            inbox_repo=inbox_repo,
            outcome_repo=outcome_repo,
            link_repo=_MemInboxRepo(),
            router=_RaisingRouter(),
        )
        await processor.process_pending()
        # Second tick still sees it as pending (claim was released).
        claims = await inbox_repo.claim_pending()
        assert [c["id"] for c in claims] == [record_id]

    async def test_outcome_persist_failure_never_marks_processed(self):
        inbox_repo = _MemInboxRepo()
        outcome_repo = _MemOutcomeRepo(fail=True)
        record_id = await _seed_processed_webhook(inbox_repo)

        processor = WebhookInboxProcessor(
            inbox_repo=inbox_repo,
            outcome_repo=outcome_repo,
            link_repo=_MemInboxRepo(),
            router=_OkRouter(),
        )
        count = await processor.process_pending()

        assert count == 1
        record = inbox_repo.get(record_id)
        assert record["processed"] is False
        assert record["processing"] is False


class TestSuccessAndTerminalDispositions:
    async def test_full_success_marks_processed(self):
        inbox_repo = _MemInboxRepo()
        outcome_repo = _MemOutcomeRepo()
        record_id = await _seed_processed_webhook(inbox_repo)

        processor = WebhookInboxProcessor(
            inbox_repo=inbox_repo,
            outcome_repo=outcome_repo,
            link_repo=_MemInboxRepo(),
            router=_OkRouter(),
        )
        count = await processor.process_pending()

        assert count == 1
        record = inbox_repo.get(record_id)
        assert record["processed"] is True
        # The outcome was persisted and handed off.
        assert len(outcome_repo._store) == 1

    async def test_signature_unverified_is_terminal_dead_letter(self):
        """A forged/unsigned record is dead-lettered with an error — retrying
        cannot change the signature result, so it is marked processed."""
        inbox_repo = _MemInboxRepo()
        outcome_repo = _MemOutcomeRepo()
        record_id = str(uuid.uuid4())
        body = json.dumps(_callback_payload())
        await inbox_repo.insert(record_id, {
            "id": record_id,
            "tenant_id": "t-dl",
            "provider": "webhook",
            # Headers signed with the CORRECT secret, but the record stores a
            # WRONG signing_secret → HMAC fails → unverified.
            **_signed_webhook_record(body, sig_secret=_WEBHOOK_SECRET),
            "signing_secret": "wrong-secret",
            "raw_body": body,
        })

        processor = WebhookInboxProcessor(
            inbox_repo=inbox_repo,
            outcome_repo=outcome_repo,
            link_repo=_MemInboxRepo(),
            router=_OkRouter(),
        )
        count = await processor.process_pending()

        assert count == 1
        record = inbox_repo.get(record_id)
        assert record["processed"] is True
        assert record.get("processing_error") == "signature_unverified"
        # Never routed a forged payload.
        assert outcome_repo._store == {}
