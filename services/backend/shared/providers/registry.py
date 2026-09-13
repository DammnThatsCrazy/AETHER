"""
Aether Shared -- Provider Registry

Central registry for all provider instances, organised by category.
Manages system-default providers and BYOK tenant overrides.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.logger.logger import get_logger
from shared.providers.base import Provider, ProviderConfig
from shared.providers.categories import (
    CATEGORY_PROVIDERS,
    PROVIDER_FACTORY,
    ProviderCategory,
)
from shared.providers.key_vault import BYOKKeyVault

logger = get_logger("aether.providers.registry")


class ProviderRegistry:
    """
    Two-tier registry:
        _system_providers[category][provider_name]  = Provider
        _tenant_providers[tenant_id][category][name] = Provider   (lazy)
    """

    def __init__(self, key_vault: BYOKKeyVault) -> None:
        self._key_vault = key_vault
        self._system_providers: dict[ProviderCategory, dict[str, Provider]] = {}
        self._tenant_providers: dict[str, dict[ProviderCategory, dict[str, Provider]]] = {}
        self._initialized = False

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def initialize_system_providers(self, settings: Any) -> None:
        """Bootstrap system-default providers from config/settings.py."""

        # -- Blockchain RPC --
        rpc: dict[str, Provider] = {}
        if settings.quicknode.api_key or settings.quicknode.endpoint:
            rpc["quicknode"] = PROVIDER_FACTORY["quicknode"](ProviderConfig(
                name="quicknode",
                api_key=settings.quicknode.api_key,
                endpoint=settings.quicknode.endpoint,
                max_rps=settings.quicknode.max_rps,
                is_system_default=True,
                priority=0,
            ))

        gw = settings.provider_gateway
        if gw.alchemy_api_key:
            rpc["alchemy"] = PROVIDER_FACTORY["alchemy"](ProviderConfig(
                name="alchemy",
                api_key=gw.alchemy_api_key,
                endpoint=gw.alchemy_endpoint,
                is_system_default=True,
                priority=1,
            ))
        if gw.infura_api_key:
            rpc["infura"] = PROVIDER_FACTORY["infura"](ProviderConfig(
                name="infura",
                api_key=gw.infura_api_key,
                extra={"project_id": gw.infura_project_id},
                is_system_default=True,
                priority=2,
            ))
        if rpc:
            self._system_providers[ProviderCategory.BLOCKCHAIN_RPC] = rpc

        # -- Block Explorer --
        exp: dict[str, Provider] = {}
        if gw.etherscan_api_key:
            exp["etherscan"] = PROVIDER_FACTORY["etherscan"](ProviderConfig(
                name="etherscan", api_key=gw.etherscan_api_key,
                is_system_default=True, priority=0,
            ))
        if gw.moralis_api_key:
            exp["moralis"] = PROVIDER_FACTORY["moralis"](ProviderConfig(
                name="moralis", api_key=gw.moralis_api_key,
                is_system_default=True, priority=1,
            ))
        if exp:
            self._system_providers[ProviderCategory.BLOCK_EXPLORER] = exp

        # Initialise all providers
        for category, providers in self._system_providers.items():
            for name, provider in providers.items():
                await provider.initialize()
                logger.info(f"System provider initialised: {category.value}/{name}")

        self._initialized = True
        total = sum(len(p) for p in self._system_providers.values())
        logger.info(
            f"ProviderRegistry initialised: {total} system providers "
            f"across {len(self._system_providers)} categories"
        )

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    async def get_provider(
        self,
        category: ProviderCategory,
        tenant_id: Optional[str] = None,
        preferred_name: Optional[str] = None,
    ) -> Optional[Provider]:
        """Resolve a single provider via priority chain."""
        # 1. Tenant BYOK
        if tenant_id:
            tp = await self._get_tenant_provider(tenant_id, category, preferred_name)
            if tp:
                return tp

        # 2. System default
        sys_provs = self._system_providers.get(category, {})
        if preferred_name and preferred_name in sys_provs:
            return sys_provs[preferred_name]
        if sys_provs:
            return sorted(sys_provs.values(), key=lambda p: p.config.priority)[0]

        return None

    async def get_all_providers(
        self,
        category: ProviderCategory,
        tenant_id: Optional[str] = None,
    ) -> list[Provider]:
        """All available providers for a category, tenant-first ordering."""
        providers: list[Provider] = []

        if tenant_id:
            tenant_cat = self._tenant_providers.get(tenant_id, {}).get(category, {})
            providers.extend(sorted(tenant_cat.values(), key=lambda p: p.config.priority))

        tenant_names = {p.name for p in providers}
        for provider in sorted(
            self._system_providers.get(category, {}).values(),
            key=lambda p: p.config.priority,
        ):
            if provider.name not in tenant_names:
                providers.append(provider)

        return providers

    async def _get_tenant_provider(
        self,
        tenant_id: str,
        category: ProviderCategory,
        preferred_name: Optional[str] = None,
    ) -> Optional[Provider]:
        """Lazily create a BYOK provider on first access."""
        tenant_cat = self._tenant_providers.get(tenant_id, {}).get(category, {})
        if preferred_name and preferred_name in tenant_cat:
            return tenant_cat[preferred_name]
        if tenant_cat:
            return next(iter(tenant_cat.values()))

        names = [preferred_name] if preferred_name else CATEGORY_PROVIDERS.get(category, [])
        for name in names:
            if name not in PROVIDER_FACTORY:
                continue
            key = await self._key_vault.get_key(tenant_id, name)
            if key:
                endpoint = await self._key_vault.get_endpoint(tenant_id, name)
                config = ProviderConfig(
                    name=name, api_key=key, endpoint=endpoint or "",
                    tenant_id=tenant_id, priority=0,
                )
                provider = PROVIDER_FACTORY[name](config)
                await provider.initialize()

                self._tenant_providers.setdefault(tenant_id, {})
                self._tenant_providers[tenant_id].setdefault(category, {})
                self._tenant_providers[tenant_id][category][name] = provider
                logger.info(
                    f"BYOK provider created: tenant={tenant_id} "
                    f"category={category.value} provider={name}"
                )
                return provider

        return None

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_categories(self) -> dict[str, list[str]]:
        """List all categories and their supported provider names."""
        return {cat.value: names for cat, names in CATEGORY_PROVIDERS.items()}

    async def health_check(self) -> dict:
        """Health status for all system providers."""
        result: dict[str, dict[str, str]] = {}
        for category, providers in self._system_providers.items():
            cat_health: dict[str, str] = {}
            for name, provider in providers.items():
                status = await provider.health_check()
                cat_health[name] = status.value
            result[category.value] = cat_health
        return result

    async def teardown(self) -> None:
        """Shut down all provider instances."""
        for providers in self._system_providers.values():
            for provider in providers.values():
                await provider.teardown()
        for categories in self._tenant_providers.values():
            for providers in categories.values():
                for provider in providers.values():
                    await provider.teardown()
        self._tenant_providers.clear()
        logger.info("ProviderRegistry shut down")
