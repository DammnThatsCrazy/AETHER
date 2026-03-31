"""
Aether Intelligence — Extraction Defense Views

Analyst-oriented endpoints for investigating extraction activity,
cluster behavior, and alert management.

Endpoints:
    GET  /v1/intelligence/extraction/overview      — System-wide extraction overview
    GET  /v1/intelligence/extraction/actor/{id}     — Actor extraction profile
    GET  /v1/intelligence/extraction/alerts          — Recent extraction alerts
    GET  /v1/intelligence/extraction/clusters        — Suspicious cluster summary
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

from shared.common.common import APIResponse, utc_now
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.intelligence.extraction")
router = APIRouter(prefix="/v1/intelligence/extraction", tags=["Extraction Intelligence"])


class ExtractionOverview(BaseModel):
    total_requests_1h: int = 0
    blocked_requests_1h: int = 0
    active_alerts: int = 0
    red_band_actors: int = 0
    orange_band_actors: int = 0
    top_signals: list[dict[str, Any]] = []


class ActorExtractionProfile(BaseModel):
    actor_id: str
    risk_score: float = 0.0
    risk_band: str = "green"
    signals: list[dict[str, Any]] = []
    budget_usage: dict[str, Any] = {}
    recent_models: list[str] = []
    linked_identities: list[str] = []


class ExtractionAlert(BaseModel):
    alert_id: str = ""
    actor_id: str = ""
    risk_score: float = 0.0
    band: str = ""
    reasons: list[str] = []
    timestamp: str = ""
    status: str = "open"


# ── In-memory alert store (production: persisted via alert repo) ─────

_alerts: list[dict[str, Any]] = []
_overview_cache: dict[str, Any] = {}


def record_extraction_alert(
    actor_id: str,
    risk_score: float,
    band: str,
    reasons: list[str],
) -> None:
    """Record an extraction alert for analyst visibility."""
    import uuid
    alert = {
        "alert_id": f"exalert_{uuid.uuid4().hex[:12]}",
        "actor_id": actor_id,
        "risk_score": round(risk_score, 2),
        "band": band,
        "reasons": reasons[:10],
        "timestamp": utc_now().isoformat(),
        "status": "open",
    }
    _alerts.append(alert)
    # Cap at 1000 alerts in memory
    if len(_alerts) > 1000:
        _alerts.pop(0)
    metrics.increment("extraction_alert_opened", labels={"band": band})
    logger.warning(
        "Extraction alert: actor=%s score=%.1f band=%s",
        actor_id[:12] + "..." if len(actor_id) > 12 else actor_id,
        risk_score,
        band,
    )


def update_overview_metrics(
    total_requests_1h: int = 0,
    blocked_requests_1h: int = 0,
    red_count: int = 0,
    orange_count: int = 0,
) -> None:
    """Update cached overview metrics."""
    _overview_cache.update({
        "total_requests_1h": total_requests_1h,
        "blocked_requests_1h": blocked_requests_1h,
        "red_band_actors": red_count,
        "orange_band_actors": orange_count,
        "updated_at": utc_now().isoformat(),
    })


# ── Routes ───────────────────────────────────────────────────────────

@router.get("/overview")
async def extraction_overview(request: Request):
    """System-wide extraction defense overview for analyst dashboards."""
    request.state.tenant.require_permission("admin")

    open_alerts = [a for a in _alerts if a["status"] == "open"]

    overview = {
        "total_requests_1h": _overview_cache.get("total_requests_1h", 0),
        "blocked_requests_1h": _overview_cache.get("blocked_requests_1h", 0),
        "active_alerts": len(open_alerts),
        "red_band_actors": _overview_cache.get("red_band_actors", 0),
        "orange_band_actors": _overview_cache.get("orange_band_actors", 0),
        "recent_alerts": open_alerts[-10:],
        "updated_at": _overview_cache.get("updated_at", utc_now().isoformat()),
    }

    return APIResponse(data=overview).to_dict()


@router.get("/alerts")
async def extraction_alerts(request: Request, status: str = "open", limit: int = 50):
    """List recent extraction alerts."""
    request.state.tenant.require_permission("admin")

    filtered = [a for a in _alerts if a["status"] == status]
    return APIResponse(data={
        "alerts": filtered[-limit:],
        "total": len(filtered),
    }).to_dict()


@router.get("/actor/{actor_id}")
async def actor_extraction_profile(actor_id: str, request: Request):
    """Get extraction risk profile for a specific actor."""
    request.state.tenant.require_permission("admin")

    actor_alerts = [a for a in _alerts if a["actor_id"] == actor_id]
    latest_alert = actor_alerts[-1] if actor_alerts else None

    profile = {
        "actor_id": actor_id,
        "risk_score": latest_alert["risk_score"] if latest_alert else 0.0,
        "risk_band": latest_alert["band"] if latest_alert else "green",
        "alert_count": len(actor_alerts),
        "recent_alerts": actor_alerts[-5:],
    }

    return APIResponse(data=profile).to_dict()


@router.get("/clusters")
async def suspicious_clusters(request: Request, min_score: float = 50.0):
    """List identity clusters with elevated extraction risk."""
    request.state.tenant.require_permission("admin")

    # Aggregate alerts by actor and identify cluster-level patterns
    actor_scores: dict[str, float] = {}
    for alert in _alerts:
        actor = alert["actor_id"]
        actor_scores[actor] = max(actor_scores.get(actor, 0), alert["risk_score"])

    suspicious = [
        {"actor_id": actor, "max_risk_score": score}
        for actor, score in sorted(actor_scores.items(), key=lambda x: -x[1])
        if score >= min_score
    ]

    return APIResponse(data={
        "clusters": suspicious[:50],
        "total_suspicious": len(suspicious),
    }).to_dict()
