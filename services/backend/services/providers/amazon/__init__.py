"""Amazon provider plugin for the Universal Provider Runtime."""

from services.providers.amazon.plugin import AmazonOrdersPlugin

try:
    from services.provider_runtime.plugin import register_provider

    _REGISTRATION_AVAILABLE = True
except ImportError:  # runtime not present — self-registration degrades to a no-op.
    register_provider = None  # type: ignore[assignment]
    _REGISTRATION_AVAILABLE = False

AMAZON_PLUGINS: list[type[AmazonOrdersPlugin]] = [AmazonOrdersPlugin]


def install_amazon_providers(registry) -> None:
    """Registry-friendly install path: register every Amazon plugin once."""
    for cls in AMAZON_PLUGINS:
        registry.register(cls(), source="amazon")


# Self-registration at import time (idempotent; the runtime makes
# register_provider idempotent against double-loads from the registry's
# load_all()).
if _REGISTRATION_AVAILABLE:
    try:
        register_provider(AmazonOrdersPlugin())
    except Exception:  # pragma: no cover - defensive: runtime not yet present
        pass

__all__ = ["AMAZON_PLUGINS", "AmazonOrdersPlugin", "install_amazon_providers"]
