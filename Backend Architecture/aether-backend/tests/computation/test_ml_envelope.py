"""Prediction-envelope + telemetry-honesty regression for ml_serving.

Proves, against the pure helpers in ``services.ml_serving.routes`` (no HTTP path):

  * ``grounded`` is no longer hardcoded to ``1`` — it is ``None`` (unknown) when
    the model returns no grounding evidence, and honest when it does;
  * a missing model confidence is ``None`` (unknown), never a fabricated ``0.0``
    (0 is a claim);
  * journey payloads do not fabricate ``observed_events``;
  * the /predict envelope carries ``feature_schema_hash`` + the feature digest
    that also keys the prediction cache, binding a prediction to its exact
    model + feature context.
"""

from __future__ import annotations

import os
import sys

# Make the ML feature-contract package importable so the envelope's
# feature_schema_hash resolves to a real value here, mirroring how GET /features
# computes it at runtime. Best-effort: absence is tolerated by the test below.
_HERE = os.path.dirname(__file__)
_ML_ROOT = os.path.abspath(
    os.path.join(_HERE, "..", "..", "..", "..", "ML Models", "aether-ml")
)
if os.path.isdir(_ML_ROOT) and _ML_ROOT not in sys.path:
    sys.path.insert(0, _ML_ROOT)

from services.ml_serving.routes import (  # noqa: E402
    _build_payload,
    _derive_confidence,
    _grounded_signal,
    _prediction_cache_hash,
    _prediction_envelope,
)


# --- observed_events must not be fabricated --------------------------------


def test_journey_payload_does_not_fabricate_observed_events():
    payload = _build_payload("journey_prediction", "id-1", {})
    assert payload["observed_events"] == []  # NOT ["page_view"]


def test_journey_payload_passes_through_real_events():
    payload = _build_payload(
        "journey_prediction", "id-1", {"observed_events": ["signup"]}
    )
    assert payload["observed_events"] == ["signup"]


# --- missing confidence is unknown (None), not 0.0 -------------------------


def test_missing_confidence_is_none_not_zero():
    assert _derive_confidence({}) is None
    assert _derive_confidence({"confidence": None}) is None
    assert _derive_confidence(None) is None
    assert _derive_confidence({"other": 1}) is None


def test_present_confidence_is_returned():
    # An explicit 0.0 from the model is an honest datapoint and is kept as-is;
    # only an *omitted* confidence becomes None.
    assert _derive_confidence({"confidence": 0.0}) == 0.0
    assert _derive_confidence({"confidence": 0.83}) == 0.83


# --- grounded is not hardcoded 1 -------------------------------------------


def test_grounded_unknown_is_none_not_one():
    # These serving models return no grounding evidence -> unknown, never 1.
    assert _grounded_signal({}) is None
    assert _grounded_signal({"confidence": 0.9, "prediction": "churn"}) is None
    assert _grounded_signal(None) is None


def test_grounded_reflects_explicit_signal():
    assert _grounded_signal({"grounded": True}) == 1
    assert _grounded_signal({"grounded": False}) == 0
    assert _grounded_signal({"grounded": None}) is None


def test_grounded_derived_from_evidence():
    assert _grounded_signal({"citations": ["doc:1"]}) == 1
    assert _grounded_signal({"citations": []}) == 0
    assert _grounded_signal({"sources": ["s"]}) == 1


# --- envelope carries feature_schema_hash + feature digest -----------------


def test_envelope_carries_schema_hash_and_feature_digest():
    tenant, features, consent = "t1", {"x": 1, "y": 2}, ["marketing"]
    env = _prediction_envelope("churn_prediction", tenant, features, consent)

    # The feature digest is exactly the value that keys the prediction cache,
    # so a response can be traced back to its exact feature payload.
    assert env["feature_digest"] == _prediction_cache_hash(tenant, features, consent)

    # Placeholder fields are always present as honest None (not fabricated).
    assert "calibration_segment" in env and env["calibration_segment"] is None
    assert "drift_status" in env and env["drift_status"] is None

    # feature_schema_hash is always present; real when the contract registry is
    # importable, honest None otherwise — never fabricated.
    assert "feature_schema_hash" in env
    try:
        from common.feature_contracts import compute_schema_hash
    except ImportError:
        assert env["feature_schema_hash"] is None
    else:
        assert env["feature_schema_hash"] == compute_schema_hash("churn_prediction")
        assert env["feature_schema_hash"]  # non-empty real hash


def test_envelope_feature_digest_changes_with_features():
    a = _prediction_envelope("churn_prediction", "t1", {"x": 1}, [])
    b = _prediction_envelope("churn_prediction", "t1", {"x": 2}, [])
    assert a["feature_digest"] != b["feature_digest"]  # binds to feature values
