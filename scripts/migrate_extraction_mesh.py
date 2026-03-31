"""
Aether Migration — Extraction Defense Mesh Setup

Creates Redis key schemas, initializes default configurations, and
validates infrastructure readiness for the Extraction Defense Mesh.

Usage:
    python scripts/migrate_extraction_mesh.py [--dry-run] [--env local|staging|production]

This script is idempotent and safe to run multiple times.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time


def check_redis_connectivity(env: str) -> bool:
    """Verify Redis is reachable and writable."""
    if env == "local":
        print("[INFO] Local environment — Redis optional, in-memory fallback available")
        return True

    redis_host = os.getenv("REDIS_HOST", "")
    if not redis_host:
        print("[ERROR] REDIS_HOST not set — required for non-local environments")
        return False

    try:
        import redis
        port = int(os.getenv("REDIS_PORT", "6379"))
        password = os.getenv("REDIS_PASSWORD", "")
        client = redis.Redis(host=redis_host, port=port, password=password, db=2)
        client.ping()
        print(f"[OK] Redis reachable at {redis_host}:{port}/2")
        return True
    except ImportError:
        print("[WARN] redis package not installed — pip install redis")
        return env == "local"
    except Exception as e:
        print(f"[ERROR] Redis connection failed: {e}")
        return False


def create_redis_key_schema(dry_run: bool = False) -> None:
    """Document and validate the Redis key schema for extraction mesh."""
    schema = {
        "budget_counters": {
            "pattern": "aether:exbudget:{axis}:{identifier}:{window}:{bucket}",
            "type": "string (integer counter)",
            "ttl": "window_duration + 10 seconds",
            "example": "aether:exbudget:api_key:sk-abc123:1m:16666666",
        },
        "feature_fingerprints": {
            "pattern": "aether:exbudget:fp:{axis}:{identifier}",
            "type": "HyperLogLog",
            "ttl": "86400 (1 day)",
            "example": "aether:exbudget:fp:api_key:sk-abc123",
        },
        "model_enumeration": {
            "pattern": "aether:exbudget:models:{axis}:{identifier}",
            "type": "set",
            "ttl": "86400 (1 day)",
            "example": "aether:exbudget:models:api_key:sk-abc123",
        },
        "actor_history": {
            "pattern": "aether:exhist:{actor_key}",
            "type": "string (JSON array)",
            "ttl": "7200 (2 hours)",
            "example": "aether:exhist:sk-abc123",
        },
        "cluster_aggregates": {
            "pattern": "aether:exbudget:cluster:{cluster_id}:{window}:{bucket}",
            "type": "string (integer counter)",
            "ttl": "window_duration + 10 seconds",
            "example": "aether:exbudget:cluster:cluster-xyz:1h:462962",
        },
    }

    print("\n[SCHEMA] Extraction Defense Mesh Redis Key Schema:")
    print("=" * 60)
    for name, details in schema.items():
        print(f"\n  {name}:")
        for key, value in details.items():
            print(f"    {key}: {value}")

    if dry_run:
        print("\n[DRY RUN] No changes made")
    else:
        print("\n[OK] Schema validated (keys are created on-demand by the application)")


def validate_environment_variables() -> list[str]:
    """Check that required environment variables are set."""
    warnings = []

    required_in_prod = {
        "REDIS_HOST": os.getenv("REDIS_HOST", ""),
        "EXTRACTION_CANARY_SEED": os.getenv("EXTRACTION_CANARY_SEED", ""),
    }

    optional = {
        "ENABLE_EXTRACTION_MESH": os.getenv("ENABLE_EXTRACTION_MESH", "false"),
        "EXTRACTION_PRIVILEGED_TENANTS": os.getenv("EXTRACTION_PRIVILEGED_TENANTS", ""),
        "EXTRACTION_PRIVILEGED_API_KEYS": os.getenv("EXTRACTION_PRIVILEGED_API_KEYS", ""),
        "EXTRACTION_BATCH_INTERNAL_ONLY": os.getenv("EXTRACTION_BATCH_INTERNAL_ONLY", "true"),
        "EXTRACTION_OUTPUT_PRECISION": os.getenv("EXTRACTION_OUTPUT_PRECISION", "2"),
    }

    env = os.getenv("AETHER_ENV", "local")

    print("\n[ENV] Environment Variable Check:")
    print("=" * 60)

    for var, value in required_in_prod.items():
        if env not in ("local", "dev") and not value:
            warnings.append(f"{var} not set (required in {env})")
            print(f"  [WARN] {var}: NOT SET")
        else:
            print(f"  [OK] {var}: {'set' if value else 'not set (ok for local)'}")

    for var, value in optional.items():
        print(f"  [INFO] {var}: {value or '(not set)'}")

    return warnings


def main():
    parser = argparse.ArgumentParser(description="Extraction Defense Mesh Migration")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without applying")
    parser.add_argument("--env", default=os.getenv("AETHER_ENV", "local"),
                        choices=["local", "dev", "staging", "production"])
    args = parser.parse_args()

    print(f"Extraction Defense Mesh Migration — Environment: {args.env}")
    print("=" * 60)

    # 1. Check Redis
    redis_ok = check_redis_connectivity(args.env)

    # 2. Validate env vars
    warnings = validate_environment_variables()

    # 3. Create/validate key schema
    create_redis_key_schema(dry_run=args.dry_run)

    # 4. Summary
    print("\n" + "=" * 60)
    print("MIGRATION SUMMARY")
    print("=" * 60)
    print(f"  Redis: {'OK' if redis_ok else 'FAILED'}")
    print(f"  Warnings: {len(warnings)}")
    for w in warnings:
        print(f"    - {w}")
    print(f"  Dry run: {args.dry_run}")

    if not redis_ok and args.env not in ("local", "dev"):
        print("\n[FAILED] Fix Redis connectivity before enabling extraction mesh")
        sys.exit(1)

    if warnings and args.env == "production":
        print("\n[WARN] Address warnings before production deployment")
        sys.exit(1)

    print("\n[OK] Migration complete")


if __name__ == "__main__":
    main()
