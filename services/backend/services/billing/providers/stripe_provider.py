"""Stripe billing provider — import-safe, feature-flagged stub.

This is a *readiness* implementation: it never imports the ``stripe`` SDK at
module load, never performs network calls in local/test, and activates only
behind ``AETHER_STRIPE_BILLING_ENABLED`` with configured secrets. Webhook
signature verification uses the standard Stripe HMAC scheme (no SDK required)
and never logs secrets. External mutating operations raise
``ProviderDisabledError`` until real wiring is enabled in deployment.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime
from typing import Any, Optional

from config.settings import settings
from shared.logger.logger import get_logger

from services.billing.providers.base import (
    BillingProvider,
    InvoiceExportMode,
    PaymentStatus,
    ProviderDisabledError,
    WebhookResult,
)
from services.billing.providers.mappings import load_mappings

logger = get_logger("aether.billing.providers.stripe")

# In-memory idempotency guard for processed webhook event ids (per process).
_SEEN_WEBHOOK_EVENTS: set[str] = set()

# Map Stripe event types → resulting tenant payment status.
_EVENT_PAYMENT_STATUS: dict[str, PaymentStatus] = {
    "invoice.paid": "paid",
    "invoice.payment_succeeded": "paid",
    "invoice.payment_failed": "failed",
    "customer.subscription.deleted": "cancelled",
    "customer.subscription.paused": "pending",
}


class StripeBillingProvider(BillingProvider):
    provider_type = "stripe"

    def __init__(self) -> None:
        self._cfg = settings.external_billing

    def is_configured(self) -> bool:
        return bool(self._cfg.stripe_billing_enabled and self._cfg.stripe_secret_key)

    def invoice_export_mode(self) -> InvoiceExportMode:
        return "provider_export" if self.is_configured() else "approved_preview"

    def _require_configured(self) -> None:
        if not self.is_configured():
            raise ProviderDisabledError(
                "Stripe billing is not enabled/configured "
                "(set AETHER_STRIPE_BILLING_ENABLED=true and STRIPE_SECRET_KEY)."
            )

    def _stripe(self):
        import stripe as _stripe
        _stripe.api_key = self._cfg.stripe_secret_key
        return _stripe

    async def create_customer(self, *, tenant_id: str, email: Optional[str] = None, metadata: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self._require_configured()
        stripe = self._stripe()
        customer = stripe.Customer.create(
            email=email,
            metadata={"tenant_id": tenant_id, **(metadata or {})},
        )
        logger.info("stripe customer created", extra={"tenant_id": tenant_id, "customer_id": customer.id})
        return {"provider": "stripe", "customer_id": customer.id, "tenant_id": tenant_id}

    async def sync_customer(self, *, tenant_id: str) -> dict[str, Any]:
        if not self.is_configured():
            return {"provider": "stripe", "tenant_id": tenant_id, "synced": False, "reason": "not_configured"}
        stripe = self._stripe()
        results = stripe.Customer.search(query=f'metadata["tenant_id"]:"{tenant_id}"', limit=1)
        if not results.data:
            return {"provider": "stripe", "tenant_id": tenant_id, "synced": False, "reason": "not_found"}
        customer = results.data[0]
        return {"provider": "stripe", "customer_id": customer.id, "tenant_id": tenant_id, "synced": True}

    async def create_subscription(self, *, tenant_id: str, plan_tier: str, metadata: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self._require_configured()
        stripe = self._stripe()
        sync = await self.sync_customer(tenant_id=tenant_id)
        customer_id = sync.get("customer_id")
        if not customer_id:
            created = await self.create_customer(tenant_id=tenant_id)
            customer_id = created["customer_id"]
        price_id = self.map_price(plan_tier=plan_tier)
        if not price_id:
            raise ProviderDisabledError(f"No Stripe price mapping for plan_tier={plan_tier!r}")
        sub = stripe.Subscription.create(
            customer=customer_id,
            items=[{"price": price_id}],
            metadata={"tenant_id": tenant_id, **(metadata or {})},
        )
        return {"provider": "stripe", "subscription_id": sub.id, "tenant_id": tenant_id, "status": sub.status}

    async def update_subscription(self, *, tenant_id: str, plan_tier: str) -> dict[str, Any]:
        self._require_configured()
        stripe = self._stripe()
        sync = await self.sync_customer(tenant_id=tenant_id)
        customer_id = sync.get("customer_id")
        if not customer_id:
            raise ProviderDisabledError(f"No Stripe customer found for tenant {tenant_id!r}")
        subs = stripe.Subscription.list(customer=customer_id, status="active", limit=1)
        if not subs.data:
            raise ProviderDisabledError(f"No active Stripe subscription for tenant {tenant_id!r}")
        sub = subs.data[0]
        price_id = self.map_price(plan_tier=plan_tier)
        if not price_id:
            raise ProviderDisabledError(f"No Stripe price mapping for plan_tier={plan_tier!r}")
        updated = stripe.Subscription.modify(sub.id, items=[{"id": sub["items"].data[0].id, "price": price_id}])
        return {"provider": "stripe", "subscription_id": updated.id, "tenant_id": tenant_id, "status": updated.status}

    async def cancel_subscription(self, *, tenant_id: str) -> dict[str, Any]:
        self._require_configured()
        stripe = self._stripe()
        sync = await self.sync_customer(tenant_id=tenant_id)
        customer_id = sync.get("customer_id")
        if not customer_id:
            raise ProviderDisabledError(f"No Stripe customer found for tenant {tenant_id!r}")
        subs = stripe.Subscription.list(customer=customer_id, status="active", limit=1)
        if not subs.data:
            return {"provider": "stripe", "tenant_id": tenant_id, "cancelled": False, "reason": "no_active_subscription"}
        cancelled = stripe.Subscription.cancel(subs.data[0].id)
        return {"provider": "stripe", "subscription_id": cancelled.id, "tenant_id": tenant_id, "cancelled": True, "status": cancelled.status}

    async def create_invoice_preview(self, *, tenant_id: str, usage_summary: dict[str, Any]) -> dict[str, Any]:
        return {"provider": "stripe", "tenant_id": tenant_id, "mode": self.invoice_export_mode(), "usage_summary": usage_summary}

    async def export_invoice(self, *, tenant_id: str, invoice_preview: dict[str, Any]) -> dict[str, Any]:
        self._require_configured()
        stripe = self._stripe()
        invoice_id = invoice_preview.get("stripe_invoice_id") or invoice_preview.get("invoice_id")
        if invoice_id:
            invoice = stripe.Invoice.retrieve(str(invoice_id))
        else:
            sync = await self.sync_customer(tenant_id=tenant_id)
            customer_id = sync.get("customer_id")
            if not customer_id:
                raise ProviderDisabledError(f"No Stripe customer found for tenant {tenant_id!r}")
            invoices = stripe.Invoice.list(customer=customer_id, limit=1)
            invoice = invoices.data[0] if invoices.data else None
        if not invoice:
            return {"provider": "stripe", "tenant_id": tenant_id, "exported": False, "reason": "no_invoice"}
        return {
            "provider": "stripe",
            "invoice_id": invoice.id,
            "tenant_id": tenant_id,
            "exported": True,
            "amount_due": invoice.amount_due,
            "status": invoice.status,
            "hosted_invoice_url": invoice.hosted_invoice_url,
        }

    async def sync_payment_status(self, *, tenant_id: str) -> PaymentStatus:
        if not self.is_configured():
            return "unknown"
        sync = await self.sync_customer(tenant_id=tenant_id)
        customer_id = sync.get("customer_id")
        if not customer_id:
            return "unknown"
        stripe = self._stripe()
        subs = stripe.Subscription.list(customer=customer_id, status="active", limit=1)
        if not subs.data:
            return "unknown"
        sub_status = subs.data[0].status
        _STATUS_MAP: dict[str, PaymentStatus] = {
            "active": "paid",
            "past_due": "failed",
            "canceled": "cancelled",
            "unpaid": "unpaid",
            "trialing": "paid",
            "paused": "pending",
            "incomplete": "pending",
        }
        return _STATUS_MAP.get(sub_status, "unknown")

    async def _find_subscription_item(self, *, tenant_id: str, usage_dimension: str) -> str:
        stripe = self._stripe()
        sync = await self.sync_customer(tenant_id=tenant_id)
        customer_id = sync.get("customer_id")
        if not customer_id:
            raise ProviderDisabledError(f"No Stripe customer for tenant {tenant_id!r}")
        subs = stripe.Subscription.list(customer=customer_id, status="active", limit=1)
        if not subs.data:
            raise ProviderDisabledError(f"No active Stripe subscription for tenant {tenant_id!r}")
        price_id = self.map_price(plan_tier="", usage_dimension=usage_dimension)
        for item in subs.data[0]["items"].data:
            if price_id and item.price.id == price_id:
                return str(item.id)
        return str(subs.data[0]["items"].data[0].id)

    async def record_usage(self, *, tenant_id: str, usage_dimension: str, quantity: float) -> dict[str, Any]:
        return await self.create_usage_record(tenant_id=tenant_id, usage_dimension=usage_dimension, quantity=quantity)

    async def create_usage_record(self, *, tenant_id: str, usage_dimension: str, quantity: float, timestamp: Optional[str] = None) -> dict[str, Any]:
        self._require_configured()
        stripe = self._stripe()
        si_id = await self._find_subscription_item(tenant_id=tenant_id, usage_dimension=usage_dimension)
        ts = int(datetime.fromisoformat(timestamp).timestamp()) if timestamp else int(time.time())
        record = stripe.SubscriptionItem.create_usage_record(
            si_id,
            quantity=int(quantity),
            timestamp=ts,
            action="increment",
        )
        return {
            "provider": "stripe",
            "usage_record_id": record.id,
            "tenant_id": tenant_id,
            "quantity": quantity,
            "dimension": usage_dimension,
        }

    def map_product(self, *, package_id: str) -> Optional[str]:
        for m in load_mappings():
            if m.package_id == package_id and m.provider_product_id:
                return m.provider_product_id
        return None

    def map_price(self, *, plan_tier: str, usage_dimension: Optional[str] = None) -> Optional[str]:
        for m in load_mappings():
            if m.plan_tier == plan_tier and m.usage_dimension == usage_dimension and m.provider_price_id:
                return m.provider_price_id
        return None

    def _verify_signature(self, payload: bytes, signature: Optional[str], timestamp: Optional[str]) -> bool:
        secret = self._cfg.stripe_webhook_secret
        if not secret or not signature or not timestamp:
            return False
        signed_payload = f"{timestamp}.".encode("utf-8") + payload
        expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        # constant-time compare; never log the secret or the expected signature.
        return hmac.compare_digest(expected, signature)

    async def handle_webhook(self, *, payload: bytes, signature: Optional[str], timestamp: Optional[str] = None) -> WebhookResult:
        if not self.is_configured():
            return WebhookResult(handled=False, reason="stripe provider not configured")
        timestamp = timestamp or str(int(time.time()))
        if not self._verify_signature(payload, signature, timestamp):
            logger.warning("stripe webhook signature verification failed")
            return WebhookResult(handled=False, reason="invalid signature")
        try:
            event = json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return WebhookResult(handled=False, reason="invalid payload")
        event_id = str(event.get("id") or "")
        event_type = str(event.get("type") or "")
        if event_id and event_id in _SEEN_WEBHOOK_EVENTS:
            return WebhookResult(handled=True, event_type=event_type, idempotent_skip=True)
        if event_id:
            _SEEN_WEBHOOK_EVENTS.add(event_id)
        return WebhookResult(
            handled=True,
            event_type=event_type,
            payment_status=_EVENT_PAYMENT_STATUS.get(event_type),
        )
