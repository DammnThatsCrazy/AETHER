#!/usr/bin/env python3
"""Validate that TypeScript events.ts and Python generated_registry.py are in sync with
the canonical event-registry.json.

Exits 0 on success, 1 on drift.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

REGISTRY_JSON = ROOT / "packages" / "shared" / "contracts" / "event-registry.json"
TS_SOURCE = ROOT / "packages" / "shared" / "events.ts"
PY_SOURCE = (
    ROOT
    / "Backend Architecture"
    / "aether-backend"
    / "services"
    / "ingestion"
    / "generated_registry.py"
)


def load_registry_types() -> set[str]:
    data = json.loads(REGISTRY_JSON.read_text())
    return {e["type"] for e in data["events"]}


def extract_ts_event_types(path: Path) -> set[str]:
    text = path.read_text()
    match = re.search(r"export type EventType\s*=(.*?)\s*;", text, re.DOTALL)
    if not match:
        print(f"ERROR: Could not find EventType union in {path}", file=sys.stderr)
        sys.exit(1)
    block = match.group(1)
    return {m.strip("'\" ") for m in re.findall(r"'([a-z0-9_]+)'", block)}


def extract_py_event_types(path: Path) -> set[str]:
    text = path.read_text()
    match = re.search(
        r"CANONICAL_EVENT_TYPES\s*:\s*frozenset\[str\]\s*=\s*frozenset\(\{(.*?)\}\)",
        text,
        re.DOTALL,
    )
    if not match:
        print(f"ERROR: Could not find CANONICAL_EVENT_TYPES frozenset in {path}", file=sys.stderr)
        sys.exit(1)
    block = match.group(1)
    return {m.strip("'\" ") for m in re.findall(r'"([a-z0-9_]+)"', block)}


def main() -> int:
    registry_types = load_registry_types()
    ts_types = extract_ts_event_types(TS_SOURCE)
    py_types = extract_py_event_types(PY_SOURCE)

    errors: list[str] = []

    only_in_ts = ts_types - registry_types
    only_in_py = py_types - registry_types
    only_in_registry_vs_ts = registry_types - ts_types
    only_in_registry_vs_py = registry_types - py_types

    if only_in_ts:
        errors.append(f"  In TS only (not in registry): {sorted(only_in_ts)}")
    if only_in_py:
        errors.append(f"  In Python only (not in registry): {sorted(only_in_py)}")
    if only_in_registry_vs_ts:
        errors.append(f"  In registry only (missing from TS): {sorted(only_in_registry_vs_ts)}")
    if only_in_registry_vs_py:
        errors.append(f"  In registry only (missing from Python): {sorted(only_in_registry_vs_py)}")

    if errors:
        print("DRIFT: EventType registry out of sync:", file=sys.stderr)
        for e in errors:
            print(e, file=sys.stderr)
        print(f"\n  Registry: {REGISTRY_JSON}", file=sys.stderr)
        print(f"  TS:       {TS_SOURCE}", file=sys.stderr)
        print(f"  Python:   {PY_SOURCE}", file=sys.stderr)
        print("\nRun: python scripts/generate_contracts.py", file=sys.stderr)
        return 1

    print(f"OK: EventType parity confirmed ({len(registry_types)} types in registry, TS, and Python)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
