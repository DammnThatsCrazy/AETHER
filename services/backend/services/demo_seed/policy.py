from __future__ import annotations

import os
from urllib.parse import urlsplit

from .errors import SeedPolicyError


def _database_url_is_loopback() -> bool:
    """True when DATABASE_URL is unset or points at a loopback host.

    An unset DATABASE_URL means the process uses in-memory repositories (the
    local/test default) — no shared database is being targeted. A unix-socket
    DSN has no hostname and is treated as local.
    """
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return True
    host = (urlsplit(url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1", ""}


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
    if env in {"local", "test"} and os.getenv("AETHER_ALLOW_NONLOCAL_DB", "").lower() != "1":
        if not _database_url_is_loopback():
            raise SeedPolicyError(
                "demo operations in local/test must target a loopback database "
                "(unset DATABASE_URL, or localhost/127.0.0.1/::1); refusing "
                f"{os.getenv('DATABASE_URL')!r} — set AETHER_ALLOW_NONLOCAL_DB=1 "
                "to explicitly allow a non-local database"
            )
