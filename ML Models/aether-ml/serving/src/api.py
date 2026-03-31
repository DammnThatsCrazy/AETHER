"""
Aether ML -- Model Serving API

FastAPI inference server supporting all 9 models with caching, latency tracking,
batch prediction, and health monitoring.

Deployed as: ECS Fargate service behind ALB, or SageMaker endpoint.
"""

from __future__ import annotations

import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("aether.serving")

# ---------------------------------------------------------------------------
# Extraction defense — lazy import to avoid hard dependency
# ---------------------------------------------------------------------------
_defense_layer = None


def _get_defense_layer():
    """Lazy-init the extraction defense layer from env config."""
    global _defense_layer
    if _defense_layer is not None:
        return _defense_layer

    if os.getenv("ENABLE_EXTRACTION_DEFENSE", "false").lower() != "true":
        return None

    try:
        from security.model_extraction_defense import ExtractionDefenseLayer
        _defense_layer = ExtractionDefenseLayer.from_env()
        logger.info("Extraction defense layer loaded")
    except ImportError:
        logger.debug("Extraction defense module not available — skipping")
        _defense_layer = None
    return _defense_layer


# =============================================================================
# REQUEST / RESPONSE SCHEMAS
# =============================================================================


class PredictionRequest(BaseModel):
    """Generic single-instance prediction request."""

    features: dict[str, Any]


class PredictionResponse(BaseModel):
    """Generic single-instance prediction response."""

    prediction: Any
    model: str
    version: str
    latency_ms: float


class IntentPredictionRequest(BaseModel):
    """Request schema for real-time intent prediction."""

    session_id: str
    features: dict[str, float]


class IntentPredictionResponse(BaseModel):
    """Response schema for intent prediction."""

    session_id: str
    predicted_action: str
    confidence: float
    exit_risk: float
    conversion_probability: float
    journey_stage: str
    latency_ms: float


class BotDetectionRequest(BaseModel):
    """Request schema for bot vs human classification."""

    session_id: str
    features: dict[str, float]


class BotDetectionResponse(BaseModel):
    """Response schema for bot detection."""

    session_id: str
    is_bot: bool
    confidence: float
    bot_type: str
    latency_ms: float


class SessionScoreRequest(BaseModel):
    """Request schema for session engagement scoring."""

    session_id: str
    features: dict[str, float]


class SessionScoreResponse(BaseModel):
    """Response schema for session scoring."""

    session_id: str
    engagement_score: int
    conversion_probability: float
    recommended_intervention: str
    latency_ms: float


class ChurnPredictionRequest(BaseModel):
    """Request schema for churn risk prediction."""

    identity_id: str
    features: Optional[dict[str, float]] = None


class ChurnPredictionResponse(BaseModel):
    """Response schema for churn prediction."""

    identity_id: str
    churn_probability: float
    risk_segment: str
    top_factors: list[str]
    latency_ms: float


class LTVPredictionRequest(BaseModel):
    """Request schema for lifetime value prediction."""

    identity_id: str
    features: Optional[dict[str, float]] = None


class LTVPredictionResponse(BaseModel):
    """Response schema for LTV prediction."""

    identity_id: str
    predicted_ltv: float
    latency_ms: float


class JourneyPredictionRequest(BaseModel):
    """Request schema for journey step prediction."""

    identity_id: str
    observed_events: list[str]
    n_steps: int = Field(default=5, ge=1, le=50)


class JourneyPredictionResponse(BaseModel):
    """Response schema for journey prediction."""

    identity_id: str
    predicted_journey: list[dict[str, Any]]
    conversion_reached: bool
    latency_ms: float


class AttributionRequest(BaseModel):
    """Request schema for multi-touch attribution."""

    conversion_id: str
    touchpoints: list[dict[str, Any]]
    method: str = Field(default="shapley", pattern="^(shapley|linear|time_decay|position_based)$")


class AttributionResponse(BaseModel):
    """Response schema for attribution."""

    conversion_id: str
    attribution: list[dict[str, Any]]
    method: str
    latency_ms: float


class BatchPredictionRequest(BaseModel):
    """Request schema for batch prediction across any model."""

    model: str
    instances: list[dict[str, Any]]


class BatchPredictionResponse(BaseModel):
    """Response schema for batch prediction."""

    model: str
    predictions: list[dict[str, Any]]
    count: int
    total_latency_ms: float


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str
    models_loaded: list[str]
    uptime_seconds: float


