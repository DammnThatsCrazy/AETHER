"""Kyber operator routes — card-linked observability diagnostics.

Nested under the payment-rails admin surface. Operator-gated; exposes
coverage/freshness/reconciliation/privacy state and the release gate —
never raw tenant-private payloads, never enforcement actions.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from config.settings import settings
from shared.common.common import APIResponse, BadRequestError
from shared.logger.logger import get_logger

from services.card_linked_payments.clusters import build_card_linked_clusters
from services.card_linked_payments.diagnostics import card_linked_diagnostics
from services.card_linked_payments.governance import run_release_gate

logger = get_logger("aether.card_linked.kyber")

card_linked_kyber_router = APIRouter(
    prefix="/v1/admin/kyber/payment-rails/card-linked",
    tags=["Admin — Kyber Card-Linked Payment Rails"],
)


def _require_operator(request: Request):
    from services.security.request_context import require_kyber_operator
    return require_kyber_operator(request)


def _require_kyber_enabled() -> None:
    flags = settings.card_linked_payment_rails
    if not (flags.enabled or flags.kyber_enabled):
        raise BadRequestError(
            "Kyber card-linked surfaces are not enabled "
            "(KYBER_CARD_LINKED_PAYMENT_RAILS_ENABLED=false)"
        )


@card_linked_kyber_router.get("/diagnostics")
async def diagnostics(request: Request, tenant_id: str = Query(...)):
    """Catalog freshness, source quality, reconciliation, privacy gates."""
    _require_kyber_enabled()
    _require_operator(request)
    data = await card_linked_diagnostics(tenant_id)
    data["region_policy_defaults"] = {
        "eu_restricted_mode": settings.card_linked_payment_rails.eu_restricted_mode,
        "apac_restricted_mode": settings.card_linked_payment_rails.apac_restricted_mode,
        "provider_pii_block": settings.card_linked_payment_rails.provider_pii_block,
    }
    return APIResponse(data=data).to_dict()


@card_linked_kyber_router.get("/clusters")
async def clusters(request: Request, tenant_id: str = Query(...)):
    """Card-linked cohorts (review/intelligence outputs; never enforcement)."""
    _require_kyber_enabled()
    _require_operator(request)
    if not settings.card_linked_payment_rails.clustering_enabled:
        raise BadRequestError("Card-linked clustering is not enabled")
    items = await build_card_linked_clusters(tenant_id)
    return APIResponse(data={"items": items, "count": len(items)}).to_dict()


@card_linked_kyber_router.get("/release-gate")
async def release_gate(request: Request):
    """Structural semantic/privacy gate results (fail-closed checks)."""
    _require_kyber_enabled()
    _require_operator(request)
    results = [
        {"name": r.name, "passed": r.passed, "detail": r.detail}
        for r in run_release_gate()
    ]
    return APIResponse(data={
        "checks": results,
        "passed": all(r["passed"] for r in results),
    }).to_dict()
