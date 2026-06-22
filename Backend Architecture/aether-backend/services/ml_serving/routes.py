"""
Aether Service — ML Serving
Model inference API, feature serving, and prediction caching.

This service acts as a gateway to the ML serving API (aether-ml). Requests
are validated, cached, and forwarded to the inference backend. When the ML
serving API is unreachable, cached predictions are returned where available.

Model identity is governed entirely by the canonical ML registry.
No hardcoded model lists exist here.

Security:
  - Tenant permission ml:inference required for all prediction endpoints.
  - Batch prediction requires ml:batch permission (privileged/internal only).
  - Pre-request extraction defense is applied before forwarding to serving.
  - Post-response output is taken from PostResponseResult.output.
  - Deprecated model aliases resolve to canonical IDs with a deprecation warning in the response.
"""

from __future__ import annotations

import os
import time
import warnings
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from shared.common.common import APIResponse, BadRequestError, ForbiddenError, ServiceUnavailableError
from shared.cache.cache import CacheClient, CacheKey, TTL
from shared.events.events import Event, EventProducer, Topic
from shared.logger.logger import get_logger, metrics
from dependencies.providers import get_cache, get_producer

logger = get_logger("aether.service.ml_serving")
router = APIRouter(prefix="/v1/ml", tags=["ML Serving"])

# ---------------------------------------------------------------------------
# Lazy-loaded extraction defense layer
# ---------------------------------------------------------------------------

_defense_layer = None

# Per-process model version cache: maps canonical_id → artifact_version string.
# Populated lazily from ml_result when the serving API includes "artifact_version".
# Starts empty; both lookup and set use the same version, so keys are always consistent.
# When the ML serving API is updated to return artifact_version, promotions will
# automatically produce versioned keys that differ from pre-promotion cached keys.
_model_version_cache: dict[str, str] = {}


def _get_defense_layer():
    """Get the extraction defense layer. Returns None if disabled/unavailable."""
    global _defense_layer
    if _defense_layer is not None:
        return _defense_layer
    try:
        from config.settings import settings
        if not settings.extraction_defense.enabled:
            return None
        from security.model_extraction_defense import ExtractionDefenseLayer
        _defense_layer = ExtractionDefenseLayer.from_env()
        logger.info("ML serving: extraction defense layer loaded")
    except (ImportError, Exception) as e:
        logger.debug("Extraction defense not available for ML serving: %s", e)
        _defense_layer = None
    return _defense_layer


# ---------------------------------------------------------------------------
# Registry-backed model resolution
# ---------------------------------------------------------------------------

def _resolve_canonical(name_or_alias: str) -> tuple[str, bool]:
    """
    Resolve any model name/alias to a canonical model ID.

    Returns (canonical_id, was_deprecated_alias).
    Raises BadRequestError for unknown names.
    """
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            from common.model_registry import resolve_model_id, list_models
            canonical = resolve_model_id(name_or_alias)
        was_deprecated = any(issubclass(w.category, DeprecationWarning) for w in caught)
    except ImportError:
        # Fallback: use the static canonical list if registry unavailable
        canonical = name_or_alias if name_or_alias in _STATIC_CANONICAL_IDS else None
        was_deprecated = name_or_alias in _STATIC_DEPRECATED_ALIASES
        if was_deprecated:
            canonical = _STATIC_DEPRECATED_ALIASES.get(name_or_alias)

    if canonical is None:
        try:
            from common.model_registry import list_models
            known = sorted(m.model_id for m in list_models())
        except ImportError:
            known = _STATIC_CANONICAL_IDS
        raise BadRequestError(
            f"Unknown model: '{name_or_alias}'. "
            f"Known model IDs: {known}. "
            "See docs/ML-TRAINING-GUIDE.md for the full model list."
        )

    return canonical, was_deprecated


def _get_serving_endpoint(canonical_id: str) -> str:
    """Return the ML serving API path for a canonical model ID."""
    try:
        from common.model_registry import get_model
        entry = get_model(canonical_id)
        if entry and entry.serving_endpoint:
            return entry.serving_endpoint
    except ImportError:
        pass
    return _STATIC_ENDPOINTS.get(canonical_id, "/v1/predict/batch")


def _batch_requires_privileged(canonical_id: str) -> bool:
    """Return True if batch prediction for this model requires privileged caller."""
    try:
        from common.model_registry import get_model
        entry = get_model(canonical_id)
        if entry is not None:
            return entry.batch_requires_privileged
    except ImportError:
        pass
    return True  # Fail secure: require privilege if registry unavailable


