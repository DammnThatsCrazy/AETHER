"""External billing / payment provider readiness.

Provider-safe abstraction layered on top of the existing internal billing/revops
layer. Defaults to ``internal_only`` so local dev and the current revops layer
are unaffected; an external provider (Stripe) activates only behind feature
flags. No external billing env vars are required for local dev.

Secrets are never logged, returned, or persisted by these providers.
"""
from __future__ import annotations

from config.settings import settings

from services.billing.providers.base import (
    BillingProvider,
    InvoiceExportMode,
    PaymentStatus,
    ProductPriceMapping,
    ProviderDisabledError,
    ProviderType,
)
from services.billing.providers.internal import InternalOnlyProvider
from services.billing.providers.mappings import load_mappings, mapping_status_summary
from services.billing.providers.stripe_provider import StripeBillingProvider

__all__ = [
    "BillingProvider",
    "InternalOnlyProvider",
    "StripeBillingProvider",
    "ProviderType",
    "PaymentStatus",
    "InvoiceExportMode",
    "ProductPriceMapping",
    "ProviderDisabledError",
    "get_billing_provider",
    "provider_status_summary",
    "load_mappings",
    "mapping_status_summary",
]


def resolve_provider_type() -> ProviderType:
    """Resolve the active provider type from feature flags / config."""
    cfg = settings.external_billing
    if not cfg.external_billing_enabled:
        return "internal_only"
    if cfg.stripe_billing_enabled or cfg.provider_mode == "stripe":
        return "stripe"
    mode = cfg.provider_mode
    if mode in ("manual_invoice", "enterprise_contract", "internal_only"):
        return mode  # type: ignore[return-value]
    return "internal_only"


def get_billing_provider() -> BillingProvider:
    """Factory: returns the configured provider. Safe + offline by default."""
    provider_type = resolve_provider_type()
    if provider_type == "stripe":
        return StripeBillingProvider()
    return InternalOnlyProvider(provider_type=provider_type)


def provider_status_summary() -> dict:
    """Operator-facing provider/sync status (no secrets)."""
    cfg = settings.external_billing
    provider = get_billing_provider()
    mappings = load_mappings()
    summary = mapping_status_summary(mappings)
    return {
        "external_billing_enabled": cfg.external_billing_enabled,
        "billing_provider_mode": resolve_provider_type(),
        "provider_configured": provider.is_configured(),
        "provider_sync_enabled": cfg.kyber_provider_sync_enabled,
        "stripe_billing_enabled": cfg.stripe_billing_enabled,
        "invoice_export_mode": provider.invoice_export_mode(),
        "product_mapping_status": summary,
        "unmapped_usage_dimensions": summary["unmapped_usage_dimensions"],
        "failed_billing_syncs": [],  # populated by sync workers in deployment
    }
