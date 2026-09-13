"""TikTok Shop provider plugin for the Universal Provider Runtime."""

from services.providers.tiktok.plugin import TikTokOrdersPlugin

try:
    from services.provider_runtime.plugin import register_provider

    _REGISTRATION_AVAILABLE = True
except ImportError:  # runtime not present — self-registration degrades to a no-op.
    register_provider = None  # type: ignore[assignment]
    _REGISTRATION_AVAILABLE = False

TIKTOK_PLUGINS: list[type[TikTokOrdersPlugin]] = [TikTokOrdersPlugin]


def install_tiktok_providers(registry) -> None:
    """Registry-friendly install path: register every TikTok Shop plugin once."""
    for cls in TIKTOK_PLUGINS:
        registry.register(cls(), source="tiktok")


# Self-registration at import time (idempotent; the runtime makes
# register_provider idempotent against double-loads from the registry's
# load_all()).
if _REGISTRATION_AVAILABLE:
    try:
        register_provider(TikTokOrdersPlugin())
    except Exception:  # pragma: no cover - defensive: runtime not yet present
        pass

__all__ = ["TIKTOK_PLUGINS", "TikTokOrdersPlugin", "install_tiktok_providers"]
