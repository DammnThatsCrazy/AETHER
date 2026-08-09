"""Etsy provider plugin for the Universal Provider Runtime."""

from services.providers.etsy.plugin import EtsyOrdersPlugin

try:
    from services.provider_runtime.plugin import register_provider

    _REGISTRATION_AVAILABLE = True
except ImportError:  # runtime not present — self-registration degrades to a no-op.
    register_provider = None  # type: ignore[assignment]
    _REGISTRATION_AVAILABLE = False

ETSY_PLUGINS: list[type[EtsyOrdersPlugin]] = [EtsyOrdersPlugin]


def install_etsy_providers(registry) -> None:
    """Registry-friendly install path: register every Etsy plugin once."""
    for cls in ETSY_PLUGINS:
        registry.register(cls(), source="etsy")


# Self-registration at import time (idempotent; the runtime makes
# register_provider idempotent against double-loads from the registry's
# load_all()).
if _REGISTRATION_AVAILABLE:
    try:
        register_provider(EtsyOrdersPlugin())
    except Exception:  # pragma: no cover - defensive: runtime not yet present
        pass

__all__ = ["ETSY_PLUGINS", "EtsyOrdersPlugin", "install_etsy_providers"]
