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
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
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


class IdentityResolutionRequest(BaseModel):
    """Request schema for real-time identity resolution (single pair)."""

    profile_pair_id: str
    features: dict[str, Any]


class IdentityResolutionResponse(BaseModel):
    """Response schema for real-time identity resolution."""

    profile_pair_id: str
    is_same_entity: bool
    merge_probability: float
    confidence: float
    latency_ms: float
    model_version: str


class AnomalyDetectionRequest(BaseModel):
    """Request schema for real-time anomaly detection."""

    record_id: str
    features: dict[str, Any]


class AnomalyDetectionResponse(BaseModel):
    """Response schema for anomaly detection."""

    record_id: str
    is_anomaly: bool
    anomaly_score: float
    latency_ms: float


class ReadinessResponse(BaseModel):
    """Readiness probe response — used by load balancers for traffic gating."""

    ready: bool
    reason: Optional[str] = None
    models_loaded: list[str]
    sla_violation_rate: float
    freshness_summary: dict[str, Any]


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

# Derived from the canonical registry — do NOT add model names here manually.
# To register a new model, add it to common/model_registry.py.
try:
    from common.model_registry import list_trainable_models as _list_trainable
    _TRAINABLE_ENTRIES = list(_list_trainable())
    MODEL_NAMES: list[str] = [m.model_id for m in _TRAINABLE_ENTRIES]
    MODEL_TYPES: dict[str, str] = {m.model_id: m.tier.value for m in _TRAINABLE_ENTRIES}
    del _list_trainable, _TRAINABLE_ENTRIES
