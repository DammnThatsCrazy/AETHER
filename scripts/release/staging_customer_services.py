#!/usr/bin/env python3
"""Customer-facing staging services outside the worker matrix.

``config/runtime_deployment.yaml`` declares them per profile under
``customer_services`` (today only the Access Kit MCP service). The staging
lifecycle adds an enabled entry to its exact ECS inventory with a fixed desired
count multiplied by ``staging_state`` and **no** autoscaling target, so nothing
can scale it back out while staging sleeps. Terraform's ``enable_access_mcp``
must equal the ``enabled`` flag (an output precondition enforces it).

The lifecycle workflow imports :func:`enabled_customer_services`; the CLI prints
one ECS service name per line for shell steps that build an expected list.
Every staging planner (lifecycle wake/sleep, pilot plan, remote CI plan) passes
the declared MCP state through ``--promote-inputs`` or ``--terraform-vars``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

RUNTIME_DEPLOYMENT = Path(__file__).resolve().parents[2] / "config" / "runtime_deployment.yaml"
# ECS service-name suffix per customer service key; must match
# infra/aws/terraform/modules/access_mcp (staging names `AETHER-staging-access-mcp`).
KNOWN_CUSTOMER_SERVICES = frozenset({"access-mcp"})


def _load(path: Path = RUNTIME_DEPLOYMENT) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def enabled_customer_services(
    profile: str, runtime: dict[str, Any] | None = None,
) -> dict[str, int]:
    """Return ``{service_key: awake_desired_count}`` for enabled customer services.

    Raises ``ValueError`` for an unknown key or a malformed entry so a lifecycle
    step fails closed instead of silently dropping a service from its inventory.
    """
    data = runtime if runtime is not None else _load()
    pcfg = (data.get("profiles") or {}).get(profile) or {}
    declared = pcfg.get("customer_services") or {}
    if not isinstance(declared, dict):
        raise ValueError(f"profiles.{profile}.customer_services must be a mapping")
    enabled: dict[str, int] = {}
    for key, cfg in declared.items():
        if key not in KNOWN_CUSTOMER_SERVICES:
            raise ValueError(f"unknown customer service {key!r} in profile {profile}")
        if not isinstance(cfg, dict) or not isinstance(cfg.get("enabled"), bool):
            raise ValueError(f"customer service {key} needs a boolean 'enabled'")
        desired = cfg.get("desired_count")
        if not isinstance(desired, int) or isinstance(desired, bool) or not 1 <= desired <= 4:
            raise ValueError(f"customer service {key} desired_count must be an integer 1-4")
        if "autoscaling" in cfg:
            raise ValueError(
                f"customer service {key} must not declare autoscaling; staging sleep "
                "relies on it having no scaling target"
            )
        if cfg["enabled"]:
            enabled[key] = desired
    return enabled


_DIGEST_PREFIX = "sha256:"


def access_mcp_promote_inputs(
    profile: str, runtime: dict[str, Any] | None = None,
) -> list[tuple[str, str]]:
    """Promotion-workflow inputs that reproduce the declared staging MCP state.

    The lifecycle's wake and sleep plans pass these so an enabled (or merely
    provisioned) MCP repository and service survive every plan instead of
    failing Terraform's agreement precondition or being planned away.
    """
    data = runtime if runtime is not None else _load()
    entry = (((data.get("profiles") or {}).get(profile) or {}).get("customer_services") or {}).get(
        "access-mcp"
    ) or {}
    enabled = bool(entry.get("enabled", False))
    repository = bool(entry.get("repository", False))
    digest = str(entry.get("image_digest") or "")
    oauth = bool(entry.get("oauth", False))
    dcr = bool(entry.get("dcr", False))
    for name in ("enabled", "repository", "oauth", "dcr"):
        if name in entry and not isinstance(entry[name], bool):
            raise ValueError(f"customer service access-mcp {name} must be a boolean")
    if digest and not (
        digest.startswith(_DIGEST_PREFIX)
        and len(digest) == len(_DIGEST_PREFIX) + 64
        and all(c in "0123456789abcdef" for c in digest[len(_DIGEST_PREFIX):])
    ):
        raise ValueError("customer service access-mcp image_digest must be an immutable sha256 digest")
    if enabled and not (repository and digest):
        raise ValueError("access-mcp enabled requires repository: true and an image_digest")
    if oauth and not enabled:
        raise ValueError("access-mcp oauth requires enabled: true")
    if dcr and not oauth:
        raise ValueError("access-mcp dcr requires oauth: true")
    flag = lambda value: "true" if value else "false"  # noqa: E731
    return [
        ("enable_access_mcp_repository", flag(repository)),
        ("enable_access_mcp", flag(enabled)),
        ("enable_access_mcp_oauth", flag(oauth)),
        ("enable_access_mcp_dcr", flag(dcr)),
        ("access_mcp_image_digest", digest),
    ]


def ecs_service_name(cluster_or_prefix: str, key: str) -> str:
    """``AETHER-staging`` + ``access-mcp`` -> ``AETHER-staging-access-mcp``."""
    return f"{cluster_or_prefix}-{key}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="staging")
    parser.add_argument("--cluster", help="ECS cluster / name prefix, e.g. AETHER-staging")
    parser.add_argument(
        "--promote-inputs", action="store_true",
        help="print `-f name=value` workflow inputs, one token per line, for the staging MCP state",
    )
    parser.add_argument(
        "--terraform-vars", action="store_true",
        help="print `-var=name=value` Terraform arguments, one per line, for the staging MCP state",
    )
    args = parser.parse_args(argv)
    try:
        if args.promote_inputs:
            for name, value in access_mcp_promote_inputs(args.profile):
                print("-f")
                print(f"{name}={value}")
            return 0
        if args.terraform_vars:
            for name, value in access_mcp_promote_inputs(args.profile):
                print(f"-var={name}={value}")
            return 0
        if not args.cluster:
            parser.error("--cluster is required unless --promote-inputs or --terraform-vars is given")
        services = enabled_customer_services(args.profile)
    except ValueError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    for key in sorted(services):
        print(ecs_service_name(args.cluster, key))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
