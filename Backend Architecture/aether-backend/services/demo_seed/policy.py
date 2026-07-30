from __future__ import annotations

import os


class SeedPolicyError(RuntimeError):
    pass


def assert_seed_allowed(*, environment: str, tenant_id: str) -> None:
    env = environment.strip().lower()
    if env == "production":
        raise SeedPolicyError("demo seed and reset operations are disabled in production")
    if env == "staging":
        enabled = os.getenv("AETHER_STAGING_DEMO_ENABLED", "").lower() == "true"
        allowlist = {
            value.strip()
            for value in os.getenv("AETHER_STAGING_DEMO_TENANT_ALLOWLIST", "").split(",")
            if value.strip()
        }
        if not enabled or tenant_id not in allowlist:
            raise SeedPolicyError(
                "staging demo operations require AETHER_STAGING_DEMO_ENABLED=true "
                "and an allowlisted tenant"
            )
    if env not in {"local", "test", "staging"}:
        raise SeedPolicyError(f"unsupported AETHER_ENV for demo operations: {environment!r}")
