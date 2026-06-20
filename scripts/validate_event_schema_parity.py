#!/usr/bin/env python3
"""Validate that the TypeScript EventType registry and the Python CANONICAL_EVENT_TYPES are in sync.

Exits 0 if they match, 1 if there is drift.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

TS_SOURCE = ROOT / "packages" / "shared" / "events.ts"
PY_SOURCE = ROOT / "Backend Architecture" / "aether-backend" / "services" / "ingestion" / "batch.py"


def extract_ts_event_types(path: Path) -> set[str]:
    text = path.read_text()
    # Extract the EventType union block between 'export type EventType =' and ';'
    match = re.search(r"export type EventType\s*=(.*?);", text, re.DOTALL)
    if not match:
        print(f"ERROR: Could not find EventType union in {path}", file=sys.stderr)
        sys.exit(1)
    block = match.group(1)
    return {m.strip("'\" ") for m in re.findall(r"'([a-z0-9_]+)'", block)}


def extract_py_event_types(path: Path) -> set[str]:
    text = path.read_text()
    match = re.search(r"CANONICAL_EVENT_TYPES\s*:\s*frozenset\[str\]\s*=\s*frozenset\(\{(.*?)\}\)", text, re.DOTALL)
    if not match:
        print(f"ERROR: Could not find CANONICAL_EVENT_TYPES frozenset in {path}", file=sys.stderr)
        sys.exit(1)
    block = match.group(1)
    return {m.strip("'\" ") for m in re.findall(r'"([a-z0-9_]+)"', block)}


def main() -> int:
    ts_types = extract_ts_event_types(TS_SOURCE)
    py_types = extract_py_event_types(PY_SOURCE)

    only_in_ts = ts_types - py_types
    only_in_py = py_types - ts_types

    if not only_in_ts and not only_in_py:
        print(f"OK: EventType parity confirmed ({len(ts_types)} types)")
        return 0

    print("DRIFT: EventType registry out of sync between TypeScript and Python", file=sys.stderr)
    if only_in_ts:
        print(f"  In TS only: {sorted(only_in_ts)}", file=sys.stderr)
    if only_in_py:
        print(f"  In Python only: {sorted(only_in_py)}", file=sys.stderr)
    print(f"\n  TS source:  {TS_SOURCE}", file=sys.stderr)
    print(f"  Py source:  {PY_SOURCE}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
