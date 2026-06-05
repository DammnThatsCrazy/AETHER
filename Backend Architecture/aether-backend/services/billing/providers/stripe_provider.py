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

    async def create_customer(self, *, tenant_id: str, email: Optional[str] = None, metadata: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self._require_configured()
        # Real wiring (lazy import) would call stripe.Customer.create here.
        raise ProviderDisabledError("Stripe create_customer not wired in this build")

    async def sync_customer(self, *, tenant_id: str) -> dict[str, Any]:
        if not self.is_configured():
            return {"provider": "stripe", "tenant_id": tenant_id, "synced": False, "reason": "not_configured"}
        raise ProviderDisabledError("Stripe sync_customer not wired in this build")

    async def create_subscription(self, *, tenant_id: str, plan_tier: str, metadata: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        self._require_configured()
        raise ProviderDisabledError("Stripe create_subscription not wired in this build")

    async def update_subscription(self, *, tenant_id: str, plan_tier: str) -> dict[str, Any]:
        self._require_configured()
        raise ProviderDisabledError("Stripe update_subscription not wired in this build")

    async def cancel_subscription(self, *, tenant_id: str) -> dict[str, Any]:
        self._require_configured()
        raise ProviderDisabledError("Stripe cancel_subscription not wired in this build")

    async def create_invoice_preview(self, *, tenant_id: str, usage_summary: dict[str, Any]) -> dict[str, Any]:
        return {"provider": "stripe", "tenant_id": tenant_id, "mode": self.invoice_export_mode(), "usage_summary": usage_summary}

    async def export_invoice(self, *, tenant_id: str, invoice_preview: dict[str, Any]) -> dict[str, Any]:
        self._require_configured()
        raise ProviderDisabledError("Stripe export_invoice not wired in this build")

    async def sync_payment_status(self, *, tenant_id: str) -> PaymentStatus:
        # Without a live API call we cannot assert a real status.
        return "unknown"

    async def record_usage(self, *, tenant_id: str, usage_dimension: str, quantity: float) -> dict[str, Any]:
        self._require_configured()
        raise ProviderDisabledError("Stripe record_usage not wired in this build")

    async def create_usage_record(self, *, tenant_id: str, usage_dimension: str, quantity: float, timestamp: Optional[str] = None) -> dict[str, Any]:
        self._require_configured()
        raise ProviderDisabledError("Stripe create_usage_record not wired in this build")

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
