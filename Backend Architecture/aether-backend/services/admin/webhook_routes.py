"""
Aether Service — Stripe Webhook Handler

Receives and processes incoming Stripe webhook events. This endpoint is
PUBLIC — auth is provided by Stripe-Signature HMAC verification, not by
Aether API keys. The path is listed in feature_gate.PUBLIC_PATHS so the
auth/rate-limit middleware stack is bypassed entirely.

Endpoint:
    POST /v1/admin/billing/stripe/webhook

Events handled:
    checkout.session.completed      — New subscription; maps customer to tenant,
                                      activates plan tier
    customer.subscription.created   — Subscription object created (may arrive
                                      alongside or instead of checkout event)
    customer.subscription.updated   — Plan changed, status changed, renewal
    customer.subscription.deleted   — Subscription ended → downgrade to P1
    invoice.paid                    — Payment succeeded; upsert invoice, confirm active
    invoice.payment_failed          — Payment failed → mark subscription past_due
    invoice.finalized               — Invoice finalized → upsert invoice record

Idempotency:
    Each event is claimed in stripe_webhook_events (unique on event_id) before
    processing. Duplicate deliveries silently return 200. If the DB insert fails
    we return 5xx so Stripe retries. If handler logic fails after claiming, we
    delete the claim so the next retry starts clean.

Design notes:
    - Raw body bytes must be read before any JSON parsing for sig verification.
    - All recognised event types return 200 even if we take no action.
    - Unknown event types return 200 immediately (no retry needed).
    - Unhandled exceptions propagate as 5xx → Stripe retries with backoff.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import JSONResponse

from config.settings import settings
from shared.billing import stripe_client, stripe_repository
from shared.billing.stripe_client import get_plan_for_price_id
from shared.auth.auth import PlanTier
from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.service.admin.stripe_webhook")

router = APIRouter(tags=["Admin — Stripe Webhook"])

# Plan tier used when a subscription is deleted / payment lapses beyond recovery.
_FALLBACK_TIER = PlanTier.P1_HOBBYIST


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ts_to_dt(value: Any) -> Optional[datetime]:
    """Convert a Stripe Unix timestamp or None to a timezone-aware datetime."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _invoice_record(inv: dict[str, Any], tenant_id: str) -> dict[str, Any]:
    """Map a Stripe invoice object to the shape expected by upsert_invoice()."""
    return {
        "stripe_invoice_id": inv.get("id"),
        "tenant_id": tenant_id,
        "stripe_customer_id": inv.get("customer"),
        "stripe_subscription_id": inv.get("subscription"),
        "status": inv.get("status"),
        "currency": inv.get("currency"),
        "amount_due": inv.get("amount_due"),
        "amount_paid": inv.get("amount_paid"),
        "amount_remaining": inv.get("amount_remaining"),
        "hosted_invoice_url": inv.get("hosted_invoice_url"),
        "invoice_pdf": inv.get("invoice_pdf"),
        "period_start": _ts_to_dt(inv.get("period_start")),
        "period_end": _ts_to_dt(inv.get("period_end")),
        "created_at": _ts_to_dt(inv.get("created")),
    }


async def _resolve_tenant_by_customer(customer_id: str) -> Optional[str]:
    """Look up tenant_id from a Stripe customer ID."""
    if not customer_id:
        return None
    account = await stripe_repository.get_by_stripe_customer_id(customer_id)
    return account.get("tenant_id") if account else None


async def _resolve_tenant_by_subscription(subscription_id: str) -> Optional[str]:
    """Look up tenant_id from a Stripe subscription ID."""
    if not subscription_id:
        return None
    account = await stripe_repository.get_by_stripe_subscription_id(subscription_id)
    return account.get("tenant_id") if account else None


async def _resolve_tenant(
    obj: dict[str, Any],
    *,
    prefer_metadata: bool = True,
) -> Optional[str]:
    """Resolve a tenant_id from a Stripe object (subscription or invoice).

    Resolution order:
      1. obj.metadata.tenant_id   — set by Aether at checkout time
      2. obj.customer lookup      — fallback via tenant_billing_accounts
      3. obj.subscription lookup  — last resort for invoice objects
    """
    if prefer_metadata:
        meta = obj.get("metadata") or {}
        if meta.get("tenant_id"):
            return meta["tenant_id"]

    customer_id = obj.get("customer") or ""
    if customer_id:
        tenant_id = await _resolve_tenant_by_customer(customer_id)
        if tenant_id:
            return tenant_id

    subscription_id = obj.get("subscription") or ""
    if subscription_id:
        return await _resolve_tenant_by_subscription(subscription_id)

    return None


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

