"""ML cache-key regression: the prediction cache key must bind the tenant,
feature VALUES, and consent scope — not just (model, entity_id)."""

from __future__ import annotations

from shared.cache.cache import CacheKey
from services.ml_serving.routes import _prediction_cache_hash


def test_different_features_different_hash():
    h1 = _prediction_cache_hash("t1", {"x": 1}, [])
    h2 = _prediction_cache_hash("t1", {"x": 2}, [])
    assert h1 != h2  # same entity, different features must NOT collide


def test_same_inputs_same_hash():
    assert _prediction_cache_hash("t1", {"x": 1, "y": 2}, ["a"]) == _prediction_cache_hash(
        "t1", {"y": 2, "x": 1}, ["a"]
    )  # order-independent, deterministic


def test_tenant_and_consent_are_bound():
    base = _prediction_cache_hash("t1", {"x": 1}, ["a"])
    assert _prediction_cache_hash("t2", {"x": 1}, ["a"]) != base  # tenant bound
    assert _prediction_cache_hash("t1", {"x": 1}, ["a", "b"]) != base  # consent bound


def test_cache_key_includes_feature_hash():
    fhash = _prediction_cache_hash("t1", {"x": 1}, [])
    key_a = CacheKey.prediction("churn", "e1", artifact_version="v1", contract_hash=fhash)
    key_b = CacheKey.prediction(
        "churn", "e1", artifact_version="v1",
        contract_hash=_prediction_cache_hash("t1", {"x": 999}, []),
    )
    assert key_a != key_b  # different features -> different cache key