except ImportError:
    # Fallback used only during isolated unit tests where common/ is not on sys.path.
    # Staging and production must never reach this branch.
    import os as _os
    if _os.getenv("AETHER_ENV", "local").lower() in ("staging", "production"):
        raise RuntimeError(
            "Cannot import common.model_registry. "
            "The serving package requires aether-ml[serving] to be installed."
        )
    MODEL_NAMES = [
        "intent_prediction", "bot_detection", "session_scorer",
        "churn_prediction", "ltv_prediction", "journey_prediction",
        "campaign_attribution", "anomaly_detection", "identity_resolution",
    ]
    MODEL_TYPES = {
        "intent_prediction": "edge", "bot_detection": "edge", "session_scorer": "edge",
        "churn_prediction": "server", "ltv_prediction": "server",
        "journey_prediction": "server", "campaign_attribution": "server",
        "anomaly_detection": "server", "identity_resolution": "server",
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
        self._loaders: dict[str, Any] = {
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
        self._stub_factories: dict[str, Any] = {
            "intent_prediction": _StubIntentModel,
            "bot_detection": _StubBotModel,
            "session_scorer": _StubSessionModel,
            "churn_prediction": _StubChurnModel,
            "ltv_prediction": _StubLTVModel,
            "journey_prediction": _StubJourneyModel,
            "campaign_attribution": _StubAttributionModel,
            "anomaly_detection": _StubAnomalyModel,
            "identity_resolution": _StubIdentityModel,
        }

    # --------------------------------------------------------------------- #
    # Model loading
    # --------------------------------------------------------------------- #

    @staticmethod
    def _allow_stubs() -> bool:
        return os.getenv("AETHER_ENV", "local").lower() not in ("production", "staging")

    def discover_artifacts(self) -> list[str]:
        """Return model names whose artifact directory exists on disk."""
        if not self.models_dir.exists():
            return []
        return [name for name in MODEL_NAMES if (self.models_dir / name).exists()]

    def _record(self, name: str, model: Any, version: str | None = None) -> Any:
        self._models[name] = model
        self._versions[name] = version or getattr(model, "version", "0.0.0")
        self._statuses[name] = "loaded"
        return model

    def _load_one(self, name: str) -> Any:
        """Load a single model from disk; fall back to a stub in dev environments."""
        loader = self._loaders.get(name)
        if loader is None:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown model '{name}'. Known: {list(self._loaders)}",
            )

        model_path = self.models_dir / name
        if model_path.exists():
            try:
                model = loader(model_path)
                logger.info("Loaded model on demand: %s", name)
                return self._record(name, model)
            except Exception as exc:
                self._statuses[name] = "error"
                logger.warning("Failed to load %s: %s", name, exc)
                raise HTTPException(
                    status_code=503,
                    detail=f"Model '{name}' failed to load: {exc}",
                ) from exc

        if self._allow_stubs():
            factory = self._stub_factories[name]
            logger.info("No artifact for %s; using stub (local/dev mode only)", name)
            return self._record(name, factory(), version="test-stub")

        self._statuses[name] = "not_loaded"
        raise HTTPException(
            status_code=503,
            detail=(
                f"Model '{name}' has no artifact at {model_path}. "
                "Train and deploy the model before serving requests."
            ),
        )

    def load_all_models(self) -> list[str]:
        """Eagerly load every model with an artifact on disk.

        Retained for tests and admin tooling. Production startup uses lazy
        per-route loading via :meth:`get_model` and does NOT call this.
        """
        for name in MODEL_NAMES:
            if name in self._models:
                continue
            try:
                self._load_one(name)
            except HTTPException:
                continue
        return self.loaded_models()

    # --------------------------------------------------------------------- #
    # Model access
    # --------------------------------------------------------------------- #

    def get_model(self, name: str) -> Any:
        """Return a loaded model by canonical name, loading it on first use."""
        if name in self._models:
            return self._models[name]
        return self._load_one(name)

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

    def load_baseline(self, model_id: str) -> "pd.DataFrame | None":
        """Load the drift detection baseline sample for a model, if available.

        Returns the reference DataFrame saved by the training pipeline, or None
        if no baseline exists (model not yet trained, or trained before baseline
        saving was added).
        """
        baseline_path = self.models_dir / model_id / "baseline.joblib"
        if not baseline_path.exists():
            return None
        try:
            import joblib as _jl
            return _jl.load(baseline_path)
        except Exception as exc:
            logger.debug("Failed to load drift baseline for %s: %s", model_id, exc)
            return None

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
        from edge.models import IntentPrediction

        m = IntentPrediction()
        m.load(path)
        return m

    def _load_bot(self, path: Path) -> Any:
        from edge.models import BotDetection

        m = BotDetection()
        m.load(path)
        return m

    def _load_session(self, path: Path) -> Any:
        from edge.models import SessionScorer

        m = SessionScorer()
        m.load(path)
        return m

    def _load_churn(self, path: Path) -> Any:
        # Prefer ONNX artifact (slim serving image, no XGBoost required).
        from serving.src.onnx_models import OnnxChurnModel
        onnx = OnnxChurnModel.load(path, "churn_prediction")
        if onnx is not None:
            return onnx
        # Fall back to native XGBoost loader (training image only).
        from server.models import ChurnPrediction
        m = ChurnPrediction()
        m.load(path)
        return m

    def _load_ltv(self, path: Path) -> Any:
        # Prefer ONNX artifact (slim serving image, no XGBoost required).
        from serving.src.onnx_models import OnnxLTVModel
        onnx = OnnxLTVModel.load(path, "ltv_prediction")
        if onnx is not None:
            return onnx
        # Fall back to native XGBoost loader (training image only).
        from server.models import LTVPrediction
        m = LTVPrediction()
        m.load(path)
        return m

    def _load_journey(self, path: Path) -> Any:
        from server.journey_prediction import JourneyPrediction

        m = JourneyPrediction()
        m.load(path)
        return m

    def _load_attribution(self, path: Path) -> Any:
        from server.campaign_attribution import CampaignAttribution

        m = CampaignAttribution()
        m.load(path)
        return m

    def _load_anomaly(self, path: Path) -> Any:
        from server.models import AnomalyDetection

        m = AnomalyDetection()
        m.load(path)
        return m

    def _load_identity(self, path: Path) -> Any:
        from server.models import IdentityResolution

        m = IdentityResolution()
        m.load(path)
        return m


# =============================================================================
# FASTAPI APPLICATION
# =============================================================================

server = ModelServer()

# ---------------------------------------------------------------------------
# Freshness SLA tracker — lazy import so serving starts if monitoring module
# is unavailable (e.g., in stripped container images).
# ---------------------------------------------------------------------------
try:
    from monitoring.monitor import DataFreshnessSLATracker as _DataFreshnessSLATracker
    _freshness_tracker: "_DataFreshnessSLATracker | None" = _DataFreshnessSLATracker()
except Exception:  # ImportError or any init failure
    _freshness_tracker = None

try:
    from monitoring.monitor import ExtractionDefenseMonitor as _ExtractionDefenseMonitor
    _extraction_monitor: "_ExtractionDefenseMonitor | None" = _ExtractionDefenseMonitor()
except Exception:
    _extraction_monitor = None

# ---------------------------------------------------------------------------
# Per-model prediction input buffer — holds last 500 feature dicts per model
# for drift detection. In-memory only; cleared on restart. Drift detection
# skips models with fewer than 30 buffered rows.
# Local/dev: in-memory deques only.
# Staging/production: Redis-backed freshness tracking wired via _freshness_tracker
# during lifespan startup (~line 835). These deques remain as a fast local buffer
# for the background drift-computation task.
# ---------------------------------------------------------------------------
from collections import deque as _deque
_prediction_buffers: dict[str, "_deque[dict[str, Any]]"] = {
    m: _deque(maxlen=500) for m in MODEL_NAMES
}

# Stores the output of the most recent drift detection run (updated by the
# background task every 300s). Empty until the first run completes.
_last_drift_results: dict[str, Any] = {}

# ---------------------------------------------------------------------------
# Drift detection helpers
# ---------------------------------------------------------------------------

def _run_drift_check() -> None:
    """Compare per-model prediction buffers against training baselines.

    Called by the background task every 300s. Skips models with fewer than
    30 buffered predictions or no baseline on disk. Results are stored in
    _last_drift_results for the /v1/monitoring/drift endpoint.
    """
    try:
        from monitoring.monitor import MonitoringPipeline
    except ImportError:
        return

    pipeline = MonitoringPipeline()
    reference_data: dict[str, Any] = {}
    current_data: dict[str, Any] = {}
    model_metrics: dict[str, Any] = {}

    for model_id in MODEL_NAMES:
        buffer = list(_prediction_buffers[model_id])
        if len(buffer) < 30:
            continue
        reference_df = server.load_baseline(model_id)
        if reference_df is None or len(reference_df) < 30:
            continue
        current_df = pd.DataFrame(buffer)
        numeric_features = list(reference_df.select_dtypes(include="number").columns)
        common_cols = [c for c in numeric_features if c in current_df.columns]
        if not common_cols:
            continue
        reference_data[model_id] = reference_df[common_cols]
        current_data[model_id] = current_df[common_cols]
        model_metrics[model_id] = {
            "current": {},
            "baseline": {},
            "numeric_features": common_cols,
            "categorical_features": [],
        }

    if not reference_data:
        return

    try:
        results = pipeline.run(reference_data, current_data, model_metrics)
        _last_drift_results.clear()
        _last_drift_results.update(results)
        _last_drift_results["_buffer_sizes"] = {
            m: len(b) for m, b in _prediction_buffers.items()
        }
    except Exception as exc:
        logger.warning("Drift pipeline run failed: %s", exc)


async def _drift_check_periodic(interval: int = 300) -> None:
    """Background coroutine that runs drift detection every `interval` seconds."""
    import asyncio
    while True:
        await asyncio.sleep(interval)
        try:
            _run_drift_check()
        except Exception as exc:
            logger.warning("Drift check error: %s", exc)


# ---------------------------------------------------------------------------
# Service token auth — checked on every route when ML_SERVICE_TOKEN is set.
# No-op when the env var is absent (local dev). Fail-closed in staging/prod.
# ---------------------------------------------------------------------------


def _require_service_token(x_service_token: str = Header(default="")) -> None:
    env = os.getenv("AETHER_ENV", "local").lower()
    expected = os.environ.get("ML_SERVICE_TOKEN", "")
    if env in ("staging", "production"):
        if not expected:
            raise HTTPException(
                status_code=503,
                detail="ML_SERVICE_TOKEN is required in staging/production but is not configured.",
            )
        if not _hmac_compare(x_service_token, expected):
            raise HTTPException(status_code=401, detail="Invalid or missing service token")
    elif expected and not _hmac_compare(x_service_token, expected):
        # Local/dev: only validate if token is explicitly configured
        raise HTTPException(status_code=401, detail="Invalid or missing service token")


def _hmac_compare(a: str, b: str) -> bool:
    import hmac
    return hmac.compare_digest(a.encode(), b.encode())


# ---------------------------------------------------------------------------
# Shared router — importable by the consolidated aether-app backend (E2).
# All predict/defense routes are registered here so they can be mounted at
# any prefix. The standalone app below includes this router after setup.
# ---------------------------------------------------------------------------
router = APIRouter(dependencies=[Depends(_require_service_token)])


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: announce model artifacts, clean up on shutdown.

    Models load lazily on first request to keep startup fast and resilient.
    If no artifacts exist in a production environment, the service still comes
    up; the first prediction request will surface a clear 503 and trigger
    existing alarming, rather than CrashLoopBackOff hiding the root cause.
    """
    available = server.discover_artifacts()
    env = os.getenv("AETHER_ENV", "local").lower()
    if not available and env in ("production", "staging"):
        logger.error(
            "No ML model artifacts found in %s at %s. Prediction routes will return 503 "
            "until artifacts are deployed.",
            env,
            server.models_dir,
        )
    else:
        logger.info(
            "Lazy-loading enabled. %d artifact(s) discovered: %s",
            len(available),
            available,
        )

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

    # Start background drift detection task (runs every 300s; degrades gracefully)
    import asyncio as _asyncio
    _drift_task = _asyncio.create_task(_drift_check_periodic(interval=300))
    logger.info("Drift detection background task started (interval=300s)")

    # Wire Redis to monitoring instances for durable state across replicas/restarts.
    # Uses MONITOR_REDIS_DB (default 3) to isolate from rate-limiter (db=2) and
    # application cache (db=0). Fails open in all environments — monitoring loss
    # is not a production blocker.
    _monitor_redis_url = os.getenv("REDIS_URL")
    if _monitor_redis_url and (_freshness_tracker is not None or _extraction_monitor is not None):
        try:
            import redis as _redis_lib
            _monitor_rc = _redis_lib.from_url(
                _monitor_redis_url,
                db=int(os.getenv("MONITOR_REDIS_DB", "3")),
                decode_responses=True,
            )
            _monitor_rc.ping()
            if _freshness_tracker is not None:
                _freshness_tracker.set_redis(_monitor_rc)
            if _extraction_monitor is not None:
                _extraction_monitor.set_redis(_monitor_rc)
            logger.info(
                "Monitoring state backed by Redis (db=%s)",
                os.getenv("MONITOR_REDIS_DB", "3"),
            )
        except Exception as _monitor_exc:
            logger.warning(
                "Redis unavailable for monitoring state — in-memory only: %s", _monitor_exc
            )

    yield

    _drift_task.cancel()
    logger.info("Drift detection background task cancelled")
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

_cors_origins = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", "http://localhost:3000,https://app.aether.io").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"],
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

    if _extraction_monitor is not None:
        _ra = pre_result.risk_assessment
        _tier_band = {"normal": "green", "elevated": "yellow", "high": "orange", "critical": "red"}
        _extraction_monitor.record_extraction_event(
            risk_score=_ra.risk_score if _ra else 0.0,
            band=_tier_band.get(_ra.tier, "unknown") if _ra else "unknown",
            signals=[
                {"name": "velocity", "value": _ra.velocity_signal},
                {"name": "pattern", "value": _ra.pattern_signal},
                {"name": "similarity", "value": _ra.similarity_signal},
                {"name": "entropy", "value": _ra.entropy_signal},
                {"name": "canary", "value": _ra.canary_signal},
            ] if _ra else [],
            policy_action="deny" if pre_result.blocked else "allow",
            model_name=model_name,
            is_batch=batch_size > 1,
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


def _validated_frame(model_id: str, features: dict) -> pd.DataFrame:
    """Contract-validate a request's feature dict, then build the model frame.

    The contract's min/max bounds and dtype rules were declared and hashed but
    never enforced at serving until now; a violation is the caller's error, so
    it surfaces as 422 rather than silently scoring garbage.
    """
    from common.feature_contracts import FeatureValidationError, validate_features

    try:
        validate_features(model_id, features, reject_unknown=True)
    except FeatureValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except KeyError:
        # Model without a registered contract: nothing to enforce.
        pass
    return pd.DataFrame([features])


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


def startup_ml() -> None:
    """Announce ML model artifacts — call from the parent app's lifespan.

    The consolidated aether-app backend calls this during its own startup so
    lazy-load discovery runs once rather than on the first prediction request.
    """
    server.discover_artifacts()


# =============================================================================
# HEALTH & METADATA
# =============================================================================


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Return service health status, loaded models, and uptime.

    Does NOT trigger model loading — this endpoint must stay sub-millisecond
    so load balancer health checks pass immediately after container start.
    """
    return HealthResponse(
        status="healthy",
        version="4.0.0",
        models_loaded=server.loaded_models(),
        uptime_seconds=round(time.time() - server.start_time, 1),
    )


@router.get("/ready", response_model=ReadinessResponse)
async def ready() -> ReadinessResponse:
    """Readiness probe — used by load balancers to gate traffic.

    In staging/production: all fail_closed_required models with artifacts must be loaded.
    Returns 503 if any required model is missing or freshness SLA is violated.
    Unlike /health, this may be slightly slower and is NOT used for liveness.
    """
    env = os.getenv("AETHER_ENV", "local").lower()
    models_loaded = server.loaded_models()
    missing_required: list[str] = []

    # Required model gate — staging and production only
    if env in ("staging", "production"):
        try:
            from common.model_registry import list_serving_models
            required_ids = [
                m.model_id for m in list_serving_models()
                if m.fail_closed_required and m.artifact_required
            ]
            missing_required = [mid for mid in required_ids if mid not in models_loaded]
        except ImportError:
            logger.warning("Cannot import model registry for readiness check")

    if missing_required:
        raise HTTPException(
            status_code=503,
            detail=ReadinessResponse(
                ready=False,
                reason=f"Required models not loaded: {missing_required}",
                models_loaded=models_loaded,
                sla_violation_rate=0.0,
                freshness_summary={},
            ).model_dump(),
        )

    # Freshness SLA check
    violation_rate = 0.0
    summary: dict[str, Any] = {}
    if _freshness_tracker is not None:
        violation_rate = _freshness_tracker.get_violation_rate()
        summary = _freshness_tracker.get_summary()

    _SLA_RATE_THRESHOLD = 0.10
    if violation_rate >= _SLA_RATE_THRESHOLD:
        raise HTTPException(
            status_code=503,
            detail=ReadinessResponse(
                ready=False,
                reason=(
                    f"Freshness SLA violation rate {violation_rate:.1%} "
                    f"exceeds threshold {_SLA_RATE_THRESHOLD:.0%}"
                ),
                models_loaded=models_loaded,
                sla_violation_rate=round(violation_rate, 4),
                freshness_summary=summary,
            ).model_dump(),
        )

    return ReadinessResponse(
        ready=True,
        models_loaded=models_loaded,
        sla_violation_rate=round(violation_rate, 4),
        freshness_summary=summary,
    )


@router.get("/models")
async def list_models() -> dict[str, list[dict[str, Any]]]:
    """Return metadata for every known model including load status."""
    return {"models": [model.model_dump() for model in server.model_info()]}


# =============================================================================
# PREDICTION ENDPOINTS
# =============================================================================


@router.post("/v1/predict/intent", response_model=IntentPredictionResponse)
async def predict_intent(req: IntentPredictionRequest, request: Request) -> IntentPredictionResponse:
    """Real-time intent prediction for a browsing session.

    Predicts the next most likely user action, exit risk, and conversion
    probability based on in-session behavioural features.
    """
    t0 = time.perf_counter()
    model = server.get_model("intent_prediction")

    df = _validated_frame("intent_prediction", req.features)
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

    if _freshness_tracker is not None:
        _freshness_tracker.check("intent_prediction", "behavioral_features", None)

    latency_ms = (time.perf_counter() - t0) * 1000
    _prediction_buffers["intent_prediction"].append(dict(req.features))
    return IntentPredictionResponse(
        session_id=req.session_id,
        predicted_action=str(predicted_action),
        confidence=round(confidence, 4),
        exit_risk=round(exit_risk, 4),
        conversion_probability=round(conversion_prob, 4),
        journey_stage=journey_stage,
        latency_ms=round(latency_ms, 2),
    )


@router.post("/v1/predict/bot", response_model=BotDetectionResponse)
async def predict_bot(req: BotDetectionRequest, request: Request) -> BotDetectionResponse:
    """Classify a session as bot or human.

    Returns a boolean classification, confidence score, and bot type label
    (e.g. ``"scraper"``, ``"crawler"``, ``"human"``).
    """
    t0 = time.perf_counter()
    model = server.get_model("bot_detection")

    df = _validated_frame("bot_detection", req.features)
    prediction = model.predict(df)[0]
    proba = model.predict_proba(df)[0]

    confidence = _apply_output_defense(request, float(np.max(proba)), req.features)

    if _freshness_tracker is not None:
        _freshness_tracker.check("bot_detection", "behavioral_features", None)

    latency_ms = (time.perf_counter() - t0) * 1000
    _prediction_buffers["bot_detection"].append(dict(req.features))
    return BotDetectionResponse(
        session_id=req.session_id,
        is_bot=bool(prediction),
        confidence=round(confidence, 4),
        bot_type="bot" if prediction else "human",
        latency_ms=round(latency_ms, 2),
    )


@router.post("/v1/predict/session-score", response_model=SessionScoreResponse)
async def predict_session_score(req: SessionScoreRequest, request: Request) -> SessionScoreResponse:
    """Score session engagement level.

    Produces an integer engagement score (0--100), conversion probability,
    and a recommended real-time intervention action.
    """
    t0 = time.perf_counter()
    model = server.get_model("session_scorer")

    df = _validated_frame("session_scorer", req.features)
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

    if _freshness_tracker is not None:
        _freshness_tracker.check("session_scorer", "session_features", None)

    latency_ms = (time.perf_counter() - t0) * 1000
    _prediction_buffers["session_scorer"].append(dict(req.features))
    return SessionScoreResponse(
        session_id=req.session_id,
        engagement_score=engagement,
        conversion_probability=round(conversion, 4),
        recommended_intervention=intervention,
        latency_ms=round(latency_ms, 2),
    )


@router.post("/v1/predict/churn", response_model=ChurnPredictionResponse)
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
    df = _validated_frame("churn_prediction", features)
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

    if _freshness_tracker is not None:
        _freshness_tracker.check("churn_prediction", "behavioral_features", None)

    latency_ms = (time.perf_counter() - t0) * 1000
    _prediction_buffers["churn_prediction"].append(dict(features))
    return ChurnPredictionResponse(
        identity_id=req.identity_id,
        churn_probability=round(churn_prob, 4),
        risk_segment=risk_segment,
        top_factors=top_factors,
        latency_ms=round(latency_ms, 2),
    )


@router.post("/v1/predict/ltv", response_model=LTVPredictionResponse)
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
    df = _validated_frame("ltv_prediction", features)
    prediction = model.predict(df)

    ltv = _apply_output_defense(request, float(prediction[0]), features)

    if _freshness_tracker is not None:
        _freshness_tracker.check("ltv_prediction", "behavioral_features", None)

    latency_ms = (time.perf_counter() - t0) * 1000
    _prediction_buffers["ltv_prediction"].append(dict(features))
    return LTVPredictionResponse(
        identity_id=req.identity_id,
        predicted_ltv=round(ltv, 2),
        latency_ms=round(latency_ms, 2),
    )


@router.post("/v1/predict/anomaly", response_model=AnomalyDetectionResponse)
async def predict_anomaly(req: AnomalyDetectionRequest, request: Request) -> AnomalyDetectionResponse:
    """Detect anomalies in a single record.

    Returns an anomaly flag, anomaly score (0–1), and latency. Use
    ``/v1/predict/batch`` with ``model_name=anomaly_detection`` for bulk
    screening.
    """
    t0 = time.perf_counter()
    model = server.get_model("anomaly_detection")
    df = _validated_frame("anomaly_detection", req.features)
    score = _apply_output_defense(request, float(model.predict(df)[0]), req.features)
    _prediction_buffers["anomaly_detection"].append(dict(req.features))
    if _freshness_tracker is not None:
        _freshness_tracker.check("anomaly_detection", "record_features", None)
    latency_ms = (time.perf_counter() - t0) * 1000
    return AnomalyDetectionResponse(
        record_id=req.record_id,
        is_anomaly=score > 0.5,
        anomaly_score=round(score, 4),
        latency_ms=round(latency_ms, 2),
    )


@router.post("/v1/predict/journey", response_model=JourneyPredictionResponse)
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
    if _freshness_tracker is not None:
        _freshness_tracker.check("journey_prediction", "journey_features", None)

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


@router.post("/v1/predict/attribution", response_model=AttributionResponse)
async def predict_attribution(req: AttributionRequest, request: Request) -> AttributionResponse:
    """Compute multi-touch attribution for a conversion.

    Distributes credit across touchpoints using the specified method
    (``shapley``, ``linear``, ``time_decay``, ``position_based``).
    """
    t0 = time.perf_counter()
    model = server.get_model("campaign_attribution")

    journeys = pd.DataFrame(req.touchpoints)
    journeys["conversion_id"] = req.conversion_id

    if _freshness_tracker is not None:
        _freshness_tracker.check("campaign_attribution", "attribution_features", None)
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


@router.post("/v1/predict/identity", response_model=IdentityResolutionResponse)
async def predict_identity(req: IdentityResolutionRequest, request: Request) -> IdentityResolutionResponse:
    """Real-time identity resolution for a cross-device / cross-wallet profile pair.

    Scores the probability that two profiles belong to the same entity using
    device fingerprint similarity, behavioural similarity, temporal overlap,
    and wallet linkage signals. This is a real-time single-pair endpoint —
    bulk merging uses the offline BatchPredictor.

    Requires eight features from the identity_resolution_v1 feature contract:
    device_fingerprint_sim, behavioral_sim, temporal_overlap, shared_ip_count,
    session_sequence_score, geo_distance, browser_match, os_match.
    Optional: wallet_link_score (default 0.0).
    """
    t0 = time.perf_counter()

    # Extraction defense pre-request check
    defense = _get_defense_layer()
    if defense is not None:
        api_key = request.headers.get("X-API-Key", "anon")
        pre = defense.pre_request(api_key, req.features)
        if not pre.allowed:
            raise HTTPException(status_code=429, detail="Request rate limited by extraction defense")
        request.state.extraction_risk = pre.risk_score
        request.state.extraction_disclosure = pre.disclosure

    model = server.get_model("identity_resolution")

    features = dict(req.features)
    features.setdefault("wallet_link_score", 0.0)

    df = _validated_frame("identity_resolution", features)
    raw = model.predict(df)
    merge_probability = float(raw[0]) if hasattr(raw, "__len__") else float(raw)
    merge_probability = max(0.0, min(1.0, merge_probability))

    # Record SLA check for the identity feature group
    if _freshness_tracker is not None:
        _freshness_tracker.check("identity_resolution", "identity_features", None)

    # Apply extraction defense perturbation
    confidence = _apply_output_defense(request, merge_probability, features)

    latency_ms = (time.perf_counter() - t0) * 1000
    _prediction_buffers["identity_resolution"].append(dict(features))
    return IdentityResolutionResponse(
        profile_pair_id=req.profile_pair_id,
        is_same_entity=confidence > 0.5,
        merge_probability=round(merge_probability, 4),
        confidence=round(confidence, 4),
        latency_ms=round(latency_ms, 2),
        model_version=getattr(model, "version", "unknown"),
    )


# =============================================================================
# BATCH PREDICTION
# =============================================================================


@router.post("/v1/predict/batch", response_model=BatchPredictionResponse)
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

    # ── Batch privilege enforcement via RBAC only ────────────────────
    # Caller-supplied headers are not trusted for privilege determination.
    is_privileged = (
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


@router.get("/v1/defense/status")
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


@router.get("/v1/defense/metrics")
async def defense_metrics():
    """Return extraction defense metrics snapshot for monitoring dashboards."""
    defense = _get_defense_layer()
    if defense is None:
        return {"enabled": False, "message": "Extraction defense is not enabled"}
    return defense.get_metrics_snapshot()


@router.get("/v1/defense/risk-scores")
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


@router.get("/v1/defense/canary-triggers")
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


@router.get("/v1/monitoring/freshness")
async def freshness_status() -> dict[str, Any]:
    """Return feature freshness SLA health summary.

    Reports per-model SLA violation counts, violation rates, and maximum
    observed feature age. Intended for monitoring dashboards and alerting;
    not used by inference paths.
    """
    if _freshness_tracker is None:
        return {
            "enabled": False,
            "total_checks": 0,
            "total_violations": 0,
            "violation_rate": 0.0,
            "by_model": {},
        }
    return {"enabled": True, **_freshness_tracker.get_summary()}


@router.get("/v1/monitoring/drift")
async def drift_status() -> dict[str, Any]:
    """Return latest per-model drift detection results.

    Reports PSI/KS/JS divergence scores computed by the background drift
    checker. Returns empty results when the baseline or prediction buffer
    has insufficient data (< 30 rows). The background task runs every 300 s.
    """
    return {
        "last_run": _last_drift_results.get("timestamp"),
        "models": _last_drift_results.get("models", {}),
        "buffer_sizes": {m: len(buf) for m, buf in _prediction_buffers.items()},
    }


@router.get("/v1/monitoring/extraction")
async def extraction_monitor_status() -> dict[str, Any]:
    """Return extraction defense monitoring summary.

    Reports block rates, policy action distribution, band distribution, and
    average risk scores. Returns ``{"enabled": false}`` when the extraction
    defense monitor is unavailable.
    """
    if _extraction_monitor is None:
        return {"enabled": False}
    return {"enabled": True, **_extraction_monitor.get_summary()}


# Mount the shared router on the standalone app so `uvicorn serving.src.api:app`
# continues to work unchanged. When the backend imports `router` directly it
# mounts the same handlers at its own prefix without touching this `app`.
app.include_router(router)


# =============================================================================
# ENTRYPOINT
# =============================================================================


def serve(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Start the serving API with uvicorn."""
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    serve()