async def _handle_checkout_session_completed(event_data: dict[str, Any]) -> None:
    """
    checkout.session.completed fires once per successful Checkout flow.

    The session carries:
      - client_reference_id  → tenant_id (set by create_checkout_session)
      - customer             → Stripe customer ID (new or existing)
      - subscription         → Stripe subscription ID
      - metadata.tenant_id   → same tenant_id, belt-and-suspenders
      - metadata.requested_plan_tier → PlanTier value
    """
    session = event_data.get("object", {})
    tenant_id: Optional[str] = (
        session.get("client_reference_id")
        or (session.get("metadata") or {}).get("tenant_id")
    )
    if not tenant_id:
        logger.warning("checkout.session.completed: no tenant_id in session; skipping")
        return

    customer_id: str = session.get("customer") or ""
    subscription_id: str = session.get("subscription") or ""
    contact_email: str = (
        session.get("customer_details", {}).get("email", "")
        or (session.get("metadata") or {}).get("contact_email", "")
    )

    # Persist the customer ↔ tenant mapping so future events can resolve.
    await stripe_repository.update_customer_mapping(
        tenant_id=tenant_id,
        stripe_customer_id=customer_id or None,
        stripe_subscription_id=subscription_id or None,
        contact_email=contact_email or None,
    )

    # The subscription object is not embedded in the session — plan tier comes
    # from the session metadata that was set at checkout creation time.
    requested_tier_value: str = (
        (session.get("metadata") or {}).get("requested_plan_tier", "")
    )
    plan_tier: Optional[PlanTier] = None
    if requested_tier_value:
        try:
            plan_tier = PlanTier(requested_tier_value)
        except ValueError:
            logger.warning(
                f"checkout.session.completed: unknown plan_tier "
                f"'{requested_tier_value}' for tenant={tenant_id}"
            )

    # Do NOT update plan_tier here. The subscription.created / subscription.updated
    # event always arrives after checkout completion and carries the authoritative
    # price_id → plan_tier mapping. Updating plan_tier from checkout metadata
    # would race with that event and could leave the tier in an inconsistent
    # state if the subscription is later modified before the events settle.
    metrics.increment(
        "stripe_webhook_checkout_completed",
        labels={"plan_tier": plan_tier.value if plan_tier else "unknown"},
    )

    logger.info(
        f"checkout.session.completed: tenant={tenant_id} "
        f"customer={customer_id} subscription={subscription_id} "
        f"plan_tier={plan_tier.value if plan_tier else 'pending'}"
    )


async def _handle_subscription_created(event_data: dict[str, Any]) -> None:
    """
    customer.subscription.created fires when a subscription is first created.

    We extract price_id → plan_tier and persist the subscription state.
    Tenant resolution prefers metadata (set at checkout), then customer lookup.
    """
    sub = event_data.get("object", {})
    await _apply_subscription_state(sub, event_name="customer.subscription.created")


async def _handle_subscription_updated(event_data: dict[str, Any]) -> None:
    """
    customer.subscription.updated fires on:
      - Plan upgrades / downgrades (new price_id)
      - Renewal (current_period_end advances)
      - cancel_at_period_end toggled
      - Status transitions (active → past_due, past_due → active, etc.)
    """
    sub = event_data.get("object", {})
    await _apply_subscription_state(sub, event_name="customer.subscription.updated")


async def _apply_subscription_state(sub: dict[str, Any], *, event_name: str) -> None:
    """Shared logic for subscription.created and subscription.updated."""
    tenant_id = await _resolve_tenant(sub)
    if not tenant_id:
        customer_id = sub.get("customer", "")
        logger.warning(
            f"{event_name}: cannot resolve tenant "
            f"(customer={customer_id}); skipping plan update"
        )
        return

    subscription_id: str = sub.get("id") or ""
    customer_id: str = sub.get("customer") or ""
    status: str = sub.get("status") or ""
    current_period_end = _ts_to_dt(sub.get("current_period_end"))

    # Extract price_id from the first subscription item.
    price_id: str = ""
    items_data: list = (sub.get("items") or {}).get("data") or []
    if items_data:
        price_id = (items_data[0].get("price") or {}).get("id") or ""

    plan_tier: Optional[PlanTier] = get_plan_for_price_id(price_id) if price_id else None

    # Ensure customer mapping is current.
    if customer_id and subscription_id:
        await stripe_repository.update_customer_mapping(
            tenant_id=tenant_id,
            stripe_customer_id=customer_id,
            stripe_subscription_id=subscription_id,
        )

    await stripe_repository.update_subscription_state(
        tenant_id=tenant_id,
        stripe_subscription_id=subscription_id or None,
        stripe_price_id=price_id or None,
        subscription_status=status or None,
        current_period_end=current_period_end,
    )

    if plan_tier:
        await stripe_repository.update_plan_tier(tenant_id, plan_tier.value)
        metrics.increment(
            f"stripe_webhook_{event_name.replace('.', '_').replace('customer_', '')}",
            labels={"plan_tier": plan_tier.value, "status": status},
        )
    else:
        metrics.increment(
            f"stripe_webhook_{event_name.replace('.', '_').replace('customer_', '')}",
            labels={"plan_tier": "unknown", "status": status},
        )

    logger.info(
        f"{event_name}: tenant={tenant_id} subscription={subscription_id} "
        f"status={status} plan_tier={plan_tier.value if plan_tier else 'unknown'} "
        f"period_end={current_period_end}"
    )


