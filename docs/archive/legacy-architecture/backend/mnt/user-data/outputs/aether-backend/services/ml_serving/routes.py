"""
Aether Service — ML Serving
Model inference API, feature serving, and prediction caching.
Tech: Python (FastAPI) + SageMaker client.
Scaling: Endpoint autoscaling on inference volume.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from shared.cache.cache import TTL, CacheClient, CacheKey
from shared.common.common import APIResponse, BadRequestError
from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger

logger = get_logger("aether.service.ml_serving")
router = APIRouter(prefix="/v1/ml", tags=["ML Serving"])

_cache = CacheClient()
_producer = EventProducer()

# All 9 models from the spec
AVAILABLE_MODELS = [
    # Edge models (3)
    "intent_prediction",
    "bot_detection",
    "session_scorer",
    # Server models (6)
    "identity_gnn",
    "journey_tft",
    "churn_prediction",
    "ltv_prediction",
    "anomaly_detection",
    "campaign_attribution",
]


# ── Models ────────────────────────────────────────────────────────────

class PredictionRequest(BaseModel):
    model_name: str
    entity_id: str
    features: dict[str, Any] = Field(default_factory=dict)
    use_cache: bool = True


class BatchPredictionRequest(BaseModel):
    model_name: str
    entities: list[dict[str, Any]] = Field(..., min_length=1, max_length=100)


class FeatureRequest(BaseModel):
    entity_id: str
    feature_set: str = "default"


# ── Routes ────────────────────────────────────────────────────────────

@router.get("/models")
async def list_models(request: Request):
    """List all available ML models and their status."""
    return APIResponse(data={
        "models": [
            {"name": m, "status": "active", "version": "1.0"}
            for m in AVAILABLE_MODELS
        ]
    }).to_dict()


@router.post("/predict")
async def predict(body: PredictionRequest, request: Request):
    """Run inference on a single entity against a model."""
    tenant = request.state.tenant
    tenant.require_permission("ml:inference")

    if body.model_name not in AVAILABLE_MODELS:
        raise BadRequestError(f"Unknown model: {body.model_name}")

    # Check prediction cache
    if body.use_cache:
        cache_key = CacheKey.prediction(body.model_name, body.entity_id)
        cached = await _cache.get_json(cache_key)
        if cached:
            return APIResponse(data={**cached, "cached": True}).to_dict()

    # --- STUB: call SageMaker endpoint ---
    prediction = {
        "model": body.model_name,
        "entity_id": body.entity_id,
        "score": 0.0,
        "label": "stub",
        "confidence": 0.0,
        "features_used": list(body.features.keys()),
    }

    # Cache the prediction
    cache_key = CacheKey.prediction(body.model_name, body.entity_id)
    await _cache.set_json(cache_key, prediction, TTL.PREDICTION)

    await _producer.publish(Event(
        topic=Topic.PREDICTION_GENERATED,
        tenant_id=tenant.tenant_id,
        source_service="ml_serving",
        payload=prediction,
    ))

    return APIResponse(data={**prediction, "cached": False}).to_dict()


@router.post("/predict/batch")
async def predict_batch(body: BatchPredictionRequest, request: Request):
    """Batch inference for multiple entities."""
    tenant = request.state.tenant
    tenant.require_permission("ml:inference")

    if body.model_name not in AVAILABLE_MODELS:
        raise BadRequestError(f"Unknown model: {body.model_name}")

    # Stub batch predictions
    predictions = [
        {
            "entity_id": entity.get("entity_id", f"unknown_{i}"),
            "score": 0.0,
            "label": "stub",
        }
        for i, entity in enumerate(body.entities)
    ]

    return APIResponse(data={
        "model": body.model_name,
        "predictions": predictions,
        "count": len(predictions),
    }).to_dict()


@router.get("/features/{entity_id}")
async def get_features(entity_id: str, request: Request):
    """Serve pre-computed features for an entity (feature store)."""
    # Stub — replace with SageMaker Feature Store or custom feature pipeline
    return APIResponse(data={
        "entity_id": entity_id,
        "features": {},
        "computed_at": None,
    }).to_dict()
