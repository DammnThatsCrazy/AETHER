"""Focused tests for the silver Communication360 message reader."""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from journeys.comms.contracts import MessageCategory  # noqa: E402
from journeys.communication360.reader import to_message  # noqa: E402


def _silver_row(**extra: object) -> dict[str, object]:
    row: dict[str, object] = {
        "tenant_id": "tenant-reader",
        "fact_id": "fact-1",
        "message_id": "message-1",
        "occurred_at": "2026-10-18T12:00:00Z",
    }
    row.update(extra)
    return row


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
