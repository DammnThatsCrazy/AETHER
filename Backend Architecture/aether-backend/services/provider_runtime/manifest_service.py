"""Merged manifest surface: the derived catalog + installed plugins (Team C).

The runtime exposes one manifest view: the derived catalog (inbound connector
projections, observe-only payment rails, and deferred credit bureaus) extended
by the manifests of installed plugins. A plugin manifest that collides with a
catalog manifest is only admitted when byte-identical — the legacy-compatibility
re-derivation case; any other collision is a hard error so the surface never
ships two conflicting claims for the same identity.
"""

from __future__ import annotations

from shared.integration_contracts.catalog import manifest_by_identity
from shared.integration_contracts.manifest import ProviderManifest

from services.provider_runtime.registry import ProviderRegistry, provider_registry


class ManifestService:
    """Collision-asserted, merged manifest surface for the runtime."""

    def __init__(self, registry: ProviderRegistry = provider_registry) -> None:
        self._registry = registry

    def catalog(self) -> dict[str, ProviderManifest]:
        """The derived catalog alone (identity key -> manifest)."""
        return dict(manifest_by_identity)

    def installed(self) -> dict[str, ProviderManifest]:
        """Installed plugin manifests alone (identity key -> manifest)."""
        return self._registry.manifests()

    def merged_manifests(self) -> dict[str, ProviderManifest]:
        """Catalog + installed plugin manifests, collision-asserted.

        A plugin manifest colliding with a catalog manifest is admitted only
        when byte-identical (``model_dump()`` equal — the legacy re-derivation
        case); any other collision raises :class:`ValueError`.
        """
        merged: dict[str, ProviderManifest] = dict(manifest_by_identity)
        for key, manifest in self._registry.manifests().items():
            existing = merged.get(key)
            if existing is not None:
                if existing.model_dump() == manifest.model_dump():
                    continue
                raise ValueError(
                    f"plugin manifest for {key!r} conflicts with the derived "
                    "catalog (plugin manifests must match the catalog byte-for-byte)"
                )
            merged[key] = manifest
        return merged


manifest_service = ManifestService()


__all__ = ["ManifestService", "manifest_service"]
