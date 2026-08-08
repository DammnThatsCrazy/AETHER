#!/usr/bin/env python3
"""Generate ``docs/_generated/reward-rail-matrix.json`` from source.

Canonical source: ``services/rewards/rail_matrix.py::build_rail_matrix()`` —
every reward rail's tier (production / sandbox / explicit_beta /
intentionally_unsupported), delivery mode, custody boundary, and external
action. Deterministic + timestamp-free so the CI extract-docs-drift gate
re-runs the generator and fails on any uncommitted change.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
OUTPUT = ROOT / "docs" / "_generated" / "reward-rail-matrix.json"


def read_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return m.group(1) if m else "0.0.0"


def main() -> int:
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    try:
        from services.rewards.rail_matrix import build_rail_matrix
    except Exception as exc:  # pragma: no cover — surfaces a real wiring break
        print(f"error: could not import reward rail matrix: {exc}", file=sys.stderr)
        return 1

    payload = {
        "version": read_version(),
        "generated_from": "Backend Architecture/aether-backend/services/rewards/rail_matrix.py",
        **build_rail_matrix(),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = payload.get("summary", {})
    print(
        f"extract_reward_rail_matrix: wrote {OUTPUT.relative_to(ROOT)} "
        f"({summary.get('total')} rails; by_tier={summary.get('by_tier')})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
