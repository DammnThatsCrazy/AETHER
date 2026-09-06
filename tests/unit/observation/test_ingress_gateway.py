"""Tests for the universal ingestion gateway (WS-B1).

Covers ``validate_and_stamp``: Envelope-B schema re-validation (rebuild of the
runtime model), canonical event-type / family checks against the Contract
Spine, tenant match, provenance/quality stamping (credential class, adapter
identity, source-trust basis, ``gateway:accepted``), and the typed rejected
outcomes — plus the round-trip guarantee that an accepted stamped envelope
still re-parses as a :class:`UniversalObservationEnvelope`.
"""

from __future__ import annotations

from shared.observation.envelope import UniversalObservationEnvelope
from services.ingestion.adapters.sdk import SdkIngressAdapter
from services.ingestion.gateway import validate_and_stamp


def _accepted_envelope_dict(adapter: SdkIngressAdapter) -> dict:
    """A gateway-valid SDK envelope built by the SDK adapter on a real event."""
    normalized = {
        "event_id": "evt_1",
        "tenant_id": "t1",
        "event_type": "track",
        "event_family": "core",
        "anonymous_id": "anon-1",
        "user_id": "u-1",
        "properties": {"amount": 1, "currency": "USD"},
        "context": {},
        "timestamp": "2026-09-05T00:00:00.000Z",
        "received_at": "2026-09-05T00:00:00.100Z",
        "ingested_at": "2026-09-05T00:00:00.200Z",
    }
    envelope = adapter.build_observation_envelope(normalized)
    assert envelope is not None
    return envelope.to_bronze_additive()


def test_gateway_accepts_and_stamps_an_adapter_built_envelope() -> None:
    result = validate_and_stamp(
        _accepted_envelope_dict(SdkIngressAdapter()),
        adapter=SdkIngressAdapter(),
        tenant_id="t1",
    )
    assert result.status == "accepted"
    assert result.accepted is True
    assert result.reasons == ()
    assert result.envelope is not None
    stamped = result.envelope
    # provenance: credential class + adapter identity stamped by the gateway
    assert stamped["provenance"]["credential_class"] == "PUBLIC_CLIENT"
    assert stamped["provenance"]["adapter"] == "sdk"
    assert stamped["provenance"]["adapter_version"] == "1.0.0"
    # effective trust basis of an unsigned observation = its ingress credential
    assert stamped["provenance"]["source_trust"] == "PUBLIC_CLIENT"
    # quality: gateway validation state recorded
    assert stamped["quality"]["validation_state"] == "gateway:accepted"
    # round-trip: the stamped additive dict still parses as the runtime model
    reparsed = UniversalObservationEnvelope(**stamped)
    assert reparsed.observation.observation_type == "track"


def test_gateway_rejects_schema_invalid_envelope() -> None:
    bad = _accepted_envelope_dict(SdkIngressAdapter())
    del bad["tenancy"]  # required block — runtime model rejects
    result = validate_and_stamp(bad, adapter=SdkIngressAdapter(), tenant_id="t1")
    assert result.status == "rejected"
    assert result.reasons == ("envelope_schema_invalid",)
    assert result.envelope is None


def test_gateway_rejects_unknown_observation_type() -> None:
    env = _accepted_envelope_dict(SdkIngressAdapter())
    env["observation"]["observation_type"] = "not_a_real_event"
    result = validate_and_stamp(env, adapter=SdkIngressAdapter(), tenant_id="t1")
    assert result.status == "rejected"
    assert result.reasons == ("unknown_observation_type",)


def test_gateway_rejects_family_mismatch_against_the_spine() -> None:
    """An adapter that declares a family the Contract Spine does not assign to
    the event type is a mis-built envelope — rejected, never silently fixed."""
    env = _accepted_envelope_dict(SdkIngressAdapter())
    env["observation"]["family"] = "stablecoin"  # track is `core`
    result = validate_and_stamp(env, adapter=SdkIngressAdapter(), tenant_id="t1")
    assert result.status == "rejected"
    assert result.reasons == ("family_mismatch",)


def test_gateway_rejects_tenant_mismatch() -> None:
    result = validate_and_stamp(
        _accepted_envelope_dict(SdkIngressAdapter()),
        adapter=SdkIngressAdapter(),
        tenant_id="another-tenant",
    )
    assert result.status == "rejected"
    assert result.reasons == ("tenant_mismatch",)


def test_gateway_honors_an_adapter_asserted_source_trust() -> None:
    """When the adapter already asserted a source_trust, the gateway keeps it
    (credential_class is still the adapter's, stamped authoritatively)."""
    env = _accepted_envelope_dict(SdkIngressAdapter())
    env["provenance"]["source_trust"] = "TENANT_SERVER"
    result = validate_and_stamp(env, adapter=SdkIngressAdapter(), tenant_id="t1")
    assert result.accepted is True
    assert result.envelope["provenance"]["source_trust"] == "TENANT_SERVER"
    assert result.envelope["provenance"]["credential_class"] == "PUBLIC_CLIENT"


def test_gateway_result_observation_id_surfaces_even_on_reject() -> None:
    result = validate_and_stamp(
        {"observation": {"observation_id": "obs_x"}},
        adapter=SdkIngressAdapter(),
        tenant_id="t1",
    )
    assert result.observation_id == "obs_x"
    assert result.reasons == ("envelope_schema_invalid",)
