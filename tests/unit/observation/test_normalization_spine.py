"""WS-B5 normalization-spine tests: one consumption-side view over the three
validated-topic payload shapes (additive ``observation_envelope`` / flat
SDK/comms dict / provider-runtime ``AetherEvent`` dump), plus flag-gated
consumer convergence.

The spine (:func:`services.ingestion.spine.to_observation_view`) never raises and
every field is Optional, so a consumer degrades to skip exactly as it does on a
missing key. Flag OFF keeps every legacy read (byte/row parity — the branch the
existing Silver write-path tests assert); flag ON routes consumers through the
spine so an AetherEvent ``subject_id``/``actor_id`` becomes a reachable
``user_id``/``agent_id`` subject.
"""

from __future__ import annotations

import inspect
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.ingestion import observation_envelope as oe
from services.ingestion import workers
from services.ingestion.spine import (
    ObservationView,
    normalization_spine_enabled,
    to_observation_view,
)
from services.resolution.consumer import ResolutionEventConsumer
from services.semantic_intelligence.consumer import _to_semantic_payload
from services.silver.dispatcher import ProjectionOutcome
from shared.events.events import Event, Topic


def _core_normalized() -> dict:
    return {
        "event_id": "evt_1",
        "tenant_id": "t1",
        "event_type": "track",
        "event_family": "analytics",
        "anonymous_id": "anon-1",
        "user_id": "u-1",
        "properties": {"amount": 1, "currency": "USD"},
        "context": {"tenantId": "t1", "correlation": {"correlationId": "c-1"}},
        "timestamp": "2026-09-05T00:00:00.000Z",
        "received_at": "2026-09-05T00:00:00.100Z",
        "ingested_at": "2026-09-05T00:00:00.200Z",
    }


def _sdk_envelope_additive(normalized: dict) -> dict:
    envelope = oe.build_sdk_observation_envelope(normalized)
    assert envelope is not None
    return envelope.to_bronze_additive()


def _aether_event_dump(**overrides) -> dict:
    """``AetherEvent.model_dump()`` key set published by provider_runtime.bridge."""
    dump = {
        "event_id": "evt_aether_1",
        "event_type": "commerce.order.created",
        "event_family": "commerce",
        "tenant_id": "t1",
        "provider": "shopify",
        "provider_identity": "shopify.orders.read",
        "source_record_id": "raw-1",
        "occurred_at": "2026-09-05T00:00:00.000Z",
        "observed_at": "2026-09-05T00:00:00.100Z",
        "account_id": "",
        "subject_id": "u-9",
        "actor_id": "agent-7",
        "data": {"amount": 5, "currency": "USD"},
        "context": {"acquisition_mode": "poll"},
        "schema_version": "1",
    }
    dump.update(overrides)
    return dump


def _flat_sdk_payload(**overrides) -> dict:
    payload = {
        "event_id": "evt_flat",
        "tenant_id": "t1",
        "event_type": "page",
        "event_family": "analytics",
        "user_id": "u-2",
        "anonymous_id": "anon-2",
        "session_id": "sess-2",
        "properties": {"path": "/pricing"},
        "context": {"tenantId": "spoofed", "platform": "web"},
        "timestamp": "2026-09-05T01:00:00.000Z",
        "received_at": "2026-09-05T01:00:00.100Z",
    }
    payload.update(overrides)
    return payload


# ── Envelope branch ──────────────────────────────────────────────────────────


def test_envelope_present_view_projects_envelope_blocks() -> None:
    normalized = _core_normalized()
    normalized["observation_envelope"] = _sdk_envelope_additive(normalized)
    envelope = normalized["observation_envelope"]
    obs = envelope["observation"]
    view = to_observation_view(normalized)

    assert view.envelope_source is True
    assert view.observation_id == "evt_1"
    assert view.observation_type == "track"
    assert view.family == "analytics"
    assert view.tenant_id == "t1"
    # envelope instants are datetime-normalized to canonical ISO (the .000 is
    # stripped) — the view mirrors the envelope block verbatim
    assert view.occurred_at == obs["occurred_at"]
    assert view.received_at == obs["received_at"]
    assert view.ingested_at == obs["ingested_at"]
    assert view.source_type == "sdk"
    assert view.correlation_id == "c-1"
    # user/anonymous synthesized from the first matching subjects entries
    assert view.user_id == "u-1"
    assert view.anonymous_id == "anon-1"
    assert view.session_id is None
    assert dict(view.payload_dict) == {"amount": 1, "currency": "USD"}  # type: ignore[arg-type]
    identifiers = [s.identifier_type for s in view.subjects]
    assert identifiers == ["anonymous_id", "user_id"]
    assert view.subjects[0].trust_class == "OBSERVED"
    assert view.subjects[1].trust_class == "CLIENT_HINT"


