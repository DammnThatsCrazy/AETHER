#!/usr/bin/env python3
"""Aether Platform — AWS Secrets Manager Bootstrap

Pushes all generated secrets into AWS Secrets Manager under the
`aether/<environment>/` prefix, creating each secret if it doesn't
exist or updating it if it does.

Usage:
    # Push to staging
    python scripts/bootstrap_aws_secrets.py --env staging

    # Push to production
    python scripts/bootstrap_aws_secrets.py --env production

    # Read values from a local .env file instead of generating them
    python scripts/bootstrap_aws_secrets.py --env staging --from-env .env.production

    # Preview secret paths without writing (dry-run)
    python scripts/bootstrap_aws_secrets.py --env staging --dry-run

    # Set a single secret by name (useful for Stripe keys that come from the dashboard)
    python scripts/bootstrap_aws_secrets.py --env production \\
        --set STRIPE_SECRET_KEY=sk_live_xxx

Prerequisites:
    pip install boto3
    AWS credentials in environment or ~/.aws/credentials with access to:
      - secretsmanager:CreateSecret
      - secretsmanager:PutSecretValue
      - secretsmanager:DescribeSecret

Secret paths (stored as individual SecretString):
    aether/<env>/jwt-secret
    aether/<env>/byok-encryption-key
    aether/<env>/watermark-secret-key
    aether/<env>/canary-secret-seed
    aether/<env>/extraction-canary-seed
    aether/<env>/oracle-signer-private-key
    aether/<env>/grafana-admin-password
    aether/<env>/stripe-secret-key          (manual — from Stripe Dashboard)
    aether/<env>/stripe-webhook-secret      (manual — from Stripe Dashboard)
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path
from typing import Optional

# ── Secret name -> AWS Secrets Manager path ───────────────────────────────

_ENV_VAR_TO_SECRET_PATH: dict[str, str] = {
    "JWT_SECRET": "jwt-secret",
    "BYOK_ENCRYPTION_KEY": "byok-encryption-key",
    "WATERMARK_SECRET_KEY": "watermark-secret-key",
    "CANARY_SECRET_SEED": "canary-secret-seed",
    "EXTRACTION_CANARY_SEED": "extraction-canary-seed",
    "ORACLE_SIGNER_PRIVATE_KEY": "oracle-signer-private-key",
    "GRAFANA_ADMIN_PASSWORD": "grafana-admin-password",
    "STRIPE_SECRET_KEY": "stripe-secret-key",
    "STRIPE_WEBHOOK_SECRET": "stripe-webhook-secret",
    "STRIPE_PRICE_P1": "stripe-price-p1",
    "STRIPE_PRICE_P2": "stripe-price-p2",
    "STRIPE_PRICE_P3": "stripe-price-p3",
    "STRIPE_PRICE_P4": "stripe-price-p4",
}

# These are generated automatically; others must be supplied manually.
_AUTO_GENERATED = {
    "JWT_SECRET",
    "BYOK_ENCRYPTION_KEY",
    "WATERMARK_SECRET_KEY",
    "CANARY_SECRET_SEED",
    "EXTRACTION_CANARY_SEED",
    "ORACLE_SIGNER_PRIVATE_KEY",
    "GRAFANA_ADMIN_PASSWORD",
}


def _generate_fernet_key() -> str:
    try:
        from cryptography.fernet import Fernet
        return Fernet.generate_key().decode()
    except ImportError:
        import base64
        return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def _generate_eth_private_key() -> str:
    try:
        from eth_account import Account
        return Account.create().key.hex()
    except ImportError:
        return f"0x{secrets.token_hex(32)}"


def _generate_all() -> dict[str, str]:
    return {
        "JWT_SECRET": secrets.token_urlsafe(64),
        "BYOK_ENCRYPTION_KEY": _generate_fernet_key(),
        "WATERMARK_SECRET_KEY": secrets.token_urlsafe(32),
        "CANARY_SECRET_SEED": secrets.token_urlsafe(32),
        "EXTRACTION_CANARY_SEED": secrets.token_urlsafe(32),
        "ORACLE_SIGNER_PRIVATE_KEY": _generate_eth_private_key(),
        "GRAFANA_ADMIN_PASSWORD": secrets.token_urlsafe(24),
    }


def _load_env_file(path: str) -> dict[str, str]:
    result: dict[str, str] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            val = val.split(" #")[0].strip()
            result[key.strip()] = val
    return result


def _parse_set_args(set_args: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in set_args or []:
        if "=" not in item:
            print(f"ERROR: --set argument must be KEY=VALUE, got: {item!r}", file=sys.stderr)
            sys.exit(1)
        k, _, v = item.partition("=")
        result[k.strip()] = v
    return result


def _push_secret(
    client: object,
    secret_path: str,
    value: str,
    dry_run: bool,
    tags: list[dict],
) -> str:
    """Create or update a secret. Returns 'created', 'updated', or 'dry-run'."""
    if dry_run:
        return "dry-run"

    try:
        client.describe_secret(SecretId=secret_path)  # type: ignore[attr-defined]
        exists = True
    except client.exceptions.ResourceNotFoundException:  # type: ignore[attr-defined]
        exists = False

    if exists:
        client.put_secret_value(  # type: ignore[attr-defined]
            SecretId=secret_path,
            SecretString=value,
        )
        return "updated"
    else:
        client.create_secret(  # type: ignore[attr-defined]
            Name=secret_path,
            SecretString=value,
            Tags=tags,
        )
        return "created"


def run(
    env: str,
    from_env: Optional[str],
    set_overrides: dict[str, str],
    dry_run: bool,
    aws_region: Optional[str],
    skip_manual: bool,
) -> None:
    try:
        import boto3
    except ImportError:
        print("ERROR: boto3 is not installed. Run: pip install boto3", file=sys.stderr)
        sys.exit(1)

    region = aws_region or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    client = boto3.client("secretsmanager", region_name=region)

    # Build value map: generated + optional env-file overrides + CLI overrides
    values = _generate_all()
    if from_env:
        file_vals = _load_env_file(from_env)
        values.update(file_vals)
    values.update(set_overrides)

    tags = [
        {"Key": "Project", "Value": "aether"},
        {"Key": "Environment", "Value": env},
        {"Key": "ManagedBy", "Value": "bootstrap-script"},
    ]

    prefix = f"aether/{env}/"

    print(f"{'DRY-RUN: ' if dry_run else ''}Pushing secrets to AWS Secrets Manager")
    print(f"  Region : {region}")
    print(f"  Prefix : {prefix}")
    print(f"  Source : {'generated' if not from_env else from_env}")
    print()

    results: dict[str, str] = {}
    skipped: list[str] = []

    for env_var, path_suffix in _ENV_VAR_TO_SECRET_PATH.items():
        value = values.get(env_var, "")
        secret_path = f"{prefix}{path_suffix}"

        if not value:
            if env_var in _AUTO_GENERATED:
                # Should have been generated; something is wrong
                print(f"  WARN  {secret_path}  (no value — skipping)")
            else:
                if skip_manual:
                    skipped.append(env_var)
                    continue
                # Manual secret with no value — skip with notice
                skipped.append(env_var)
            continue

        action = _push_secret(client, secret_path, value, dry_run, tags)
        results[secret_path] = action
        symbol = {"created": "+", "updated": "~", "dry-run": "?"}.get(action, " ")
        print(f"  [{symbol}] {secret_path}  ({action})")

    print()
    if skipped:
        print("Skipped (no value configured — set manually):")
        for k in skipped:
            path = f"{prefix}{_ENV_VAR_TO_SECRET_PATH[k]}"
            print(f"  - {path}")
            if k.startswith("STRIPE_"):
                print(f"      Obtain from: https://dashboard.stripe.com")
        print()

    if not dry_run:
        pushed = len(results)
        print(f"Done. {pushed} secret(s) written to AWS Secrets Manager ({region}).")
        print()
        print("Next steps:")
        print("  1. Reference these secrets in your ECS task definition:")
        print(f"       {{\"name\": \"JWT_SECRET\", \"valueFrom\": \"arn:aws:secretsmanager:{region}:ACCOUNT:secret:{prefix}jwt-secret\"}}")
        print("  2. Grant your ECS task role:")
        print("       secretsmanager:GetSecretValue on the above ARNs")
        print("  3. Rotate secrets on a schedule with AWS Secrets Manager rotation.")
    else:
        print("Dry-run complete. Re-run without --dry-run to write to AWS.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bootstrap Aether secrets into AWS Secrets Manager.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--env", required=True,
        choices=["staging", "production"],
        help="Target environment (aether/<env>/ prefix in Secrets Manager).",
    )
    parser.add_argument(
        "--from-env", metavar="ENV_FILE",
        help="Read secret values from a local .env file instead of generating.",
    )
    parser.add_argument(
        "--set", dest="set_args", action="append", default=[], metavar="KEY=VALUE",
        help="Override or add a specific secret (can be repeated).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview paths without writing anything to AWS.",
    )
    parser.add_argument(
        "--region", metavar="AWS_REGION",
        help="AWS region (default: AWS_DEFAULT_REGION env var or us-east-1).",
    )
    parser.add_argument(
        "--skip-manual", action="store_true",
        help="Silently skip secrets that have no value (e.g. Stripe keys).",
    )
    args = parser.parse_args()

    set_overrides = _parse_set_args(args.set_args)
    run(
        env=args.env,
        from_env=args.from_env,
        set_overrides=set_overrides,
        dry_run=args.dry_run,
        aws_region=args.region,
        skip_manual=args.skip_manual,
    )


if __name__ == "__main__":
    main()
