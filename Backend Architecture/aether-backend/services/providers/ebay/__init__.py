"""eBay provider plugin for the Universal Provider Runtime."""

from services.providers.ebay.plugin import EbayOrdersPlugin

try:
    from services.provider_runtime.plugin import register_provider

    _REGISTRATION_AVAILABLE = True
except ImportError:  # runtime not present — self-registration degrades to a no-op.
    register_provider = None  # type: ignore[assignment]
    _REGISTRATION_AVAILABLE = False

EBAY_PLUGINS: list[type[EbayOrdersPlugin]] = [EbayOrdersPlugin]


def install_ebay_providers(registry) -> None:
    """Registry-friendly install path: register every eBay plugin once."""
    for cls in EBAY_PLUGINS:
        registry.register(cls(), source="ebay")


# Self-registration at import time (idempotent; the runtime makes
# register_provider idempotent against double-loads from the registry's
# load_all()).
if _REGISTRATION_AVAILABLE:
    try:
        register_provider(EbayOrdersPlugin())
    except Exception:  # pragma: no cover - defensive: runtime not yet present
        pass

__all__ = ["EBAY_PLUGINS", "EbayOrdersPlugin", "install_ebay_providers"]
