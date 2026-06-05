"""Internal-only billing provider (default).

No external payment processor. Subscriptions/invoices are managed by the
internal revops layer; payment is reported as ``externally_managed`` (i.e.
handled outside an integrated payment processor — manual/enterprise/internal).
Used for ``internal_only``, ``manual_invoice`` and ``enterprise_contract`` modes.
"""
from __future__ import annotations

from typing import Any, Optional

from services.billing.providers.base import (
    BillingProvider,
    InvoiceExportMode,
    PaymentStatus,
    ProviderType,
    WebhookResult,
)
from services.billing.providers.mappings import load_mappings


class InternalOnlyProvider(BillingProvider):
    def __init__(self, provider_type: ProviderType = "internal_only") -> None:
        self.provider_type = provider_type

    def is_configured(self) -> bool:
        # No external processor needed — internal billing is always "configured".
        return True

    def invoice_export_mode(self) -> InvoiceExportMode:
        return "manual_artifact" if self.provider_type == "manual_invoice" else "internal_preview"

    async def create_customer(self, *, tenant_id: str, email: Optional[str] = None, metadata: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return {"provider": self.provider_type, "tenant_id": tenant_id, "external_customer_id": None, "managed": "internal"}

    async def sync_customer(self, *, tenant_id: str) -> dict[str, Any]:
        return {"provider": self.provider_type, "tenant_id": tenant_id, "synced": False, "managed": "internal"}

    async def create_subscription(self, *, tenant_id: str, plan_tier: str, metadata: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return {"provider": self.provider_type, "tenant_id": tenant_id, "plan_tier": plan_tier, "external_subscription_id": None, "managed": "internal"}

    async def update_subscription(self, *, tenant_id: str, plan_tier: str) -> dict[str, Any]:
        return {"provider": self.provider_type, "tenant_id": tenant_id, "plan_tier": plan_tier, "managed": "internal"}

    async def cancel_subscription(self, *, tenant_id: str) -> dict[str, Any]:
        return {"provider": self.provider_type, "tenant_id": tenant_id, "cancelled": True, "managed": "internal"}

    async def create_invoice_preview(self, *, tenant_id: str, usage_summary: dict[str, Any]) -> dict[str, Any]:
        # Reuse the internal usage summary verbatim; no external preview.
        return {"provider": self.provider_type, "tenant_id": tenant_id, "mode": self.invoice_export_mode(), "usage_summary": usage_summary}

    async def export_invoice(self, *, tenant_id: str, invoice_preview: dict[str, Any]) -> dict[str, Any]:
        return {"provider": self.provider_type, "tenant_id": tenant_id, "mode": self.invoice_export_mode(), "exported": True, "artifact": "internal"}

    async def sync_payment_status(self, *, tenant_id: str) -> PaymentStatus:
        return "externally_managed"

    async def record_usage(self, *, tenant_id: str, usage_dimension: str, quantity: float) -> dict[str, Any]:
        return {"provider": self.provider_type, "tenant_id": tenant_id, "usage_dimension": usage_dimension, "quantity": quantity, "recorded": "internal"}

    async def create_usage_record(self, *, tenant_id: str, usage_dimension: str, quantity: float, timestamp: Optional[str] = None) -> dict[str, Any]:
        return {"provider": self.provider_type, "tenant_id": tenant_id, "usage_dimension": usage_dimension, "quantity": quantity, "recorded": "internal"}

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

    async def handle_webhook(self, *, payload: bytes, signature: Optional[str], timestamp: Optional[str] = None) -> WebhookResult:
        # No external provider → no webhooks to process.
        return WebhookResult(handled=False, reason="internal_only provider does not process webhooks")
