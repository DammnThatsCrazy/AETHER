from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

from .manifest import DEFAULT_NAMESPACE
from .service import DemoSeedService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m services.demo_seed.cli",
        description="Explicit backend-owned demonstration dataset management",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("seed", "status", "verify", "reset"):
        item = sub.add_parser(command)
        item.add_argument("--tenant", required=True, dest="tenant_id")
        item.add_argument("--namespace", default=DEFAULT_NAMESPACE)
        if command == "reset":
            item.add_argument(
                "--confirm",
                required=True,
                help='must exactly equal "RESET <tenant> <namespace>"',
            )
    return parser


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    service = DemoSeedService(environment=os.getenv("AETHER_ENV"))
    common = {"tenant_id": args.tenant_id, "namespace": args.namespace}
    if args.command == "seed":
        return (await service.seed(**common, actor="demo-seed-cli")).to_dict()
    if args.command == "status":
        return await service.status(**common)
    if args.command == "verify":
        return await service.verify(**common)
    if args.command == "reset":
        return await service.reset(
            **common, confirmation=args.confirm, actor="demo-reset-cli",
        )
    raise AssertionError(args.command)


def main() -> None:
    args = _parser().parse_args()
    print(json.dumps(asyncio.run(_run(args)), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
