#!/usr/bin/env python3
"""Validate the explicit CI performance policy without making SLO claims."""

from __future__ import annotations

import json
import sys

ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.ci_performance import PerformancePolicyError, load_policy  # noqa: E402


def main() -> int:
    try:
        policy = load_policy()
    except (PerformancePolicyError, OSError, ValueError) as exc:
        print(json.dumps({"schema_version": 1, "status": "FAILED", "errors": [str(exc)]}, indent=2))
        return 1
    print(json.dumps({
        "schema_version": 1,
        "status": "PASS",
        "sample_threshold": policy["sample_threshold"],
        "stages": sorted(policy["stages"]),
        "pr_classes": sorted(policy["pr_classes"]),
        "claims_require_samples": policy["sample_threshold"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
