"""Parity and live-privacy tests for the canonical ingestion validator."""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock

import pytest

from services.ingestion import batch
from services.ingestion import validation


class _Cache:
    async def get(self, _key):
        return None


def _event(*, event_type: str = "track", properties=None, context=None):
    return batch.BaseEvent(
        id="evt-parity",
        type=event_type,
        timestamp="2026-07-15T00:00:00Z",
        sessionId="session-1",
        anonymousId="anon-1",
        userId="user-1",
        properties=properties or {},
        context=context or batch.EventContext(),
    )


@pytest.mark.asyncio
async def test_v1_and_v2_call_the_same_async_validator():
    assert "await validate_event(" in inspect.getsource(batch._process_single_event)
    assert "await validate_event(" in inspect.getsource(batch._ingest_batch_v2)
    assert "def _classify_event_v2" not in inspect.getsource(batch)


def test_request_privacy_headers_are_normalized_without_raw_values():
    signals = validation.RequestPrivacySignals.from_headers({
        "sec-gpc": "1",
        "dnt": "banana",
    })
    assert signals.gpc is True
    assert signals.dnt is False
    assert signals.malformed == ("dnt",)
    assert "banana" not in repr(signals)


@pytest.mark.asyncio
async def test_live_dnt_suppresses_analytics_before_persistence(monkeypatch):
    event = _event()
    decision = await validation.validate_event(
        sdk_event=event,
        tenant_id="tenant-1",
        batch_id="batch-1",
        received_at="2026-07-15T00:00:01Z",
        request_privacy=validation.RequestPrivacySignals(dnt=True),
    )
    assert decision.allowed is False
    assert decision.reason_code == "dnt_suppressed"
    assert decision.required_purpose == "analytics"
    assert decision.normalized_event is None
    assert validation.format_rejection(decision, event) == "dnt_suppressed:analytics"


@pytest.mark.asyncio
async def test_recursive_fingerprint_classifier_fails_closed(monkeypatch):
    monkeypatch.setattr(
        validation,
        "evaluate_data_policy",
        AsyncMock(return_value=(False, "fingerprinting_not_authorized")),
    )
    event = _event(properties={
        "nested": {"canvasFingerprint": "must-not-be-retained-in-audit"}
    })
    decision = await validation.validate_event(
        sdk_event=event,
        tenant_id="tenant-1",
        batch_id="batch-1",
        received_at="2026-07-15T00:00:01Z",
    )
    assert decision.allowed is False
    assert decision.reason_code == "fingerprinting_not_authorized"
    assert decision.audit_metadata["fingerprint_paths"] == [
        "properties.nested.canvasFingerprint"
    ]
    assert "must-not-be-retained" not in repr(decision.audit_metadata)


@pytest.mark.asyncio
async def test_allowed_result_is_typed_sanitized_and_canonical_id_free(monkeypatch):
    monkeypatch.setattr(
        validation,
        "evaluate_data_policy",
        AsyncMock(return_value=(True, None)),
    )
    event = _event(
        properties={
            "nested": {"api_key": "secret", "canonicalEntityId": "client-owned"}
        },
        context=batch.EventContext(
            privacy={"refresh_token": "secret"},
            fingerprint={"deviceFingerprint": "classified-but-authorized"},
        ),
    )
    decision = await validation.validate_event(
        sdk_event=event,
        tenant_id="tenant-1",
        batch_id="batch-1",
        received_at="2026-07-15T00:00:01Z",
    )
    assert decision.allowed is True
    assert decision.normalized_event is not None
    assert decision.normalized_event["properties"]["nested"]["api_key"] == "[REDACTED]"
    assert "canonicalEntityId" not in decision.normalized_event["properties"]["nested"]
    assert decision.normalized_event["context"]["privacy"]["refresh_token"] == "[REDACTED]"
    assert decision.audit_metadata["sensitive_fields_scrubbed"] is True


@pytest.mark.asyncio
async def test_v1_processor_consumes_precomputed_validation(monkeypatch):
    decision = validation.EventValidationResult(
        allowed=True,
        reason_code=None,
        required_purpose="analytics",
        normalized_event={"event_id": "evt-parity"},
        deployment_id=None,
    )
    validate_spy = AsyncMock(side_effect=AssertionError("must not revalidate"))
    monkeypatch.setattr(batch, "validate_event", validate_spy)
    result = await batch._process_single_event(
        sdk_event=_event(),
        tenant_id="tenant-1",
        batch_id="batch-1",
        received_at="2026-07-15T00:00:01Z",
        cache=_Cache(),
        validation=decision,
    )
    assert result.status == "accepted"
    validate_spy.assert_not_awaited()
