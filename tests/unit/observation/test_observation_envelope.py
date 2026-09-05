"""Runtime tests for the UniversalObservationEnvelope (Envelope B) model and
its flag-gated SDK mapping (WS-A5).

Covers pydantic construction, ``extra=forbid`` rejection, curated-vocabulary
enforcement, JSON-safe additive persistence, the ``build_sdk_observation_envelope``
mapping (subject trust derivation incl. ``EVENT_FIELD_TRUST`` overrides), the
degrade-to-None path, and the /v1/batch flag-gated adoption site.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from shared.observation.envelope import (
    CorrelationBlock,
    ObservationBlock,
    ProvenanceBlock,
    SourceBlock,
    SubjectRef,
    TemporalBlock,
    TenancyBlock,
    UniversalObservationEnvelope,
)
from services.ingestion import batch
from services.ingestion import observation_envelope as oe


def _core_normalized() -> dict:
    return {
        "event_id": "evt_1",
        "tenant_id": "t1",
        "event_type": "track",
        "event_family": "analytics",
        "anonymous_id": "anon-1",
        "user_id": "u-1",
        "properties": {"amount": 1, "currency": "USD"},
        "context": {"correlation": {"correlationId": "c-1", "traceId": "t-1"}},
        "timestamp": "2026-09-05T00:00:00.000Z",
        "received_at": "2026-09-05T00:00:00.100Z",
        "ingested_at": "2026-09-05T00:00:00.200Z",
    }


# ── Model construction / validation ──────────────────────────────────────────

def test_minimal_envelope_builds_and_persists_additively() -> None:
    """The required core alone builds; unset optionals are excluded from dump."""
    env = UniversalObservationEnvelope(
        observation=ObservationBlock(
            observation_id="obs-1",
            observation_type="track",
            occurred_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
            received_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
            ingested_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
            schema_version="1.0.0",
        ),
        tenancy=TenancyBlock(tenant_id="t1"),
        source=SourceBlock(source_type="sdk"),
    )
    dumped = env.to_bronze_additive()
    # subjects defaults to [] (present, empty); every other optional is excluded
    assert set(dumped) == {"observation", "tenancy", "source", "subjects"}
    assert dumped["subjects"] == []
    # JSON-safe: datetimes are serialized, not kept as objects
    assert isinstance(dumped["observation"]["occurred_at"], str)
    assert dumped["observation"]["observation_id"] == "obs-1"


def test_extra_fields_are_rejected() -> None:
    """Every block and the envelope itself is extra=forbid."""
    with pytest.raises(ValidationError):
        ObservationBlock(
            observation_id="x",
            observation_type="track",
            occurred_at="2026-09-05T00:00:00Z",
            received_at="2026-09-05T00:00:00Z",
            ingested_at="2026-09-05T00:00:00Z",
            schema_version="1.0.0",
            surprise=True,
        )
    with pytest.raises(ValidationError):
        UniversalObservationEnvelope(
            observation=ObservationBlock(
                observation_id="x",
                observation_type="track",
                occurred_at="2026-09-05T00:00:00Z",
                received_at="2026-09-05T00:00:00Z",
                ingested_at="2026-09-05T00:00:00Z",
                schema_version="1.0.0",
            ),
            tenancy=TenancyBlock(tenant_id="t1"),
            source=SourceBlock(source_type="sdk"),
            extra_block={},
        )


@pytest.mark.parametrize(
    "kwarg",
    [
        {"source_type": "sdk"},
        {"source_type": "webhook"},
        {"source_type": "connector"},
        {"source_type": "feed"},
        {"source_type": "import"},
        {"source_type": "harness"},
        {"source_type": "replay"},
    ],
)
def test_all_source_types_accepted(kwarg: dict) -> None:
    SourceBlock(**kwarg)


def test_unknown_source_type_rejected() -> None:
    with pytest.raises(ValidationError):
        SourceBlock(source_type="carrier_pigeon")


def test_subject_trust_defaults_to_observed() -> None:
    subj = SubjectRef(identifier_type="anonymous_id", identifier_value="a1")
    assert subj.trust_class == "OBSERVED"


def test_subject_unknown_identifier_or_trust_rejected() -> None:
    with pytest.raises(ValidationError):
        SubjectRef(identifier_type="not_a_type", identifier_value="x")
    with pytest.raises(ValidationError):
        SubjectRef(identifier_type="user_id", identifier_value="x", trust_class="GOD_MODE")


def test_credential_class_vocabulary_enforced() -> None:
    with pytest.raises(ValidationError):
        ProvenanceBlock(credential_class="SKETCHY_CLIENT")


def test_blocks_can_be_attached_and_are_json_safe() -> None:
    env = UniversalObservationEnvelope(
        observation=ObservationBlock(
            observation_id="obs-1",
            observation_type="track",
            occurred_at="2026-09-05T00:00:00Z",
            received_at="2026-09-05T00:00:00Z",
            ingested_at="2026-09-05T00:00:00Z",
            schema_version="1.0.0",
        ),
        tenancy=TenancyBlock(tenant_id="t1"),
        source=SourceBlock(source_type="sdk", ingress_path="/v1/batch"),
        subjects=[
            SubjectRef(identifier_type="user_id", identifier_value="u1", trust_class="CLIENT_HINT")
        ],
        correlation=CorrelationBlock(correlation_id="c1"),
        temporal=TemporalBlock(source_time="2026-09-05T00:00:00Z", sequence="7"),
        payload={"amount": 1},
        provenance=ProvenanceBlock(adapter="ingestion.batch", adapter_version="1.0.0"),
    )
    dumped = env.to_bronze_additive()
    assert dumped["subjects"][0]["trust_class"] == "CLIENT_HINT"
    assert dumped["temporal"]["sequence"] == "7"
    assert dumped["correlation"]["correlation_id"] == "c1"


# ── SDK mapping ──────────────────────────────────────────────────────────────

def test_sdk_mapping_builds_envelope_from_normalized() -> None:
    env = oe.build_sdk_observation_envelope(_core_normalized())
    assert env is not None
    d = env.to_bronze_additive()
    assert d["observation"]["observation_id"] == "evt_1"
    assert d["observation"]["observation_type"] == "track"
    assert d["tenancy"]["tenant_id"] == "t1"
    assert d["source"]["source_type"] == "sdk"
    # anonymous first, then user — trust fallbacks respected
    assert [s["identifier_type"] for s in d["subjects"]] == ["anonymous_id", "user_id"]
    assert d["subjects"][0]["trust_class"] == "OBSERVED"
    assert d["subjects"][1]["trust_class"] == "CLIENT_HINT"
    assert d["payload"] == {"amount": 1, "currency": "USD"}
    assert d["correlation"]["correlation_id"] == "c-1"
    assert d["correlation"]["trace_id"] == "t-1"


def test_sdk_mapping_respects_event_field_trust_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """user_id trust_class follows EVENT_FIELD_TRUST when the event declares an override."""
    monkeypatch.setattr(
        oe,
        "EVENT_FIELD_TRUST",
        {"custom_event": {"userId": {"trustClass": "SOURCE_ASSERTED"}}},
    )
    norm = _core_normalized()
    norm["event_type"] = "custom_event"
    d = oe.build_sdk_observation_envelope(norm).to_bronze_additive()  # type: ignore[union-attr]
    user_subject = [s for s in d["subjects"] if s["identifier_type"] == "user_id"][0]
    assert user_subject["trust_class"] == "SOURCE_ASSERTED"


def test_sdk_mapping_maps_temporal_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    """The temporal enforcement stamp is preserved (sequence coerced to str)."""
    monkeypatch.setattr(oe, "EVENT_FIELD_TRUST", {})
    norm = _core_normalized()
    norm["temporal"] = {
        "source_timestamp_original": "2026-09-05T00:00:00.000Z",
        "source_time_zone": "UTC",
        "source_utc_offset_minutes": 0,
        "clock_source": "device",
        "temporal_state": "authoritative",
    }
    norm["context"] = {"sequence": {"event": 7}}
    d = oe.build_sdk_observation_envelope(norm).to_bronze_additive()  # type: ignore[union-attr]
    assert d["temporal"]["source_time"] == "2026-09-05T00:00:00.000Z"
    assert d["temporal"]["timezone"] == "UTC"
    assert d["temporal"]["utc_offset"] == "+00:00"
    assert d["temporal"]["sequence"] == "7"
    assert d["temporal"]["temporal_quality"] == "authoritative"


def test_sdk_mapping_degrades_to_none_without_core() -> None:
    assert oe.build_sdk_observation_envelope({"event_type": "track"}) is None
    assert oe.build_sdk_observation_envelope(
        {**_core_normalized(), "timestamp": "not-a-date", "received_at": "no", "ingested_at": "no"}
    ) is None


def test_flag_gated_batch_attach_is_additive() -> None:
    """Mirrors the /v1/batch accepted-path block: attaching the envelope key
    leaves every pre-existing normalized key untouched."""
    normalized = _core_normalized()
    original_keys = set(normalized)
    envelope = oe.build_sdk_observation_envelope(normalized)
    assert envelope is not None
    normalized["observation_envelope"] = envelope.to_bronze_additive()
    assert original_keys <= set(normalized)
    assert "observation_envelope" in normalized


# ── /v1/batch adoption site (flag-gated, default OFF) ────────────────────────

def test_batch_v1_accepted_path_guards_on_flag() -> None:
    """The accepted-path block must reference the flag and degrade on failure."""
    source = inspect.getsource(batch)
    assert "settings.observation_envelope.enabled" in source
    assert "build_sdk_observation_envelope" in source
    assert 'normalized["observation_envelope"]' in source
    assert "except Exception" in source


def test_settings_flag_exists_and_defaults_off() -> None:
    from config import settings as settings_module

    cfg = settings_module.settings.observation_envelope
    assert cfg.enabled is False
    # The dataclass field is wired to the documented env var (default OFF).
    assert "AETHER_OBSERVATION_ENVELOPE_ENABLED" in inspect.getsource(settings_module.ObservationEnvelopeConfig)
