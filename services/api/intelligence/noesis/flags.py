"""Feature flags for Noesis production rollout."""

from __future__ import annotations

import os


class NoesisFlags:
    """Reads Noesis feature flags from environment variables."""

    @property
    def noesis_enabled(self) -> bool:
        return os.getenv("NOESIS_ENABLED", "true").lower() in ("true", "1", "yes")

    @property
    def llm_enabled(self) -> bool:
        return os.getenv("NOESIS_LLM_ENABLED", "false").lower() in ("true", "1", "yes")

    @property
    def debug_enabled(self) -> bool:
        # Always enabled in local dev; opt-in only in staging/production
        if os.getenv("AETHER_ENV", "local").lower() == "local":
            return True
        return os.getenv("NOESIS_DEBUG_ENABLED", "false").lower() in ("true", "1", "yes")

    @property
    def cross_tenant_enabled(self) -> bool:
        return os.getenv("NOESIS_CROSS_TENANT_ENABLED", "true").lower() in ("true", "1", "yes")

    @property
    def multi_hop_enabled(self) -> bool:
        return os.getenv("NOESIS_MULTI_HOP_ENABLED", "false").lower() in ("true", "1", "yes")

    @property
    def max_queries_per_minute(self) -> int:
        return int(os.getenv("NOESIS_RATE_LIMIT_QPM", "60"))

    @property
    def max_daily_queries(self) -> int:
        return int(os.getenv("NOESIS_DAILY_QUOTA", "1000"))

    @property
    def provider_token_budget(self) -> int:
        return int(os.getenv("NOESIS_PROVIDER_TOKEN_BUDGET", "100000"))

    @property
    def canary_tenants(self) -> list[str]:
        raw = os.getenv("NOESIS_CANARY_TENANTS", "").strip()
        if not raw:
            return []
        return [t.strip() for t in raw.split(",") if t.strip()]

    def is_tenant_allowed(self, tenant_id: str) -> bool:
        canaries = self.canary_tenants
        if not canaries:
            return True
        return tenant_id in canaries
