#!/usr/bin/env python3
"""Require populated identity verification key secrets without reading values."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Callable, Mapping


SECRET_NAMES = (
    "identity-verification-token-key-previous",
    "identity-verification-token-key",
)
Runner = Callable[..., subprocess.CompletedProcess[str]]


def _has_current_version(metadata: Mapping[str, object]) -> bool:
    if metadata.get("DeletedDate") is not None:
        return False
    versions = metadata.get("VersionIdsToStages") or {}
    if not isinstance(versions, Mapping):
        return False
    return any(
        isinstance(stages, list) and "AWSCURRENT" in stages
        for stages in versions.values()
    )


def secret_errors(
    *, prefix: str = "aether/", runner: Runner = subprocess.run
) -> list[str]:
    """Check Secrets Manager metadata only; never request a secret value."""
    errors: list[str] = []
    for name in SECRET_NAMES:
        result = runner(
            [
                "aws",
                "secretsmanager",
                "describe-secret",
                "--secret-id",
                f"{prefix}{name}",
                "--output",
                "json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            errors.append(f"required secret {prefix}{name} is missing or unreadable")
            continue
        try:
            metadata = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            errors.append(f"required secret {prefix}{name} returned invalid metadata")
            continue
        if not isinstance(metadata, Mapping) or not _has_current_version(metadata):
            errors.append(f"required secret {prefix}{name} has no usable AWSCURRENT version")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default="aether/", help="Secrets Manager name prefix.")
    args = parser.parse_args(argv)
    errors = secret_errors(prefix=args.prefix)
    if errors:
        print("::error::identity verification secrets are not ready:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("identity verification secrets have AWSCURRENT versions; secret values were not read")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
