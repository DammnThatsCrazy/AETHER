"""Shopify provider plugin for the Universal Provider Runtime."""

from services.providers.shopify.plugin import ShopifyOrdersPlugin

try:
    from services.provider_runtime.plugin import register_provider

    _REGISTRATION_AVAILABLE = True
except ImportError:  # Team C has not landed yet — self-registration degrades to a no-op.
    register_provider = None  # type: ignore[assignment]
    _REGISTRATION_AVAILABLE = False

SHOPIFY_PLUGINS: list[type[ShopifyOrdersPlugin]] = [ShopifyOrdersPlugin]


def install_shopify_providers(registry) -> None:
    """Registry-friendly install path: register every Shopify plugin once."""
    for cls in SHOPIFY_PLUGINS:
        registry.register(cls(), source="shopify")


# Self-registration at import time (idempotent; the runtime makes
# register_provider idempotent against double-loads from the registry's
# load_all()).
if _REGISTRATION_AVAILABLE:
    try:
        register_provider(ShopifyOrdersPlugin())
    except Exception:  # pragma: no cover - defensive: runtime not yet present
        pass

__all__ = ["SHOPIFY_PLUGINS", "ShopifyOrdersPlugin", "install_shopify_providers"]
