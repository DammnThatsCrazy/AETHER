"""
Aether Service — API Gateway
Health checks, root endpoint, metrics, and the public status history feed.
In production: AWS API Gateway + Lambda authorizer.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Query, Request
from fastapi.responses import JSONResponse

from config.settings import settings
from shared.common.common import APIResponse, problem_response, utc_now
from shared.logger.logger import get_logger, metrics
from dependencies.providers import get_registry
from services.gateway import component_status, status_history
from services.gateway.readiness import readiness_report

logger = get_logger("aether.service.gateway")

router = APIRouter(tags=["Gateway"])


@router.get("/health")
@router.get("/v1/health")
async def health_check(request: Request, background_tasks: BackgroundTasks):
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

    The same verdict feeds the public status history: at most once per sample
    interval per process it is folded into the daily rollups behind
    ``/v1/status/history``, as a background task that runs after this response
    is sent and swallows its own failures (services/gateway/status_history.py).
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
    overall_healthy = dependencies_ok and components_ok

    record = status_history.recorder.claim(
        overall_healthy=overall_healthy, components=components
    )
    if record is not None:
        background_tasks.add_task(record)

    return {
        "status": "healthy" if overall_healthy else "degraded",
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


@router.get("/v1/status/history")
async def status_history_feed(
    request: Request,
    days: int = Query(
        status_history.DEFAULT_HISTORY_DAYS,
        ge=1,
        le=status_history.MAX_HISTORY_DAYS,
        description="Days of history ending today (UTC), 1-90.",
    ),
):
    """Public per-component daily uptime for the status page (read-only).

    Unauthenticated (listed in ``feature_gate.PUBLIC_PATHS``) and aggregate
    only: each component lists the UTC days that have observed health samples,
    with ``status`` (operational / degraded / outage) and ``uptime_pct``. Days
    without samples are omitted so the page renders them as "no data". Rate
    limited per client IP and cached briefly in-process; the response carries
    a public ``Cache-Control``. Scoring and sample provenance:
    services/gateway/status_history.py.
    """
    request_id = getattr(request.state, "request_id", "")
    peer = request.client.host if request.client else None
    redis = getattr(getattr(get_registry(), "cache", None), "_redis", None)
    retry_after = await status_history.rate_limiter.check(
        status_history.client_ip(request.headers, peer), redis
    )
    if retry_after is not None:
        metrics.increment("status_history_rate_limited_total")
        return problem_response(
            429,
            "Too Many Requests",
            "Status history rate limit exceeded",
            code="RATE_LIMITED",
            retryable=True,
            request_id=request_id,
            headers={"Retry-After": str(retry_after)},
        )
    try:
        body = await status_history.service.history(days)
    except Exception as exc:  # noqa: BLE001 - public surface: no internals leak
        logger.warning(f"status history unavailable: {type(exc).__name__}")
        metrics.increment("status_history_read_failures_total")
        return problem_response(
            503,
            "Service Unavailable",
            "Status history is temporarily unavailable",
            code="STATUS_HISTORY_UNAVAILABLE",
            retryable=True,
            request_id=request_id,
            headers={"Cache-Control": "no-store"},
        )
    return JSONResponse(
        content=body,
        headers={"Cache-Control": status_history.CACHE_CONTROL},
    )
