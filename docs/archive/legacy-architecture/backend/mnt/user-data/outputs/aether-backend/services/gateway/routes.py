"""
Aether Service — API Gateway
Health checks, root endpoint, and request routing.
In production: AWS API Gateway + Lambda authorizer.
"""

from __future__ import annotations

from fastapi import APIRouter
from shared.common.common import utc_now

router = APIRouter(tags=["Gateway"])


@router.get("/health")
@router.get("/v1/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": utc_now().isoformat(),
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


@router.get("/")
async def root():
    return {
        "name": "Aether API",
        "version": "v1",
        "docs": "/docs",
        "health": "/v1/health",
    }
