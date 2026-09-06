"""
Aether Service — API Gateway
Health checks, root endpoint, and metrics.
In production: AWS API Gateway + Lambda authorizer.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from config.settings import settings
from shared.common.common import APIResponse, utc_now
from shared.logger.logger import metrics
from dependencies.providers import get_registry
from services.gateway import component_status
from services.gateway.readiness import readiness_report

router = APIRouter(tags=["Gateway"])


@router.get("/health")
@router.get("/v1/health")
async def health_check(request: Request):
    """Container liveness probe — is this process alive and serving?

    ECS uses this route as the API container's ``healthCheck`` command and the
    ALB target group uses it as its health check path, so it answers a liveness
    question and keeps returning 200 for as long as the process can serve. A
    degraded dependency must not make the orchestrator kill an otherwise-live
    container; that verdict belongs to ``/v1/ready``, which returns 503.

    What the body reports is a different matter: every per-component state here
    is derived from observed state (router table, dependency probes, worker
    supervisor, published backlog gauges, model registry, work counters), and a
    signal this process cannot observe is reported as unknown and listed under
    the component's ``unverified`` key. See services/gateway/component_status.py.
    """
    registry = get_registry()
    dependency_health = await registry.health_check()

    components = component_status.component_report(
        dependency_health=dependency_health,
        route_paths=component_status.collect_route_paths(request.app),
        worker_view=component_status.collect_worker_view(request.app),
        metrics_snapshot=metrics.snapshot(),
    )
    dependencies_ok = all(
        entry.get("status") == component_status.STATUS_OK
        for entry in dependency_health.values()
        if isinstance(entry, dict)
    )
    components_ok = component_status.aggregate_status(components) == component_status.STATUS_OK

    return {
        "status": "healthy" if dependencies_ok and components_ok else "degraded",
        "probe": "liveness",
        "readiness_probe": "/v1/ready",
        "timestamp": utc_now().isoformat(),
        "dependencies": dependency_health,
        "components": components,
    }


@router.get("/ready")
@router.get("/v1/ready")
async def readiness_check(request: Request):
    """Readiness probe — infra, migration alignment, and worker health.

    Worker health is no longer advisory. A failed, stopped, stale-heartbeat or
    entirely unregistered release-critical role fails this probe; a non-critical
    role failure marks only its own entry in the ``capabilities`` map and leaves
    the probe passing. Deployment gates read this route, not ``/v1/health``,
    which stays a liveness predicate so a degraded container is not killed
    mid-rollout.

    Scope worth knowing when gating on it: this evaluates the supervisor in
    *this* process. The ALB fronts the api service, which supervises no worker
    roles, so its workers check reports "skipped" and asserts nothing about the
    worker fleet. Worker processes serve their own readiness surface for that.

    Returns 200 when ready, 503 with the full check map when not.
    """
    registry = get_registry()
    supervisor = getattr(request.app.state, "worker_supervisor", None)
    ready, report = await readiness_report(registry, supervisor, settings)
    return JSONResponse(status_code=200 if ready else 503, content=report)


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


@router.get("/v1/health/pipeline")
async def health_pipeline():
    """Ingestion funnel pipeline health (WS-E 3).

    Fixes the previously-phantom ``GET /v1/health/pipeline`` the Kyber operator
    hook called. Reports the ingestion funnel the same way the other health
    routes report components: a 200-shaped payload with ``status`` healthy /
    degraded / disabled. ``enabled: false`` (with zeroed counters) while the
    ingestion-observability flag is OFF, so the liveness surface stays stable.
    """
    from services.ingestion.ingestion_observability import pipeline_snapshot

    return pipeline_snapshot()
