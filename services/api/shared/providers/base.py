"""
Aether Shared -- Provider Base
Protocol definition and abstract base for all provider adapters.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ProviderStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass
class ProviderResult:
    """Standardised result from any provider call."""

    success: bool
    data: Any = None
    error: Optional[str] = None
    provider_name: str = ""
    latency_ms: float = 0.0
    from_cache: bool = False
    failover_used: bool = False

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "provider_name": self.provider_name,
            "latency_ms": round(self.latency_ms, 2),
            "from_cache": self.from_cache,
            "failover_used": self.failover_used,
        }


@dataclass
class ProviderConfig:
    """Runtime configuration for a single provider instance."""

    name: str
    api_key: str = ""
    endpoint: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    is_system_default: bool = False
    tenant_id: Optional[str] = None
    max_rps: int = 100
    priority: int = 0  # Lower = higher priority in failover ordering


class Provider(ABC):
    """
    Abstract base for all provider adapters.

    Each concrete provider (QuickNodeProvider, AlchemyProvider, etc.)
    implements ``execute()`` for its specific API contract.
    """

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config
        self._request_count = 0
        self._last_request_time: float = 0.0

    @property
    def name(self) -> str:
        return self.config.name

    @abstractmethod
    async def execute(self, method: str, params: dict[str, Any]) -> ProviderResult:
        """Execute an API call through this provider."""
        ...

    @abstractmethod
    async def health_check(self) -> ProviderStatus:
        """Check provider health.  Must be non-blocking and fast."""
        ...

    async def initialize(self) -> None:
        """Optional setup hook (connection pools, session creation)."""

    async def teardown(self) -> None:
        """Optional cleanup hook."""
