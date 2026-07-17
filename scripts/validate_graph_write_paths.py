#!/usr/bin/env python3
"""Graph write-path gate.

Historically material graph writes must route through the canonical mutation
gateway (PR 2 of the unified-platform program). Until every writer is
migrated, this gate freezes the blast radius: the committed allowlist
(``scripts/allowlists/graph_write_paths.json``) names every file that calls
``add_edge`` / ``upsert_vertex`` / ``add_vertex`` / ``revoke_edge`` directly
today. A NEW direct writer fails CI; a migrated writer must be removed from
the allowlist (shrink-only). When the gateway lands, the allowlist shrinks to
the gateway internals + the in-memory backend.

Usage:
  python scripts/validate_graph_write_paths.py           # validate (CI gate)
  python scripts/validate_graph_write_paths.py --seed    # rewrite allowlist
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
BACKEND = ROOT / "Backend Architecture" / "aether-backend"
ALLOWLIST = ROOT / "scripts" / "allowlists" / "graph_write_paths.json"

_WRITE_CALL = re.compile(r"\.(add_edge|upsert_vertex|add_vertex|revoke_edge)\s*\(")

# The graph client itself and (future) canonical gateway are the sanctioned owners.
_EXEMPT = (
    "shared/graph/graph.py",
    "shared/graph/mutation_gateway.py",
)


def scan() -> set[str]:
    offenders: set[str] = set()
    for base in (BACKEND / "services", BACKEND / "shared", BACKEND / "repositories"):
        for path in base.rglob("*.py"):
            rel = str(path.relative_to(ROOT))
            if any(rel.endswith(marker) or marker in rel for marker in _EXEMPT):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if _WRITE_CALL.search(text):
                offenders.add(rel)
    return offenders


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", action="store_true", help="rewrite the allowlist from current state")
    args = parser.parse_args()

    actual = scan()

    if args.seed:
        ALLOWLIST.parent.mkdir(parents=True, exist_ok=True)
        ALLOWLIST.write_text(json.dumps(sorted(actual), indent=2) + "\n")
        print(f"seeded graph write-path allowlist: {len(actual)} direct writers")
        return 0

    allowlist = set(json.loads(ALLOWLIST.read_text())) if ALLOWLIST.exists() else set()
    errors: list[str] = []
    for f in sorted(actual - allowlist):
        errors.append(f"NEW direct graph writer (use the mutation gateway): {f}")
    for f in sorted(allowlist - actual):
        errors.append(f"allowlist entry no longer writes directly — REMOVE it (shrink-only): {f}")

    if errors:
        print("GRAPH WRITE-PATH VIOLATIONS:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print(f"graph write paths OK: {len(actual)} direct writers frozen (gateway migration pending)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