def test_envelope_present_with_user_id_subject_synthesizes_user() -> None:
    envelope = {
        "observation": {
            "observation_id": "obs-x",
            "observation_type": "page",
            "occurred_at": "2026-09-05T00:00:00Z",
        },
        "tenancy": {"tenant_id": "t-x"},
        "source": {"source_type": "webhook"},
        "subjects": [
            {
                "identifier_type": "user_id",
                "identifier_value": "profile-123",
                "trust_class": "SERVER_STAMPED",
            }
        ],
    }
    view = to_observation_view({"observation_envelope": envelope})
    assert view.envelope_source is True
    assert view.user_id == "profile-123"
    assert view.anonymous_id is None
    assert view.source_type == "webhook"


# ── Flat SDK / comms branch ──────────────────────────────────────────────────


def test_envelope_absent_sdk_flat_maps_legacy_bus_key_set() -> None:
    payload = _flat_sdk_payload()
    view = to_observation_view(payload)

    assert view.envelope_source is False
    # Field-for-field the key set the legacy _bus_payload_to_sdk_envelope reads.
    assert view.observation_type == "page"
    assert view.observation_id == "evt_flat"
    assert view.user_id == "u-2"
    assert view.anonymous_id == "anon-2"
    assert view.session_id == "sess-2"
    assert view.occurred_at == "2026-09-05T01:00:00.000Z"
    assert view.received_at == "2026-09-05T01:00:00.100Z"
    assert dict(view.payload_dict) == {"path": "/pricing"}  # type: ignore[arg-type]
    assert view.family == "analytics"
    assert view.tenant_id == "t1"
    assert view.context == payload["context"]  # type: ignore[comparison-overlap]
    assert view.correlation_id is None  # correlation is carried in context only


def test_flat_comms_shape_maps_source_and_context() -> None:
    comms = {
        "event_id": "comms-1",
        "tenant_id": "t1",
        "event_type": "email_delivered",
        "event_family": "comms",
        "session_id": "sess-c",
        "user_id": "profile-9",
        "properties": {"channel": "email"},
        "context": {"tenantId": "t1", "sourceConnectorId": "conn-1"},
        "timestamp": "2026-09-05T02:00:00.000Z",
        "received_at": "2026-09-05T02:00:00.100Z",
    }
    view = to_observation_view(comms)
    assert view.observation_type == "email_delivered"
    assert view.family == "comms"
    assert view.user_id == "profile-9"
    assert view.session_id == "sess-c"
    assert view.source_type is None  # the flat comms dict has no source_type key


# ── AetherEvent dump branch ──────────────────────────────────────────────────


def test_aether_event_dump_projects_subject_actor_and_data() -> None:
    payload = _aether_event_dump()
    view = to_observation_view(payload)

    assert view.envelope_source is False
    assert view.observation_type == "commerce.order.created"
    assert view.family == "commerce"
    assert view.tenant_id == "t1"
    assert view.provider == "shopify"
    assert view.provider_identity == "shopify.orders.read"
    assert view.occurred_at == "2026-09-05T00:00:00.000Z"
    assert view.received_at is None  # AetherEvent has no receipt instant
    assert dict(view.payload_dict) == {"amount": 5, "currency": "USD"}  # type: ignore[arg-type]
    # subject_id → user_id subject; actor_id → agent_id subject
    assert [s.identifier_type for s in view.subjects] == ["user_id", "agent_id"]
    assert view.subjects[0].value == "u-9"
    assert view.subjects[1].value == "agent-7"
    assert view.user_id == "u-9"
    assert view.anonymous_id is None


def test_aether_event_without_subject_id_leaves_user_none() -> None:
    view = to_observation_view(_aether_event_dump(subject_id=None, actor_id=None))
    assert view.user_id is None
    assert view.subjects == ()


# ── Resolution precedence ────────────────────────────────────────────────────


def test_envelope_wins_when_both_envelope_and_aether_shape_present() -> None:
    payload = _aether_event_dump()
    payload["observation_envelope"] = _sdk_envelope_additive(_core_normalized())
    view = to_observation_view(payload)
    assert view.envelope_source is True
    assert view.observation_type == "track"  # envelope block wins over data shape
    assert view.user_id == "u-1"


