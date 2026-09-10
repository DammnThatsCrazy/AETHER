#!/usr/bin/env python3
"""Validate the impact graph and all of its router/test-registry bindings."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.impact_graph import ImpactGraphConfigError, load_impact_graph  # noqa: E402


def main() -> int:
    try:
        graph = load_impact_graph()
    except (ImpactGraphConfigError, OSError, ValueError) as exc:
        print(json.dumps({"schema_version": 1, "status": "FAILED", "errors": [str(exc)]}, indent=2))
        return 1
    print(
        json.dumps(
            {
                "schema_version": graph.schema_version,
                "status": "PASS",
                "component_count": len(graph.components),
                "contract_count": len(graph.contracts),
                "deployable_count": len(graph.deployables),
                "edge_count": sum(len(targets) for targets in graph.edges.values()),
                "test_suite_count": len(graph.test_suites),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