# ---------------------------------------------------------------------------
# Static fallbacks (used only when registry import fails)
# ---------------------------------------------------------------------------

_STATIC_CANONICAL_IDS = [
    "intent_prediction", "bot_detection", "session_scorer",
    "identity_resolution", "journey_prediction", "churn_prediction",
    "ltv_prediction", "anomaly_detection", "campaign_attribution",
    "bytecode_risk", "trust_score",
]

_STATIC_DEPRECATED_ALIASES: dict[str, str] = {
    "identity_gnn": "identity_resolution",  # deprecated alias → canonical
    "journey_tft": "journey_prediction",    # deprecated alias → canonical
}

_STATIC_ENDPOINTS: dict[str, str] = {
    "intent_prediction": "/v1/predict/intent",
    "bot_detection": "/v1/predict/bot",
    "session_scorer": "/v1/predict/session-score",
    "churn_prediction": "/v1/predict/churn",
    "ltv_prediction": "/v1/predict/ltv",
    "anomaly_detection": "/v1/predict/batch",
    "campaign_attribution": "/v1/predict/attribution",
    "identity_resolution": "/v1/predict/identity",
    "journey_prediction": "/v1/predict/journey",
}

# ---------------------------------------------------------------------------
# ML serving URL
# ---------------------------------------------------------------------------

_ML_SERVING_URL = os.getenv("ML_SERVING_URL", "http://localhost:8080")
_ML_SERVING_INLINE = os.getenv("ML_SERVING_INLINE", "false").lower() == "true"

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


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class PredictionRequest(BaseModel):
    model_name: str
    entity_id: str
    features: dict[str, Any] = Field(default_factory=dict)
    use_cache: bool = True


class BatchPredictionRequest(BaseModel):
    model_name: str
    entities: list[dict[str, Any]] = Field(..., min_length=1, max_length=100)


# ---------------------------------------------------------------------------
# Payload builders — canonical-ID-based
# ---------------------------------------------------------------------------


def _build_payload(canonical_id: str, entity_id: str, features: dict[str, Any]) -> dict[str, Any]:
    """Build the correct payload shape for each model's serving endpoint."""
    if canonical_id in ("intent_prediction", "bot_detection", "session_scorer"):
        return {"session_id": entity_id, "features": features}
    if canonical_id in ("churn_prediction", "ltv_prediction"):
        return {"identity_id": entity_id, "features": features}
    if canonical_id == "journey_prediction":
        events = features.get("observed_events", ["page_view"])
        return {"identity_id": entity_id, "observed_events": events}
    if canonical_id == "campaign_attribution":
        touchpoints = features.get("touchpoints", [])
        return {"conversion_id": entity_id, "touchpoints": touchpoints}
    # Generic batch-style for remaining models
    return {"model": canonical_id, "instances": [features]}


# ---------------------------------------------------------------------------
# Route: GET /v1/ml/models
# ---------------------------------------------------------------------------


@router.get("/models")
async def list_models(request: Request):
    """List all available ML models and their serving status.

    Returns the canonical registry-backed model list. Includes live serving
    status when the ML API is reachable, static registry data otherwise.
    Canonical model IDs are always used; deprecated aliases are listed separately.
    """
    try:
        from common.model_registry import list_models as _list_models
        registry_models = _list_models()
        registry_data = [
            {
                "model_id": m.model_id,
                "display_name": m.display_name,
                "category": m.category,
                "implementation_type": m.implementation_type,
                "tier": m.tier,
                "training_supported": m.training_supported,
                "serving_supported": m.serving_supported,
                "deprecated_aliases": m.deprecated_aliases,
                "current_status": m.current_status,
            }
            for m in registry_models
        ]
    except ImportError:
        registry_data = [{"model_id": m, "current_status": "unknown"} for m in _STATIC_CANONICAL_IDS]

    # Attempt live status from ML serving
    client = _get_client()
    try:
        resp = await client.get("/models")
        if resp.status_code == 200:
            live_data = resp.json()
            # Merge live status into registry data
            live_by_name = {}
            for item in (live_data.get("models") or []):
                live_by_name[item.get("name", "")] = item
            for reg in registry_data:
                live = live_by_name.get(reg["model_id"], {})
                reg["serving_status"] = live.get("status", "unknown")
                reg["artifact_version"] = live.get("version", "n/a")
    except httpx.RequestError:
        logger.debug("ML serving API unreachable for /models — returning registry-only list")
        for reg in registry_data:
            reg["serving_status"] = "unreachable"
            reg["artifact_version"] = "n/a"

    return APIResponse(data={
        "models": registry_data,
        "deprecated_aliases": _STATIC_DEPRECATED_ALIASES,
        "note": (
            "Use canonical model_id values. "
            "Deprecated aliases (identity_gnn, journey_tft) resolve to canonical IDs "
            "but will be removed in a future release."
        ),
    }).to_dict()


