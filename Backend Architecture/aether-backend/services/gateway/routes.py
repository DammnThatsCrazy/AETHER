"""
Aether Service — API Gateway
Health checks, root endpoint, and metrics.
In production: AWS API Gateway + Lambda authorizer.
"""

from __future__ import annotations

from fastapi import APIRouter

from shared.common.common import APIResponse, utc_now
from shared.logger.logger import metrics
from dependencies.providers import get_registry

router = APIRouter(tags=["Gateway"])


@router.get("/health")
@router.get("/v1/health")
async def health_check():
    """Deep health check — probes all dependencies."""
    registry = get_registry()
    dep_health = await registry.health_check()

    all_ok = all(v.get("status") == "ok" for v in dep_health.values())
    return {
        "status": "healthy" if all_ok else "degraded",
        "timestamp": utc_now().isoformat(),
        "dependencies": dep_health,
        "services": {
            "ingestion": "ok",
            "identity": "ok",
            "analytics": "ok",
            "ml_serving": "ok",
            "agent": "ok",
            "campaign": "ok",
            "consent": "ok",
            "notification": "ok",
            "admin": "ok",
        },
    }


@router.get("/v1/metrics")
async def prometheus_metrics():
    """Prometheus metrics endpoint for /metrics scraping."""
    from fastapi.responses import PlainTextResponse
    data = metrics.prometheus_export()
    return PlainTextResponse(content=data.decode("utf-8"), media_type="text/plain; charset=utf-8")


@router.get("/")
async def root():
    return {
        "name": "Aether API",
        "version": "v1",
        "docs": "/docs",
        "health": "/v1/health",
        "metrics": "/v1/metrics",
    }


@router.get("/v1/metrics/json")
async def get_metrics():
    """Internal metrics endpoint (JSON format)."""
    return APIResponse(data=metrics.snapshot()).to_dict()
