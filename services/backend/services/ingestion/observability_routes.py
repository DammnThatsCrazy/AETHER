"""Operator route for ingestion funnel observability + Observation Inspector
(WS-E 1/2, blueprint §17).

The Kyber operator ingestion control plane over
:mod:`services.ingestion.ingestion_observability` — Kyber-operator-only
(router-level ``require_kyber_operator``). These surfaces are READ-ONLY and
mirror the replay route's adoption posture: the router stays mounted so gateway
discovery sees it, and each body reports ``enabled`` from the flag-gated ledger
(``settings.ingestion_observability.enabled``,
``AETHER_INGESTION_OBSERVABILITY_ENABLED``, default OFF). While OFF no
instrumentation runs and the surfaces return empty/disabled rather than error,
so the UI can render the feature as not-enabled.

The GET /v1/health/pipeline health surface and the GET /v1/config/sdk/versions
capability-manifest surface live beside this router (gateway / sdk_config
routes respectively) and read the same ledger / tier model.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from services.ingestion.ingestion_observability import (
    funnel_snapshot,
    recent_trace_snapshot,
    trace_snapshot,
)
from services.security.request_context import require_kyber_operator

ingestion_observability_router = APIRouter(
    prefix="/v1/kyber/ingest/observability",
    tags=["Kyber Ingestion Observability"],
    dependencies=[Depends(require_kyber_operator)],
)


@ingestion_observability_router.get(
    "", summary="Ingestion observability status (funnel + instrumentation)"
)
async def observability_status() -> dict:
    """Operator visibility: the ledger switch + what this slice monitors.

    ``monitored_stages`` are the stages this build records (RECEIVED / VALIDATED
    / BRONZE from the API process, NORMALIZED / PROJECTIONS from the worker
    functions); ``declared_unmonitored`` completes the blueprint §17 ladder for
    the control plane to render.
    """
    snapshot = funnel_snapshot()
    return {
        "enabled": snapshot["enabled"],
        "recorded_at": snapshot["recorded_at"],
        "instrumentation": snapshot["instrumentation"],
    }


@ingestion_observability_router.get(
    "/funnel", summary="Ingestion funnel telemetry (per-stage counts)"
)
async def funnel() -> dict:
    """Per-stage ingestion funnel telemetry for the Kyber control plane.

    Rollup: received / accepted / duplicates / rejected / degraded. Per-stage
    buckets carry the disposition split (accepted / duplicate / rejected /
    degraded / observed). ``monitored: false`` stages complete the ladder but
    are not instrumented in this slice.
    """
    return funnel_snapshot()


@ingestion_observability_router.get(
    "/traces/{event_id}",
    summary="Observation Inspector — one observation's stage trace",
)
async def observation_trace(event_id: str, tenant_id: str = "") -> dict:
    """The RAW→…→METRICS/FINDINGS ladder for one observation.

    ``event_id`` is the client event id (the same id returned by /v1/batch);
    ``tenant_id`` (query) scopes the lookup. Returns ``{"trace": {...}}`` or
    ``{"trace": null}`` when the ledger has no record for that key. Flag OFF
    returns ``{"trace": null}`` — no instrumentation ran.
    """
    return {"trace": trace_snapshot(tenant_id=tenant_id, event_id=event_id)}


@ingestion_observability_router.get(
    "/traces", summary="Recent observation traces (inspector browse)"
)
async def recent_traces(limit: int = 50) -> dict:
    """The most recently started observation traces (bounded; flag-gated)."""
    return {"traces": recent_trace_snapshot(limit=limit)}
