"""Risk360 Phase-5 producer-convergence adapter tests (signals.py).

Verifies each shipped producer artifact (fraud result, fraud-network detectors,
device risk, geo enrichment, behavioral scan, trust vector) converges into
typed ``RiskSignal``(s): registered risk dimensions, honest claim states,
reused ``EvidenceRef``(s), detector versions only when the producer exposes
one, deterministic content ids, and — the scoring-honesty core — no score is
ever fabricated from an absent/uncalibrated numeric.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from services.fraud.signals import SignalResult  # noqa: E402
from services.risk360.contracts import EpistemicStatus  # noqa: E402
from services.risk360.signals import (  # noqa: E402
    RiskEvidenceBundle,
    adapt_producer_signal,
    signal_from_behavioral_scan,
    signal_from_device_risk,
    signal_from_fraud_result,
    signal_from_geo_lookup,
    signal_from_trust_vector,
    signals_from_fraud_network_evidence,
)

SUBJ = dict(subject_kind="entity", subject_id="ent_1", tenant_id="ten_1")


def _fraud_result(signals, *, verdict="flag", audit_id="fra_abc"):
    return {
        "audit_id": audit_id,
        "composite_score": 55.0,
        "verdict": verdict,
        "signals": signals,
        "evaluation_ms": 12.0,
        "timestamp": "2026-09-03T12:00:00Z",
        "config_snapshot": {},
    }


# ── fraud signals ───────────────────────────────────────────────────────────

def test_fraud_result_calibrated_signal_scales_and_maps_dimension():
    signals = signal_from_fraud_result(
        _fraud_result(
            [
                {
                    "name": "velocity",
                    "score": 80.0,
                    "weight": 0.15,
                    "triggered": True,
                    "calibrated": True,
                }
            ]
        ),
        **SUBJ,
    )
    assert len(signals) == 1
    sig = signals[0]
    # velocity → behavioral dimension, 80/100 → 0.8
    assert sig.risk_dimension == "behavioral"
    assert sig.score == pytest.approx(0.8)
    assert sig.claim_state == EpistemicStatus.DERIVED
    assert sig.source == "fraud.signals"
    assert sig.evidence_refs[0].type == "model_output"
    assert sig.evidence_refs[0].source == "fraud.signals"


def test_fraud_result_uncalibrated_score_never_becomes_a_number():
    # Engine to_dict() DROPS calibrated/score_kind — no calibrated flag must mean
    # "do not promote the uncalibrated heuristic to a risk score".
    signals = signal_from_fraud_result(
        _fraud_result(
            [
                {
                    "name": "velocity",
                    "score": 80.0,
                    "weight": 0.15,
                    "triggered": True,
                }
            ]
        ),
        **SUBJ,
    )
    assert len(signals) == 1
    assert signals[0].score is None


def test_fraud_result_calibrated_dataclass_artifact_scales():
    # A SignalResult dataclass object (in-memory engine path) carries calibrated.
    result = _fraud_result(
        [
            SignalResult(
                name="wallet_age",
                score=70.0,
                weight=0.10,
                triggered=True,
                calibrated=True,
            )
        ]
    )
    signals = signal_from_fraud_result(result, **SUBJ)
    assert len(signals) == 1
    # wallet_age → identity dimension, 70/100 → 0.7
    assert signals[0].risk_dimension == "identity"
    assert signals[0].score == pytest.approx(0.7)


def test_fraud_result_nontriggered_signals_are_not_emitted():
    signals = signal_from_fraud_result(
        _fraud_result(
            [
                {
                    "name": "bot_detection",
                    "score": 90.0,
                    "triggered": False,
                    "calibrated": True,
                }
            ]
        ),
        **SUBJ,
    )
    assert signals == []


# ── fraud-network detectors ─────────────────────────────────────────────────

def test_fraud_network_evidence_relationship_and_transaction_types():
    raw = [
        ("shared_device", ["ent_1", "ent_2"], {"device_fingerprint": "fp1"}),
        ("commerce_abuse", ["ent_1"], {"refund_rate": 0.8}),
    ]
    signals = signals_from_fraud_network_evidence(raw, **SUBJ)
    assert len(signals) == 2
    rel = next(s for s in signals if s.risk_dimension == "relationship")
    fra = next(s for s in signals if s.risk_dimension == "fraud")
    assert rel.evidence_refs[0].type == "relationship"
    assert fra.evidence_refs[0].type == "transaction"
    # detector output carries no numeric → score stays None (never fabricated)
    assert all(s.score is None for s in signals)
    # network evidence is an inferred structural link, never a fact
    assert all(s.claim_state == EpistemicStatus.INFERRED for s in signals)
    assert rel.evidence_refs[0].confidence is not None  # reused detector confidence


def test_fraud_network_signal_ids_are_deterministic():
    raw = [("shared_ip", ["ent_1", "ent_2"], {"ip": "1.2.3.4"})]
    first = signals_from_fraud_network_evidence(raw, **SUBJ)
    second = signals_from_fraud_network_evidence(raw, **SUBJ)
    assert first[0].signal_id == second[0].signal_id


# ── device risk ─────────────────────────────────────────────────────────────

def test_blocked_device_emits_infrastructure_signal():
    signals = signal_from_device_risk(
        {
            "device_id": "dev_1",
            "risk_state": "blocked",
            "approval_state": "revoked",
            "risk_signals": ["approval_state_withdrawn"],
        },
        **SUBJ,
    )
    assert len(signals) == 1
    assert signals[0].risk_dimension == "infrastructure"
    assert signals[0].claim_state == EpistemicStatus.DERIVED
    assert signals[0].score is None
    assert signals[0].evidence_refs[0].type == "entity"
    assert signals[0].source == "kyber.device_risk"


def test_ok_device_with_no_signals_is_not_a_risk_claim():
    assert signal_from_device_risk({"device_id": "dev_1", "risk_state": "ok"}, **SUBJ) == []


def test_device_risk_string_posture_artifact():
    signals = signal_from_device_risk("suspect", **SUBJ)
    assert len(signals) == 1
    assert signals[0].risk_dimension == "infrastructure"


# ── geo enrichment ──────────────────────────────────────────────────────────

def test_datacenter_geo_emits_geographic_inferred_signal():
    signals = signal_from_geo_lookup(
        {
            "state": "ready",
            "country_code": "US",
            "asn": 15169,
            "asn_class": "datacenter",
            "provider": "maxmind_geolite2",
            "provider_database_version": "2026.08.0",
            "datacenter_likelihood": 0.9,
        },
        **SUBJ,
    )
    assert len(signals) == 1
    assert signals[0].risk_dimension == "geographic"
    assert signals[0].score == pytest.approx(0.9)
    assert signals[0].claim_state == EpistemicStatus.INFERRED
    assert signals[0].detector_version == "2026.08.0"
    assert signals[0].evidence_refs[0].type == "event"


def test_geo_not_ready_or_residential_emits_nothing():
    assert (
        signal_from_geo_lookup(
            {"state": "not_provisioned", "datacenter_likelihood": 0.0}, **SUBJ
        )
        == []
    )
    assert (
        signal_from_geo_lookup(
            {"state": "ready", "asn_class": "network", "datacenter_likelihood": 0.0},
            **SUBJ,
        )
        == []
    )


# ── behavioral scan ─────────────────────────────────────────────────────────

def test_behavioral_scan_maps_families_to_dimensions_without_fabricating_scores():
    scan = {
        "entity_id": "ent_1",
        "signals_computed": 2,
        "signals": {
            "intent_residue": {"confidence": 0.6, "signal_family": "intent_residue"},
            "wallet_friction": {"confidence": 0.4, "signal_family": "wallet_friction"},
        },
        "scanned_at": "2026-09-03T12:00:00Z",
    }
    signals = signal_from_behavioral_scan(scan, **SUBJ)
    dims = {s.risk_dimension for s in signals}
    # heuristic engine output carries calibrated:False → score never promoted
    assert all(s.score is None for s in signals)
    assert all(s.claim_state == EpistemicStatus.DERIVED for s in signals)
    assert dims == {"behavioral", "payment"}


# ── trust vector ────────────────────────────────────────────────────────────

def _trust_dict(**observed):
    from shared.scoring.trust_vector import TRUST_DIMENSIONS

    dims = {}
    for name in TRUST_DIMENSIONS:
        dims[name] = {"value": 0.5, "coverage": "complete", "observed": False}
    dims.update(observed)
    return {"weights_version": "2026.08.0", "dimensions": dims}


def test_trust_vector_inverts_trust_for_risk_except_automation():
    artifact = _trust_dict(
        identity_assurance={"value": 0.8, "coverage": "complete", "observed": True},
        automation_likelihood={"value": 0.9, "coverage": "complete", "observed": True},
    )
    signals = signal_from_trust_vector(artifact, **SUBJ)
    by_dim = {s.risk_dimension: s for s in signals}
    # strong identity trust → LOW identity risk (1 - 0.8 = 0.2)
    assert by_dim["identity"].score == pytest.approx(0.2)
    # high automation likelihood is itself the risk (0.9 → 0.9)
    assert by_dim["agentic"].score == pytest.approx(0.9)


def test_trust_vector_skips_unobserved_dimensions():
    artifact = _trust_dict(
        identity_assurance={"value": 0.8, "coverage": "complete", "observed": False}
    )
    signals = signal_from_trust_vector(artifact, **SUBJ)
    # unobserved dimensions get priors in the trust plane — never a fabricated
    # risk score here.
    assert signals == []


# ── dispatcher + bundle ─────────────────────────────────────────────────────

def test_unknown_producer_fails_closed_with_known_list():
    with pytest.raises(KeyError, match="Known producers"):
        adapt_producer_signal("nope", None, **SUBJ)


def test_evidence_bundle_forbids_misspelled_producer_fields():
    with pytest.raises(ValidationError):
        RiskEvidenceBundle(fraud_reslt={})  # misspelling must not silently pass
