"""WooCommerce provider plugin for the Universal Provider Runtime."""

from services.providers.woocommerce.plugin import WooCommerceOrdersPlugin

try:
    from services.provider_runtime.plugin import register_provider

    _REGISTRATION_AVAILABLE = True
except ImportError:  # runtime not present — self-registration degrades to a no-op.
    register_provider = None  # type: ignore[assignment]
    _REGISTRATION_AVAILABLE = False

WOOCOMMERCE_PLUGINS: list[type[WooCommerceOrdersPlugin]] = [WooCommerceOrdersPlugin]


def install_woocommerce_providers(registry) -> None:
    """Registry-friendly install path: register every WooCommerce plugin once."""
    for cls in WOOCOMMERCE_PLUGINS:
        registry.register(cls(), source="woocommerce")


# Self-registration at import time (idempotent; the runtime makes
# register_provider idempotent against double-loads from the registry's
# load_all()).
if _REGISTRATION_AVAILABLE:
    try:
        register_provider(WooCommerceOrdersPlugin())
    except Exception:  # pragma: no cover - defensive: runtime not yet present
        pass

__all__ = [
    "WOOCOMMERCE_PLUGINS",
    "WooCommerceOrdersPlugin",
    "install_woocommerce_providers",
]
