#!/usr/bin/env python3
"""Validate the canonical change-aware verification router registry."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.verification_router import load_router_registry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config" / "verification_router.yaml",
        help="router YAML path (defaults to the canonical registry)",
    )
    args = parser.parse_args()
    try:
        registry = load_router_registry(args.config)
    except (OSError, ValueError) as exc:
        print(json.dumps({"schema_version": 1, "status": "FAILED", "errors": [str(exc)]}, indent=2))
        return 1
    print(
        json.dumps(
            {
                "schema_version": registry.schema_version,
                "status": "PASS",
                "default_lane": registry.default_lane,
                "lanes": list(registry.lanes),
                "check_count": len(registry.checks),
                "domain_count": len(registry.domains),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
