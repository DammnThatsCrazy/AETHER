"""Focused tests for the silver Communication360 message reader."""

from __future__ import annotations

import os
import sys
import json
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from journeys.comms.contracts import MessageCategory  # noqa: E402
from journeys.communication360.reader import SilverCommsSource, to_message  # noqa: E402
from journeys.comms.repository import CommsFactsRepository  # noqa: E402


def _silver_row(**extra: object) -> dict[str, object]:
    row: dict[str, object] = {
        "tenant_id": "tenant-reader",
        "fact_id": "fact-1",
        "message_id": "message-1",
        "occurred_at": "2026-10-18T12:00:00Z",
    }
    row.update(extra)
    return row


@pytest.mark.asyncio
async def test_reply_reference_survives_durable_payload_and_exact_target_read(monkeypatch):
    repo = CommsFactsRepository()

    async def no_pool():
        return None

    monkeypatch.setattr(repo, "_pool", no_pool)
    scope = dict(provider="reply-provider", provider_account_id="account-1", external_thread_id="thread-1")
    target = _silver_row(**scope, fact_id="reply-target-fact", message_id="reply-target", external_message_id="target-external", idempotency_key="reply-target-test")
    await repo.upsert(target)
    source = SilverCommsSource(repo)
    messages, complete = await source.reply_targets("tenant-reader", "reply-provider", "account-1", "thread-1", "target-external")
    assert complete and len(messages) == 1
    assert messages[0].message_id == "reply-target"
    reply = to_message(_silver_row(payload=json.dumps({"reply_to_external_message_id": "target-external", "reply_correlation_method": "in_reply_to"})))
    assert reply.reply_to_external_message_id == "target-external"
    assert reply.reply_correlation_method == "in_reply_to"
    assert await source.reply_targets("tenant-reader", "reply-provider", "wrong-account", "thread-1", "target-external") == ([], True)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [None, {"tenant_id": "other"}, {"tenant_id": "tenant-reader", "provider": []}])
async def test_reply_target_source_does_not_hide_invalid_rows(invalid):
    class Repo:
        async def reply_targets(self, *args, **kwargs):
            return [_silver_row(provider="provider", provider_account_id="account", external_thread_id="thread", external_message_id="message"), invalid], True

    assert await SilverCommsSource(Repo()).reply_targets("tenant-reader", "provider", "account", "thread", "message") == ([], False)


def test_to_message_preserves_canonical_message_category_as_enum() -> None:
    message = to_message(_silver_row(message_category="marketing"))

    assert message.message_category is MessageCategory.MARKETING
    assert message.model_dump(mode="json")["message_category"] == "marketing"


def test_to_message_keeps_absent_message_category_unknown() -> None:
    message = to_message(_silver_row())

    assert message.message_category is None
    assert message.model_dump(mode="json")["message_category"] is None


def test_to_message_keeps_unrecognized_message_category_unknown() -> None:
    message = to_message(_silver_row(message_category="future_private_category"))

    assert message.message_category is None
    assert message.message_id == "message-1"
    assert message.fact_id == "fact-1"
    assert [ref.id for ref in message.evidence_refs] == ["fact-1"]


def test_to_message_preserves_server_recorded_historical_consent_and_binding() -> None:
    message = to_message(
        _silver_row(
            recipient_entity_id="canonical-recipient-1",
            recipient_identity_binding_id="identity-binding-1",
            consent_purpose="marketing",
            consent_subject_id="canonical-recipient-1",
            consent_snapshot_id="receipt-1",
            consent_evaluation_state="recorded",
            consent_identity_binding_id="identity-binding-1",
            consent_authority="server_consent_authority",
        )
    )

    assert message.recipient_entity_id == "canonical-recipient-1"
    assert message.recipient_identity_binding_id == "identity-binding-1"
    assert message.consent_evidence.state == "recorded"
    assert message.consent_evidence.purpose == "marketing"
    assert message.consent_evidence.receipt_id == "receipt-1"
    assert message.consent_evidence.subject_entity_id == "canonical-recipient-1"
    assert message.consent_evidence.identity_binding_id == "identity-binding-1"
    assert {ref.id for ref in message.consent_evidence.evidence_refs} == {
        "receipt-1",
        "identity-binding-1",
    }


