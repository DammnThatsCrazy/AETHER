"""Aether Billing — Stripe client.

Thin wrapper around the Stripe Python SDK. Plan identity is sourced from
shared.plans.catalog.PLAN_CATALOG; pricing amounts live in the catalog (and
in Stripe's Dashboard). This module only maps PlanTier <-> Stripe Price ID.

Local fallback behaviour:
  When AETHER_ENV=local and Stripe configuration is incomplete (missing
  secret_key or required Price IDs), Checkout/Portal calls return mocked
  objects instead of raising. This is never used outside local mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from config.settings import Environment, settings
from shared.auth.auth import PlanTier
from shared.common.common import BadRequestError, ServiceUnavailableError
from shared.logger.logger import get_logger
from shared.plans.catalog import PLAN_CATALOG

logger = get_logger("aether.billing.stripe")

try:
    import stripe  # type: ignore
    STRIPE_SDK_AVAILABLE = True
except ImportError:
    stripe = None  # type: ignore[assignment]
    STRIPE_SDK_AVAILABLE = False


# ---------------------------------------------------------------------------
# Mocked URL helpers (LOCAL ONLY)
# ---------------------------------------------------------------------------

_MOCK_CHECKOUT_BASE = "http://localhost:3000/mock-stripe/checkout"
_MOCK_PORTAL_BASE = "http://localhost:3000/mock-stripe/portal"


def _is_local() -> bool:
    return settings.env == Environment.LOCAL


def _stripe_config_complete() -> bool:
    cfg = settings.stripe_billing
    return bool(
        cfg.enabled
        and cfg.secret_key
        and cfg.price_p1
        and cfg.price_p2
        and cfg.price_p3
        and cfg.price_p4
        and STRIPE_SDK_AVAILABLE
    )


def _use_mocked_mode() -> bool:
    """Use mocked URLs only when in local AND Stripe config is incomplete."""
    return _is_local() and not _stripe_config_complete()


def _ensure_real_stripe() -> None:
    """Raise if Stripe SDK or config not available (non-local enforcement)."""
    if not STRIPE_SDK_AVAILABLE:
        raise ServiceUnavailableError(
            "Stripe SDK not installed. Install with: pip install 'stripe>=10.0.0'"
        )
    cfg = settings.stripe_billing
    if not cfg.enabled:
        raise ServiceUnavailableError("Stripe Billing is not enabled")
    if not cfg.secret_key:
        raise ServiceUnavailableError("Stripe secret key is not configured")
    stripe.api_key = cfg.secret_key  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Plan <-> Price ID mapping
# ---------------------------------------------------------------------------

def get_stripe_price_id(plan_tier: PlanTier) -> str:
    """Return the configured Stripe Price ID for a PlanTier.

    Raises BadRequestError if the plan_tier has no configured Price ID.
    """
    cfg = settings.stripe_billing
    mapping = {
        PlanTier.P1_HOBBYIST: cfg.price_p1,
        PlanTier.P2_PROFESSIONAL: cfg.price_p2,
        PlanTier.P3_GROWTH_INTELLIGENCE: cfg.price_p3,
        PlanTier.P4_PROTOCOL_MASTER: cfg.price_p4,
    }
    price_id = mapping.get(plan_tier, "")
    if not price_id:
        if _is_local() and not _stripe_config_complete():
            # In local-mock mode, return a synthetic price ID stub. This is
            # never used in real Stripe API calls.
            return f"price_mock_{plan_tier.value}"
        raise BadRequestError(
            f"No Stripe Price ID configured for plan {plan_tier.value}. "
            f"Set STRIPE_PRICE_{plan_tier.value} in env."
        )
    return price_id


def get_plan_for_price_id(price_id: str) -> Optional[PlanTier]:
    """Reverse lookup: configured Stripe Price ID -> PlanTier.

    Returns None if the price_id does not match any configured plan.
    """
    if not price_id:
        return None
    cfg = settings.stripe_billing
    reverse = {
        cfg.price_p1: PlanTier.P1_HOBBYIST,
        cfg.price_p2: PlanTier.P2_PROFESSIONAL,
        cfg.price_p3: PlanTier.P3_GROWTH_INTELLIGENCE,
        cfg.price_p4: PlanTier.P4_PROTOCOL_MASTER,
    }
    # Strip empty keys to avoid matching a stub against unconfigured plans.
    reverse.pop("", None)
    return reverse.get(price_id)


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CheckoutSession:
    session_id: str
    url: str
    mocked: bool = False


@dataclass(frozen=True)
class PortalSession:
    url: str
    mocked: bool = False


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------

async def create_or_get_customer(
    tenant_id: str,
    contact_email: Optional[str] = None,
    existing_customer_id: Optional[str] = None,
) -> Optional[str]:
    """Return a Stripe customer ID for a tenant. Creates one if needed.

    In local-mock mode, returns a stub `cus_mock_{tenant_id}` so downstream
    flows can be exercised without real Stripe.
    """
    if _use_mocked_mode():
        return existing_customer_id or f"cus_mock_{tenant_id}"
    _ensure_real_stripe()

    if existing_customer_id:
        # Optionally update mapping/email — keep best-effort.
        try:
            stripe.Customer.modify(  # type: ignore[union-attr]
                existing_customer_id,
                email=contact_email or None,
                metadata={"tenant_id": tenant_id},
                idempotency_key=f"customer-update:{tenant_id}",
            )
        except Exception as e:  # pragma: no cover — best-effort sync
            logger.debug(f"Stripe customer update failed: {e}")
        return existing_customer_id

    try:
        customer = stripe.Customer.create(  # type: ignore[union-attr]
            email=contact_email or None,
            metadata={"tenant_id": tenant_id, "contact_email": contact_email or ""},
            idempotency_key=f"customer:{tenant_id}",
        )
        return customer["id"]
    except Exception as e:
        logger.warning(f"Stripe customer create failed: {e}")
        raise ServiceUnavailableError(f"Stripe customer create failed: {e}")


# ---------------------------------------------------------------------------
# Checkout / Portal
# ---------------------------------------------------------------------------

async def create_checkout_session(
    tenant_id: str,
    plan_tier: PlanTier,
    contact_email: Optional[str] = None,
    customer_id: Optional[str] = None,
) -> CheckoutSession:
    """Create a Stripe subscription Checkout Session for a plan_tier.

    Metadata always includes tenant_id, requested_plan_tier, and (when known)
    contact_email so the webhook can resolve the AETHER tenant on completion.
    """
    if plan_tier not in PLAN_CATALOG:
        raise BadRequestError(f"Unknown plan_tier: {plan_tier!r}")

    if _use_mocked_mode():
        session_id = f"cs_mock_{tenant_id}_{plan_tier.value}"
        url = (
            f"{_MOCK_CHECKOUT_BASE}"
            f"?tenant_id={tenant_id}&plan_tier={plan_tier.value}"
            f"&session_id={session_id}"
        )
        return CheckoutSession(session_id=session_id, url=url, mocked=True)

    _ensure_real_stripe()
    cfg = settings.stripe_billing
    price_id = get_stripe_price_id(plan_tier)
    metadata = {
        "tenant_id": tenant_id,
        "requested_plan_tier": plan_tier.value,
    }
    if contact_email:
        metadata["contact_email"] = contact_email

    kwargs: dict[str, Any] = {
        "mode": "subscription",
        "client_reference_id": tenant_id,
        "metadata": metadata,
        "subscription_data": {"metadata": metadata},
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": cfg.checkout_success_url,
        "cancel_url": cfg.checkout_cancel_url,
    }
    if customer_id:
        kwargs["customer"] = customer_id
    elif contact_email:
        kwargs["customer_email"] = contact_email

    try:
        session = stripe.checkout.Session.create(  # type: ignore[union-attr]
            idempotency_key=f"checkout:{tenant_id}:{plan_tier.value}",
            **kwargs,
        )
        return CheckoutSession(
            session_id=session["id"],
            url=session.get("url") or "",
            mocked=False,
        )
    except Exception as e:
        logger.warning(f"Stripe checkout create failed: {e}")
        raise ServiceUnavailableError(f"Stripe checkout create failed: {e}")


async def create_portal_session(
    tenant_id: str,
    customer_id: Optional[str] = None,
) -> PortalSession:
    """Create a Stripe Billing Portal session for a customer."""
    if _use_mocked_mode():
        return PortalSession(
            url=f"{_MOCK_PORTAL_BASE}?tenant_id={tenant_id}",
            mocked=True,
        )

    _ensure_real_stripe()
    if not customer_id:
        raise BadRequestError(
            "Stripe customer ID is required to open the Billing Portal. "
            "Run a Checkout flow first."
        )
    cfg = settings.stripe_billing
    try:
        portal = stripe.billing_portal.Session.create(  # type: ignore[union-attr]
            customer=customer_id,
            return_url=cfg.portal_return_url,
            idempotency_key=f"portal:{tenant_id}",
        )
        return PortalSession(url=portal["url"], mocked=False)
    except Exception as e:
        logger.warning(f"Stripe portal create failed: {e}")
        raise ServiceUnavailableError(f"Stripe portal create failed: {e}")


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------

def construct_webhook_event(payload: bytes, sig_header: str) -> Any:
    """Verify a Stripe webhook signature and return the parsed event.

    Raises BadRequestError on missing/invalid signature.
    """
    if not STRIPE_SDK_AVAILABLE:
        raise ServiceUnavailableError("Stripe SDK not installed")
    cfg = settings.stripe_billing
    if not cfg.webhook_secret:
        raise ServiceUnavailableError("Stripe webhook secret not configured")
    if not sig_header:
        raise BadRequestError("Missing Stripe-Signature header")
    try:
        return stripe.Webhook.construct_event(  # type: ignore[union-attr]
            payload, sig_header, cfg.webhook_secret,
        )
    except Exception as e:
        raise BadRequestError(f"Invalid Stripe-Signature: {e}")


# ---------------------------------------------------------------------------
# Overage invoicing (only when STRIPE_OVERAGE_PRICE_ID is configured)
# ---------------------------------------------------------------------------

async def create_overage_invoice_item(
    tenant_id: str,
    customer_id: str,
    billing_period: str,
    overage_requests: int,
    amount_cents: int,
    currency: str = "usd",
) -> dict[str, Any]:
    """Create a Stripe invoice item + finalize an invoice for an overage charge.

    Disabled unless STRIPE_OVERAGE_PRICE_ID is configured. Idempotent on
    (tenant_id, billing_period). Returns dict with invoice_item_id and (if
    successful) invoice_id.
    """
    cfg = settings.stripe_billing
    if not cfg.overage_invoicing_enabled:
        raise BadRequestError(
            "Stripe overage invoicing is not configured "
            "(set STRIPE_OVERAGE_PRICE_ID)."
        )
    _ensure_real_stripe()
    if not customer_id:
        raise BadRequestError("Stripe customer ID required for overage invoice")

    metadata = {
        "tenant_id": tenant_id,
        "billing_period": billing_period,
        "overage_requests": str(overage_requests),
    }
    try:
        item = stripe.InvoiceItem.create(  # type: ignore[union-attr]
            customer=customer_id,
            price=cfg.overage_price_id,
            quantity=max(1, overage_requests),
            currency=currency,
            metadata=metadata,
            idempotency_key=f"invoice-overage:{tenant_id}:{billing_period}",
        )
        invoice = stripe.Invoice.create(  # type: ignore[union-attr]
            customer=customer_id,
            auto_advance=True,
            metadata=metadata,
            idempotency_key=f"invoice-overage-finalize:{tenant_id}:{billing_period}",
        )
        return {
            "stripe_invoice_item_id": item["id"],
            "stripe_invoice_id": invoice["id"],
            "amount_cents": amount_cents,
        }
    except Exception as e:
        logger.warning(f"Stripe overage invoice failed: {e}")
        raise ServiceUnavailableError(f"Stripe overage invoice failed: {e}")


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

async def list_customer_invoices(
    customer_id: str, limit: int = 50, starting_after: Optional[str] = None,
) -> list[dict[str, Any]]:
    """List invoices for a Stripe customer (live data, not local cache)."""
    _ensure_real_stripe()
    kwargs: dict[str, Any] = {"customer": customer_id, "limit": min(100, limit)}
    if starting_after:
        kwargs["starting_after"] = starting_after
    try:
        result = stripe.Invoice.list(**kwargs)  # type: ignore[union-attr]
        return list(result["data"])
    except Exception as e:
        logger.warning(f"Stripe invoice list failed: {e}")
        return []


async def retrieve_invoice(stripe_invoice_id: str) -> Optional[dict[str, Any]]:
    """Retrieve a single Stripe invoice (live data)."""
    _ensure_real_stripe()
    try:
        return dict(stripe.Invoice.retrieve(stripe_invoice_id))  # type: ignore[union-attr]
    except Exception as e:
        logger.warning(f"Stripe invoice retrieve failed: {e}")
        return None