class ModelInfo(BaseModel):
    """Metadata about a loaded model."""

    name: str
    version: str
    type: str  # "edge" or "server"
    status: str  # "loaded", "error", "not_loaded"


# =============================================================================
# TEST / FALLBACK STUB MODELS
# =============================================================================


class _StubIntentModel:
    version = "test-stub"

    def predict_full(self, df: pd.DataFrame) -> dict[str, Any]:
        n = len(df)
        action_proba = np.tile(np.array([[0.1, 0.2, 0.6, 0.1]]), (n, 1))
        return {
            "action": ["browse"] * n,
            "action_proba": action_proba,
            "exit_risk": np.full(n, 0.2),
            "conversion_proba": np.full(n, 0.35),
        }


class _StubBotModel:
    version = "test-stub"

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return np.zeros(len(df), dtype=int)

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        return np.tile(np.array([[0.8, 0.2]]), (len(df), 1))


class _StubSessionModel:
    version = "test-stub"

    def predict_full(self, df: pd.DataFrame) -> dict[str, Any]:
        n = len(df)
        return {
            "engagement_score": np.full(n, 50),
            "conversion_proba": np.full(n, 0.4),
        }


class _StubChurnModel:
    version = "test-stub"

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return np.full(len(df), 0.25)

    def predict_with_factors(self, df: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({
            "churn_probability": np.full(len(df), 0.25),
            "top_factor_1": ["days_since_last_visit"] * len(df),
            "top_factor_2": ["session_count_30d"] * len(df),
            "top_factor_3": ["email_open_rate"] * len(df),
        })


class _StubLTVModel:
    version = "test-stub"

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return np.full(len(df), 123.45)


class _StubJourneyModel:
    version = "test-stub"

    def predict_journey(self, df: pd.DataFrame, n_steps: int = 5) -> list[dict[str, Any]]:
        return [{"predicted_journey": [{"event": "browse", "probability": 0.5}] * n_steps, "conversion_reached": False}]


class _StubAttributionModel:
    version = "test-stub"

    def attribute(self, journeys: pd.DataFrame, method: str = "linear") -> pd.DataFrame:
        rows = journeys.copy()
        denom = max(len(rows), 1)
        rows["credit"] = 1.0 / denom
        return rows[[col for col in rows.columns if col in {"channel", "touchpoint_index", "conversion_value", "credit"}]]


class _StubIdentityModel:
    version = "test-stub"

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return np.ones(len(df), dtype=int)


class _StubAnomalyModel:
    version = "test-stub"

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        return np.zeros(len(df), dtype=int)


# =============================================================================
# MODEL SERVER
# =============================================================================

# Canonical model names used throughout the serving layer.
MODEL_NAMES: list[str] = [
    "intent_prediction",
    "bot_detection",
    "session_scorer",
    "churn_prediction",
    "ltv_prediction",
    "journey_prediction",
    "campaign_attribution",
    "anomaly_detection",
    "identity_resolution",
]

# Classification of each model as edge (real-time, sub-10ms) or server (batch-capable).
MODEL_TYPES: dict[str, str] = {
    "intent_prediction": "edge",
    "bot_detection": "edge",
    "session_scorer": "edge",
    "churn_prediction": "server",
    "ltv_prediction": "server",
    "journey_prediction": "server",
    "campaign_attribution": "server",
    "anomaly_detection": "server",
    "identity_resolution": "server",
}


class ModelServer:
    """
    Manages model loading, lifecycle, and inference dispatch.

    On startup the server scans ``models_dir`` for serialized model artifacts,
    loading each model into memory.  Individual prediction endpoints delegate
    to ``predict()`` which looks up the in-memory model instance and runs
    inference.
    """

    def __init__(self, models_dir: str = "/opt/ml/models") -> None:
        self.models_dir = Path(models_dir)
        self._models: dict[str, Any] = {}
        self._versions: dict[str, str] = {}
        self._statuses: dict[str, str] = {name: "not_loaded" for name in MODEL_NAMES}
        self.start_time: float = time.time()

    # --------------------------------------------------------------------- #
    # Model loading
    # --------------------------------------------------------------------- #

    def load_all_models(self) -> list[str]:
        """Attempt to load every known model from disk.

        Returns a list of model names that loaded successfully.
        """
        loaders: dict[str, Any] = {
            "intent_prediction": self._load_intent,
            "bot_detection": self._load_bot,
            "session_scorer": self._load_session,
            "churn_prediction": self._load_churn,
            "ltv_prediction": self._load_ltv,
            "journey_prediction": self._load_journey,
            "campaign_attribution": self._load_attribution,
            "anomaly_detection": self._load_anomaly,
            "identity_resolution": self._load_identity,
        }

        loaded: list[str] = []
        for name, loader in loaders.items():
            model_path = self.models_dir / name
            if not model_path.exists():
                logger.debug("Model artifact not found: %s", model_path)
                continue
            try:
                model = loader(model_path)
                self._models[name] = model
                self._versions[name] = getattr(model, "version", "0.0.0")
                self._statuses[name] = "loaded"
                loaded.append(name)
                logger.info("Loaded model: %s (v%s)", name, self._versions[name])
            except Exception as exc:
                self._statuses[name] = "error"
                logger.warning("Failed to load %s: %s", name, exc)

        if not loaded:
            import os
            env = os.getenv("AETHER_ENV", "local").lower()
            if env in ("production", "staging"):
                logger.error(
                    "CRITICAL: No trained ML model artifacts found in %s environment. "
                    "ML serving will return errors until models are trained and deployed. "
                    "Run: python -m training.pipelines.train --model all",
                    env,
                )
                # Do NOT load stubs in production/staging — return empty so
                # prediction endpoints return clear errors instead of fake data
                return []

            stub_models = {
                "intent_prediction": _StubIntentModel(),
                "bot_detection": _StubBotModel(),
                "session_scorer": _StubSessionModel(),
                "churn_prediction": _StubChurnModel(),
                "ltv_prediction": _StubLTVModel(),
                "journey_prediction": _StubJourneyModel(),
                "campaign_attribution": _StubAttributionModel(),
                "anomaly_detection": _StubAnomalyModel(),
                "identity_resolution": _StubIdentityModel(),
            }
            for name, model in stub_models.items():
                self._models[name] = model
                self._versions[name] = getattr(model, "version", "test-stub")
                self._statuses[name] = "loaded"
            loaded = list(stub_models.keys())
            logger.info("No serialized models found; loaded stub models (local/dev mode only)")

        return loaded

    # --------------------------------------------------------------------- #
    # Model access
    # --------------------------------------------------------------------- #

    def get_model(self, name: str) -> Any:
        """Return a loaded model by canonical name.

        Raises:
            HTTPException: If the model is not loaded.
        """
        if not self._models:
            self.load_all_models()
        if name not in self._models:
            raise HTTPException(
                status_code=503,
                detail=f"Model '{name}' is not loaded. Available: {self.loaded_models()}",
            )
        return self._models[name]

    def loaded_models(self) -> list[str]:
        """Return the names of all successfully loaded models."""
        return list(self._models.keys())

    def model_info(self) -> list[ModelInfo]:
        """Return metadata for every known model."""
        info: list[ModelInfo] = []
        for name in MODEL_NAMES:
            info.append(
                ModelInfo(
                    name=name,
                    version=self._versions.get(name, "n/a"),
                    type=MODEL_TYPES.get(name, "server"),
                    status=self._statuses.get(name, "not_loaded"),
                )
            )
        return info

    def predict(self, model_name: str, features: dict[str, Any]) -> Any:
        """Run single-instance inference through the named model.

        Converts the feature dict into a single-row DataFrame and delegates
        to the underlying model's ``predict`` method.
        """
        model = self.get_model(model_name)
        df = pd.DataFrame([features])
        raw = model.predict(df)
        # Return the scalar prediction for a single instance.
        if hasattr(raw, "__len__") and len(raw) > 0:
            value = raw[0]
            if isinstance(value, (np.integer,)):
                return int(value)
            if isinstance(value, (np.floating,)):
                return float(value)
            return value
        return raw

    # --------------------------------------------------------------------- #
    # Individual model loaders
    # --------------------------------------------------------------------- #

    def _load_intent(self, path: Path) -> Any:
        from edge.models import IntentPredictionModel

        m = IntentPredictionModel()
        m.load(path)
        return m

    def _load_bot(self, path: Path) -> Any:
        from edge.models import BotDetectionModel

        m = BotDetectionModel()
        m.load(path)
        return m

    def _load_session(self, path: Path) -> Any:
        from edge.models import SessionScorerModel

        m = SessionScorerModel()
        m.load(path)
        return m

    def _load_churn(self, path: Path) -> Any:
        from server.models import ChurnPredictionModel

        m = ChurnPredictionModel()
        m.load(path)
        return m

    def _load_ltv(self, path: Path) -> Any:
        from server.models import LTVPredictionModel

        m = LTVPredictionModel()
        m.load(path)
        return m

    def _load_journey(self, path: Path) -> Any:
        from server.journey_prediction import JourneyPredictionModel

        m = JourneyPredictionModel()
        m.load(path)
        return m

    def _load_attribution(self, path: Path) -> Any:
        from server.campaign_attribution import CampaignAttributionModel

        m = CampaignAttributionModel()
        m.load(path)
        return m

    def _load_anomaly(self, path: Path) -> Any:
        from server.models import AnomalyDetectionModel

        m = AnomalyDetectionModel()
        m.load(path)
        return m

    def _load_identity(self, path: Path) -> Any:
        from server.models import IdentityResolutionModel

        m = IdentityResolutionModel()
        m.load(path)
        return m


# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

server = ModelServer()


def _ensure_models_loaded() -> None:
    if not server.loaded_models():
        server.load_all_models()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: load models on startup, clean up on shutdown."""
    _ensure_models_loaded()
    loaded = server.loaded_models()
    logger.info("Serving %d models: %s", len(loaded), loaded)

    # Start extraction defense cleanup task if defense is enabled
    _cleanup_task = None
    defense = _get_defense_layer()
    if defense is not None:
        try:
            from security.model_extraction_defense.cleanup import cleanup_periodic
            import asyncio
            _cleanup_task = asyncio.create_task(cleanup_periodic(defense, interval_seconds=300))
            logger.info("Extraction defense cleanup task started (interval=300s)")
        except ImportError:
            pass

    yield

    if _cleanup_task is not None:
        _cleanup_task.cancel()
        logger.info("Extraction defense cleanup task cancelled")
    logger.info("Shutting down Aether ML serving API")


app = FastAPI(
    title="Aether ML Serving API",
    description="Real-time and batch prediction API for Aether ML models",
    version="4.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)


# =============================================================================
# MIDDLEWARE
# =============================================================================


@app.middleware("http")
async def add_latency_header(request: Request, call_next):
    """Inject ``X-Inference-Latency-Ms`` response header on every request."""
    t0 = time.perf_counter()
    response = await call_next(request)
    latency_ms = (time.perf_counter() - t0) * 1000
    response.headers["X-Inference-Latency-Ms"] = f"{latency_ms:.2f}"
    return response


@app.middleware("http")
async def extraction_defense_middleware(request: Request, call_next):
    """Pre-request extraction defense checks (rate limit, canary, risk scoring).

    Only activates when ``ENABLE_EXTRACTION_DEFENSE=true``.  Stores the
    risk assessment on ``request.state`` so post-response perturbation
    can be applied by individual endpoints.
    """
    defense = _get_defense_layer()
    if defense is None or not request.url.path.startswith("/v1/predict"):
        return await call_next(request)

    api_key = request.headers.get("X-API-Key", request.headers.get("Authorization", "anon"))
    ip_address = request.client.host if request.client else "0.0.0.0"

    # Read body once — Starlette caches the result so downstream endpoint
    # parsing (Pydantic model binding) still works on repeated reads.
    body_bytes = await request.body()
    features: dict = {}
    body: dict = {}
    batch_size = 1
    try:
        body = json.loads(body_bytes) if body_bytes else {}
        features = body.get("features", {})
        if "instances" in body:
            batch_size = len(body["instances"])
            features = body["instances"][0] if body["instances"] else {}
    except (json.JSONDecodeError, IndexError, TypeError):
        pass

    model_name = request.url.path.rsplit("/", 1)[-1]

    pre_result = defense.pre_request(
        api_key=api_key,
        ip_address=ip_address,
        features=features,
        model_name=model_name,
        batch_size=batch_size,
    )

    if pre_result.blocked:
        status = 429 if "rate limit" in pre_result.block_reason.lower() else 403
        headers = {}
        if pre_result.retry_after_seconds:
            headers["Retry-After"] = str(pre_result.retry_after_seconds)
        return JSONResponse(
            status_code=status,
            content={
                "error": {
                    "code": status,
                    "message": pre_result.block_reason,
                }
            },
            headers=headers,
        )

    # Stash risk info for post-response perturbation
    request.state.extraction_risk = (
        pre_result.risk_assessment.risk_score
        if pre_result.risk_assessment
        else 0.0
    )
    request.state.extraction_features = features

    return await call_next(request)


# =============================================================================
# EXTRACTION DEFENSE — POST-RESPONSE HELPER
# =============================================================================


def _apply_output_defense(request: Request, value: float, features: dict) -> float:
    """Apply extraction mesh disclosure control + legacy defense to a scalar output.

    Applies in order:
    1. Extraction Mesh disclosure policy (rounding, bucketing, suppression)
    2. Legacy defense perturbation + watermark (if enabled)

    Returns the original value unchanged when no defense layer is active.
    """
    # ── Extraction Mesh disclosure control (no perturbation) ─────────
    disclosure = getattr(request.state, "extraction_disclosure", None)
    if disclosure is not None:
        value = disclosure.apply_confidence(value)
        # If hidden, return sentinel (caller should omit the field)
        if value == -1.0:
            return 0.0  # Safe fallback for hidden mode

    # ── Legacy defense (perturbation + watermark) ────────────────────
    defense = _get_defense_layer()
    if defense is None:
        return value

    risk_score = getattr(request.state, "extraction_risk", 0.0)
    api_key = request.headers.get("X-API-Key", "anon")
    result = defense.post_response(api_key, value, features, risk_score=risk_score)
    return result.output


# =============================================================================
# HEALTH & METADATA
# =============================================================================


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Return service health status, loaded models, and uptime."""
    _ensure_models_loaded()
    return HealthResponse(
        status="healthy",
        version="4.0.0",
        models_loaded=server.loaded_models(),
        uptime_seconds=round(time.time() - server.start_time, 1),
    )


@app.get("/models")
async def list_models() -> dict[str, list[dict[str, Any]]]:
    """Return metadata for every known model including load status."""
    _ensure_models_loaded()
    return {"models": [model.model_dump() for model in server.model_info()]}


# =============================================================================
# PREDICTION ENDPOINTS
# =============================================================================


@app.post("/v1/predict/intent", response_model=IntentPredictionResponse)
async def predict_intent(req: IntentPredictionRequest, request: Request) -> IntentPredictionResponse:
    """Real-time intent prediction for a browsing session.

    Predicts the next most likely user action, exit risk, and conversion
    probability based on in-session behavioural features.
    """
    t0 = time.perf_counter()
    model = server.get_model("intent_prediction")

    df = pd.DataFrame([req.features])
    result = model.predict_full(df)

    # Extract individual prediction heads from the multi-output model.
    predicted_action = result.get("action", ["browse"])[0]
    action_proba = result.get("action_proba", None)
    confidence = (
        float(np.max(action_proba[0])) if action_proba is not None else 0.5
    )
    exit_risk = float(result.get("exit_risk", [0.0])[0])
    conversion_prob = float(result.get("conversion_proba", [0.0])[0])

    # Apply extraction defense perturbation to probability outputs
    confidence = _apply_output_defense(request, confidence, req.features)
    exit_risk = _apply_output_defense(request, exit_risk, req.features)
    conversion_prob = _apply_output_defense(request, conversion_prob, req.features)

    # Derive journey stage from conversion probability thresholds.
    if conversion_prob > 0.7:
        journey_stage = "decision"
    elif conversion_prob > 0.3:
        journey_stage = "consideration"
    else:
        journey_stage = "awareness"

    latency_ms = (time.perf_counter() - t0) * 1000
    return IntentPredictionResponse(
        session_id=req.session_id,
        predicted_action=str(predicted_action),
        confidence=round(confidence, 4),
        exit_risk=round(exit_risk, 4),
        conversion_probability=round(conversion_prob, 4),
        journey_stage=journey_stage,
        latency_ms=round(latency_ms, 2),
    )


@app.post("/v1/predict/bot", response_model=BotDetectionResponse)
async def predict_bot(req: BotDetectionRequest, request: Request) -> BotDetectionResponse:
    """Classify a session as bot or human.

    Returns a boolean classification, confidence score, and bot type label
    (e.g. ``"scraper"``, ``"crawler"``, ``"human"``).
    """
    t0 = time.perf_counter()
    model = server.get_model("bot_detection")

    df = pd.DataFrame([req.features])
    prediction = model.predict(df)[0]
    proba = model.predict_proba(df)[0]

    confidence = _apply_output_defense(request, float(np.max(proba)), req.features)

    latency_ms = (time.perf_counter() - t0) * 1000
    return BotDetectionResponse(
        session_id=req.session_id,
        is_bot=bool(prediction),
        confidence=round(confidence, 4),
        bot_type="bot" if prediction else "human",
        latency_ms=round(latency_ms, 2),
    )


@app.post("/v1/predict/session-score", response_model=SessionScoreResponse)
async def predict_session_score(req: SessionScoreRequest, request: Request) -> SessionScoreResponse:
    """Score session engagement level.

    Produces an integer engagement score (0--100), conversion probability,
    and a recommended real-time intervention action.
    """
    t0 = time.perf_counter()
    model = server.get_model("session_scorer")

    df = pd.DataFrame([req.features])
    result = model.predict_full(df)

    engagement = int(result.get("engagement_score", [0])[0])
    conversion = float(result.get("conversion_proba", [0.0])[0])

    conversion = _apply_output_defense(request, conversion, req.features)

    # Determine intervention based on conversion probability and engagement.
    if conversion > 0.6:
        intervention = "soft_cta"
    elif engagement < 20:
        intervention = "exit_offer"
    elif engagement > 80:
        intervention = "upsell"
    else:
        intervention = "none"

    latency_ms = (time.perf_counter() - t0) * 1000
    return SessionScoreResponse(
        session_id=req.session_id,
        engagement_score=engagement,
        conversion_probability=round(conversion, 4),
        recommended_intervention=intervention,
        latency_ms=round(latency_ms, 2),
    )


@app.post("/v1/predict/churn", response_model=ChurnPredictionResponse)
async def predict_churn(req: ChurnPredictionRequest, request: Request) -> ChurnPredictionResponse:
    """Predict churn risk for a known identity.

    If ``features`` are omitted the server will attempt to fetch them from
    the online feature store using ``identity_id``.
    """
    t0 = time.perf_counter()
    features = req.features
    if features is None:
        raise HTTPException(
            status_code=400,
            detail="Features are required. Pass them directly or configure a feature store.",
        )

    model = server.get_model("churn_prediction")
    df = pd.DataFrame([features])
    result = model.predict_with_factors(df)

    churn_prob = float(result["churn_probability"].iloc[0])
    churn_prob = _apply_output_defense(request, churn_prob, features)

    # Map probability to a human-readable risk segment.
    if churn_prob > 0.7:
        risk_segment = "high"
    elif churn_prob > 0.4:
        risk_segment = "medium"
    else:
        risk_segment = "low"

    top_factors = [
        str(result["top_factor_1"].iloc[0]),
        str(result["top_factor_2"].iloc[0]),
        str(result["top_factor_3"].iloc[0]),
    ]

    latency_ms = (time.perf_counter() - t0) * 1000
    return ChurnPredictionResponse(
        identity_id=req.identity_id,
        churn_probability=round(churn_prob, 4),
        risk_segment=risk_segment,
        top_factors=top_factors,
        latency_ms=round(latency_ms, 2),
    )


@app.post("/v1/predict/ltv", response_model=LTVPredictionResponse)
async def predict_ltv(req: LTVPredictionRequest, request: Request) -> LTVPredictionResponse:
    """Predict lifetime value for a known identity.

    If ``features`` are omitted the server will attempt to fetch them from
    the online feature store using ``identity_id``.
    """
    t0 = time.perf_counter()
    features = req.features
    if features is None:
        raise HTTPException(
            status_code=400,
            detail="Features are required. Pass them directly or configure a feature store.",
        )

    model = server.get_model("ltv_prediction")
    df = pd.DataFrame([features])
    prediction = model.predict(df)

    ltv = _apply_output_defense(request, float(prediction[0]), features)

    latency_ms = (time.perf_counter() - t0) * 1000
    return LTVPredictionResponse(
        identity_id=req.identity_id,
        predicted_ltv=round(ltv, 2),
        latency_ms=round(latency_ms, 2),
    )


@app.post("/v1/predict/journey", response_model=JourneyPredictionResponse)
async def predict_journey(req: JourneyPredictionRequest, request: Request) -> JourneyPredictionResponse:
    """Predict the next N steps in a user journey.

    Accepts an ordered list of observed events and forecasts the most
    probable continuation, including whether a conversion event is reached.
    """
    t0 = time.perf_counter()
    model = server.get_model("journey_prediction")

    # Build a minimal event DataFrame from the observed sequence.
    df = pd.DataFrame(
        {
            "identity_id": [req.identity_id] * len(req.observed_events),
            "event_type": req.observed_events,
            "timestamp": pd.date_range(
                end="now", periods=len(req.observed_events), freq="1min"
            ),
        }
    )

    results = model.predict_journey(df, n_steps=req.n_steps)

    latency_ms = (time.perf_counter() - t0) * 1000

    result = (
        results[0]
        if results
        else {"predicted_journey": [], "conversion_reached": False}
    )

    # Apply extraction defense to probability values in predicted journey steps
    defense = _get_defense_layer()
    if defense is not None:
        risk_score = getattr(request.state, "extraction_risk", 0.0)
        api_key = request.headers.get("X-API-Key", "anon")
        features = {"identity_id_hash": hash(req.identity_id) % 1000}
        for step in result.get("predicted_journey", []):
            if isinstance(step, dict):
                for k, v in list(step.items()):
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        post = defense.post_response(api_key, float(v), features, risk_score=risk_score)
                        step[k] = post.output

    return JourneyPredictionResponse(
        identity_id=req.identity_id,
        predicted_journey=result["predicted_journey"],
        conversion_reached=result["conversion_reached"],
        latency_ms=round(latency_ms, 2),
    )


@app.post("/v1/predict/attribution", response_model=AttributionResponse)
async def predict_attribution(req: AttributionRequest, request: Request) -> AttributionResponse:
    """Compute multi-touch attribution for a conversion.

    Distributes credit across touchpoints using the specified method
    (``shapley``, ``linear``, ``time_decay``, ``position_based``).
    """
    t0 = time.perf_counter()
    model = server.get_model("campaign_attribution")

    journeys = pd.DataFrame(req.touchpoints)
    journeys["conversion_id"] = req.conversion_id

    attribution = model.attribute(journeys, method=req.method)
    attr_records = attribution.to_dict(orient="records")

    # Apply extraction defense to attribution scores
    defense = _get_defense_layer()
    if defense is not None:
        risk_score = getattr(request.state, "extraction_risk", 0.0)
        api_key = request.headers.get("X-API-Key", "anon")
        features = {"conversion_id_hash": hash(req.conversion_id) % 1000}
        for record in attr_records:
            for k, v in list(record.items()):
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    post = defense.post_response(api_key, float(v), features, risk_score=risk_score)
                    record[k] = post.output

    latency_ms = (time.perf_counter() - t0) * 1000
    return AttributionResponse(
        conversion_id=req.conversion_id,
        attribution=attr_records,
        method=req.method,
        latency_ms=round(latency_ms, 2),
    )


# =============================================================================
# BATCH PREDICTION
# =============================================================================


@app.post("/v1/predict/batch", response_model=BatchPredictionResponse)
async def batch_predict(req: BatchPredictionRequest, request: Request) -> BatchPredictionResponse:
    """Run batch prediction for any loaded model.

    INTERNAL / PRIVILEGED ONLY. Non-privileged callers receive 403.
    Enforces maximum batch rows by trust level and logs request coverage
    statistics. For larger workloads use the offline ``BatchPredictor``.
    """
    # ── Extraction Mesh: batch is internal-only ──────────────────────
    disclosure = getattr(request.state, "extraction_disclosure", None)
    if disclosure is not None and not disclosure.batch_allowed:
        raise HTTPException(
            status_code=403,
            detail="Batch prediction is restricted to privileged callers",
        )

    # ── Batch privilege enforcement via header ───────────────────────
    privileged_header = request.headers.get("X-Batch-Privilege", "")
    is_privileged = privileged_header == "internal" or (
        hasattr(request.state, "tenant")
        and getattr(request.state.tenant, "role", None)
        and request.state.tenant.role.value == "service"
    )
    # Only enforce batch restriction when extraction mesh is enabled
    mesh_enabled = os.getenv("ENABLE_EXTRACTION_MESH", "false").lower() == "true"
    if not is_privileged and mesh_enabled and os.getenv("EXTRACTION_BATCH_INTERNAL_ONLY", "true").lower() == "true":
        raise HTTPException(
            status_code=403,
            detail="Batch prediction is restricted to internal/privileged callers",
        )

    if not req.instances:
        raise HTTPException(status_code=400, detail="instances list must not be empty")

    # ── Enforce max batch rows ───────────────────────────────────────
    max_rows = 10000 if is_privileged else 0
    if disclosure is not None:
        max_rows = disclosure.max_batch_rows
    if len(req.instances) > max_rows > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Batch size {len(req.instances)} exceeds maximum {max_rows}",
        )

    t0 = time.perf_counter()
    try:
        model = server.get_model(req.model)
    except HTTPException as exc:
        raise HTTPException(status_code=500, detail=exc.detail) from exc

    df = pd.DataFrame(req.instances)
    raw_predictions = model.predict(df)

    defense = _get_defense_layer()
    risk_score = getattr(request.state, "extraction_risk", 0.0)
    api_key = request.headers.get("X-API-Key", "anon")

    # ── Apply disclosure policy to batch results ─────────────────────
    results: list[dict[str, Any]] = []
    for idx, pred in enumerate(raw_predictions):
        if isinstance(pred, (np.integer,)):
            value: Any = int(pred)
        elif isinstance(pred, (np.floating,)):
            value = float(pred)
        elif isinstance(pred, np.ndarray):
            value = pred.tolist()
        else:
            value = pred

        # Apply disclosure control for privileged callers
        if disclosure is not None and isinstance(value, (int, float)):
            value = disclosure.apply_confidence(float(value))

        # Apply legacy extraction defense
        if defense is not None and isinstance(value, (int, float, list)):
            features = req.instances[idx] if idx < len(req.instances) else {}
            post = defense.post_response(api_key, value, features, risk_score=risk_score)
            value = post.output

        results.append({"index": idx, "prediction": value})

    # ── Log batch coverage statistics ────────────────────────────────
    logger.info(
        "Batch prediction: model=%s instances=%d privileged=%s api_key=%s",
        req.model,
        len(req.instances),
        is_privileged,
        api_key[:8] + "..." if api_key else "anon",
    )

    latency_ms = (time.perf_counter() - t0) * 1000
    return BatchPredictionResponse(
        model=req.model,
        predictions=results,
        count=len(results),
        total_latency_ms=round(latency_ms, 2),
    )


