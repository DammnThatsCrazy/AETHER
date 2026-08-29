#!/usr/bin/env python3
"""
Aether Platform — Infrastructure Validation Script

Validates that all required infrastructure is reachable and configured.
Run after provisioning infrastructure, before deploying the application.

Usage:
    python scripts/validate_infra.py
    python scripts/validate_infra.py --env staging
    python scripts/validate_infra.py --env production

Profile-aware: which infra vars are REQUIRED is derived from the active
deployment profile's canonical backends (config/deployment_profiles.yaml), so a
staging or production-lean deploy — whose canonical profiles forbid msk,
elasticache, neptune and clickhouse — is NOT required to set Kafka, Redis or
Neptune connection vars. Only the connection vars for the backends the profile
actually declares are required.

Checks:
    1. Required env vars for the active profile's canonical backends
    2. Secrets present and non-default (JWT_SECRET, BYOK_ENCRYPTION_KEY, etc.)
    3. Connectivity for the backends the profile actually uses
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# ``python scripts/validate_infra.py`` puts ``scripts/`` (not the repository
# root) on ``sys.path``.  Add the root before importing the shared helpers so
# the documented invocation works in a clean runner as well as via ``-m``.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.preflight_env import PLACEHOLDER_SUBSTRINGS, REQUIRED_SECRET_VARS

# Values that are syntactically non-empty but are explicitly rejected by the
# backend outside local mode. Keep these here as well so infrastructure
# preflight cannot report a false green immediately before task startup.
KNOWN_INSECURE_DEFAULTS = frozenset({"aether-mesh-canary-seed"})


def _is_placeholder_or_insecure_default(value: str) -> bool:
    normalized = value.strip().lower()
    return (
        not normalized
        or normalized in KNOWN_INSECURE_DEFAULTS
        or any(marker in normalized for marker in PLACEHOLDER_SUBSTRINGS)
    )

# Backend dimension -> canonical backend value -> env vars that gate it.
# A profile that uses redis for cache must set REDIS_HOST; one that uses
# dynamodb must not (DynamoDB is reached through AWS SDK credentials, no host
# var). A profile whose event bus is sns_sqs must set SQS_QUEUE_URL, not
# KAFKA_BOOTSTRAP_SERVERS.
BACKEND_REQUIRED_VARS = {
    "database": {
        "postgres": ["DATABASE_URL"],
        "aurora_postgres": ["DATABASE_URL"],
    },
    "cache": {
        "redis": ["REDIS_HOST"],
        "dynamodb": [],
        "memory": [],
    },
    "event": {
        "kafka": ["KAFKA_BOOTSTRAP_SERVERS"],
        "sns_sqs": ["SQS_QUEUE_URL"],
        "memory": [],
        "localstack": [],
    },
    "graph": {
        "neptune": ["NEPTUNE_ENDPOINT"],
        "postgres": [],
    },
    "analytics": {
        "clickhouse": ["CLICKHOUSE_HOST"],
        "postgres": [],
    },
}

# AETHER_ENV -> default profile when DEPLOYMENT_PROFILE is not set.
ENV_DEFAULT_PROFILE = {
    "local": "local",
    "dev": "local-full",
    "integration": "local-full",
    "staging": "staging",
    "production": "production-lean",
}


def _profile() -> str:
    prof = os.getenv("DEPLOYMENT_PROFILE", "")
    if prof:
        return prof
    return ENV_DEFAULT_PROFILE.get(os.getenv("AETHER_ENV", "local").lower(), "local")


def _canonical_backends() -> dict[str, str] | None:
    """Backends for the active profile, or None if the profile is unknown."""
    try:
        import yaml

        data = yaml.safe_load(
            (ROOT / "config" / "deployment_profiles.yaml").read_text(encoding="utf-8")
        )
    except Exception:
        return None
    prof = (data.get("profiles") or {}).get(_profile())
    return (prof or {}).get("backends")


def _required_infra_vars() -> list[tuple[str, bool]]:
    """(var, required) pairs derived from the profile's canonical backends.

    Falls back to the legacy blanket rule (redis + kafka required in any
    non-local env) only when the profile is unknown — preserving prior
    behavior rather than silently skipping checks.
    """
    backends = _canonical_backends()
    if backends is None:
        env = os.getenv("AETHER_ENV", "local").lower()
        return [
            ("REDIS_HOST", env != "local"),
            ("KAFKA_BOOTSTRAP_SERVERS", env != "local"),
        ]
    pairs: list[tuple[str, bool]] = []
    for dim, backend in backends.items():
        for var in BACKEND_REQUIRED_VARS.get(dim, {}).get(backend, []):
            pairs.append((var, True))
    if backends.get("event") == "sns_sqs":
        # Fanout topic is optional; the queue URL is the required anchor.
        pairs.append(("SNS_TOPIC_ARN", False))
    return pairs


def check_env_var(name: str, required: bool = True) -> str | None:
    """Check if an environment variable is set."""
    value = os.getenv(name, "")
    if not value and required:
        print(f"  ✗ {name} — NOT SET (required)")
        return None
    elif not value:
        print(f"  ⚠ {name} — not set (optional)")
        return None
    else:
        # Mask secrets
        display = value[:8] + "..." if len(value) > 12 else "(set)"
        print(f"  ✓ {name} = {display}")
        return value


def check_postgres(url: str) -> bool:
    """Validate PostgreSQL connectivity."""
    try:
        import asyncio

        import asyncpg

        async def _check():
            conn = await asyncpg.connect(url, timeout=5)
            result = await conn.fetchval("SELECT 1")
            await conn.close()
            return result == 1

        return asyncio.run(_check())
    except ImportError:
        print("  ⚠ asyncpg not installed — cannot validate PostgreSQL")
        return False
    except Exception as e:
        print(f"  ✗ PostgreSQL connection failed: {e}")
        return False


def check_redis(host: str, port: str) -> bool:
    """Validate Redis connectivity."""
    try:
        import redis

        r = redis.Redis(host=host, port=int(port), socket_timeout=5)
        return r.ping()
    except ImportError:
        print("  ⚠ redis not installed — cannot validate Redis")
        return False
    except Exception as e:
        print(f"  ✗ Redis connection failed: {e}")
        return False


def check_kafka(bootstrap: str) -> bool:
    """Validate Kafka broker connectivity."""
    try:
        from kafka import KafkaAdminClient

        admin = KafkaAdminClient(bootstrap_servers=bootstrap, request_timeout_ms=5000)
        admin.list_topics()
        admin.close()
        return True
    except ImportError:
        print("  ⚠ kafka-python not installed — cannot validate Kafka")
        return False
    except Exception as e:
        print(f"  ✗ Kafka connection failed: {e}")
        return False


def main() -> None:
    env = os.getenv("AETHER_ENV", "local")
    profile = _profile()
    print(f"Aether Infrastructure Validation — {env} environment (profile: {profile})")
    print("=" * 60)

    errors = 0

    # 1. Required environment variables
    print("\n1. Environment Variables")
    vars_to_check: list[tuple[str, bool]] = [
        ("AETHER_ENV", True),
        ("DATABASE_URL", env != "local"),
        ("JWT_SECRET", True),
        ("BYOK_ENCRYPTION_KEY", env != "local"),
        ("WATERMARK_SECRET_KEY", env != "local"),
        ("CANARY_SECRET_SEED", env != "local"),
        ("ML_SERVING_URL", False),
    ]
    # Keep this list identical to the backend Settings() preflight.  A
    # deployment must not pass infrastructure validation and then fail during
    # application startup because a signing/canary secret was omitted here.
    vars_to_check.extend((name, env != "local") for name in REQUIRED_SECRET_VARS)
    vars_to_check += _required_infra_vars()
    # DATABASE_URL can come from both the base list and the profile's database
    # dimension; report each var once (True wins over False).
    by_name: dict[str, bool] = {}
    for name, required in vars_to_check:
        by_name[name] = by_name.get(name, False) or required
    vars_to_check = list(by_name.items())
    for name, required in vars_to_check:
        result = check_env_var(name, required=(required and env != "local"))
        if required and env != "local" and result is None:
            errors += 1

    # 2. Secret validation
    print("\n2. Secret Validation")
    jwt = os.getenv("JWT_SECRET", "")
    if _is_placeholder_or_insecure_default(jwt):
        print("  ✗ JWT_SECRET is default/empty — MUST be rotated")
        if env != "local":
            errors += 1
    else:
        print("  ✓ JWT_SECRET is set and non-default")

    byok = os.getenv("BYOK_ENCRYPTION_KEY", "")
    if byok:
        try:
            from cryptography.fernet import Fernet

            Fernet(byok.encode())
            print("  ✓ BYOK_ENCRYPTION_KEY is a valid Fernet key")
        except Exception:
            print("  ✗ BYOK_ENCRYPTION_KEY is not a valid Fernet key")
            errors += 1
    elif env != "local":
        print("  ✗ BYOK_ENCRYPTION_KEY not set (required)")
        errors += 1

    for name in REQUIRED_SECRET_VARS:
        value = os.getenv(name, "")
        if env != "local" and _is_placeholder_or_insecure_default(value):
            print(f"  ✗ {name} is missing or a placeholder — MUST be provisioned")
            errors += 1
        elif value:
            print(f"  ✓ {name} is set and non-placeholder")

    # 3. Infrastructure connectivity — only for the backends the profile
    #    actually declares (each block is guarded on the var being set).
    print("\n3. Infrastructure Connectivity")
    db_url = os.getenv("DATABASE_URL", "")
    if db_url:
        if check_postgres(db_url):
            print("  ✓ PostgreSQL — connected")
        else:
            errors += 1

    redis_host = os.getenv("REDIS_HOST", "")
    redis_port = os.getenv("REDIS_PORT", "6379")
    if redis_host:
        if check_redis(redis_host, redis_port):
            print("  ✓ Redis — connected")
        else:
            errors += 1

    kafka = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "")
    if kafka:
        if check_kafka(kafka):
            print("  ✓ Kafka — connected")
        else:
            errors += 1

    # Summary
    print("\n" + "=" * 60)
    if errors == 0:
        print(f"✓ All checks passed for {env} environment")
        sys.exit(0)
    else:
        print(f"✗ {errors} check(s) failed for {env} environment")
        sys.exit(1)


if __name__ == "__main__":
    main()
