"""Tests for ReplayIngressAdapter (WS-B4).

Covers the replay-family adapter identity (OPERATOR_REPLAY credential), the two
source-shape build paths (re-validate the STORED observation_envelope vs
rebuild the SDK-equivalent envelope for a pre-Envelope-B row), and the
unconditional replay rewrite — original-time preservation (Invariant #15):
``observation.occurred_at`` / flat ``timestamp`` stay ORIGINAL while
``received_at`` / ``ingested_at`` are the fresh replay stamps; the envelope is
re-keyed as ``source_type="replay"`` with the original family on
``source_provider``, provenance is the replay adapter identity, and
``lineage.raw_record_ref`` carries the Bronze row ref. Degrades to None (never
raises) when the ``_replay`` context or the envelope core is missing.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from services.ingestion.adapters.replay import (
    DEFAULT_REPLAY_INGRESS_PATH,
    REPLAY_CONTEXT_KEY,
    ReplayIngressAdapter,
)
from shared.observation.envelope import UniversalObservationEnvelope
from services.ingestion.observation_envelope import (
    build_sdk_observation_envelope as sdk_build,
)

ADAPTER = ReplayIngressAdapter()


def _flat_normalized() -> dict:
    return {
        "event_id": "evt_1",
        "tenant_id": "t1",
        "event_type": "track",
        "event_family": "core",
        "anonymous_id": "anon-1",
        "user_id": "u-1",
        "properties": {"amount": 1, "currency": "USD"},
        "context": {},
        "timestamp": "2026-09-05T00:00:00.000Z",  # ORIGINAL occurrence
        "received_at": "2026-09-05T00:00:00.100Z",  # ORIGINAL server receipt
        "ingested_at": "2026-09-05T00:00:00.200Z",
    }


def _replay_context(bronze_ref: str = "bronze_ref_1", original_event_id: str = "evt_1") -> dict:
    return {
        "original_event_id": original_event_id,
        "replay_received_at": "2026-09-06T01:02:03.000Z",  # fresh replay stamps
        "replay_ingested_at": "2026-09-06T01:02:03.000Z",
        "bronze_ref": bronze_ref,
        "replay_run_id": "run_1",
    }


def _with_replay(normalized: dict, bronze_ref: str = "bronze_ref_1") -> dict:
    payload = dict(normalized)
    payload[REPLAY_CONTEXT_KEY] = _replay_context(bronze_ref=bronze_ref)
    return payload


# ── Adapter identity ──────────────────────────────────────────────────────────

def test_replay_adapter_declares_operator_identity() -> None:
    assert ADAPTER.family == "replay"
    assert ADAPTER.credential_class == "OPERATOR_REPLAY"
    assert ADAPTER.adapter_id == "replay"
    assert ADAPTER.adapter_version == "1.0.0"
    assert ADAPTER.description


def test_replay_adapter_is_the_registry_identity_for_replay_family() -> None:
    from services.ingestion.adapters.registry import REGISTERED_ADAPTERS

    assert REGISTERED_ADAPTERS["replay"] is ReplayIngressAdapter


# ── Flag-off row: rebuild path (pre-Envelope-B durable row) ───────────────────

def test_build_rebuilds_envelope_from_flat_normalized_row() -> None:
    envelope = ADAPTER.build_observation_envelope(_with_replay(_flat_normalized()))
    assert envelope is not None
    assert isinstance(envelope, UniversalObservationEnvelope)
    d = envelope.to_bronze_additive()
    assert d["observation"]["observation_type"] == "track"
    assert d["observation"]["observation_id"] == "evt_1"
    assert d["tenancy"]["tenant_id"] == "t1"
    # replay delivery surface
    assert d["source"]["source_type"] == "replay"
    assert d["source"]["source_provider"] == "sdk"  # original ingress family
    assert d["source"]["source_native_id"] == "evt_1"
    assert d["source"]["ingress_path"] == DEFAULT_REPLAY_INGRESS_PATH
    # replay provenance identity (gateway adds the credential_class later)
    assert d["provenance"]["adapter"] == "replay"
    assert d["provenance"]["adapter_version"] == "1.0.0"
    # durable Bronze ref on the lineage block (Invariant #14)
    assert d["lineage"]["raw_record_ref"] == "bronze_ref_1"


# ── Flag-on row: re-validate the STORED envelope path ────────────────────────

def test_build_revalidates_and_rewrites_a_stored_envelope() -> None:
    """A row whose payload carries the stored observation_envelope (Envelope-B
    was ON during the original ingest) re-validates THAT envelope — the replayed
    occurrence can never drift from what was durably recorded."""
    stored = sdk_build(_flat_normalized()).to_bronze_additive()  # type: ignore[union-attr]
    normalized = dict(_flat_normalized())
    normalized["observation_envelope"] = stored
    envelope = ADAPTER.build_observation_envelope(_with_replay(normalized))
    assert envelope is not None
    d = envelope.to_bronze_additive()
    assert d["observation"]["observation_type"] == "track"
    assert d["observation"]["observation_id"] == "evt_1"
    assert d["source"]["source_type"] == "replay"
    assert d["source"]["source_provider"] == "sdk"
    # subjects/tenancy survived the rewrite from the stored envelope
    assert d["tenancy"]["tenant_id"] == "t1"
    assert d["source"]["source_native_id"] == "evt_1"


def test_stored_envelope_present_but_invalid_degrades_to_none() -> None:
    normalized = dict(_flat_normalized())
    normalized["observation_envelope"] = {"observation": {}}  # not a real envelope
    assert ADAPTER.build_observation_envelope(_with_replay(normalized)) is None


# ── Invariant #15: original-time preservation ────────────────────────────────

def test_original_occurrence_is_preserved_and_receipt_stamps_are_fresh() -> None:
    envelope = ADAPTER.build_observation_envelope(_with_replay(_flat_normalized()))
    assert envelope is not None
    obs = envelope.observation
    assert obs.observation_id == "evt_1"
    # ORIGINAL occurrence — never now, never the original receipt time
    assert obs.occurred_at.isoformat() == "2026-09-05T00:00:00+00:00"
    # fresh replay receipt/ingest stamps (Invariant #15 observed-vs-received)
    assert obs.received_at.isoformat() == "2026-09-06T01:02:03+00:00"
    assert obs.ingested_at.isoformat() == "2026-09-06T01:02:03+00:00"
    assert obs.received_at != obs.occurred_at


# ── Correlation / provenance rewrite ─────────────────────────────────────────

def test_original_observation_type_and_family_are_kept() -> None:
    envelope = ADAPTER.build_observation_envelope(_with_replay(_flat_normalized()))
    assert envelope is not None
    assert envelope.observation.observation_type == "track"
    assert envelope.observation.family == "core"


# ── Degradation (never raises) ───────────────────────────────────────────────

def test_missing_replay_context_returns_none() -> None:
    # No _replay context injected (e.g. a caller forgot the runner contract).
    assert ADAPTER.build_observation_envelope(_flat_normalized()) is None


def test_missing_core_returns_none() -> None:
    # _replay present but the flat payload cannot supply the envelope core.
    normalized = {"event_id": "evt_x", "tenant_id": "t1", "event_type": "track"}
    assert ADAPTER.build_observation_envelope(_with_replay(normalized)) is None


def test_unparseable_replay_stamps_return_none() -> None:
    normalized = _with_replay(_flat_normalized())
    normalized[REPLAY_CONTEXT_KEY] = dict(
        _replay_context(), replay_received_at="not-a-date"
    )
    assert ADAPTER.build_observation_envelope(normalized) is None


def test_custom_ingress_path_is_honoured() -> None:
    envelope = ADAPTER.build_observation_envelope(
        _with_replay(_flat_normalized()), ingress_path="/v1/kyber/ingest/replay"
    )
    assert envelope is not None
    assert envelope.source.ingress_path == "/v1/kyber/ingest/replay"
