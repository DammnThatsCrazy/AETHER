"""
Aether Shared -- Provider Gateway

Unified abstraction for all third-party provider calls.
Supports BYOK key management, automatic failover, and usage metering.

Quick-start::

    from shared.providers import (
        AdaptiveRouter,
        BYOKKeyVault,
        Provider,
        ProviderCategory,
        ProviderConfig,
        ProviderRegistry,
        ProviderResult,
        ProviderStatus,
        UsageMeter,
    )
"""

from shared.providers.base import Provider, ProviderConfig, ProviderResult, ProviderStatus
from shared.providers.categories import CATEGORY_PROVIDERS, PROVIDER_FACTORY, ProviderCategory
from shared.providers.key_vault import BYOKKeyVault
from shared.providers.meter import UsageMeter, UsageRecord
from shared.providers.registry import ProviderRegistry
from shared.providers.router import AdaptiveRouter

__all__ = [
    # Base
    "Provider",
    "ProviderConfig",
    "ProviderResult",
    "ProviderStatus",
    # Categories
    "ProviderCategory",
    "PROVIDER_FACTORY",
    "CATEGORY_PROVIDERS",
    # Key vault
    "BYOKKeyVault",
    # Meter
    "UsageMeter",
    "UsageRecord",
    # Registry
    "ProviderRegistry",
    # Router
    "AdaptiveRouter",
]