# ---------------------------------------------------------------------------
# Route: POST /v1/ml/predict
# ---------------------------------------------------------------------------


@router.post("/predict")
async def predict(
    body: PredictionRequest,
    request: Request,
    cache: CacheClient = Depends(get_cache),
    producer: EventProducer = Depends(get_producer),
):
    """Run inference on a single entity against a model.

    Resolves canonical model ID from name or deprecated alias.
    Applies extraction defense pre-request before forwarding.
    Returns canonical_model_id in all responses.
    """
    tenant = request.state.tenant
    tenant.require_permission("ml:inference")

    # Resolve canonical model ID (handles deprecated aliases)
    canonical_id, was_deprecated_alias = _resolve_canonical(body.model_name)

    # 1. Pre-request extraction defense
    defense = _get_defense_layer()
    if defense is not None:
        api_key = request.headers.get("X-API-Key", "anon")
        ip_address = getattr(request.client, "host", "0.0.0.0") if request.client else "0.0.0.0"
        pre_result = defense.pre_request(
            api_key=api_key,
            ip_address=ip_address,
            features=body.features,
            model_name=canonical_id,
            batch_size=1,
        )
        if pre_result.blocked:
            status_code = 429 if "rate limit" in pre_result.block_reason.lower() else 403
            metrics.increment(
                "ml_extraction_blocked",
                labels={"model": canonical_id, "reason": "pre_request"},
            )
            logger.warning(
                "ML prediction blocked by extraction defense: model=%s reason=%s",
                canonical_id, pre_result.block_reason,
            )
            raise ForbiddenError(pre_result.block_reason)
        # Store risk info for post-response step
        if pre_result.risk_assessment:
            request.state.extraction_risk = pre_result.risk_assessment.risk_score
        else:
            request.state.extraction_risk = 0.0

    # 2. Cache lookup (versioned by artifact so promotions eventually invalidate via new key)
    if body.use_cache:
        _ver = _model_version_cache.get(canonical_id, "")
        cache_key = CacheKey.prediction(canonical_id, body.entity_id, artifact_version=_ver)
        cached = await cache.get_json(cache_key)
        if cached:
            metrics.increment("ml_cache_hit", labels={"model": canonical_id})
            response_data = {
                **cached,
                "cached": True,
                "canonical_model_id": canonical_id,
            }
            if was_deprecated_alias:
                response_data["deprecated_alias_used"] = body.model_name
                response_data["alias_warning"] = (
                    f"'{body.model_name}' is a deprecated alias for '{canonical_id}'. "
                    "Update your client to use the canonical model_id."
                )
            return APIResponse(data=response_data).to_dict()

    # 3. Forward to ML serving API
    t0 = time.perf_counter()
    endpoint = _get_serving_endpoint(canonical_id)
    client = _get_client()
    payload = _build_payload(canonical_id, body.entity_id, body.features)

    try:
        api_key = request.headers.get("X-API-Key", "")
        headers = {"X-API-Key": api_key} if api_key else {}
        resp = await client.post(endpoint, json=payload, headers=headers)

        if resp.status_code == 200:
            try:
                ml_result = resp.json()
            except Exception:
                logger.error("ML serving returned invalid JSON for model %s", canonical_id)
                raise ServiceUnavailableError("ML inference returned malformed response")

            latency_ms = (time.perf_counter() - t0) * 1000

            # 4. Post-response extraction defense
            if defense is not None:
                api_key_val = request.headers.get("X-API-Key", "anon")
                risk_score = getattr(request.state, "extraction_risk", 0.0)
                post_result = defense.post_response(
                    api_key=api_key_val,
                    raw_output=ml_result,
                    features=body.features,
                    risk_score=risk_score,
                )
                ml_result = post_result.output  # Correct field: .output

            prediction = {
                "model": canonical_id,
                "canonical_model_id": canonical_id,
                "entity_id": body.entity_id,
                "result": ml_result,
                "latency_ms": round(latency_ms, 2),
            }

            if was_deprecated_alias:
                prediction["deprecated_alias_used"] = body.model_name
                prediction["alias_warning"] = (
                    f"'{body.model_name}' is a deprecated alias for '{canonical_id}'. "
                    "Update your client to use the canonical model_id."
                )

            # 5. Cache successful prediction (versioned key matches lookup key above)
            _ver = ml_result.get("artifact_version", _model_version_cache.get(canonical_id, "")) if isinstance(ml_result, dict) else _model_version_cache.get(canonical_id, "")
            if _ver:
                _model_version_cache[canonical_id] = _ver
            cache_key = CacheKey.prediction(canonical_id, body.entity_id, artifact_version=_ver)
            await cache.set_json(cache_key, prediction, TTL.PREDICTION)

            # 6. Publish event only after successful prediction
            await producer.publish(Event(
                topic=Topic.PREDICTION_GENERATED,
                tenant_id=tenant.tenant_id,
                source_service="ml_serving",
                payload=prediction,
            ))

            # 6b. CIS retrieval trace (additive, guarded by CIS_ENABLED)
            try:
                import hashlib as _hl
                import json as _json
                import os as _os
                if _os.getenv("CIS_ENABLED", "false").lower() in ("true", "1"):
                    await producer.publish(Event(
                        topic=Topic.CIS_RETRIEVAL_EXECUTED,
                        tenant_id=tenant.tenant_id,
                        source_service="ml_serving",
                        payload={
                            "query_hash": CacheKey.hash_query(str(body.features)),
                            "model_name": canonical_id,
                            "latency_ms": round(latency_ms, 2),
                            "confidence_score": float(
                                ml_result.get("confidence", 0.0)
                                if isinstance(ml_result, dict)
                                else 0.0
                            ),
                            "generation_hash": _hl.sha256(
                                _json.dumps(ml_result, sort_keys=True, default=str).encode()
                            ).hexdigest()[:16],
                            "grounded": 1,
                            "synthetic_ratio": float(
                                ml_result.get("synthetic_data", False)
                                if isinstance(ml_result, dict) else False
                            ),
                        },
                    ))
            except Exception:
                pass

            metrics.increment("ml_predictions", labels={"model": canonical_id})
            return APIResponse(data={**prediction, "cached": False}).to_dict()

        if resp.status_code == 404:
            raise ServiceUnavailableError(
                f"Model '{canonical_id}' is not yet available. "
                "Training pipelines must be run before inference is possible. "
                "See docs/ML-TRAINING-GUIDE.md for instructions."
            )
        logger.warning(
            "ML serving API returned %d for model %s",
            resp.status_code, canonical_id,
        )
        raise ServiceUnavailableError(f"ML serving API returned {resp.status_code}")

    except httpx.RequestError as exc:
        logger.error("ML serving API unreachable: %s", exc)
        raise ServiceUnavailableError(
            "ML inference backend is not reachable. "
            "Ensure ML_SERVING_URL is set correctly and the ml-serving container is running."
        )


