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


# ── Commerce Diagnostics ──────────────────────────────────────────────────────

_COMMERCE_DIAG_ROUTER = APIRouter(prefix="/v1/diagnostics/commerce", tags=["Commerce Diagnostics"])


@_COMMERCE_DIAG_ROUTER.get("/verification-failures")
async def commerce_verification_failures(request: Request, limit: int = 50):
    """List recent payment verification failures with reason and tx_hash."""
    request.state.tenant.require_permission("commerce:read")
    tenant_id = request.state.tenant.tenant_id

    from repositories.repos import SettlementEventRepository
    repo = SettlementEventRepository()
    rows = await repo.find_many(
        filters={"tenant_id": tenant_id, "status": "failed"},
        limit=limit,
    )
    rows.sort(key=lambda r: r.get("occurred_at", ""), reverse=True)
    return APIResponse(data={"failures": rows[:limit], "count": len(rows)}).to_dict()


@_COMMERCE_DIAG_ROUTER.get("/settlement-timeouts")
async def commerce_settlement_timeouts(request: Request, timeout_seconds: int = 300):
    """
    Identify settlements stuck in pending/verifying state beyond timeout_seconds.
    These represent potential stuck payment flows requiring manual review.
    """
    request.state.tenant.require_permission("commerce:read")
    tenant_id = request.state.tenant.tenant_id

    from datetime import datetime, timedelta, timezone
    from services.x402.commerce_store import get_commerce_store
    store = get_commerce_store()
    settlements = await store.list_settlements(tenant_id)

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
    stuck = []
    for s in settlements:
        if s.state.value in ("pending", "verifying"):
            try:
                created = datetime.fromisoformat(s.created_at)
                if created < cutoff:
                    stuck.append({
                        "settlement_id": s.settlement_id,
                        "state": s.state.value,
                        "created_at": s.created_at,
                        "age_seconds": int((datetime.now(timezone.utc) - created).total_seconds()),
                        "resource_id": getattr(s, "resource_id", None),
                        "amount": getattr(s, "amount_usd", None),
                    })
            except Exception:
                continue

    stuck.sort(key=lambda x: x["age_seconds"], reverse=True)
    return APIResponse(data={"stuck_settlements": stuck, "count": len(stuck), "timeout_seconds": timeout_seconds}).to_dict()


@_COMMERCE_DIAG_ROUTER.get("/approval-expirations")
async def commerce_approval_expirations(request: Request):
    """List approval requests that have expired without a decision."""
    request.state.tenant.require_permission("commerce:read")
    tenant_id = request.state.tenant.tenant_id

    from datetime import datetime, timezone
    from services.x402.commerce_store import get_commerce_store
    from services.x402.commerce_models import ApprovalStatus
    store = get_commerce_store()
    approvals = await store.list_approvals(tenant_id)

    now = datetime.now(timezone.utc)
    expired = []
    for a in approvals:
        if a.status == ApprovalStatus.EXPIRED:
            expired.append({
                "approval_id": a.approval_id,
                "reference_id": a.reference_id,
                "priority": a.priority.value if hasattr(a.priority, "value") else a.priority,
                "created_at": a.created_at,
                "expires_at": getattr(a, "expires_at", None),
                "assignee": getattr(a, "assignee_id", None),
            })

    return APIResponse(data={"expired_approvals": expired, "count": len(expired)}).to_dict()


@_COMMERCE_DIAG_ROUTER.get("/duplicate-payments")
async def commerce_duplicate_payments(request: Request, window_seconds: int = 3600):
    """
    Detect potential duplicate payment attempts within the given window.
    Groups settlement events by (agent_id, resource_id, amount) within the window.
    """
    request.state.tenant.require_permission("commerce:read")
    tenant_id = request.state.tenant.tenant_id

    from datetime import datetime, timedelta, timezone
    from collections import defaultdict
    from repositories.repos import SettlementEventRepository
    repo = SettlementEventRepository()
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=window_seconds)).isoformat()
    rows = await repo.find_many(filters={"tenant_id": tenant_id}, limit=5000)
    recent = [r for r in rows if r.get("occurred_at", "") >= cutoff]

    groups: dict[str, list] = defaultdict(list)
    for r in recent:
        key = f"{r.get('agent_id')}:{r.get('provider')}:{r.get('amount')}:{r.get('currency')}"
        groups[key].append(r)

    duplicates = [
        {"key": key, "count": len(events), "events": events}
        for key, events in groups.items()
        if len(events) > 1
    ]
    duplicates.sort(key=lambda x: x["count"], reverse=True)
    return APIResponse(data={"duplicates": duplicates, "count": len(duplicates), "window_seconds": window_seconds}).to_dict()


@_COMMERCE_DIAG_ROUTER.get("/reconciliation-drift")
async def commerce_reconciliation_drift(request: Request):
    """
    Identify payment intents that have no corresponding settlement event —
    these represent potential reconciliation gaps.
    """
    request.state.tenant.require_permission("commerce:read")
    tenant_id = request.state.tenant.tenant_id

    from repositories.repos import PaymentIntentRepository, SettlementEventRepository
    intents_repo = PaymentIntentRepository()
    settlements_repo = SettlementEventRepository()

    intents = await intents_repo.find_many(filters={"tenant_id": tenant_id}, limit=5000)
    settlements = await settlements_repo.find_many(filters={"tenant_id": tenant_id}, limit=5000)
    settled_intent_ids = {s.get("intent_id") for s in settlements}

    drifted = [
        i for i in intents
        if i.get("intent_id") not in settled_intent_ids
        and i.get("settlement_status") not in ("settled", "paid", "success", "access_granted", "failed")
    ]
    return APIResponse(data={
        "drifted_intents": drifted,
        "count": len(drifted),
        "total_intents_scanned": len(intents),
    }).to_dict()


commerce_diagnostics_router = _COMMERCE_DIAG_ROUTER
