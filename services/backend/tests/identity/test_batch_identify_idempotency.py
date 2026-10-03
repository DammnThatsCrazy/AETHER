"""The V1 batch path deduplicates canonical identify side effects by event ID."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from services.ingestion import batch
from services.ingestion.validation import EventValidationResult


class _Cache:
    def __init__(self):
        self.keys = set()
        self.fail = False

    async def set_nx(self, key, value, ttl):
        if self.fail:
            raise RuntimeError("cache unavailable")
        if key in self.keys:
            return False
        self.keys.add(key)
        return True

    async def delete(self, key):
        self.keys.discard(key)


class _Bronze:
    async def ingest(self, **kwargs):
        return None


class _Producer:
    def __init__(self):
        self.batches = []
        self.fail_next = False

    async def publish_batch(self, events):
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("broker unavailable")
        self.batches.append(list(events))


@pytest.mark.asyncio
async def test_retry_of_identify_event_does_not_repeat_canonical_resolution(monkeypatch):
    cache = _Cache()
    producer = _Producer()
    resolver_calls = []
    resolver = SimpleNamespace(
        resolve_event=lambda payload, tenant_id: _record_resolution(
            resolver_calls, payload, tenant_id
        )
    )
    registry = SimpleNamespace(cache=cache)
    normalized = {
        "event_id": "stable-event-123",
        "event_type": "identify",
        "user_id": "host-user-1",
        "anonymous_id": "anon-1",
        "session_id": "session-1",
        "properties": {"idempotency_key": "stable-event-123"},
        "context": {},
    }

    async def validate(**kwargs):
        payload = {**normalized, "event_id": kwargs["sdk_event"].id}
        return EventValidationResult(
            allowed=True,
            reason_code=None,
            required_purpose=None,
            normalized_event=payload,
            deployment_id=None,
        )

    async def process(**kwargs):
        return batch.EventResult(id=kwargs["sdk_event"].id, status="accepted")

    monkeypatch.setattr(batch, "get_registry", lambda: registry)
    monkeypatch.setattr(batch, "get_identity_resolver", lambda: resolver)
    monkeypatch.setattr(batch, "validate_event", validate)
    monkeypatch.setattr(batch, "_process_single_event", process)
    monkeypatch.setattr(
        batch, "_apply_temporal_enforcement", lambda **kwargs: kwargs["result"]
    )
    monkeypatch.setattr(batch, "BronzeRepository", lambda _name: _Bronze())
    monkeypatch.setattr(batch, "_emit_sequence_integrity_meters", lambda *args: None)
    async def no_meter(*args, **kwargs):
        return None
    monkeypatch.setattr(batch, "meter_family_usage", no_meter)
    monkeypatch.setattr(
        "services.sdk_distribution.install_verifier.schedule_install_projection",
        lambda *args, **kwargs: None,
    )

    event = batch.BaseEvent(
        id="stable-event-123",
        type="identify",
        timestamp="2026-09-27T10:00:00+00:00",
        sessionId="session-1",
        anonymousId="anon-1",
        userId="host-user-1",
        properties={"idempotency_key": "stable-event-123"},
    )

    first = await batch.ingest_events(
        [event], tenant_id="tenant-a", request_privacy=batch.RequestPrivacySignals(),
        server_context=None, granted_consents=frozenset(), sent_at=None,
        producer=producer,
    )
    await asyncio.sleep(0)
    second = await batch.ingest_events(
        [event], tenant_id="tenant-a", request_privacy=batch.RequestPrivacySignals(),
        server_context=None, granted_consents=frozenset(), sent_at=None,
        producer=producer,
    )
    await asyncio.sleep(0)

    assert first.accepted == 1
    assert second.duplicates == 1
    assert len(producer.batches) == 1
    assert len(resolver_calls) == 1
    assert resolver_calls[0][0]["event_id"] == "stable-event-123"
    assert resolver_calls[0][1] == "tenant-a"

    retry_event = event.model_copy(update={"id": "event-publish-retry"})
    producer.fail_next = True
    with pytest.raises(batch.ServiceUnavailableError):
        await batch.ingest_events(
            [retry_event], tenant_id="tenant-a", request_privacy=batch.RequestPrivacySignals(),
            server_context=None, granted_consents=frozenset(), sent_at=None,
            producer=producer,
        )
    # A failed publish releases its event claim, so a retry can publish and
    # resolve once after delivery succeeds.
    retried = await batch.ingest_events(
        [retry_event], tenant_id="tenant-a", request_privacy=batch.RequestPrivacySignals(),
        server_context=None, granted_consents=frozenset(), sent_at=None,
        producer=producer,
    )
    await asyncio.sleep(0)
    assert retried.accepted == 1
    assert [call[0]["event_id"] for call in resolver_calls] == [
        "stable-event-123", "event-publish-retry"
    ]

    cache.fail = True
    publish_count = len(producer.batches)
    with pytest.raises(batch.ServiceUnavailableError):
        await batch.ingest_events(
            [event.model_copy(update={"id": "event-cache-error"})],
            tenant_id="tenant-a", request_privacy=batch.RequestPrivacySignals(),
            server_context=None, granted_consents=frozenset(), sent_at=None,
            producer=producer,
        )
    await asyncio.sleep(0)
    assert len(producer.batches) == publish_count
    assert len(resolver_calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "resolution_enabled,late_binding_enabled,anonymous_binding_enabled,connector_backfill_enabled",
    [
        (True, False, True, True),
        (False, True, True, True),
        (True, True, False, True),
        (True, True, True, False),
    ],
)
async def test_identity_off_flags_do_not_schedule_batch_identify_resolution(
    monkeypatch, resolution_enabled, late_binding_enabled, anonymous_binding_enabled,
    connector_backfill_enabled,
):
    cache = _Cache()
    producer = _Producer()
    resolver_calls = []
    resolver = SimpleNamespace(
        resolve_event=lambda payload, tenant_id: _record_resolution(
            resolver_calls, payload, tenant_id
        )
    )
    registry = SimpleNamespace(cache=cache)
    normalized = {
        "event_id": "stable-event-off",
        "event_type": "identify",
        "user_id": "host-user-1",
        "anonymous_id": "anon-1",
        "session_id": "session-1",
        "properties": {"idempotency_key": "stable-event-off"},
        "context": {},
    }

    async def validate(**kwargs):
        payload = {**normalized, "event_id": kwargs["sdk_event"].id}
        return EventValidationResult(
            allowed=True, reason_code=None, required_purpose=None,
            normalized_event=payload, deployment_id=None,
        )

    async def process(**kwargs):
        return batch.EventResult(id=kwargs["sdk_event"].id, status="accepted")

    monkeypatch.setattr(batch.settings, "identity_continuity", replace(
        batch.settings.identity_continuity,
        resolution_enabled=resolution_enabled,
        sdk_late_binding_enabled=late_binding_enabled,
        anonymous_to_known_binding_enabled=anonymous_binding_enabled,
        connector_backfill_enabled=connector_backfill_enabled,
    ))
    monkeypatch.setattr(batch, "get_registry", lambda: registry)
    monkeypatch.setattr(batch, "get_identity_resolver", lambda: resolver)
    monkeypatch.setattr(batch, "validate_event", validate)
    monkeypatch.setattr(batch, "_process_single_event", process)
    monkeypatch.setattr(batch, "_apply_temporal_enforcement", lambda **kwargs: kwargs["result"])
    monkeypatch.setattr(batch, "BronzeRepository", lambda _name: _Bronze())
    monkeypatch.setattr(batch, "_emit_sequence_integrity_meters", lambda *args: None)
    async def no_meter(*args, **kwargs):
        return None
    monkeypatch.setattr(batch, "meter_family_usage", no_meter)
    monkeypatch.setattr(
        "services.sdk_distribution.install_verifier.schedule_install_projection",
        lambda *args, **kwargs: None,
    )

    response = await batch.ingest_events(
        [batch.BaseEvent(
            id="stable-event-off", type="identify", timestamp="2026-09-27T10:00:00+00:00",
            sessionId="session-1", anonymousId="anon-1", userId="host-user-1",
            properties={"idempotency_key": "stable-event-off"},
        )],
        tenant_id="tenant-a", request_privacy=batch.RequestPrivacySignals(),
        server_context=None, granted_consents=frozenset(), sent_at=None,
        producer=producer,
    )
    await asyncio.sleep(0)

    assert response.accepted == 1
    if resolution_enabled and late_binding_enabled and anonymous_binding_enabled:
        assert len(resolver_calls) == 1
    else:
        assert resolver_calls == []


@pytest.mark.asyncio
async def test_sdk_late_binding_off_does_not_schedule_batch_identify_resolution(monkeypatch):
    cache = _Cache()
    producer = _Producer()
    resolver_calls = []
    resolver = SimpleNamespace(
        resolve_event=lambda payload, tenant_id: _record_resolution(
            resolver_calls, payload, tenant_id
        )
    )
    registry = SimpleNamespace(cache=cache)
    normalized = {
        "event_id": "stable-event-off",
        "event_type": "identify",
        "user_id": "host-user-1",
        "anonymous_id": "anon-1",
        "session_id": "session-1",
        "properties": {"idempotency_key": "stable-event-off"},
        "context": {},
    }

    async def validate(**kwargs):
        payload = {**normalized, "event_id": kwargs["sdk_event"].id}
        return EventValidationResult(
            allowed=True, reason_code=None, required_purpose=None,
            normalized_event=payload, deployment_id=None,
        )

    async def process(**kwargs):
        return batch.EventResult(id=kwargs["sdk_event"].id, status="accepted")

    monkeypatch.setattr(batch.settings, "identity_continuity", replace(
        batch.settings.identity_continuity,
        resolution_enabled=True,
        sdk_late_binding_enabled=False,
    ))
    monkeypatch.setattr(batch, "get_registry", lambda: registry)
    monkeypatch.setattr(batch, "get_identity_resolver", lambda: resolver)
    monkeypatch.setattr(batch, "validate_event", validate)
    monkeypatch.setattr(batch, "_process_single_event", process)
    monkeypatch.setattr(batch, "_apply_temporal_enforcement", lambda **kwargs: kwargs["result"])
    monkeypatch.setattr(batch, "BronzeRepository", lambda _name: _Bronze())
    monkeypatch.setattr(batch, "_emit_sequence_integrity_meters", lambda *args: None)
    async def no_meter(*args, **kwargs):
        return None
    monkeypatch.setattr(batch, "meter_family_usage", no_meter)
    monkeypatch.setattr(
        "services.sdk_distribution.install_verifier.schedule_install_projection",
        lambda *args, **kwargs: None,
    )

    response = await batch.ingest_events(
        [batch.BaseEvent(
            id="stable-event-off", type="identify", timestamp="2026-09-27T10:00:00+00:00",
            sessionId="session-1", anonymousId="anon-1", userId="host-user-1",
            properties={"idempotency_key": "stable-event-off"},
        )],
        tenant_id="tenant-a", request_privacy=batch.RequestPrivacySignals(),
        server_context=None, granted_consents=frozenset(), sent_at=None,
        producer=producer,
    )
    await asyncio.sleep(0)

    assert response.accepted == 1
    assert resolver_calls == []


async def _record_resolution(calls, payload, tenant_id):
    calls.append((payload, tenant_id))
    return None
