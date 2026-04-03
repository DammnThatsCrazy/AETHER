"""
Aether Backend — Automated Analytics Routes

FastAPI routes for the analytics automation service. Provides endpoints
for event ingestion through the automation pipeline, campaign metrics
retrieval, platform-wide overviews, and automated insight access.

Routes:
    POST /v1/automation/ingest                 Process event through automation pipeline
    GET  /v1/automation/metrics/{campaign_id}  Campaign metrics over a time range
    GET  /v1/automation/overview               Platform-wide analytics overview
    GET  /v1/automation/insights               Automated insights and anomalies
    POST /v1/automation/report/{campaign_id}   Generate full campaign report
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from services.analytics_automation.pipeline import AnalyticsPipeline
from shared.decorators import require_api_key_raw
from shared.logger.logger import get_logger

logger = get_logger("aether.analytics_automation.routes")

router = APIRouter(prefix="/v1/automation", tags=["analytics_automation"])

# Singleton pipeline instance (production: injected via DI container)
_pipeline = AnalyticsPipeline()


# =============================================================================
# REQUEST / RESPONSE MODELS
# =============================================================================


class IngestEventRequest(BaseModel):
    """Request body for ingesting a single event through the automation pipeline."""

    type: str = Field(..., description="Event action type (e.g. 'swap', 'purchase', 'page_view')")
    campaign_id: Optional[str] = Field(
        default="default",
        description="Campaign to attribute this event to",
    )
    user: Optional[str] = Field(
        default=None,
        description="User identifier (wallet address, user ID, etc.)",
    )
    wallet_address: Optional[str] = Field(
        default=None,
        description="Wallet address (for Web3 events)",
    )
    timestamp: Optional[str] = Field(
        default=None,
        description="ISO-8601 timestamp; server time used if omitted",
    )
    properties: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary event properties",
    )


class IngestEventResponse(BaseModel):
    """Response after processing an event through the automation pipeline."""

    success: bool
    event_id: str
    campaign_id: str
    platform: str
    intent: str
    reward_triggered: bool
    fraud_blocked: bool
    reward_id: Optional[str] = None
    insights_generated: int


class CampaignMetricsResponse(BaseModel):
    """Aggregated campaign metrics over a time range."""

    campaign_id: str
    total_events: int
    total_rewards: int
    total_fraud_blocked: int
    conversion_rate: float
    top_channels: dict[str, int]
    windows: list[dict[str, Any]]


class PlatformOverviewResponse(BaseModel):
    """Cross-platform analytics summary."""

    period_hours: int
    total_events: int
    web2_events: int
    web3_events: int
    total_conversions: int
    conversion_rate: float
    total_rewards_issued: int
    total_fraud_blocked: int
    active_campaigns: int


class InsightResponse(BaseModel):
    """A single automated insight."""

    type: str
    severity: str
    message: str
    data: dict[str, Any]
    timestamp: str


# =============================================================================
# ROUTES
# =============================================================================


@router.post("/ingest", response_model=IngestEventResponse)
async def ingest_event(
    body: IngestEventRequest,
    api_key: str = Depends(require_api_key_raw),
) -> IngestEventResponse:
    """Process an event through the full automation pipeline.

    The pipeline classifies the event, updates campaign metrics, checks reward
    eligibility, and generates automated insights when thresholds are crossed.
    """
    event_dict: dict[str, Any] = {
        "action_type": body.type,
        "campaign_id": body.campaign_id or "default",
        "user": body.user or body.wallet_address,
        "wallet_address": body.wallet_address,
        "timestamp": body.timestamp,
        "properties": body.properties,
    }

    result = await _pipeline.ingest_event(event_dict)

    logger.info(
        "Automation ingest: api_key=%s type=%s campaign=%s reward=%s",
        api_key[:8], body.type, body.campaign_id, result.get("reward_triggered"),
    )

    return IngestEventResponse(
        success=True,
        event_id=result["event_id"],
        campaign_id=result["campaign_id"],
        platform=result["platform"],
        intent=result["intent"],
        reward_triggered=result["reward_triggered"],
        fraud_blocked=result["fraud_blocked"],
        reward_id=result.get("reward_id"),
        insights_generated=result["insights_generated"],
    )


@router.get("/metrics/{campaign_id}", response_model=CampaignMetricsResponse)
async def get_campaign_metrics(
    campaign_id: str,
    hours: int = Query(default=24, ge=1, le=720, description="Lookback period in hours"),
    api_key: str = Depends(require_api_key_raw),
) -> CampaignMetricsResponse:
    """Retrieve aggregated metrics for a specific campaign."""
    metrics = await _pipeline.get_campaign_metrics(campaign_id, hours=hours)
    data = metrics.to_dict()

    return CampaignMetricsResponse(
        campaign_id=data["campaign_id"],
        total_events=data["total_events"],
        total_rewards=data["total_rewards"],
        total_fraud_blocked=data["total_fraud_blocked"],
        conversion_rate=data["conversion_rate"],
        top_channels=data["top_channels"],
        windows=data["windows"],
    )


@router.get("/overview", response_model=PlatformOverviewResponse)
async def get_platform_overview(
    hours: int = Query(default=24, ge=1, le=720, description="Lookback period in hours"),
    api_key: str = Depends(require_api_key_raw),
) -> PlatformOverviewResponse:
    """Retrieve a cross-platform analytics overview combining Web2 and Web3 data."""
    overview = await _pipeline.get_platform_overview(hours=hours)

    return PlatformOverviewResponse(**overview)


@router.get("/insights", response_model=list[InsightResponse])
async def get_insights(
    api_key: str = Depends(require_api_key_raw),
) -> list[InsightResponse]:
    """Retrieve automated insights including anomaly detection results.

    Runs the anomaly detection engine and returns both newly detected anomalies
    and previously generated insights.
    """
    # Run anomaly detection to surface any new issues
    new_anomalies = await _pipeline.detect_anomalies()

    # Combine with existing insights (last 50)
    all_insights = _pipeline._insights[-50:]

    return [
        InsightResponse(
            type=i.type,
            severity=i.severity,
            message=i.message,
            data=i.data,
            timestamp=i.timestamp.isoformat(),
        )
        for i in all_insights
    ]


@router.post("/report/{campaign_id}")
async def generate_campaign_report(
    campaign_id: str,
    api_key: str = Depends(require_api_key_raw),
) -> dict[str, Any]:
    """Generate a comprehensive campaign performance report.

    Includes ROI calculation, channel breakdown, fraud analysis,
    recent insights, and detailed metric windows.
    """
    report = await _pipeline.generate_report(campaign_id)

    logger.info(
        "Report generated: campaign=%s events=%d conversions=%d",
        campaign_id,
        report["summary"]["total_events"],
        report["summary"]["total_conversions"],
    )

    return {"success": True, "report": report}
