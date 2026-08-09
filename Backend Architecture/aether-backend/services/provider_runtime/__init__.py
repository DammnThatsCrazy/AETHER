"""Universal Provider Runtime — public surface.

Re-exports the API routers, the provider registry singleton, and the
certification harness. ``provider_registry`` is resolved lazily via PEP 562 so
importing this package does not require Team C's registry module to be present
(yet) — the feature flag in ``main.py`` gates mounting, not importability. This
package never shadows its own submodule names.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from services.provider_runtime.certification import certify_provider
from services.provider_runtime.routes import (
    admin_router,
    router,
    webhook_public_router,
)

if TYPE_CHECKING:  # pragma: no cover - typing-only
    from services.provider_runtime.registry import ProviderRegistry

__all__ = [
    "router",
    "admin_router",
    "webhook_public_router",
    "provider_registry",
    "certify_provider",
]


def __getattr__(name: str) -> Any:
    """Lazily resolve ``provider_registry`` from Team C's registry module.

    Uses the REAL registry module (``provider_registry``, with a fallback to
    ``registry``) — never a fabricated stub. Raises the real ImportError when
    the module has not landed yet.
    """
    if name == "provider_registry":
        from services.provider_runtime import registry as _registry_module

        singleton = getattr(
            _registry_module,
            "provider_registry",
            getattr(_registry_module, "registry", None),
        )
        if singleton is None:
            raise ImportError(
                "services.provider_runtime.registry exposes neither "
                "'provider_registry' nor 'registry'"
            )
        return singleton
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