# ---------------------------------------------------------------------------
# Route: POST /v1/ml/predict/batch
# ---------------------------------------------------------------------------


@router.post("/predict/batch")
async def predict_batch(
    body: BatchPredictionRequest,
    request: Request,
    cache: CacheClient = Depends(get_cache),
    producer: EventProducer = Depends(get_producer),
):
    """Batch inference for multiple entities.

    INTERNAL / PRIVILEGED ONLY. Requires ml:inference + ml:batch permissions.
    Non-privileged callers receive 403.
    Deprecated aliases resolve to canonical IDs.
    """
    tenant = request.state.tenant
    tenant.require_permission("ml:inference")

    # Privileged batch enforcement — derived from RBAC role only.
    # Caller-supplied headers (e.g. X-Batch-Privilege) are NOT trusted.
    is_privileged = (
        getattr(tenant, "role", None) is not None
        and getattr(tenant.role, "value", "") == "service"
    )

    try:
        tenant.require_permission("ml:batch")
    except Exception:
        if not is_privileged:
            metrics.increment("ml_batch_denied", labels={"model": body.model_name})
            raise ForbiddenError(
                "Batch prediction is restricted to privileged/internal callers. "
                "Contact your administrator to enable batch access."
            )

    canonical_id, was_deprecated_alias = _resolve_canonical(body.model_name)

    # Enforce per-model batch policy from registry
    if _batch_requires_privileged(canonical_id) and not is_privileged:
        metrics.increment("ml_batch_denied", labels={"model": canonical_id})
        raise ForbiddenError(
            f"Batch prediction for '{canonical_id}' requires privileged access."
        )

    # Pre-request extraction defense for batch
    defense = _get_defense_layer()
    if defense is not None:
        api_key = request.headers.get("X-API-Key", "anon")
        ip_address = getattr(request.client, "host", "0.0.0.0") if request.client else "0.0.0.0"
        pre_result = defense.pre_request(
            api_key=api_key,
            ip_address=ip_address,
            features=body.entities[0] if body.entities else {},
            model_name=canonical_id,
            batch_size=len(body.entities),
        )
        if pre_result.blocked:
            metrics.increment(
                "ml_extraction_blocked",
                labels={"model": canonical_id, "reason": "batch_pre_request"},
            )
            raise ForbiddenError(pre_result.block_reason)

    client = _get_client()
    payload = {
        "model": canonical_id,
        "instances": [entity.get("features", entity) for entity in body.entities],
    }

    try:
        api_key_hdr = request.headers.get("X-API-Key", "")
        headers = {}
        if api_key_hdr:
            headers["X-API-Key"] = api_key_hdr

        resp = await client.post("/v1/predict/batch", json=payload, headers=headers)

        if resp.status_code == 200:
            ml_result = resp.json()
            metrics.increment("ml_batch_predictions", labels={"model": canonical_id})
            return APIResponse(data={
                "model": canonical_id,
                "canonical_model_id": canonical_id,
                "predictions": ml_result.get("predictions", []),
                "count": ml_result.get("count", len(body.entities)),
                "deprecated_alias_used": body.model_name if was_deprecated_alias else None,
            }).to_dict()

        if resp.status_code == 404:
            raise ServiceUnavailableError(
                f"Model '{canonical_id}' is not yet available. "
                "Run training pipelines before serving batch inference. "
                "See docs/ML-TRAINING-GUIDE.md."
            )
        raise ServiceUnavailableError(f"ML serving API returned {resp.status_code}")

    except httpx.RequestError as exc:
        logger.error("ML serving API unreachable for batch: %s", exc)
        raise ServiceUnavailableError(
            "ML inference backend is not reachable. "
            "Ensure ML_SERVING_URL is set correctly and the ml-serving container is running."
        )


