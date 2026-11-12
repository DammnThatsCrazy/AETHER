"""Signed events: verification, tamper resistance, and the path into lineage."""
from __future__ import annotations

import base64

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from actions.agent.attestation import canonical_payload, is_valid_public_key, verify_attestation
from actions.agent_lineage.engine import LineageEngine
from actions.agent_lineage.evidence import AuthorityRecord
from ingestion.ingestion.workers import _validated_agent_deployment_marker
from ingestion.silver.projectors.agent_execution_projector import AgentExecutionProjector

T = "tenant-a"
# Shared with packages/sdk/server/src/agent-telemetry.test.ts: both must produce this.
VECTOR_SEED = bytes(range(32))
EXPECTED_SIGNATURE = "G68ByW+maN/LMs72HOrv9grBJrOq+Rt1xIEVR3zoYytFUekJggOQbpzDBZgkUcJA122fQkIevosoGYU8UAneCg=="


def _keys(seed: bytes = VECTOR_SEED):
    private = Ed25519PrivateKey.from_private_bytes(seed)
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return private, base64.b64encode(public).decode()


def _payload(**overrides):
    fields = {
        "deployment_id": "dep-1", "agent_id": "orch", "message_id": "ev-1",
        "event_type": "agent_subagent_spawned", "timestamp": "2026-11-06T10:00:00.000Z",
        "properties": {"parentAgentId": "orch", "childAgentId": "worker"},
    }
    return canonical_payload(**{**fields, **overrides})


def _sign(private, payload):
    return base64.b64encode(private.sign(payload)).decode()


def test_a_valid_signature_verifies_and_any_lineage_change_breaks_it():
    private, public = _keys()
    signature = _sign(private, _payload())
    assert is_valid_public_key(public)
    assert verify_attestation(public, signature, _payload())
    for change in (
        {"properties": {"parentAgentId": "orch", "childAgentId": "evil"}},
        {"properties": {"parentAgentId": "evil", "childAgentId": "worker"}},
        {"message_id": "ev-2"}, {"deployment_id": "dep-2"}, {"agent_id": "other"},
        {"event_type": "agent_task_started"}, {"timestamp": "2026-11-06T10:00:01.000Z"},
        # Fields the projector reads for delegation and effects are covered too.
        {"properties": {"parentAgentId": "orch", "childAgentId": "worker", "delegatedToAgentId": "evil"}},
        {"properties": {"parentAgentId": "orch", "childAgentId": "worker", "externalEffectRef": "wire-1"}},
        {"blocks": {"execution_context": {"external_effect_ref": "wire-1"}}},
    ):
        assert not verify_attestation(public, signature, _payload(**change)), change


def test_bad_input_is_false_never_an_exception():
    private, public = _keys()
    other = _keys(bytes(reversed(VECTOR_SEED)))[1]
    good = _sign(private, _payload())
    assert not verify_attestation(other, good, _payload())
    for key, signature in ((None, good), (public, None), (public, "not base64!"), (public, 123),
                           ("short", good), (public, base64.b64encode(b"x").decode())):
        assert not verify_attestation(key, signature, _payload())
    assert not is_valid_public_key("nope")


def test_the_signature_format_matches_the_sdk_twin():
    # Pins the signed bytes; the TypeScript test signs the same fields with the same seed.
    assert _payload().startswith(
        b'["aether.agent-attestation.v1","dep-1","orch","ev-1","agent_subagent_spawned",'
        b'"2026-11-06T10:00:00.000Z","'
    )
    private, _ = _keys()
    assert _sign(private, _payload()) == EXPECTED_SIGNATURE


def test_the_marker_only_honours_a_literal_server_set_true():
    base = {"deployment_id": "d", "agent_id": "a"}
    assert _validated_agent_deployment_marker({"validated_agent_deployment": {**base, "attested": True}})["attested"] is True
    for value in ("true", 1, None):
        marker = _validated_agent_deployment_marker({"validated_agent_deployment": {**base, "attested": value}})
        assert "attested" not in marker


def _project(attested):
    deployment = {"agentId": "orch", "deploymentId": "dep-1"}
    if attested:
        deployment["attested"] = True
    return AgentExecutionProjector().project({
        "messageId": "ev-1", "tenantId": T, "type": "agent_subagent_spawned",
        "timestamp": "2026-11-06T10:00:00Z", "validated_agent_deployment": deployment,
        "properties": {"parentAgentId": "orch", "childAgentId": "worker"},
        "context": {"execution_context": {"execution_verification_state": "attested"}},
    }).rows[0]


