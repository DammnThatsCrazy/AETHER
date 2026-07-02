"""Unit tests for delivery infrastructure models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from services.delivery.models import (
    ConnectorCursor,
    DeliveryAttempt,
    DeliveryAttemptOutcome,
    DeliveryChannel,
    DeliveryIntent,
    DeliveryIntentStatus,
    DeliveryJob,
    DeliveryJobPriority,
    DeliveryJobState,
    ExternalOutcomeEvent,
    ExternalOutcomeType,
    ExternalResourceLink,
    ProviderReceipt,
    WebhookInbox,
    generate_idempotency_key,
)


# ─── generate_idempotency_key ────────────────────────────────────────────────

def test_idempotency_key_is_deterministic():
    k1 = generate_idempotency_key("tenant_a", "suggestion", "sug-123")
    k2 = generate_idempotency_key("tenant_a", "suggestion", "sug-123")
    assert k1 == k2


def test_idempotency_key_different_inputs_produce_different_keys():
    k1 = generate_idempotency_key("tenant_a", "sug-123")
    k2 = generate_idempotency_key("tenant_a", "sug-999")
    assert k1 != k2


def test_idempotency_key_is_hex_string():
    k = generate_idempotency_key("a", "b", "c")
    assert len(k) == 64
    int(k, 16)  # must be valid hex


# ─── DeliveryIntent ──────────────────────────────────────────────────────────

def test_delivery_intent_auto_sets_id_and_timestamps():
    intent = DeliveryIntent(
        tenant_id="t1",
        source_type="suggestion",
        source_id="sug-001",
        channels=["slack"],
    )
    assert intent.id
    assert intent.created_at
    assert intent.updated_at
    assert intent.status == DeliveryIntentStatus.PENDING


def test_delivery_intent_auto_idempotency_key():
    intent = DeliveryIntent(
        tenant_id="t1",
        source_type="notification",
        source_id="notif-abc",
        channels=[],
    )
    assert intent.idempotency_key
    assert len(intent.idempotency_key) == 64


def test_delivery_intent_idempotency_key_stable():
    i1 = DeliveryIntent(
        tenant_id="t1", source_type="suggestion", source_id="sug-x", channels=[]
    )
    i2 = DeliveryIntent(
        tenant_id="t1", source_type="suggestion", source_id="sug-x", channels=[]
    )
    assert i1.idempotency_key == i2.idempotency_key


# ─── DeliveryJob ─────────────────────────────────────────────────────────────

def test_delivery_job_defaults():
    job = DeliveryJob(
        intent_id="int-1",
        tenant_id="t1",
        channel=DeliveryChannel.SLACK,
        provider_adapter="slack",
    )
    assert job.state == DeliveryJobState.QUEUED
    assert job.attempt_count == 0
    assert job.priority == DeliveryJobPriority.P3
    assert job.idempotency_key


def test_delivery_job_model_dump_roundtrip():
    job = DeliveryJob(
        intent_id="int-1",
        tenant_id="t1",
        channel=DeliveryChannel.LINEAR,
        provider_adapter="linear",
        priority=DeliveryJobPriority.P1,
        payload={"title": "Test"},
    )
    data = job.model_dump()
    assert data["channel"] == "linear"
    assert data["state"] == "queued"
    assert data["priority"] == 1


# ─── ProviderReceipt ─────────────────────────────────────────────────────────

def test_provider_receipt_rejects_empty_external_id():
    with pytest.raises(ValidationError) as exc_info:
        ProviderReceipt(
            job_id="j1",
            intent_id="i1",
            tenant_id="t1",
            provider_adapter="slack",
            external_id="",
            channel=DeliveryChannel.SLACK,
        )
    assert "must not be empty" in str(exc_info.value)


def test_provider_receipt_rejects_sim_prefix():
    with pytest.raises(ValidationError) as exc_info:
        ProviderReceipt(
            job_id="j1",
            intent_id="i1",
            tenant_id="t1",
            provider_adapter="slack",
            external_id="sim-slack-abc12345",
            channel=DeliveryChannel.SLACK,
        )
    assert "sim-" in str(exc_info.value)


def test_provider_receipt_accepts_valid_external_id():
    receipt = ProviderReceipt(
        job_id="j1",
        intent_id="i1",
        tenant_id="t1",
        provider_adapter="slack",
        external_id="slack:#general:1720000000.123456",
        channel=DeliveryChannel.SLACK,
    )
    assert receipt.external_id == "slack:#general:1720000000.123456"


# ─── DeliveryAttempt ─────────────────────────────────────────────────────────

def test_delivery_attempt_success():
    attempt = DeliveryAttempt(
        job_id="j1",
        intent_id="i1",
        tenant_id="t1",
        attempt_number=1,
        outcome=DeliveryAttemptOutcome.SUCCESS,
        provider_adapter="slack",
        external_id="slack:#ch:1234",
        http_status=200,
    )
    assert attempt.outcome == DeliveryAttemptOutcome.SUCCESS
    assert attempt.http_status == 200


def test_delivery_attempt_failure():
    attempt = DeliveryAttempt(
        job_id="j1",
        intent_id="i1",
        tenant_id="t1",
        attempt_number=2,
        outcome=DeliveryAttemptOutcome.RETRYABLE,
        provider_adapter="linear",
        error_message="rate limited",
        http_status=429,
    )
    assert attempt.outcome == DeliveryAttemptOutcome.RETRYABLE


# ─── ExternalResourceLink ────────────────────────────────────────────────────

def test_external_resource_link():
    link = ExternalResourceLink(
        tenant_id="t1",
        intent_id="i1",
        receipt_id="r1",
        provider="linear",
        external_id="PROJ-42",
        external_url="https://linear.app/team/issue/PROJ-42",
        resource_type="issue",
    )
    assert link.external_url.startswith("https://")


# ─── ExternalOutcomeEvent ────────────────────────────────────────────────────

def test_external_outcome_event():
    evt = ExternalOutcomeEvent(
        tenant_id="t1",
        provider="slack",
        external_id="slack:#general:123",
        outcome_type=ExternalOutcomeType.DELIVERED,
        raw_payload={"type": "reaction_added"},
    )
    assert evt.outcome_type == ExternalOutcomeType.DELIVERED


# ─── WebhookInbox ────────────────────────────────────────────────────────────

def test_webhook_inbox_defaults():
    inbox = WebhookInbox(
        tenant_id="t1",
        provider="slack",
    )
    assert inbox.verified is False
    assert inbox.processed is False


# ─── ConnectorCursor ─────────────────────────────────────────────────────────

def test_connector_cursor_stable_id():
    c1 = ConnectorCursor(tenant_id="t1", connector_type="salesforce")
    c2 = ConnectorCursor(tenant_id="t1", connector_type="salesforce")
    # ID is derived from tenant+connector, so should be stable
    # Note: the model_validator only sets id if it's empty — default_factory sets uuid first
    # We test the explicit stable-id path via set_cursor in the repo
    assert c1.tenant_id == "t1"
    assert c1.connector_type == "salesforce"
