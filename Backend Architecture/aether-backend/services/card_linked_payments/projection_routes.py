"""Kyber operator routes — card-linked graph-projection outbox operations.

The durable projection outbox (``card_linked_graph_outbox``) is drained by a
supervised worker; an operator needs an HTTP surface to (a) trigger a bounded
drain, (b) reconcile the flow store against the outbox, and (c) repair drift
(re-enqueue missing projections + replay dead-letters). These three surfaces
are the program sec16 gap-2 operator plane.

Every endpoint is operator-gated (``require_kyber_operator``) and fails closed
when the card-linked rails are disabled — no Aether tenant, including
role-admins, can reach them, and no endpoint exposes tenant-private payloads
(only counts / drift summaries). Rows stay tenant-scoped inside the outbox
repository, so one tenant can never drain or reconcile another.

Endpoints:
    POST /v1/kyber/card-linked/graph-projection/drain      Bounded worker drain pass
    GET  /v1/kyber/card-linked/graph-projection/reconcile  Flow↔outbox drift report
    POST /v1/kyber/card-linked/graph-projection/repair     Re-enqueue missing + replay dead-letters

Only ``router`` is exported; mounting is done by main.py (see wiringNeeds).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from config.settings import settings
from services.security.request_context import require_kyber_operator
from shared.common.common import APIResponse, BadRequestError
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.card_linked.projection_routes")

router = APIRouter(
    prefix="/v1/kyber/card-linked/graph-projection",
    tags=["Admin — Kyber Card-Linked Graph Projection Outbox"],
)


def _require_kyber_enabled() -> None:
    flags = settings.card_linked_payment_rails
    if not (flags.enabled or flags.kyber_enabled):
        raise BadRequestError(
            "Kyber card-linked surfaces are not enabled "
            "(KYBER_CARD_LINKED_PAYMENT_RAILS_ENABLED=false)"
        )


@router.post("/drain")
async def drain_graph_projection(
    request: Request,
    tenant_id: str = Query(None, description="Scope the drain to one tenant"),
    limit: int = Query(100, ge=1, le=1000),
    actor=Depends(require_kyber_operator),
):
    """Run one bounded drain pass over the projection outbox (operator-triggered).

    The supervised worker already drains on a poll interval; this surface lets
    an operator force a pass after a deploy or a repair. Rows go through the
    same canonical ``CardLinkedGraphOutboxWorker`` (bounded retry, backoff,
    dead-lettering). Returns the drain summary counts.
    """
    _require_kyber_enabled()
    from services.card_linked_payments.graph_outbox import CardLinkedGraphOutboxWorker

    summary = await CardLinkedGraphOutboxWorker().drain_once(
        tenant_id=tenant_id or None, limit=limit
    )
    metrics.increment(
        "card_linked_graph_projection_drain_triggered_total",
        value=summary.get("processed", 0),
    )
    return APIResponse(data=summary).to_dict()


@router.get("/reconcile")
async def reconcile_graph_projection(
    request: Request,
    tenant_id: str = Query(..., description="Tenant to reconcile"),
    actor=Depends(require_kyber_operator),
):
    """Drift report between the flow store (truth) and the projection outbox.

    Surfaces never-enqueued flows, dead-letters, pending rows and a healthy
    flag per tenant so an operator can decide whether a repair is warranted.
    """
    _require_kyber_enabled()
    from services.card_linked_payments.graph_outbox import (
        CardLinkedGraphProjectionOutbox,
    )

    report = await CardLinkedGraphProjectionOutbox().reconcile(tenant_id)
    return APIResponse(data=report).to_dict()


@router.post("/repair")
async def repair_graph_projection(
    request: Request,
    tenant_id: str = Query(..., description="Tenant to repair"),
    enqueue_missing: bool = Query(True),
    replay_dead_letters: bool = Query(True),
    actor=Depends(require_kyber_operator),
):
    """Operator repair/replay entry point for the projection outbox.

    Re-enqueues never-projected flows and resets dead-lettered rows back to
    ``queued`` (attempts cleared) so the next drain reprocesses them.
    Idempotent: re-enqueue is a no-op for rows that already exist.
    """
    _require_kyber_enabled()
    from services.card_linked_payments.graph_outbox import (
        CardLinkedGraphProjectionOutbox,
    )

    report = await CardLinkedGraphProjectionOutbox().repair(
        tenant_id,
        enqueue_missing=enqueue_missing,
        replay_dead_letters=replay_dead_letters,
    )
    return APIResponse(data=report).to_dict()
