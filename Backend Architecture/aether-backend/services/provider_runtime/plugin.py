"""Provider plugin base class and module-level registration surface (Team C).

A provider plugin is a self-contained runtime unit: an identity, an honest
manifest, one optional adapter per capability, and a normalizer. This module
owns the abstract base most plugins extend (:class:`BaseProviderPlugin`) plus
the module-level in-repo registration hook (:func:`register_provider`).

The honest surface is structural by construction: every capability accessor on
the base defaults to ``None``. A plugin claims a capability only by overriding
the accessor to return an adapter, so whatever ``capability_set`` derives from
the accessors is exactly what the plugin exposes — nothing more.

The module-level store is the simple "in-repo plugin" hook. The full runtime
registry (:mod:`services.provider_runtime.registry`) pulls newly-registered
plugins out of this store after importing a plugin module, so a plugin only
needs to call :func:`register_provider`; the runtime picks it up.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional

from shared.integration_contracts.capabilities import (
    AccountAdapter,
    AuthAdapter,
    PullAdapter,
    ReconciliationAdapter,
    ReportAdapter,
    StreamAdapter,
    WebhookAdapter,
)
from shared.integration_contracts.identity import ProviderIdentity
from shared.integration_contracts.manifest import ProviderManifest
from shared.integration_contracts.normalization import EventNormalizer

logger = logging.getLogger(__name__)

# The plugin ABI version this runtime supports. A plugin built against a
# different ABI (declared via ``abi_version``) is rejected at registration so a
# mismatched plugin fails loudly instead of misbehaving at runtime.
plugin_version = "1"
PLUGIN_ABI_VERSION = plugin_version

# Local (in-repo) plugin modules auto-loaded by the registry's ``load_all`` in
# addition to entry-point-discovered plugins. A module that FAILS TO IMPORT is
# logged and skipped — a broken optional plugin must never take the runtime
# down. A module that imports but registers a dishonest plugin fails loudly at
# registration (never silently accepted). The legacy connector install is never
# skipped.
LOCAL_PLUGIN_MODULES: list[str] = [
    "services.providers.shopify",
    "services.providers.woocommerce",
    "services.providers.etsy",
    "services.providers.amazon",
    "services.providers.ebay",
    "services.providers.walmart",
    "services.providers.tiktok",
]


class BaseProviderPlugin(ABC):
    """Abstract base for provider plugins.

    Subclasses must implement :meth:`identity`, :meth:`manifest`, and
    :meth:`normalizer`. Every capability accessor defaults to ``None`` — a
    plugin claims a capability only by overriding the accessor to return an
    adapter. :meth:`report`, :meth:`stream`, and :meth:`reconciliation` are
    inherited as ``None`` returns unless a subclass genuinely implements them.
    """

    #: Plugin ABI version this plugin was built against. Plugins that do not
    #: declare a version default to the current runtime ABI.
    abi_version: str = PLUGIN_ABI_VERSION

    @abstractmethod
    def identity(self) -> ProviderIdentity:
        """The provider capability identity (``family.product.capability``)."""

    @abstractmethod
    def manifest(self) -> ProviderManifest:
        """The honest, validated :class:`ProviderManifest` for this capability."""

    @abstractmethod
    def normalizer(self) -> EventNormalizer:
        """The deterministic normalizer translating raw records into events."""

    # ── Optional capability adapters (honest ``None`` defaults) ──────────────

    def auth(self) -> Optional[AuthAdapter]:
        """Credential validation / live connectivity test adapter, if any."""
        return None

    def account(self) -> Optional[AccountAdapter]:
        """Account discovery / selection adapter, if any."""
        return None

    def pull(self) -> Optional[PullAdapter]:
        """Cursor-addressable pull ingestion adapter, if any."""
        return None

    def webhook(self) -> Optional[WebhookAdapter]:
        """Inbound webhook verification / parsing adapter, if any."""
        return None

    def report(self) -> Optional[ReportAdapter]:
        """Report-based ingestion adapter, if any."""
        return None

    def stream(self) -> Optional[StreamAdapter]:
        """Stream / subscription ingestion adapter, if any."""
        return None

    def reconciliation(self) -> Optional[ReconciliationAdapter]:
        """Snapshot-based reconciliation adapter, if any."""
        return None


# ── Module-level in-repo plugin store (idempotent by identity key) ──────────


_PLUGINS: dict[str, BaseProviderPlugin] = {}


def register_provider(plugin: BaseProviderPlugin) -> str:
    """Register a plugin into the module-level store by its identity key.

    Idempotent per identity key: re-registering the exact same object is a
    no-op returning the key; a *different* object under the same key is a
    :class:`PluginValidationError <shared.integration_contracts.plugin.PluginValidationError>`
    so conflicting claims fail loudly.

    Returns the canonical ``family.product.capability`` identity key.
    """
    from shared.integration_contracts.plugin import (
        PluginValidationError,
        plugin_identity_key,
    )

    key = plugin_identity_key(plugin)
    existing = _PLUGINS.get(key)
    if existing is not None and existing is not plugin:
        raise PluginValidationError(
            [f"duplicate plugin identity key {key!r} (already registered)"]
        )
    _PLUGINS[key] = plugin
    logger.debug("registered provider plugin %s", key)
    return key


def registered_providers() -> dict[str, BaseProviderPlugin]:
    """Snapshot of currently registered plugins (safe for the caller to mutate)."""
    return dict(_PLUGINS)


def clear_registered_providers() -> None:
    """Reset the module-level store (test seam only — not a runtime operation)."""
    _PLUGINS.clear()


__all__ = [
    "LOCAL_PLUGIN_MODULES",
    "PLUGIN_ABI_VERSION",
    "BaseProviderPlugin",
    "clear_registered_providers",
    "plugin_version",
    "register_provider",
    "registered_providers",
]
