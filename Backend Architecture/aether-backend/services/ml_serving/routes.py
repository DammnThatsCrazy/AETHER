"""
Aether Service — ML Serving
Model inference API, feature serving, and prediction caching.

This service acts as a gateway to the ML serving API (aether-ml). Requests
are validated, cached, and forwarded to the inference backend. When the ML
serving API is unreachable, cached predictions are returned where available.
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError, ServiceUnavailableError
from shared.cache.cache import CacheClient, CacheKey, TTL
from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger, metrics
from dependencies.providers import get_cache, get_producer

logger = get_logger("aether.service.ml_serving")
router = APIRouter(prefix="/v1/ml", tags=["ML Serving"])

# Lazy-loaded extraction defense layer for post-response watermarking
_defense_layer = None


def _get_defense_layer():
    """Get the extraction defense layer for post-response watermarking.

    Returns None if defense is disabled or the module is not available.
    Loaded once on first use.
    """
    global _defense_layer
    if _defense_layer is not None:
        return _defense_layer
    try:
        from config.settings import settings
        if not settings.extraction_defense.enabled:
            return None
        from security.model_extraction_defense import ExtractionDefenseLayer
        _defense_layer = ExtractionDefenseLayer.from_env()
        logger.info("ML serving: extraction defense layer loaded for watermarking")
    except (ImportError, Exception) as e:
        logger.debug(f"Extraction defense not available for ML serving: {e}")
        _defense_layer = None
    return _defense_layer

# ML serving API base URL — override via env var in production
_ML_SERVING_URL = os.getenv("ML_SERVING_URL", "http://localhost:8080")

AVAILABLE_MODELS = [
    "intent_prediction", "bot_detection", "session_scorer",
    "identity_gnn", "journey_tft", "churn_prediction",
    "ltv_prediction", "anomaly_detection", "campaign_attribution",
]

# Model name → ML serving API endpoint path mapping
_MODEL_ENDPOINTS: dict[str, str] = {
    "intent_prediction": "/v1/predict/intent",
    "bot_detection": "/v1/predict/bot",
    "session_scorer": "/v1/predict/session-score",
    "churn_prediction": "/v1/predict/churn",
    "ltv_prediction": "/v1/predict/ltv",
    "anomaly_detection": "/v1/predict/batch",
    "campaign_attribution": "/v1/predict/attribution",
    "identity_gnn": "/v1/predict/batch",
    "journey_tft": "/v1/predict/journey",
}

# Shared async HTTP client (thread-safe lazy init)
_http_client: Optional[httpx.AsyncClient] = None
_client_lock = __import__("threading").Lock()


def _get_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is not None:
        return _http_client
    with _client_lock:
        if _http_client is None:
            _http_client = httpx.AsyncClient(
                base_url=_ML_SERVING_URL,
                timeout=httpx.Timeout(30.0, connect=5.0),
            )
    return _http_client


class PredictionRequest(BaseModel):
    model_name: str
    entity_id: str
    features: dict[str, Any] = Field(default_factory=dict)
    use_cache: bool = True


class BatchPredictionRequest(BaseModel):
    model_name: str
    entities: list[dict[str, Any]] = Field(..., min_length=1, max_length=100)


@router.get("/models")
async def list_models(request: Request):
    """List all available ML models and their status.

    Attempts to fetch live status from the ML serving API; falls back
    to a static list if the serving API is unreachable.
    """
    client = _get_client()
    try:
        resp = await client.get("/models")
        if resp.status_code == 200:
            return APIResponse(data={"models": resp.json()}).to_dict()
    except httpx.RequestError:
        logger.debug("ML serving API unreachable for /models — returning static list")

    return APIResponse(data={
        "models": [
            {"name": m, "status": "unknown", "version": "n/a"}
            for m in AVAILABLE_MODELS
        ]
    }).to_dict()


@router.post("/predict")
async def predict(
    body: PredictionRequest,
    request: Request,
    cache: CacheClient = Depends(get_cache),
    producer: EventProducer = Depends(get_producer),
):
    """Run inference on a single entity against a model.

    Forwards the request to the ML serving API for real-time inference.
    Results are cached and published to the event bus.
    """
    tenant = request.state.tenant
    tenant.require_permission("ml:inference")

    if body.model_name not in AVAILABLE_MODELS:
        raise BadRequestError(f"Unknown model: {body.model_name}")

    # 1. Check cache
    if body.use_cache:
        cache_key = CacheKey.prediction(body.model_name, body.entity_id)
        cached = await cache.get_json(cache_key)
        if cached:
            metrics.increment("ml_cache_hit", labels={"model": body.model_name})
            return APIResponse(data={**cached, "cached": True}).to_dict()

    # 2. Forward to ML serving API
    t0 = time.perf_counter()
    endpoint = _MODEL_ENDPOINTS.get(body.model_name, "/v1/predict/batch")
    client = _get_client()

    # Build request payload based on model type
    if body.model_name in ("intent_prediction", "bot_detection", "session_scorer"):
        payload = {"session_id": body.entity_id, "features": body.features}
    elif body.model_name in ("churn_prediction", "ltv_prediction"):
        payload = {"identity_id": body.entity_id, "features": body.features}
    elif body.model_name == "journey_tft":
        events = body.features.get("observed_events", ["page_view"])
        payload = {"identity_id": body.entity_id, "observed_events": events}
    elif body.model_name == "campaign_attribution":
        touchpoints = body.features.get("touchpoints", [])
        payload = {"conversion_id": body.entity_id, "touchpoints": touchpoints}
    else:
        # Generic batch-style request for other models
        payload = {"model": body.model_name, "instances": [body.features]}

    try:
        api_key = request.headers.get("X-API-Key", "")
        headers = {"X-API-Key": api_key} if api_key else {}
        resp = await client.post(endpoint, json=payload, headers=headers)

        if resp.status_code == 200:
            try:
                ml_result = resp.json()
            except Exception:
                logger.error("ML serving returned invalid JSON for model %s", body.model_name)
                raise ServiceUnavailableError("ML inference returned malformed response")
            latency_ms = (time.perf_counter() - t0) * 1000

            # 2b. Apply post-response watermarking (extraction defense)
            defense = _get_defense_layer()
            if defense is not None:
                api_key = request.headers.get("X-API-Key", "")
                risk_score = getattr(request.state, "extraction_risk", 0.0)
                post_result = defense.post_response(
                    api_key=api_key,
                    raw_output=ml_result,
                    features=body.features,
                    risk_score=risk_score,
                )
                ml_result = post_result.modified_output

            prediction = {
                "model": body.model_name,
                "entity_id": body.entity_id,
                "result": ml_result,
                "latency_ms": round(latency_ms, 2),
            }

            # 3. Cache result
            cache_key = CacheKey.prediction(body.model_name, body.entity_id)
            await cache.set_json(cache_key, prediction, TTL.PREDICTION)

            # 4. Publish event
            await producer.publish(Event(
                topic=Topic.PREDICTION_GENERATED,
                tenant_id=tenant.tenant_id,
                source_service="ml_serving",
                payload=prediction,
            ))

            metrics.increment("ml_predictions", labels={"model": body.model_name})
            return APIResponse(data={**prediction, "cached": False}).to_dict()

        logger.warning(
            "ML serving API returned %d for model %s",
            resp.status_code, body.model_name,
        )
        raise ServiceUnavailableError(
            f"ML serving API returned {resp.status_code}"
        )

    except httpx.RequestError as exc:
        logger.error("ML serving API unreachable: %s", exc)
        raise ServiceUnavailableError(
            "ML inference backend is temporarily unavailable"
        )


@router.post("/predict/batch")
async def predict_batch(body: BatchPredictionRequest, request: Request):
    """Batch inference for multiple entities.

    Forwards the full batch to the ML serving API's batch endpoint.
    """
    tenant = request.state.tenant
    tenant.require_permission("ml:inference")

    if body.model_name not in AVAILABLE_MODELS:
        raise BadRequestError(f"Unknown model: {body.model_name}")

    client = _get_client()
    payload = {
        "model": body.model_name,
        "instances": [entity.get("features", entity) for entity in body.entities],
    }

    try:
        api_key = request.headers.get("X-API-Key", "")
        headers = {"X-API-Key": api_key} if api_key else {}
        resp = await client.post("/v1/predict/batch", json=payload, headers=headers)

        if resp.status_code == 200:
            ml_result = resp.json()
            metrics.increment("ml_batch_predictions", labels={"model": body.model_name})
            return APIResponse(data={
                "model": body.model_name,
                "predictions": ml_result.get("predictions", []),
                "count": ml_result.get("count", len(body.entities)),
            }).to_dict()

        raise ServiceUnavailableError(
            f"ML serving API returned {resp.status_code}"
        )

    except httpx.RequestError as exc:
        logger.error("ML serving API unreachable for batch: %s", exc)
        raise ServiceUnavailableError(
            "ML inference backend is temporarily unavailable"
        )


@router.get("/features/{entity_id}")
async def get_features(entity_id: str, request: Request, cache: CacheClient = Depends(get_cache)):
    """Serve pre-computed features for an entity.

    Looks up cached features from the feature store. Returns empty if
    no features have been computed yet.
    """
    cache_key = CacheKey.custom(f"features:{entity_id}")
    cached = await cache.get_json(cache_key)
    if cached:
        metrics.increment("feature_store_hit")
        return APIResponse(data={
            "entity_id": entity_id,
            "features": cached.get("features", {}),
            "computed_at": cached.get("computed_at"),
        }).to_dict()

    metrics.increment("feature_store_miss")
    return APIResponse(data={
        "entity_id": entity_id,
        "features": {},
        "computed_at": None,
        "message": "No pre-computed features available. Features are populated after the first prediction or via batch pipeline.",
    }).to_dict()
