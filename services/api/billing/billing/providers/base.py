"""Billing provider interface + shared contracts.

``BillingProvider`` is the provider-safe seam between the internal revops layer
and any external payment processor. Concrete providers must never raise on
import, must not require external env vars unless explicitly enabled, and must
never log/return secrets.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

ProviderType = Literal["internal_only", "stripe", "manual_invoice", "enterprise_contract"]

PaymentStatus = Literal[
    "unpaid", "pending", "paid", "failed", "cancelled", "externally_managed", "unknown"
]

InvoiceExportMode = Literal[
    "internal_preview", "approved_preview", "provider_export", "manual_artifact"
]


class ProviderDisabledError(Exception):
    """Raised when a provider-only operation is attempted while disabled."""


class ProductPriceMapping(BaseModel):
    package_id: str
    plan_tier: Optional[str] = None
    feature_key: Optional[str] = None
    usage_dimension: Optional[str] = None
    provider_product_id: Optional[str] = None
    provider_price_id: Optional[str] = None
    status: Literal["mapped", "unmapped", "pending"] = "unmapped"


class WebhookResult(BaseModel):
    handled: bool = False
    event_type: Optional[str] = None
    payment_status: Optional[PaymentStatus] = None
    idempotent_skip: bool = False
    reason: Optional[str] = None


class BillingProvider(ABC):
    """Abstract billing provider. Implementations are import-safe and offline by
    default; external calls happen only when the provider is enabled."""

    provider_type: ProviderType = "internal_only"

    def is_configured(self) -> bool:
        """Whether the provider has the config it needs to talk to a processor."""
        return False

    def invoice_export_mode(self) -> InvoiceExportMode:
        return "internal_preview"

    @abstractmethod
    async def create_customer(self, *, tenant_id: str, email: Optional[str] = None, metadata: Optional[dict[str, Any]] = None) -> dict[str, Any]: ...

    @abstractmethod
    async def sync_customer(self, *, tenant_id: str) -> dict[str, Any]: ...

    @abstractmethod
    async def create_subscription(self, *, tenant_id: str, plan_tier: str, metadata: Optional[dict[str, Any]] = None) -> dict[str, Any]: ...

    @abstractmethod
    async def update_subscription(self, *, tenant_id: str, plan_tier: str) -> dict[str, Any]: ...

    @abstractmethod
    async def cancel_subscription(self, *, tenant_id: str) -> dict[str, Any]: ...

    @abstractmethod
    async def create_invoice_preview(self, *, tenant_id: str, usage_summary: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    async def export_invoice(self, *, tenant_id: str, invoice_preview: dict[str, Any]) -> dict[str, Any]: ...

    @abstractmethod
    async def sync_payment_status(self, *, tenant_id: str) -> PaymentStatus: ...

    @abstractmethod
    async def record_usage(self, *, tenant_id: str, usage_dimension: str, quantity: float) -> dict[str, Any]: ...

    @abstractmethod
    async def create_usage_record(self, *, tenant_id: str, usage_dimension: str, quantity: float, timestamp: Optional[str] = None) -> dict[str, Any]: ...

    @abstractmethod
    def map_product(self, *, package_id: str) -> Optional[str]: ...

    @abstractmethod
    def map_price(self, *, plan_tier: str, usage_dimension: Optional[str] = None) -> Optional[str]: ...

    @abstractmethod
    async def handle_webhook(self, *, payload: bytes, signature: Optional[str], timestamp: Optional[str] = None) -> WebhookResult: ...
