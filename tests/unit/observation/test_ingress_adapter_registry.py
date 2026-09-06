"""Registry tests for the universal ingress adapters (WS-B1 / WS-B4).

Covers the canonical family registry (all seven Envelope-B ``source_type``
families declared with blueprint adapter names + allowed credential classes),
the registered adapters today (SdkIngressAdapter + ReplayIngressAdapter), the
lookup helpers, and the import-time fail-fast for a misconfigured concrete
adapter.

WS-B4 note: ``replay`` became the second *registered* family when
ReplayIngressAdapter converged (WS-B4); the other five families remain
*declared* with a WS-B convergence status — never silent stubs.
"""

from __future__ import annotations

import pytest

from shared.observation.envelope import (
    CREDENTIAL_CLASSES,
    SOURCE_TYPES,
    UniversalObservationEnvelope,
)
from services.ingestion import adapters
from services.ingestion.adapters.replay import ReplayIngressAdapter
from services.ingestion.observation_envelope import (
    build_sdk_observation_envelope as delegate_build,
)

# ── Registry shape ────────────────────────────────────────────────────────────

def test_family_specs_match_the_envelope_source_type_vocabulary() -> None:
    """Every Envelope-B source_type has exactly one canonical family spec, in
    the same order, and every spec's allowed credentials are real classes."""
    assert [s.source_type for s in adapters.FAMILY_SPECS] == list(SOURCE_TYPES)
    for spec in adapters.FAMILY_SPECS:
        assert spec.allowed_credential_classes, spec.source_type
        for cc in spec.allowed_credential_classes:
            assert cc in CREDENTIAL_CLASSES


def test_each_family_carries_a_blueprint_adapter_name() -> None:
    """The seven families map onto the blueprint diagram's adapter names."""
    names = {s.source_type: s.blueprint_adapter for s in adapters.FAMILY_SPECS}
    assert names == {
        "sdk": "SDKAdapter",
        "webhook": "WebhookAdapter",
        "connector": "ConnectorAdapter",
        "feed": "APIAdapter (API-feed)",
        "import": "ImportAdapter",
        "harness": "HarnessAdapter",
        "replay": "ReplayAdapter",
    }


def test_sdk_and_replay_families_are_registered_today() -> None:
    """WS-B1 ships the SDK adapter and WS-B4 the replay adapter; the other five
    families are *declared* with a WS-B convergence status — never silent
    stubs."""
    assert adapters.registered_families() == ("sdk", "replay")
    for spec in adapters.FAMILY_SPECS:
        if spec.source_type in ("sdk", "replay"):
            assert spec.adapter_class is not None
            assert spec.status.startswith("implemented")
        else:
            assert spec.adapter_class is None
            assert "declared" in spec.status
            assert "WS-B2" in spec.status or "WS-B" in spec.status


def test_lookup_helpers() -> None:
    assert adapters.get_adapter("sdk") is adapters.SdkIngressAdapter
    assert adapters.get_adapter("replay") is ReplayIngressAdapter
    assert adapters.get_adapter("webhook") is None
    spec = adapters.get_family_spec("sdk")
    assert spec.source_type == "sdk"
    assert spec.allowed_credential_classes == ("PUBLIC_CLIENT",)
    replay_spec = adapters.get_family_spec("replay")
    assert replay_spec.allowed_credential_classes == ("OPERATOR_REPLAY",)
    with pytest.raises(ValueError):
        adapters.get_family_spec("carrier_pigeon")


# ── SdkIngressAdapter ─────────────────────────────────────────────────────────

def _core_normalized() -> dict:
    return {
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


def test_sdk_adapter_declares_public_client_identity() -> None:
    assert adapters.SdkIngressAdapter.family == "sdk"
    assert adapters.SdkIngressAdapter.credential_class == "PUBLIC_CLIENT"
    assert adapters.SdkIngressAdapter.adapter_id == "sdk"
    assert adapters.SdkIngressAdapter.description


def test_sdk_adapter_builds_envelope_and_matches_delegate() -> None:
    """The adapter is the registry identity for the SDK family; it delegates to
    the canonical mapping so the two never drift."""
    adapter = adapters.SdkIngressAdapter()
    envelope = adapter.build_observation_envelope(_core_normalized())
    assert envelope is not None
    assert isinstance(envelope, UniversalObservationEnvelope)
    d = envelope.to_bronze_additive()
    assert d["observation"]["observation_type"] == "track"
    assert d["tenancy"]["tenant_id"] == "t1"
    assert d["source"]["source_type"] == "sdk"
    assert d["source"]["ingress_path"] == "/v1/batch"
    # canonical SDK adapter identity in provenance
    assert d["provenance"]["adapter"] == "sdk"
    # identical to the module-level delegate on the same payload
    assert d == delegate_build(_core_normalized()).to_bronze_additive()  # type: ignore[union-attr]


def test_sdk_adapter_degrades_to_none_without_core() -> None:
    assert adapters.SdkIngressAdapter().build_observation_envelope(
        {"event_type": "track"}
    ) is None


# ── Fail-fast on misconfiguration ─────────────────────────────────────────────

def test_misconfigured_concrete_adapter_fails_at_import() -> None:
    """A concrete adapter with an unknown family / credential or missing id must
    raise at class-creation time (never register silently)."""
    with pytest.raises(ValueError):

        class _Bad(adapters.UniversalIngressAdapter):
            adapter_id = "bad"
            family = "carrier_pigeon"
            credential_class = "PUBLIC_CLIENT"
            description = "bad"

            def build_observation_envelope(self, normalized, *, ingress_path=None):
                return None

    with pytest.raises(ValueError):

        class _Worse(adapters.UniversalIngressAdapter):
            adapter_id = ""
            family = "sdk"
            credential_class = "PUBLIC_CLIENT"
            description = "bad"

            def build_observation_envelope(self, normalized, *, ingress_path=None):
                return None
