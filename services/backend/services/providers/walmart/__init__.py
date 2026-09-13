"""Walmart Marketplace provider plugin for the Universal Provider Runtime."""

from services.providers.walmart.plugin import WalmartOrdersPlugin

try:
    from services.provider_runtime.plugin import register_provider

    _REGISTRATION_AVAILABLE = True
except ImportError:  # runtime not present — self-registration degrades to a no-op.
    register_provider = None  # type: ignore[assignment]
    _REGISTRATION_AVAILABLE = False

WALMART_PLUGINS: list[type[WalmartOrdersPlugin]] = [WalmartOrdersPlugin]


def install_walmart_providers(registry) -> None:
    """Registry-friendly install path: register every Walmart plugin once."""
    for cls in WALMART_PLUGINS:
        registry.register(cls(), source="walmart")


# Self-registration at import time (idempotent; the runtime makes
# register_provider idempotent against double-loads from the registry's
# load_all()).
if _REGISTRATION_AVAILABLE:
    try:
        register_provider(WalmartOrdersPlugin())
    except Exception:  # pragma: no cover - defensive: runtime not yet present
        pass

__all__ = ["WALMART_PLUGINS", "WalmartOrdersPlugin", "install_walmart_providers"]