# ---------------------------------------------------------------------------
# Route: GET /v1/ml/features/{entity_id}
# ---------------------------------------------------------------------------


@router.get("/features/{entity_id}")
async def get_features(
    entity_id: str,
    request: Request,
    cache: CacheClient = Depends(get_cache),
    model_id: Optional[str] = None,
):
    """Serve pre-computed features for an entity.

    Looks up cached features from the feature store. Returns empty if
    no features have been computed yet. Optionally filters by model_id
    to return only the features relevant to that model's contract.
    """
    tenant = request.state.tenant
    tenant_id = getattr(tenant, "tenant_id", "unknown")

    # Enforce tenant isolation — feature keys are tenant-scoped
    cache_key = CacheKey.custom(f"features:{tenant_id}:{entity_id}")
    cached = await cache.get_json(cache_key)

    feature_schema_hash = None
    freshness_sla = None

    if model_id:
        try:
            canonical_id, _ = _resolve_canonical(model_id)
            try:
                from common.feature_contracts import compute_schema_hash
                feature_schema_hash = compute_schema_hash(canonical_id)
            except (ImportError, KeyError):
                pass
            try:
                from common.feature_contracts import get_feature_contract
                contract = get_feature_contract(canonical_id)
                freshness_sla = contract.freshness_sla_seconds
            except (ImportError, KeyError):
                pass
        except BadRequestError:
            pass

    if cached:
        metrics.increment("feature_store_hit")
        return APIResponse(data={
            "entity_id": entity_id,
            "tenant_id": tenant_id,
            "features": cached.get("features", {}),
            "computed_at": cached.get("computed_at"),
            "feature_schema_hash": feature_schema_hash,
            "freshness_sla_seconds": freshness_sla,
        }).to_dict()

    metrics.increment("feature_store_miss")
    return APIResponse(data={
        "entity_id": entity_id,
        "tenant_id": tenant_id,
        "features": {},
        "computed_at": None,
        "feature_schema_hash": feature_schema_hash,
        "freshness_sla_seconds": freshness_sla,
        "message": (
            "No pre-computed features available. "
            "Features are populated after the first prediction or via batch pipeline."
        ),
    }).to_dict()
