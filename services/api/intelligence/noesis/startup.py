"""Noesis startup configuration validator.

Called from the FastAPI lifespan handler when NOESIS_ENABLED=true.
Checks that all runtime dependencies are reachable and all required
environment variables are set before accepting traffic.
"""

from __future__ import annotations

import os

from shared.logger.logger import get_logger

logger = get_logger("aether.service.noesis.startup")


class NoesisStartupValidator:
    """Validates Noesis runtime configuration at application startup."""

    def validate(self) -> list[str]:
        """Return a list of error strings. Empty list = configuration is valid."""
        errors: list[str] = []

        noesis_enabled = os.getenv("NOESIS_ENABLED", "true").lower() in ("true", "1", "yes")
        if not noesis_enabled:
            return errors  # Not enabled — nothing to validate

        llm_enabled = os.getenv("NOESIS_LLM_ENABLED", "false").lower() in ("true", "1", "yes")
        if llm_enabled:
            provider = os.getenv("NOESIS_LLM_PROVIDER", "anthropic").lower()
            if provider == "anthropic":
                if not os.getenv("ANTHROPIC_API_KEY", "").strip():
                    errors.append("ANTHROPIC_API_KEY must be set when NOESIS_LLM_ENABLED=true and NOESIS_LLM_PROVIDER=anthropic")
            elif provider == "openai":
                if not os.getenv("OPENAI_API_KEY", "").strip():
                    errors.append("OPENAI_API_KEY must be set when NOESIS_LLM_ENABLED=true and NOESIS_LLM_PROVIDER=openai")
            else:
                errors.append(f"Unknown NOESIS_LLM_PROVIDER '{provider}'. Supported: anthropic, openai")

        qpm = os.getenv("NOESIS_RATE_LIMIT_QPM", "60")
        try:
            if int(qpm) <= 0:
                errors.append(f"NOESIS_RATE_LIMIT_QPM must be a positive integer, got '{qpm}'")
        except ValueError:
            errors.append(f"NOESIS_RATE_LIMIT_QPM must be a positive integer, got '{qpm}'")

        daily = os.getenv("NOESIS_DAILY_QUOTA", "1000")
        try:
            if int(daily) <= 0:
                errors.append(f"NOESIS_DAILY_QUOTA must be a positive integer, got '{daily}'")
        except ValueError:
            errors.append(f"NOESIS_DAILY_QUOTA must be a positive integer, got '{daily}'")

        token_budget = os.getenv("NOESIS_PROVIDER_TOKEN_BUDGET", "100000")
        try:
            if int(token_budget) <= 0:
                errors.append(f"NOESIS_PROVIDER_TOKEN_BUDGET must be a positive integer, got '{token_budget}'")
        except ValueError:
            errors.append(f"NOESIS_PROVIDER_TOKEN_BUDGET must be a positive integer, got '{token_budget}'")

        return errors

    async def validate_with_connectivity(self) -> list[str]:
        """Validate config and also verify Redis is reachable."""
        errors = self.validate()
        if errors:
            return errors

        try:
            from shared.cache.cache import CacheClient
            cache = CacheClient()
            await cache.connect()
            reachable = await cache.health_check()
            await cache.close()
            if not reachable:
                errors.append("Redis is not reachable — Noesis rate limiting and token budget will not function")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Redis connectivity check failed: {exc}")

        return errors
