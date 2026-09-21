#!/usr/bin/env python3
"""Aether Platform — AWS Secrets Manager Bootstrap

Pushes all generated secrets into AWS Secrets Manager under the
`aether/` prefix, matching the path format used by the Terraform
secrets module (modules/secrets/main.tf: name = "aether/${each.key}").
ECS task definitions reference secrets by this exact ARN, so the paths
must match — the environment is captured in resource tags, not the path.

Usage:
    # Push to staging
    python scripts/bootstrap_aws_secrets.py --env staging

    # Push to production
    python scripts/bootstrap_aws_secrets.py --env production

    # Read values from a local .env file instead of generating them
    python scripts/bootstrap_aws_secrets.py --env staging --from-env .env.production

    # Preview secret paths without writing (dry-run)
    python scripts/bootstrap_aws_secrets.py --env staging --dry-run

    # Set a single secret by name. Prefer --from-env for real values because
    # command-line arguments can be captured by shell history or process lists.
    python scripts/bootstrap_aws_secrets.py --env staging --from-env .env.staging

Prerequisites:
    pip install boto3
    AWS credentials in environment or ~/.aws/credentials with access to:
      - secretsmanager:CreateSecret
      - secretsmanager:PutSecretValue
      - secretsmanager:DescribeSecret

Security note:
    Do not paste secret values into chat or place them in command-line
    arguments. Use a local, permission-restricted env file or an interactive
    secure injection path, and remove the file after the write is verified.

Secret paths (stored as individual SecretString, matching Terraform):
    aether/jwt-secret
    aether/byok-encryption-key
    aether/watermark-secret-key
    aether/canary-secret-seed
    aether/extraction-canary-seed
    aether/oracle-signer-private-key
    aether/sdk-config-secret
    aether/first-admin-bootstrap-token (manual — one-time staging bootstrap)
    aether/stripe-secret-key          (manual — from Stripe Dashboard)
    aether/stripe-webhook-secret      (manual — from Stripe Dashboard)
    aether/stripe-price-{alpha,beta,gamma,delta,epsilon,omicron,omega}
                                      (manual — from Stripe Dashboard)
    aether/kyber-google-client-id     (manual — from Google Cloud OAuth)
    aether/kyber-google-client-secret (manual — from Google Cloud OAuth)
"""

from __future__ import annotations

import argparse
import os
import re
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
    "SDK_CONFIG_SECRET": "sdk-config-secret",
    "ORACLE_SIGNER_PRIVATE_KEY": "oracle-signer-private-key",
    "FIRST_ADMIN_BOOTSTRAP_TOKEN": "first-admin-bootstrap-token",
    "STRIPE_SECRET_KEY": "stripe-secret-key",
    "STRIPE_WEBHOOK_SECRET": "stripe-webhook-secret",
    "STRIPE_PRICE_ALPHA": "stripe-price-alpha",
    "STRIPE_PRICE_BETA": "stripe-price-beta",
    "STRIPE_PRICE_GAMMA": "stripe-price-gamma",
    "STRIPE_PRICE_DELTA": "stripe-price-delta",
    "STRIPE_PRICE_EPSILON": "stripe-price-epsilon",
    "STRIPE_PRICE_OMICRON": "stripe-price-omicron",
    "STRIPE_PRICE_OMEGA": "stripe-price-omega",
    "KYBER_GOOGLE_CLIENT_ID": "kyber-google-client-id",
    "KYBER_GOOGLE_CLIENT_SECRET": "kyber-google-client-secret",
}

# These are generated automatically; others must be supplied manually.
_AUTO_GENERATED = {
    "JWT_SECRET",
    "BYOK_ENCRYPTION_KEY",
    "WATERMARK_SECRET_KEY",
    "CANARY_SECRET_SEED",
    "EXTRACTION_CANARY_SEED",
    "SDK_CONFIG_SECRET",
    "ORACLE_SIGNER_PRIVATE_KEY",
}

