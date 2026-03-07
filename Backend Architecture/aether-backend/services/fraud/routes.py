"""
Aether Backend — Fraud Detection Service Routes

Exposes the fraud scoring engine via a REST API.  The ``/evaluate`` endpoint
is the primary integration point for real-time fraud checks.

Routes:
    POST /v1/fraud/evaluate        Evaluate an event for fraud
    POST /v1/fraud/evaluate/batch  Batch fraud evaluation
    GET  /v1/fraud/config          Get current fraud configuration
    PUT  /v1/fraud/config          Update fraud configuration
    GET  /v1/fraud/stats           Fraud detection statistics
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from services.fraud.engine import FraudConfig, FraudEngine, FraudResult
from shared.decorators import api_response
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.fraud")

router = APIRouter(prefix="/v1/fraud", tags=["fraud"])


# ========================================================================
# REQUEST / RESPONSE MODELS
# ========================================================================

class FraudEvaluationRequest(BaseModel):
    """Payload for single-event fraud evaluation."""
    event: dict[str, Any] = Field(..., description="Raw event data")
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Enrichment context: IP metadata, device info, wallet data, etc.",
    )


class SignalDetail(BaseModel):
    name: str
    score: float
    weight: float
    triggered: bool
    details: dict[str, Any] = Field(default_factory=dict)


class FraudEvaluationResponse(BaseModel):
    audit_id: str
    composite_score: float
    verdict: str
    signals: list[SignalDetail]
    evaluation_ms: float


class BatchFraudRequest(BaseModel):
    """Payload for batch fraud evaluation."""
    events: list[FraudEvaluationRequest] = Field(..., min_length=1, max_length=100)


class BatchFraudResponse(BaseModel):
    results: list[FraudEvaluationResponse]
    total: int
    blocked: int
    flagged: int
    passed: int


class FraudConfigResponse(BaseModel):
    block_threshold: float
    flag_threshold: float
    enable_audit_trail: bool
    max_evaluation_ms: int
    signals: list[str]


class FraudConfigUpdate(BaseModel):
    """Partial update for fraud configuration."""
    block_threshold: Optional[float] = None
    flag_threshold: Optional[float] = None
    enable_audit_trail: Optional[bool] = None
    max_evaluation_ms: Optional[int] = None
    custom_weights: Optional[dict[str, float]] = None


class FraudStatsResponse(BaseModel):
    total_evaluated: int
    blocked: int
    flagged: int
    passed: int
    avg_score: float
    avg_evaluation_ms: float


# ========================================================================
# IN-MEMORY STATE (production: Redis / DynamoDB)
# ========================================================================

class _FraudStats:
    """Lightweight in-memory statistics accumulator."""

    def __init__(self) -> None:
        self.total: int = 0
        self.verdicts: dict[str, int] = defaultdict(int)
        self.score_sum: float = 0.0
        self.elapsed_sum: float = 0.0

    def record(self, result: FraudResult) -> None:
        self.total += 1
        self.verdicts[result.verdict] += 1
        self.score_sum += result.composite_score
        self.elapsed_sum += result.evaluation_ms

    def snapshot(self) -> dict[str, Any]:
        return {
            "total_evaluated": self.total,
            "blocked": self.verdicts.get("block", 0),
            "flagged": self.verdicts.get("flag", 0),
            "passed": self.verdicts.get("pass", 0),
            "avg_score": round(self.score_sum / max(self.total, 1), 4),
            "avg_evaluation_ms": round(self.elapsed_sum / max(self.total, 1), 2),
        }


_config = FraudConfig()
_engine = FraudEngine(_config)
_stats = _FraudStats()


# ========================================================================
# HELPERS
# ========================================================================

def _to_response(result: FraudResult) -> FraudEvaluationResponse:
    """Map engine result to API response model."""
    return FraudEvaluationResponse(
        audit_id=result.audit_id,
        composite_score=round(result.composite_score, 4),
        verdict=result.verdict,
        signals=[
            SignalDetail(
                name=s.name,
                score=round(s.score, 4),
                weight=s.weight,
                triggered=s.triggered,
                details=s.details,
            )
            for s in result.signals
        ],
        evaluation_ms=round(result.evaluation_ms, 2),
    )


# ========================================================================
# ROUTES
# ========================================================================

@router.post("/evaluate", response_model=None)
@api_response
async def evaluate_event(body: FraudEvaluationRequest, request: Request):
    """Evaluate a single event for fraud and return a scored verdict."""
    request.state.tenant.require_permission("fraud:evaluate")
    result = await _engine.evaluate(body.event, body.context)
    _stats.record(result)
    metrics.increment("fraud_evaluate_requests", labels={"verdict": result.verdict})
    return _to_response(result).model_dump()


@router.post("/evaluate/batch", response_model=None)
@api_response
async def evaluate_batch(body: BatchFraudRequest, request: Request):
    """Evaluate a batch of events. Returns individual results plus summary counts."""
    request.state.tenant.require_permission("fraud:evaluate")
    responses: list[FraudEvaluationResponse] = []
    counts: dict[str, int] = defaultdict(int)

    for item in body.events:
        result = await _engine.evaluate(item.event, item.context)
        _stats.record(result)
        counts[result.verdict] += 1
        responses.append(_to_response(result))

    metrics.increment("fraud_batch_requests")
    return BatchFraudResponse(
        results=responses,
        total=len(responses),
        blocked=counts.get("block", 0),
        flagged=counts.get("flag", 0),
        passed=counts.get("pass", 0),
    ).model_dump()


@router.get("/config", response_model=None)
@api_response
async def get_config(request: Request):
    """Return the current fraud engine configuration."""
    request.state.tenant.require_permission("fraud:read")
    return FraudConfigResponse(
        block_threshold=_config.block_threshold,
        flag_threshold=_config.flag_threshold,
        enable_audit_trail=_config.enable_audit_trail,
        max_evaluation_ms=_config.max_evaluation_ms,
        signals=_engine.list_signals(),
    ).model_dump()


@router.put("/config", response_model=None)
@api_response
async def update_config(body: FraudConfigUpdate, request: Request):
    """Update fraud engine configuration (partial update)."""
    request.state.tenant.require_permission("admin")
    global _config, _engine

    if body.block_threshold is not None:
        _config.block_threshold = body.block_threshold
    if body.flag_threshold is not None:
        _config.flag_threshold = body.flag_threshold
    if body.enable_audit_trail is not None:
        _config.enable_audit_trail = body.enable_audit_trail
    if body.max_evaluation_ms is not None:
        _config.max_evaluation_ms = body.max_evaluation_ms
    if body.custom_weights is not None:
        _config.custom_weights.update(body.custom_weights)
        # Rebuild engine so custom weights take effect
        _engine = FraudEngine(_config)

    logger.info("Fraud config updated: block=%.1f flag=%.1f", _config.block_threshold, _config.flag_threshold)
    metrics.increment("fraud_config_updates")
    return {"updated": True}


@router.get("/stats", response_model=None)
@api_response
async def get_stats(request: Request):
    """Return aggregated fraud detection statistics."""
    request.state.tenant.require_permission("fraud:read")
    return _stats.snapshot()
