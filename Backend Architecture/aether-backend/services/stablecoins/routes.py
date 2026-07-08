"""Stablecoin Intelligence tenant and Kyber operator routes.

Feature-flagged; all routes default off until PR2-PR4 product surfaces are
verified in staging. Router is registered unconditionally in main.py so the
feature flag can be checked per-request without a restart.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/v1/stablecoin", tags=["stablecoin-intelligence"])
kyber_router = APIRouter(prefix="/v1/admin/kyber/stablecoin", tags=["kyber-stablecoin"])


@router.get("/health")
async def stablecoin_health() -> dict[str, str]:
    return {"status": "ok", "domain": "stablecoin_intelligence", "feature_gate": "off_by_default"}


@kyber_router.get("/health")
async def kyber_stablecoin_health() -> dict[str, str]:
    return {"status": "ok", "domain": "kyber_stablecoin_operations", "feature_gate": "off_by_default"}