_STRIPE_PRICE_ENV_VARS = (
    "STRIPE_PRICE_ALPHA",
    "STRIPE_PRICE_BETA",
    "STRIPE_PRICE_GAMMA",
    "STRIPE_PRICE_DELTA",
    "STRIPE_PRICE_EPSILON",
    "STRIPE_PRICE_OMICRON",
    "STRIPE_PRICE_OMEGA",
)
_STRIPE_PRICE_RE = re.compile(r"^price_[A-Za-z0-9]+$")
_STRIPE_PRICE_PLACEHOLDERS = {
    "price_alpha",
    "price_beta",
    "price_gamma",
    "price_delta",
    "price_epsilon",
    "price_omicron",
    "price_omega",
    "price_placeholder",
    "price_example",
    "price_test",
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
        "SDK_CONFIG_SECRET": secrets.token_urlsafe(48),
        "ORACLE_SIGNER_PRIVATE_KEY": _generate_eth_private_key(),
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


def _validate_manual_values(values: dict[str, str]) -> None:
    """Validate provider identifiers before any Secrets Manager write.

    The value itself is never printed. Keeping this check at the secure write
    boundary lets CI prove only metadata while ensuring this bootstrap path
    cannot store a made-up price identifier.
    """
    invalid = [
        name
        for name in _STRIPE_PRICE_ENV_VARS
        if values.get(name)
        and (
            not _STRIPE_PRICE_RE.fullmatch(values[name])
            or values[name] in _STRIPE_PRICE_PLACEHOLDERS
        )
    ]
    if invalid:
        raise SystemExit(
            "ERROR: Stripe price IDs must be real price_... identifiers; "
            f"invalid fields: {', '.join(invalid)}"
        )


def _push_secret(
    client: object,
    secret_path: str,
    value: str,
    dry_run: bool,
    tags: list[dict],
    kms_key_id: str,
    *,
    preserve_existing: bool = False,
) -> str:
    """Create/update a secret without accidental generated-secret rotation."""
    if dry_run:
        return "dry-run"

    try:
        metadata = client.describe_secret(SecretId=secret_path)  # type: ignore[attr-defined]
        exists = True
    except client.exceptions.ResourceNotFoundException:  # type: ignore[attr-defined]
        metadata = {}
        exists = False

    if exists:
        if metadata.get("DeletedDate") is not None:
            raise SystemExit(
                f"ERROR: {secret_path} is pending deletion; restore it before bootstrap"
            )
        versions = metadata.get("VersionIdsToStages") or {}
        has_current = any(
            "AWSCURRENT" in (stages or []) for stages in versions.values()
        )
        if preserve_existing and has_current:
            return "preserved"
        client.put_secret_value(  # type: ignore[attr-defined]
            SecretId=secret_path,
            SecretString=value,
        )
        return "updated"
    else:
        client.create_secret(  # type: ignore[attr-defined]
            Name=secret_path,
            SecretString=value,
            KmsKeyId=kms_key_id,
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
    kms_key_id: Optional[str],
    rotate_generated: bool = False,
) -> None:
    try:
        import boto3
    except ImportError:
        print("ERROR: boto3 is not installed. Run: pip install boto3", file=sys.stderr)
        sys.exit(1)

    region = aws_region or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    effective_kms_key_id = kms_key_id or f"alias/aether-{env}-secrets"
    # A dry-run is intentionally credential-free: it enumerates the exact
    # write targets without constructing an AWS client or touching the network.
    client = None if dry_run else boto3.client("secretsmanager", region_name=region)

    # Build value map: generated + optional env-file overrides + CLI overrides.
    # Generated values are intentionally not treated as rotation requests. A
    # plain bootstrap invocation must be safe to re-run while adding a manual
    # provider value; otherwise it would silently replace the live JWT/BYOK/
    # signing material on every invocation.
    values = _generate_all()
    explicit_values: set[str] = set()
    if from_env:
        file_vals = _load_env_file(from_env)
        values.update(file_vals)
        explicit_values.update(file_vals)
    explicit_values.update(set_overrides)
    values.update(set_overrides)
    _validate_manual_values(values)

    tags = [
        {"Key": "Project", "Value": "aether"},
        {"Key": "Environment", "Value": env},
        {"Key": "ManagedBy", "Value": "bootstrap-script"},
    ]

    prefix = "aether/"

    print(f"{'DRY-RUN: ' if dry_run else ''}Pushing secrets to AWS Secrets Manager")
    print(f"  Region : {region}")
    print(f"  Env tag: {env}")
    print(f"  Prefix : {prefix}  (matches Terraform: aether/<name>)")
    print(f"  KMS    : {effective_kms_key_id}  (matches Terraform secret CMK)")
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

        action = _push_secret(
            client,
            secret_path,
            value,
            dry_run,
            tags,
            effective_kms_key_id,
            preserve_existing=(
                env_var in _AUTO_GENERATED
                and env_var not in explicit_values
                and not rotate_generated
            ),
        )
        if action != "preserved":
            results[secret_path] = action
        symbol = {
            "created": "+",
            "updated": "~",
            "preserved": "=",
            "dry-run": "?",
        }.get(action, " ")
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
        help="Target environment (resources use the aether/ prefix and an Environment tag).",
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
        "--kms-key-id",
        metavar="KMS_KEY_ID",
        help="KMS key ARN or alias for newly created secrets (default: alias/aether-<env>-secrets).",
    )
    parser.add_argument(
        "--skip-manual", action="store_true",
        help="Silently skip secrets that have no value (e.g. Stripe keys).",
    )
    parser.add_argument(
        "--rotate-generated", action="store_true",
        help="Explicitly rotate existing auto-generated secrets; default bootstrap preserves them.",
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
        kms_key_id=args.kms_key_id,
        rotate_generated=args.rotate_generated,
    )


if __name__ == "__main__":
    main()
