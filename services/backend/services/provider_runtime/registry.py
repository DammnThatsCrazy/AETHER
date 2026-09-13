"""The provider registry — discovery, honest registration, and load (Team C).

The registry is the runtime's plugin surface. Every ``register`` runs
:func:`assert_plugin_honest <services.provider_runtime.validation.assert_plugin_honest>`,
so a plugin cannot claim more than it exposes. Identity collisions are
rejected:

* a plugin already registered in this registry under the same identity key is a
  hard error (idempotent re-registration of the *same* object is a no-op); and
* a plugin manifest that collides with the derived catalog is only admitted
  when it is byte-identical to the catalog's manifest — the legacy-compatibility
  re-derivation case — anything else is a hard error.

:meth:`load_all` is idempotent per instance: it discovers entry-point plugins
(group ``aether.providers``, when enabled), imports local in-repo plugin
modules (import failures are logged and skipped), and then installs the legacy
connector compatibility plugins — which is never skipped.
"""

from __future__ import annotations

import importlib
import logging
from typing import Optional

from shared.integration_contracts.catalog import manifest_by_identity
from shared.integration_contracts.manifest import ProviderManifest
from shared.integration_contracts.plugin import PluginValidationError, plugin_identity_key

from services.provider_runtime.errors import (
    PluginIncompatible,
    ProviderNotInstalled,
)
from services.provider_runtime.plugin import (
    LOCAL_PLUGIN_MODULES,
    PLUGIN_ABI_VERSION,
    BaseProviderPlugin,
    registered_providers,
)
from services.provider_runtime.validation import assert_plugin_honest

logger = logging.getLogger(__name__)

# Entry-point group name for provider plugins (importlib.metadata).
PLUGIN_ENTRY_POINT_GROUP = "aether.providers"


class ProviderRegistry:
    """Registry of installed provider plugins."""

    def __init__(
        self,
        *,
        entry_points_enabled: bool = False,
        auto_install_legacy: bool = True,
    ) -> None:
        self.entry_points_enabled = entry_points_enabled
        self.auto_install_legacy = auto_install_legacy
        self._plugins: dict[str, BaseProviderPlugin] = {}
        self._sources: dict[str, str] = {}
        self._loaded = False

    # ── Registration ────────────────────────────────────────────────────────

    def register(
        self,
        plugin: BaseProviderPlugin,
        *,
        source: str = "direct",
    ) -> str:
        """Honesty-validate and register a plugin. Returns its identity key.

        Raises :class:`PluginValidationError
        <shared.integration_contracts.plugin.PluginValidationError>` on any
        honesty violation or identity collision (unless the collision is the
        byte-identical legacy re-derivation of a catalog manifest), and
        :class:`PluginIncompatible
        <services.provider_runtime.errors.PluginIncompatible>` when the plugin
        was built against an unsupported ABI.
        """
        assert_plugin_honest(plugin)

        abi = getattr(plugin, "abi_version", PLUGIN_ABI_VERSION)
        if abi != PLUGIN_ABI_VERSION:
            raise PluginIncompatible(
                f"plugin ABI {abi!r} is not supported by runtime ABI "
                f"{PLUGIN_ABI_VERSION!r}",
            )

        key = plugin_identity_key(plugin)
        existing = self._plugins.get(key)
        if existing is not None:
            if existing is plugin:
                return key
            raise PluginValidationError(
                [f"duplicate provider identity key {key!r} already registered"]
            )

        manifest = plugin.manifest()
        catalog_manifest = manifest_by_identity.get(key)
        if catalog_manifest is not None and (
            catalog_manifest.model_dump() != manifest.model_dump()
        ):
            raise PluginValidationError(
                [
                    f"manifest for {key!r} conflicts with the derived catalog; "
                    "plugin manifests must match the catalog byte-for-byte"
                ]
            )

        self._plugins[key] = plugin
        self._sources[key] = source
        logger.info("registered provider %s (source=%s)", key, source)
        return key

    # ── Lookup ──────────────────────────────────────────────────────────────

    def get(self, identity_key: str) -> Optional[BaseProviderPlugin]:
        """Return the plugin for ``identity_key``, or ``None`` when absent."""
        return self._plugins.get(identity_key)

    def require(self, identity_key: str) -> BaseProviderPlugin:
        """Return the plugin for ``identity_key``, raising when absent."""
        plugin = self._plugins.get(identity_key)
        if plugin is None:
            raise ProviderNotInstalled(
                f"provider {identity_key!r} is not installed"
            )
        return plugin

    def list(self) -> list[BaseProviderPlugin]:
        """All registered plugins, in registration order."""
        return list(self._plugins.values())

    def manifests(self) -> dict[str, ProviderManifest]:
        """Identity key -> honest manifest for every registered plugin."""
        return {key: plugin.manifest() for key, plugin in self._plugins.items()}

    def sources(self) -> dict[str, str]:
        """Identity key -> registration source (``legacy``, ``local``, ...)."""
        return dict(self._sources)

    def __contains__(self, identity_key: str) -> bool:
        return identity_key in self._plugins

    def __len__(self) -> int:
        return len(self._plugins)

    # ── Discovery / loading ─────────────────────────────────────────────────

    def discover_entry_points(self) -> list[str]:
        """Module names from the ``aether.providers`` entry-point group."""
        if not self.entry_points_enabled:
            return []
        try:
            from importlib.metadata import entry_points
        except ImportError:  # pragma: no cover - stdlib; defensive
            return []
        eps = entry_points(group=PLUGIN_ENTRY_POINT_GROUP)
        return sorted({str(ep.value) for ep in eps})

    def _import_plugin_module(self, module_name: str) -> int:
        """Import one plugin module; absorb its module-level registrations.

        A module that FAILS TO IMPORT is logged and skipped — a broken optional
        plugin must never take the runtime down. A module that imports but whose
        registrations fail honesty validation raises loudly here — a dishonest
        plugin is never silently accepted or skipped. Returns the number of
        plugins newly registered from the module.
        """
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001 - guarded optional import
            logger.warning("skipping plugin module %r: %s", module_name, exc)
            return 0

        newly = 0
        for key, plugin in registered_providers().items():
            if key in self._plugins:
                continue
            self.register(plugin, source="local")
            newly += 1
        return newly

    def load_all(self) -> int:
        """Discover + install every plugin. Idempotent per registry instance.

        Order: entry-point plugins (when enabled) → local in-repo modules →
        legacy connector compatibility plugins. Returns the total number of
        installed providers.
        """
        if self._loaded:
            return len(self._plugins)

        for module_name in self.discover_entry_points():
            self._import_plugin_module(module_name)
        for module_name in LOCAL_PLUGIN_MODULES:
            self._import_plugin_module(module_name)
        if self.auto_install_legacy:
            from services.provider_runtime.legacy import install_legacy_plugins

            install_legacy_plugins(self)
        self._loaded = True
        logger.info("load_all complete: %d providers installed", len(self._plugins))
        return len(self._plugins)


# Module-level singleton shared by the runtime service layer.
# ``registry`` is the canonical name used across the runtime; ``provider_registry``
# is an alias kept for callers that named the singleton explicitly.
provider_registry = ProviderRegistry()
registry = provider_registry


__all__ = [
    "PLUGIN_ENTRY_POINT_GROUP",
    "ProviderRegistry",
    "provider_registry",
    "registry",
]