def test_envelope_wins_over_flat_sdk_shape() -> None:
    payload = _flat_sdk_payload(user_id="flat-user")
    payload["observation_envelope"] = _sdk_envelope_additive(_core_normalized())
    view = to_observation_view(payload)
    assert view.envelope_source is True
    assert view.user_id == "u-1"  # envelope subject, not the flat user_id


# ── Adoption flag (config/settings.py, default OFF) ──────────────────────────


def test_settings_flag_exists_and_defaults_off() -> None:
    from config import settings as settings_module

    cfg = settings_module.settings.normalization_spine
    assert isinstance(cfg, settings_module.NormalizationSpineConfig)
    assert cfg.enabled is False
    assert "AETHER_NORMALIZATION_SPINE_ENABLED" in inspect.getsource(
        settings_module.NormalizationSpineConfig
    )


def test_spine_enabled_helper_follows_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from config import settings as settings_module

    monkeypatch.setattr(
        settings_module.settings,
        "normalization_spine",
        SimpleNamespace(enabled=False),
    )
    assert normalization_spine_enabled() is False
    monkeypatch.setattr(
        settings_module.settings,
        "normalization_spine",
        SimpleNamespace(enabled=True),
    )
    assert normalization_spine_enabled() is True


# ── Never-raises guarantee ───────────────────────────────────────────────────


def test_view_never_raises_on_garbage() -> None:
    assert to_observation_view(None) == ObservationView()  # type: ignore[arg-type]
    assert to_observation_view("nope") == ObservationView()  # type: ignore[arg-type]
    assert to_observation_view(42) == ObservationView()  # type: ignore[arg-type]
    assert to_observation_view({}) == ObservationView()
    # an envelope key that is not a dict is ignored, not raised on
    view = to_observation_view({"event_type": "page", "observation_envelope": "bad"})
    assert view.envelope_source is False
    assert view.observation_type == "page"


# ── Flag-gated worker convergence (WS-B5, default OFF) ───────────────────────