def test_only_a_verified_marker_reaches_attested_and_it_makes_a_deterministic_hop():
    assert _project(False)["execution_verification_state"] == "deployment_verified"
    row = _project(True)
    assert row["execution_verification_state"] == "attested"
    engine = LineageEngine(T)
    engine.upsert_authority(AuthorityRecord(
        tenant_id=T, authority_ref="g", grantor_entity_id="human:h", grantee_entity_id="orch", grantor_kind="principal",
    ))
    engine.ingest([row])
    engine.resolve()
    assert engine.rows()[("human:h", "worker")]["attribution_class"] == "verified"

    weak = LineageEngine(T)
    weak.upsert_authority(AuthorityRecord(
        tenant_id=T, authority_ref="g", grantor_entity_id="human:h", grantee_entity_id="orch", grantor_kind="principal",
    ))
    weak.ingest([_project(False)])
    weak.resolve()
    assert weak.rows()[("human:h", "worker")]["attribution_class"] == "inferred"


async def test_ingestion_marks_attested_only_with_a_signature_from_the_registered_key(monkeypatch):
    from types import SimpleNamespace

    from ingestion.ingestion.validation import _event_is_attested

    private, public = _keys()
    props = {"parentAgentId": "orch", "childAgentId": "worker"}
    event = SimpleNamespace(id="ev-1", type="agent_subagent_spawned", timestamp="2026-11-06T10:00:00.000Z", properties=props)
    record = {"id": "dep-1", "agent_id": "orch", "attestation_public_key": public}
    signature = _sign(private, _payload())
    assert _event_is_attested(event, {"attestation": signature}, record) is True
    assert _event_is_attested(event, {"attestation": signature}, {**record, "attestation_public_key": None}) is False
    assert _event_is_attested(event, {"attested": True}, record) is False
    forged = SimpleNamespace(**{**vars(event), "properties": {**props, "childAgentId": "evil"}})
    assert _event_is_attested(forged, {"attestation": signature}, record) is False


def test_the_real_batch_event_model_keeps_the_signed_fields_intact():
    from ingestion.ingestion.batch import BaseEvent
    from ingestion.ingestion.validation import _event_is_attested

    private, public = _keys()
    event = BaseEvent(
        id="ev-1", sessionId="s", anonymousId="a", type="agent_subagent_spawned",
        timestamp="2026-11-06T10:00:00.000Z",
        properties={"parentAgentId": "orch", "childAgentId": "worker"},
    )
    record = {"id": "dep-1", "agent_id": "orch", "attestation_public_key": public}
    assert _event_is_attested(event, {"attestation": _sign(private, _payload())}, record) is True


NUMERIC_VECTOR_SIGNATURE = "57G01kxuCFXvknLCTK8vAbVCOVTgUIIfO5C5870SXGWEIRcpq/euIfR/swlK8ko7XU40jHM98K/5uX58B62uDA=="


def test_numbers_are_canonicalized_like_json_stringify():
    """The SDK signs JSON.stringify output; Python must hash the same bytes for the
    parsed wire values (0.000001, not 1e-06). Shared with agent-telemetry.test.ts."""
    import json

    from actions.agent.attestation import _canonical_json, _js_number

    assert [_js_number(v) for v in (0.000001, 1e-7, 1e21, 1.2345678901234568e20, 1.0, -0.0, float("nan"))] == [
        "0.000001", "1e-7", "1e+21", "123456789012345680000", "1", "0", "null"]
    wire = json.loads('{"toolName":"search","confidence":0.000001,"costMicros":123456789012345680000,"floor":1e-7}')
    assert _canonical_json(wire) == (
        '{"confidence":0.000001,"costMicros":123456789012345680000,"floor":1e-7,"toolName":"search"}')
    private, public = _keys()
    payload = canonical_payload(
        deployment_id="dep-1", agent_id="orch", message_id="ev-2", event_type="agent_tool_invocation_observed",
        timestamp="2026-11-06T10:00:00.000Z", properties=wire)
    assert _sign(private, payload) == NUMERIC_VECTOR_SIGNATURE
    assert verify_attestation(public, NUMERIC_VECTOR_SIGNATURE, payload)



def test_integers_a_js_number_cannot_hold_are_never_attested():
    """2**53 + 1 would sign like 2**53 while Silver keeps the exact amount, so a
    signed amount could change under the same signature. Such values (and ones
    beyond float range) refuse canonicalization with ValueError, which leaves the
    event unattested instead of aborting the batch."""
    import json

    import pytest

    from actions.agent.attestation import _canonical_json, _js_number

    assert _js_number(2**53) == "9007199254740992"  # exactly representable: fine
    for wire in ('{"amount":9007199254740993}', '{"n":1' + "0" * 310 + '}'):
        with pytest.raises(ValueError):
            _canonical_json(json.loads(wire))
    private, public = _keys()
    signature = _sign(private, _payload(properties={"amount": 2**53}))
    with pytest.raises(ValueError):
        _payload(properties={"amount": 2**53 + 1})  # cannot verify under the 2**53 signature
    assert verify_attestation(public, signature, _payload(properties={"amount": 2**53}))