async def _handle_subscription_deleted(event_data: dict[str, Any]) -> None:
    """
    customer.subscription.deleted fires when a subscription is fully canceled
    and the grace period has elapsed (or cancel_at_period_end was false).

    We downgrade the tenant to P1 and mark the subscription as canceled.
    """
    sub = event_data.get("object", {})
    tenant_id = await _resolve_tenant(sub)
    if not tenant_id:
        logger.warning(
            f"customer.subscription.deleted: cannot resolve tenant "
            f"(customer={sub.get('customer', '')}); skipping downgrade"
        )
        return

    subscription_id: str = sub.get("id") or ""

    await stripe_repository.update_subscription_state(
        tenant_id=tenant_id,
        stripe_subscription_id=subscription_id or None,
        subscription_status="canceled",
        current_period_end=_ts_to_dt(sub.get("ended_at")),
    )
    await stripe_repository.update_plan_tier(tenant_id, _FALLBACK_TIER.value)

    metrics.increment("stripe_webhook_subscription_deleted")
    logger.info(
        f"customer.subscription.deleted: tenant={tenant_id} "
        f"subscription={subscription_id} → downgraded to {_FALLBACK_TIER.value}"
    )


async def _handle_invoice_paid(event_data: dict[str, Any]) -> None:
    """
    invoice.paid fires when a subscription invoice is successfully collected.

    For subscription invoices (billing_reason = subscription_cycle or
    subscription_create), we confirm the subscription is active and upsert
    the invoice record.
    """
    inv = event_data.get("object", {})
    customer_id: str = inv.get("customer") or ""
    subscription_id: str = inv.get("subscription") or ""

    tenant_id = await _resolve_tenant(inv)
    if not tenant_id:
        logger.warning(
            f"invoice.paid: cannot resolve tenant (customer={customer_id}); "
            "invoice not recorded"
        )
        return

    # Confirm subscription active when payment lands (guards against race with
    # subscription.updated arriving out of order on first-time payments).
    billing_reason: str = inv.get("billing_reason") or ""
    if subscription_id and billing_reason in (
        "subscription_create", "subscription_cycle", "subscription_update"
    ):
        await stripe_repository.update_subscription_state(
            tenant_id=tenant_id,
            stripe_subscription_id=subscription_id or None,
            subscription_status="active",
        )

    await stripe_repository.upsert_invoice(_invoice_record(inv, tenant_id))

    metrics.increment("stripe_webhook_invoice_paid")
    logger.info(
        f"invoice.paid: tenant={tenant_id} invoice={inv.get('id')} "
        f"amount_paid={inv.get('amount_paid')} currency={inv.get('currency')}"
    )


async def _handle_invoice_payment_failed(event_data: dict[str, Any]) -> None:
    """
    invoice.payment_failed fires when Stripe cannot collect payment for an invoice.

    Stripe will retry according to the Smart Retries schedule. We mark the
    subscription as past_due immediately so rate-limit middleware can
    optionally surface a warning. The plan tier is NOT downgraded here —
    downgrade only happens on subscription.deleted after retries are exhausted.
    """
    inv = event_data.get("object", {})
    customer_id: str = inv.get("customer") or ""
    subscription_id: str = inv.get("subscription") or ""

    tenant_id = await _resolve_tenant(inv)
    if not tenant_id:
        logger.warning(
            f"invoice.payment_failed: cannot resolve tenant (customer={customer_id}); "
            "status not updated"
        )
        return

    if subscription_id:
        await stripe_repository.update_subscription_state(
            tenant_id=tenant_id,
            stripe_subscription_id=subscription_id or None,
            subscription_status="past_due",
        )

    await stripe_repository.upsert_invoice(_invoice_record(inv, tenant_id))

    metrics.increment("stripe_webhook_invoice_payment_failed")
    logger.warning(
        f"invoice.payment_failed: tenant={tenant_id} invoice={inv.get('id')} "
        f"amount_due={inv.get('amount_due')} attempt={inv.get('attempt_count')}"
    )


