#!/usr/bin/env python3
"""Validate repository-owned telemetry event contracts without network access."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.telemetry import TelemetryContractError, load_registry  # noqa: E402


def main() -> int:
    try:
        registry = load_registry()
    except (TelemetryContractError, OSError, ValueError) as exc:
        print(json.dumps({"schema_version": 1, "status": "FAILED", "errors": [str(exc)]}, indent=2))
        return 1
    print(
        json.dumps(
            {
                "schema_version": registry.schema_version,
                "status": "PASS",
                "event_count": len(registry.events),
                "hosted_exporter": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