def test_to_message_does_not_trust_source_recipient_or_consent_claims() -> None:
    message = to_message(
        _silver_row(
            recipient_entity_id="source-claimed-recipient",
            consent_snapshot_id="source-claimed-receipt",
            consent_purpose="marketing",
            consent_evaluation_state="recorded",
        )
    )

    assert message.recipient_entity_id is None
    assert message.consent_evidence.state == "unknown"
    assert message.consent_evidence.receipt_id is None
    assert message.consent_evidence.purpose == "marketing"


def test_to_message_requires_sender_identity_binding_for_connector_actor() -> None:
    message = to_message(
        _silver_row(
            source_connector_id="connector-1",
            sender_entity_id="provider-claimed-agent",
        )
    )

    assert message.sender_entity_id is None
    assert message.sender_identity_binding_id is None


def test_to_message_preserves_server_bound_sender_agent_evidence() -> None:
    message = to_message(
        _silver_row(
            source_connector_id="connector-1",
            sender_entity_id="canonical-agent-1",
            sender_identity_binding_id="agent-binding-1",
            sender_identity_evidence_source="agent_deployment_identity_bindings",
        )
    )

    assert message.sender_entity_id == "canonical-agent-1"
    assert message.sender_identity_binding_id == "agent-binding-1"
    assert message.sender_identity_evidence_ref is not None
    assert message.sender_identity_evidence_ref.source == "agent_deployment_identity_bindings"


REPLY_SCOPE = dict(
    tenant_id="tenant-lifecycle", provider="reply-provider", provider_account_id="account-1",
    external_thread_id="thread-1", external_message_id="target-external",
)
REPLY_KEYS = ("tenant-lifecycle", "reply-provider", "account-1", "thread-1", "target-external")


async def _reply_target_repo(monkeypatch, *facts):
    """Rows shaped like the projector's: ``message_id`` equals ``external_message_id``."""
    repo = CommsFactsRepository()

    async def no_pool():
        return None

    monkeypatch.setattr(repo, "_pool", no_pool)
    monkeypatch.setattr("journeys.comms.repository._local_facts", {})
    for index, fact in enumerate(facts):
        await repo.upsert(_silver_row(**{
            **REPLY_SCOPE, "fact_id": f"fact-{index}", "idempotency_key": f"key-{index}",
            "message_id": "target-external", "direction": "outbound",
            "sender_identity_binding_id": "binding-1",
            "occurred_at": f"2026-10-18T12:0{index}:00+00:00", **fact,
        }))
    return repo


@pytest.mark.asyncio
async def test_lifecycle_facts_of_one_message_resolve_to_one_earliest_reply_target(monkeypatch):
    repo = await _reply_target_repo(
        monkeypatch,
        {"communication_state": "sent"}, {"communication_state": "delivered"},
        {"communication_state": "opened"},
    )
    rows, complete = await repo.reply_targets(*REPLY_KEYS)
    assert complete is True
    assert [row["fact_id"] for row in rows] == ["fact-0"]


@pytest.mark.asyncio
@pytest.mark.parametrize("conflict", [
    {"communication_state": "replied", "direction": "inbound"},
    {"communication_state": "delivered", "sender_identity_binding_id": "other-binding"},
    {"communication_state": "delivered", "sender_entity_id": "other-entity"},
    {"communication_state": "sent"},
    {"communication_state": "delivered", "message_id": "other-message"},
])
async def test_conflicting_claims_on_one_external_id_stay_ambiguous(monkeypatch, conflict):
    repo = await _reply_target_repo(monkeypatch, {"communication_state": "sent"}, conflict)
    rows, complete = await repo.reply_targets(*REPLY_KEYS)
    assert complete is True
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_more_than_two_claims_or_facts_over_the_bound_are_incomplete(monkeypatch):
    repo = await _reply_target_repo(
        monkeypatch, {"communication_state": "sent"}, {"direction": "inbound"}, {"direction": "internal"},
    )
    rows, complete = await repo.reply_targets(*REPLY_KEYS)
    assert len(rows) == 2 and complete is False

    monkeypatch.setattr("journeys.comms.repository._REPLY_TARGET_FACT_BOUND", 1)
    repo = await _reply_target_repo(
        monkeypatch, {"communication_state": "sent"}, {"communication_state": "delivered"},
    )
    rows, complete = await repo.reply_targets(*REPLY_KEYS)
    assert [row["fact_id"] for row in rows] == ["fact-0"] and complete is False
