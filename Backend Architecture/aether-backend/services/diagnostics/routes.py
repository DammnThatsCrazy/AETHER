"""
Aether Service — Diagnostics Routes
Exposes error registry, health checks, and diagnostic reports.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from shared.common.common import APIResponse
from shared.diagnostics.error_registry import error_registry, ErrorCategory, ErrorSeverity
from shared.logger.logger import get_logger

logger = get_logger("aether.service.diagnostics")
router = APIRouter(prefix="/v1/diagnostics", tags=["Diagnostics"])


@router.get("/health")
async def diagnostics_health(request: Request):
    """Quick health check — suitable for monitoring/alerting systems."""
    request.state.tenant.require_permission("admin")
    return APIResponse(data=error_registry.health_check()).to_dict()


@router.get("/errors")
async def list_errors(
    request: Request,
    service: str = "",
    category: str = "",
    severity: str = "",
    resolved: bool = None,
    limit: int = 50,
):
    """List tracked errors with optional filters."""
    request.state.tenant.require_permission("admin")

    cat = ErrorCategory(category) if category else None
    sev = ErrorSeverity(severity) if severity else None

    errors = error_registry.get_errors(
        service=service or None,
        category=cat,
        severity=sev,
        resolved=resolved,
        limit=limit,
    )
    return APIResponse(data={"errors": errors, "count": len(errors)}).to_dict()


@router.get("/report")
async def diagnostics_report(request: Request):
    """Generate comprehensive diagnostics report."""
    request.state.tenant.require_permission("admin")
    return APIResponse(data=error_registry.get_report()).to_dict()


@router.post("/errors/{fingerprint}/resolve")
async def resolve_error(fingerprint: str, request: Request):
    """Mark an error as resolved by its fingerprint."""
    request.state.tenant.require_permission("admin")
    resolved = error_registry.resolve(fingerprint)
    return APIResponse(data={"fingerprint": fingerprint, "resolved": resolved}).to_dict()


@router.post("/errors/{fingerprint}/suppress")
async def suppress_error(fingerprint: str, request: Request):
    """Suppress alerts for a known error by fingerprint."""
    request.state.tenant.require_permission("admin")
    error_registry.suppress(fingerprint)
    return APIResponse(data={"fingerprint": fingerprint, "suppressed": True}).to_dict()


@router.get("/circuit-breakers")
async def list_circuit_breakers(request: Request):
    """List all circuit breaker states."""
    request.state.tenant.require_permission("admin")
    breakers = {
        key: {"state": cb.state, "failures": cb._failure_count}
        for key, cb in error_registry._circuit_breakers.items()
    }
    return APIResponse(data=breakers).to_dict()
