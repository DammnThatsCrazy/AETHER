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


def ecs_service_name(cluster_or_prefix: str, key: str) -> str:
    """``AETHER-staging`` + ``access-mcp`` -> ``AETHER-staging-access-mcp``."""
    return f"{cluster_or_prefix}-{key}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="staging")
    parser.add_argument("--cluster", required=True, help="ECS cluster / name prefix, e.g. AETHER-staging")
    args = parser.parse_args(argv)
    try:
        services = enabled_customer_services(args.profile)
    except ValueError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    for key in sorted(services):
        print(ecs_service_name(args.cluster, key))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