def _set_spine(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    """Toggle settings.normalization_spine.enabled on the settings singleton."""
    from config import settings as settings_module

    monkeypatch.setattr(
        settings_module.settings,
        "normalization_spine",
        SimpleNamespace(enabled=enabled),
    )


def _connector_flat_payload(**overrides) -> dict:
    """A connector-family flat SDK/comms-shaped payload (provider fields in props)."""
    payload = {
        "event_id": "conn_evt_1",
        "tenant_id": "t1",
        "event_type": "checkout_completed",
        "event_family": "commerce",
        "user_id": "u-conn",
        "session_id": "sess-conn",
        "properties": {
            "provider": "shopify",
            "source_connector_id": "conn-1",
            "order_id": "o-1",
            "currency": "USD",
            "amount": 10,
        },
        "context": {
            "tenantId": "t1",
            "sourceConnectorId": "conn-1",
            "platform": "shopify",
        },
        "timestamp": "2026-09-05T03:00:00.000Z",
        "received_at": "2026-09-05T03:00:00.100Z",
    }
    payload.update(overrides)
    return payload


def _validated_event(payload: dict) -> Event:
    return Event(
        topic=Topic.SDK_EVENTS_VALIDATED,
        tenant_id=payload.get("tenant_id", ""),
        source_service="test",
        payload=payload,
    )


class _CaptureRepo:
    """Async fake for SilverRepository capturing upsert_record kwargs."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def upsert_record(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return {}


class _CaptureDispatcher:
    """Async fake for SilverDispatcher capturing the projector envelope."""

    def __init__(self) -> None:
        self.captured_envelopes: list[dict] = []

    async def project_with_outcome(self, envelope: dict) -> ProjectionOutcome:
        self.captured_envelopes.append(deepcopy(envelope))
        return ProjectionOutcome(event_type=envelope.get("type", ""))

    def handles(self, event_type: str) -> bool:
        return True


# ── _bus_payload_to_sdk_envelope parity / convergence ────────────────────────


def test_flag_off_bus_envelope_ignores_envelope_and_matches_legacy(monkeypatch) -> None:
    """Flag OFF: the additive envelope key is IGNORED — output equals the legacy
    flat mapping exactly (the branch existing Silver write-path tests assert)."""
    _set_spine(monkeypatch, False)
    payload = _flat_sdk_payload()
    payload["observation_envelope"] = _sdk_envelope_additive(_core_normalized())

    envelope = workers._bus_payload_to_sdk_envelope(payload)
    assert envelope["type"] == "page"
    assert envelope["messageId"] == "evt_flat"
    assert envelope["userId"] == "u-2"  # flat read, NOT the envelope's u-1
    assert envelope["timestamp"] == "2026-09-05T01:00:00.000Z"
    assert envelope["context"]["tenantId"] == "t1"


@pytest.mark.parametrize(
    "builder",
    [_flat_sdk_payload, _connector_flat_payload],
    ids=["sdk", "connector"],
)
def test_bus_envelope_flat_payload_identical_flag_on_vs_off(monkeypatch, builder) -> None:
    """Parity proof for the legacy branch: an SDK/comms fixture produces an
    identical projector envelope under flag OFF and flag ON."""
    payload = builder()
    _set_spine(monkeypatch, False)
    legacy = workers._bus_payload_to_sdk_envelope(payload)
    _set_spine(monkeypatch, True)
    converged = workers._bus_payload_to_sdk_envelope(payload)
    assert converged == legacy


def test_bus_envelope_aether_dump_gains_subject_and_occurrence_flag_on(monkeypatch) -> None:
    """Flag ON: an AetherEvent dump keeps its subject/occurrence in the projector
    envelope (the legacy path dropped them)."""
    payload = _aether_event_dump()

    _set_spine(monkeypatch, False)
    legacy = workers._bus_payload_to_sdk_envelope(payload)
    assert legacy["userId"] is None
    assert legacy["timestamp"] is None
    assert legacy["properties"] == {}
    assert legacy["type"] == "commerce.order.created"
    assert legacy["messageId"] == "evt_aether_1"

    _set_spine(monkeypatch, True)
    converged = workers._bus_payload_to_sdk_envelope(payload)
    assert converged["type"] == "commerce.order.created"
    assert converged["messageId"] == "evt_aether_1"
    assert converged["userId"] == "u-9"  # subject_id → user subject
    assert converged["timestamp"] == "2026-09-05T00:00:00.000Z"  # occurred_at
    assert converged["properties"] == {"amount": 5, "currency": "USD"}
    assert converged["context"]["tenantId"] == "t1"


# ── silver_fact_projector (the ~L180 projector-envelope seam) ────────────────


async def test_silver_fact_projector_flat_connector_envelope(monkeypatch) -> None:
    """silver_fact_projector hands the dispatcher a correct type/messageId envelope."""
    from services.silver import dispatcher as dispatcher_module

    _set_spine(monkeypatch, True)
    capture = _CaptureDispatcher()
    monkeypatch.setattr(dispatcher_module, "SilverDispatcher", lambda: capture)

    await workers.silver_fact_projector(_validated_event(_connector_flat_payload()))
    assert len(capture.captured_envelopes) == 1
    envelope = capture.captured_envelopes[0]
    assert envelope["type"] == "checkout_completed"
    assert envelope["messageId"] == "conn_evt_1"
    assert envelope["userId"] == "u-conn"
    assert envelope["properties"]["provider"] == "shopify"
    assert envelope["context"]["tenantId"] == "t1"


async def test_silver_fact_projector_aether_dump_envelope(monkeypatch) -> None:
    """Flag ON: an AetherEvent dump projects through the spine (subject reachable)."""
    from services.silver import dispatcher as dispatcher_module

    _set_spine(monkeypatch, True)
    capture = _CaptureDispatcher()
    monkeypatch.setattr(dispatcher_module, "SilverDispatcher", lambda: capture)

    payload = _aether_event_dump(event_type="commerce.order.created")
    await workers.silver_fact_projector(_validated_event(payload))
    assert len(capture.captured_envelopes) == 1
    envelope = capture.captured_envelopes[0]
    assert envelope["type"] == "commerce.order.created"
    assert envelope["messageId"] == "evt_aether_1"
    assert envelope["userId"] == "u-9"
    assert envelope["timestamp"] == "2026-09-05T00:00:00.000Z"
    assert envelope["properties"] == {"amount": 5, "currency": "USD"}


# ── silver_normalizer parity / convergence ───────────────────────────────────


async def test_silver_normalizer_flat_payload_identical_flag_on_vs_off(monkeypatch) -> None:
    repo = _CaptureRepo()
    monkeypatch.setattr(workers, "_silver", repo)
    payload = _connector_flat_payload()

    _set_spine(monkeypatch, False)
    await workers.silver_normalizer(_validated_event(deepcopy(payload)))
    _set_spine(monkeypatch, True)
    await workers.silver_normalizer(_validated_event(deepcopy(payload)))

    assert len(repo.calls) == 2
    assert repo.calls[0]["entity_id"] == repo.calls[1]["entity_id"] == "u-conn"
    assert repo.calls[0]["normalized"] == repo.calls[1]["normalized"]


async def test_silver_normalizer_aether_subject_reachable_only_flag_on(monkeypatch) -> None:
    repo = _CaptureRepo()
    monkeypatch.setattr(workers, "_silver", repo)
    payload = _aether_event_dump()

    _set_spine(monkeypatch, False)
    await workers.silver_normalizer(_validated_event(deepcopy(payload)))
    assert repo.calls[0]["entity_id"] == ""
    assert "user_id" not in repo.calls[0]["normalized"]

    _set_spine(monkeypatch, True)
    await workers.silver_normalizer(_validated_event(deepcopy(payload)))
    assert repo.calls[1]["entity_id"] == "u-9"
    assert repo.calls[1]["normalized"]["user_id"] == "u-9"
    assert repo.calls[1]["normalized"]["last_event_at"] == "2026-09-05T00:00:00.000Z"


# ── identity_signal_emitter ──────────────────────────────────────────────────


async def test_identity_signal_emitter_aether_subject_flag_on(monkeypatch) -> None:
    producer = SimpleNamespace(publish=AsyncMock())
    payload = _aether_event_dump(event_type="identify")

    _set_spine(monkeypatch, False)
    await workers.identity_signal_emitter(_validated_event(deepcopy(payload)), producer)
    assert producer.publish.await_count == 0  # legacy read has no user_id

    _set_spine(monkeypatch, True)
    await workers.identity_signal_emitter(_validated_event(deepcopy(payload)), producer)
    assert producer.publish.await_count == 1
    published: Event = producer.publish.await_args.args[0]
    assert published.payload["user_id"] == "u-9"
    assert published.payload["confidence"] == 0.95


# ── semantic_intelligence consumer mapping ───────────────────────────────────


def test_semantic_to_semantic_payload_aether_subject_flag_off(monkeypatch) -> None:
    """Flag OFF: semantic mapping keeps the legacy flat reads (no user_id)."""
    _set_spine(monkeypatch, False)
    sem = _to_semantic_payload(_validated_event(_aether_event_dump()))
    assert sem["user_id"] is None
    assert sem["anonymous_id"] is None
    assert sem["actor_ref"] == "anonymous"
    assert sem["occurred_at"] is None
    assert sem["session_id"] is None


def test_semantic_to_semantic_payload_aether_subject_flag_on(monkeypatch) -> None:
    """Flag ON: the AetherEvent subject_id is reachable as the semantic user."""
    _set_spine(monkeypatch, True)
    sem = _to_semantic_payload(
        _validated_event(_aether_event_dump(event_type="commerce.order.created"))
    )
    assert sem["user_id"] == "u-9"
    assert sem["actor_ref"] == "u-9"
    assert sem["occurred_at"] == "2026-09-05T00:00:00.000Z"
    assert sem["source_type"] == "commerce.order.created"


# ── resolution consumer ──────────────────────────────────────────────────────


async def test_resolution_consumer_aether_subject_flag_on(monkeypatch) -> None:
    engine = SimpleNamespace(resolve_event=AsyncMock(return_value=None))
    producer = SimpleNamespace(publish=AsyncMock())
    consumer = ResolutionEventConsumer(engine=engine, producer=producer)  # type: ignore[arg-type]
    payload = _aether_event_dump()

    _set_spine(monkeypatch, False)
    await consumer.on_event_validated(_validated_event(deepcopy(payload)))
    assert engine.resolve_event.await_count == 0  # legacy gate skips (no user_id)
    assert producer.publish.await_count == 0

    _set_spine(monkeypatch, True)
    await consumer.on_event_validated(_validated_event(deepcopy(payload)))
    assert engine.resolve_event.await_count == 1
    called_tenant, called_payload = engine.resolve_event.await_args.args
    assert called_tenant == "t1"
    # the engine receives a shallow copy whose user_id is the subject_id
    assert called_payload["user_id"] == "u-9"
    assert called_payload["subject_id"] == "u-9"
    assert producer.publish.await_count == 1
    resolution: Event = producer.publish.await_args.args[0]
    assert resolution.payload["user_id"] == "u-9"