async def _handle_invoice_finalized(event_data: dict[str, Any]) -> None:
    """
    invoice.finalized fires when a draft invoice is finalized (locked for
    collection). We upsert the invoice record so billing history is current.
    """
    inv = event_data.get("object", {})
    tenant_id = await _resolve_tenant(inv)
    if not tenant_id:
        logger.debug(
            f"invoice.finalized: cannot resolve tenant "
            f"(customer={inv.get('customer', '')}); skipping"
        )
        return

    await stripe_repository.upsert_invoice(_invoice_record(inv, tenant_id))

    metrics.increment("stripe_webhook_invoice_finalized")
    logger.info(
        f"invoice.finalized: tenant={tenant_id} invoice={inv.get('id')} "
        f"status={inv.get('status')}"
    )


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_HANDLERS = {
    "checkout.session.completed": _handle_checkout_session_completed,
    "customer.subscription.created": _handle_subscription_created,
    "customer.subscription.updated": _handle_subscription_updated,
    "customer.subscription.deleted": _handle_subscription_deleted,
    "invoice.paid": _handle_invoice_paid,
    "invoice.payment_failed": _handle_invoice_payment_failed,
    "invoice.finalized": _handle_invoice_finalized,
}


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.post(
    "/v1/admin/billing/stripe/webhook",
    include_in_schema=False,  # not a tenant-facing endpoint
)
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(default="", alias="stripe-signature"),
) -> Response:
    """
    Stripe webhook receiver.

    Must read raw bytes (not parsed JSON) before signature verification.
    Returns 200 for all valid, verified events — including ones we ignore —
    so Stripe does not retry. Returns 4xx/5xx only when the payload cannot
    be verified or a transient error warrants a retry.
    """
    # ── 1. Read raw body ────────────────────────────────────────────────
    payload: bytes = await request.body()

    # ── 2. Short-circuit if Stripe Billing is disabled ──────────────────
    if not settings.stripe_billing.enabled:
        # Accept but ignore — avoids log noise during local dev where Stripe
        # is not configured but webhook delivery may be forwarded via CLI.
        return JSONResponse(status_code=200, content={"received": True})

    # ── 3. Verify signature ─────────────────────────────────────────────
    try:
        event = stripe_client.construct_webhook_event(payload, stripe_signature)
    except Exception as exc:
        # construct_webhook_event raises BadRequestError for invalid sig.
        logger.warning(f"Stripe webhook signature verification failed: {exc}")
        metrics.increment("stripe_webhook_sig_failures")
        return JSONResponse(
            status_code=400,
            content={"error": "Invalid Stripe-Signature", "detail": str(exc)},
        )

    event_id: str = event.get("id", "")
    event_type: str = event.get("type", "")
    event_data: dict[str, Any] = event.get("data", {})

    # ── 4. Idempotency claim ────────────────────────────────────────────
    # record_webhook_event_once raises on DB errors (5xx → Stripe retries).
    is_new = await stripe_repository.record_webhook_event_once(event_id, event_type)
    if not is_new:
        logger.debug(f"Stripe webhook duplicate: event_id={event_id} type={event_type}")
        metrics.increment("stripe_webhook_duplicates", labels={"type": event_type})
        return JSONResponse(status_code=200, content={"received": True, "duplicate": True})

    # ── 5. Dispatch ─────────────────────────────────────────────────────
    handler = _HANDLERS.get(event_type)
    if handler is None:
        # Unrecognised event — acknowledge so Stripe stops delivering it.
        metrics.increment("stripe_webhook_unhandled", labels={"type": event_type})
        logger.debug(f"Stripe webhook unhandled type: {event_type}")
        return JSONResponse(status_code=200, content={"received": True, "handled": False})

    try:
        await handler(event_data)
    except Exception as exc:
        # Release the idempotency claim so the next Stripe retry gets a clean
        # attempt rather than silently skipping a failed first delivery.
        await stripe_repository.delete_webhook_event(event_id)
        logger.error(
            f"Stripe webhook handler failed: event_id={event_id} "
            f"type={event_type} error={exc}",
            exc_info=True,
        )
        metrics.increment("stripe_webhook_handler_errors", labels={"type": event_type})
        return JSONResponse(
            status_code=500,
            content={"error": "Webhook processing failed; will retry"},
        )

    metrics.increment("stripe_webhook_processed", labels={"type": event_type})
    return JSONResponse(status_code=200, content={"received": True, "handled": True})
