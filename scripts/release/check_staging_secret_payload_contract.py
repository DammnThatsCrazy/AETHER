#!/usr/bin/env python3
"""Fail closed when an ECS-injected staging secret is not a raw value.

ECS ``valueFrom`` mounts the complete Secrets Manager ``SecretString``.  A
JSON-wrapped value therefore reaches the application as JSON text unless the
task definition uses a JSON-key suffix, which this repository intentionally
does not do. This checker reads the selected secret payloads only long enough
to validate their shape and staging prefixes; it never prints, logs, or
returns secret values. Workflows assume the dedicated read-only secret
preflight role for this step; lifecycle and Terraform apply roles remain
value-blind.

Examples:

  python scripts/release/check_staging_secret_payload_contract.py --lane pilot
  python scripts/release/check_staging_secret_payload_contract.py --lane full
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from typing import Any, Callable


REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
BASE_SECRETS = (
    "jwt-secret",
    "byok-encryption-key",
    "stripe-secret-key",
    "stripe-webhook-secret",
    "oracle-signer-private-key",
    "watermark-secret-key",
    "canary-secret-seed",
    "extraction-canary-seed",
    "sdk-config-secret",
    "first-admin-bootstrap-token",
    "jwt-secret-previous",
    "byok-encryption-key-previous",
)
PILOT_PRICE_SECRETS = (
    "stripe-price-alpha",
    "stripe-price-beta",
    "stripe-price-gamma",
    "stripe-price-delta",
)
FULL_ONLY_SECRETS = (
    "kyber-google-client-id",
    "kyber-google-client-secret",
)
Runner = Callable[..., subprocess.CompletedProcess[str]]


def required_secret_names(lane: str) -> tuple[str, ...]:
    if lane == "pilot":
        return BASE_SECRETS + PILOT_PRICE_SECRETS
    if lane == "full":
        return BASE_SECRETS + FULL_ONLY_SECRETS
    raise ValueError(f"deployment lane must be pilot or full, got {lane!r}")


def _secret_value(
    name: str,
    *,
    region: str,
    runner: Runner,
) -> tuple[str | None, str | None]:
    result = runner(
        [
            "aws",
            "secretsmanager",
            "get-secret-value",
            "--region",
            region,
            "--secret-id",
            f"aether/{name}",
            "--output",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None, f"aether/{name} could not be read from Secrets Manager"
    try:
        payload: Any = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, f"aether/{name} returned malformed Secrets Manager metadata"
    if not isinstance(payload, Mapping):
        return None, f"aether/{name} returned malformed Secrets Manager metadata"
    value = payload.get("SecretString")
    if not isinstance(value, str) or not value:
        return None, f"aether/{name} must have a non-empty SecretString"
    try:
        json.loads(value)
    except json.JSONDecodeError:
        return value, None
    # ECS injects the bytes stored in SecretString verbatim. A successful JSON
    # decode therefore means the secret was stored as a JSON object, array, or
    # scalar wrapper rather than as the raw credential the task expects. This
    # also rejects quoted strings (which would otherwise mount with quotes).
    return None, f"aether/{name} is JSON-encoded; ECS requires a raw secret string"


def payload_errors(
    *,
    lane: str,
    region: str = REGION,
    runner: Runner = subprocess.run,
) -> list[str]:
    """Return safe, value-free errors for the selected lane's secret payloads."""
    try:
        names = required_secret_names(lane)
    except ValueError as exc:
        return [str(exc)]

    errors: list[str] = []
    values: dict[str, str] = {}
    for name in names:
        value, error = _secret_value(name, region=region, runner=runner)
        if error:
            errors.append(error)
        elif value is not None:
            values[name] = value

    if (value := values.get("stripe-secret-key")) and not value.startswith("sk_test_"):
        errors.append("aether/stripe-secret-key must use a Stripe test key in staging")
    if (value := values.get("stripe-webhook-secret")) and not value.startswith("whsec_"):
        errors.append("aether/stripe-webhook-secret must use a Stripe webhook signing secret")
    for name in PILOT_PRICE_SECRETS:
        value = values.get(name)
        if value and not value.startswith("price_"):
            errors.append(f"aether/{name} must contain a Stripe Price ID")

    return sorted(set(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lane", choices=("full", "pilot"), required=True)
    parser.add_argument("--region", default=REGION)
    args = parser.parse_args(argv)
    errors = payload_errors(lane=args.lane, region=args.region)
    if errors:
        print("staging secret payload contract FAILED:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"staging secret payload contract valid: lane={args.lane}; values were not printed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