# =============================================================================
# EXTRACTION DEFENSE — MONITORING ENDPOINTS
# =============================================================================


@app.get("/v1/defense/status")
async def defense_status():
    """Return extraction defense layer status and configuration flags."""
    defense = _get_defense_layer()
    if defense is None:
        return {"enabled": False}
    return {
        "enabled": True,
        "output_noise": defense.config.enable_output_noise,
        "watermark": defense.config.enable_watermark,
        "query_analysis": defense.config.enable_query_analysis,
        "canary_count": len(defense.canary_detector._canaries),
        "tracked_clients": len(defense.risk_scorer._states),
    }


@app.get("/v1/defense/metrics")
async def defense_metrics():
    """Return extraction defense metrics snapshot for monitoring dashboards."""
    defense = _get_defense_layer()
    if defense is None:
        return {"enabled": False, "message": "Extraction defense is not enabled"}
    return defense.get_metrics_snapshot()


@app.get("/v1/defense/risk-scores")
async def defense_risk_scores():
    """Return current risk scores for all tracked clients."""
    defense = _get_defense_layer()
    if defense is None:
        return {"enabled": False}
    scores = defense.get_all_risk_scores()
    return {
        "count": len(scores),
        "scores": {k[:12] + "...": round(v, 4) for k, v in sorted(scores.items(), key=lambda x: -x[1])},
    }


@app.get("/v1/defense/canary-triggers")
async def defense_canary_triggers():
    """Return canary trigger event history."""
    defense = _get_defense_layer()
    if defense is None:
        return {"enabled": False}
    triggers = defense.get_canary_triggers()
    return {
        "count": len(triggers),
        "triggers": [
            {
                "api_key": t.api_key[:8] + "..." if t.api_key else "",
                "ip": t.ip_address,
                "canary_id": t.canary_id,
                "timestamp": t.timestamp,
            }
            for t in triggers[-50:]  # last 50
        ],
    }


# =============================================================================
# ENTRYPOINT
# =============================================================================


def serve(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Start the serving API with uvicorn."""
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    serve()
