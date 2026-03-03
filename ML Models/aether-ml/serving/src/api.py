"""
Aether ML -- Model Serving API

FastAPI inference server supporting all 9 models with caching, latency tracking,
batch prediction, and health monitoring.

Deployed as: ECS Fargate service behind ALB, or SageMaker endpoint.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logger = logging.getLogger("aether.serving")


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

        return loaded

    # --------------------------------------------------------------------- #
    # Model access
    # --------------------------------------------------------------------- #

    def get_model(self, name: str) -> Any:
        """Return a loaded model by canonical name.

        Raises:
            HTTPException: If the model is not loaded.
        """
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: load models on startup, clean up on shutdown."""
    loaded = server.load_all_models()
    logger.info("Serving %d models: %s", len(loaded), loaded)
    yield
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


# =============================================================================
# HEALTH & METADATA
# =============================================================================


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Return service health status, loaded models, and uptime."""
    return HealthResponse(
        status="healthy",
        version="4.0.0",
        models_loaded=server.loaded_models(),
        uptime_seconds=round(time.time() - server.start_time, 1),
    )


@app.get("/models", response_model=list[ModelInfo])
async def list_models() -> list[ModelInfo]:
    """Return metadata for every known model including load status."""
    return server.model_info()


# =============================================================================
# PREDICTION ENDPOINTS
# =============================================================================


@app.post("/v1/predict/intent", response_model=IntentPredictionResponse)
async def predict_intent(req: IntentPredictionRequest) -> IntentPredictionResponse:
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
async def predict_bot(req: BotDetectionRequest) -> BotDetectionResponse:
    """Classify a session as bot or human.

    Returns a boolean classification, confidence score, and bot type label
    (e.g. ``"scraper"``, ``"crawler"``, ``"human"``).
    """
    t0 = time.perf_counter()
    model = server.get_model("bot_detection")

    df = pd.DataFrame([req.features])
    prediction = model.predict(df)[0]
    proba = model.predict_proba(df)[0]

    latency_ms = (time.perf_counter() - t0) * 1000
    return BotDetectionResponse(
        session_id=req.session_id,
        is_bot=bool(prediction),
        confidence=round(float(np.max(proba)), 4),
        bot_type="bot" if prediction else "human",
        latency_ms=round(latency_ms, 2),
    )


@app.post("/v1/predict/session-score", response_model=SessionScoreResponse)
async def predict_session_score(req: SessionScoreRequest) -> SessionScoreResponse:
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
async def predict_churn(req: ChurnPredictionRequest) -> ChurnPredictionResponse:
    """Predict churn risk for a known identity.

    If ``features`` are omitted the server will attempt to fetch them from
    the online feature store using ``identity_id``.
    """
    t0 = time.perf_counter()
    model = server.get_model("churn_prediction")

    features = req.features
    if features is None:
        raise HTTPException(
            status_code=400,
            detail="Features are required. Pass them directly or configure a feature store.",
        )

    df = pd.DataFrame([features])
    result = model.predict_with_factors(df)

    churn_prob = float(result["churn_probability"].iloc[0])

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
async def predict_ltv(req: LTVPredictionRequest) -> LTVPredictionResponse:
    """Predict lifetime value for a known identity.

    If ``features`` are omitted the server will attempt to fetch them from
    the online feature store using ``identity_id``.
    """
    t0 = time.perf_counter()
    model = server.get_model("ltv_prediction")

    features = req.features
    if features is None:
        raise HTTPException(
            status_code=400,
            detail="Features are required. Pass them directly or configure a feature store.",
        )

    df = pd.DataFrame([features])
    prediction = model.predict(df)

    latency_ms = (time.perf_counter() - t0) * 1000
    return LTVPredictionResponse(
        identity_id=req.identity_id,
        predicted_ltv=round(float(prediction[0]), 2),
        latency_ms=round(latency_ms, 2),
    )


@app.post("/v1/predict/journey", response_model=JourneyPredictionResponse)
async def predict_journey(req: JourneyPredictionRequest) -> JourneyPredictionResponse:
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
    return JourneyPredictionResponse(
        identity_id=req.identity_id,
        predicted_journey=result["predicted_journey"],
        conversion_reached=result["conversion_reached"],
        latency_ms=round(latency_ms, 2),
    )


@app.post("/v1/predict/attribution", response_model=AttributionResponse)
async def predict_attribution(req: AttributionRequest) -> AttributionResponse:
    """Compute multi-touch attribution for a conversion.

    Distributes credit across touchpoints using the specified method
    (``shapley``, ``linear``, ``time_decay``, ``position_based``).
    """
    t0 = time.perf_counter()
    model = server.get_model("campaign_attribution")

    journeys = pd.DataFrame(req.touchpoints)
    journeys["conversion_id"] = req.conversion_id

    attribution = model.attribute(journeys, method=req.method)

    latency_ms = (time.perf_counter() - t0) * 1000
    return AttributionResponse(
        conversion_id=req.conversion_id,
        attribution=attribution.to_dict(orient="records"),
        method=req.method,
        latency_ms=round(latency_ms, 2),
    )


# =============================================================================
# BATCH PREDICTION
# =============================================================================


@app.post("/v1/predict/batch", response_model=BatchPredictionResponse)
async def batch_predict(req: BatchPredictionRequest) -> BatchPredictionResponse:
    """Run batch prediction for any loaded model.

    Accepts a list of feature dictionaries and returns predictions for all
    instances in a single response.  Intended for moderate-size batches
    (up to ~1 000 instances); for larger workloads use the offline
    ``BatchPredictor``.
    """
    if not req.instances:
        raise HTTPException(status_code=400, detail="instances list must not be empty")

    t0 = time.perf_counter()
    model = server.get_model(req.model)

    df = pd.DataFrame(req.instances)
    raw_predictions = model.predict(df)

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
        results.append({"index": idx, "prediction": value})

    latency_ms = (time.perf_counter() - t0) * 1000
    return BatchPredictionResponse(
        model=req.model,
        predictions=results,
        count=len(results),
        total_latency_ms=round(latency_ms, 2),
    )


# =============================================================================
# ENTRYPOINT
# =============================================================================


def serve(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Start the serving API with uvicorn."""
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    serve()
