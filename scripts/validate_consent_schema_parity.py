#!/usr/bin/env python3
"""Validate that packages/shared/consent.ts and generated_registry.py are in sync
with the canonical consent-registry.json.

Exits 0 on success, 1 on drift.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

REGISTRY_JSON = ROOT / "packages" / "shared" / "contracts" / "consent-registry.json"
TS_SOURCE = ROOT / "packages" / "shared" / "consent.ts"
PY_SOURCE = (
    ROOT
    / "Backend Architecture"
    / "aether-backend"
    / "services"
    / "ingestion"
    / "generated_registry.py"
)


def load_registry_purposes() -> set[str]:
    data = json.loads(REGISTRY_JSON.read_text())
    return {p["key"] for p in data["purposes"]}


def extract_ts_purposes(path: Path) -> set[str]:
    text = path.read_text()
    match = re.search(r"export type ConsentPurpose\s*=(.*?)\s*;", text, re.DOTALL)
    if not match:
        print(f"ERROR: Could not find ConsentPurpose union in {path}", file=sys.stderr)
        sys.exit(1)
    block = match.group(1)
    return {m.strip("'\" ") for m in re.findall(r"'([a-z0-9_]+)'", block)}


def extract_py_purposes(path: Path) -> set[str]:
    text = path.read_text()
    # Prefer dedicated CONSENT_PURPOSES frozenset
    match = re.search(
        r"CONSENT_PURPOSES\s*:\s*frozenset\[str\]\s*=\s*frozenset\(\{(.*?)\}\)",
        text,
        re.DOTALL,
    )
    if match:
        block = match.group(1)
        return {m for m in re.findall(r'"([a-z0-9_]+)"', block)}
    # Fall back: extract unique values from EVENT_CONSENT_PURPOSE dict
    match = re.search(
        r"EVENT_CONSENT_PURPOSE\s*:\s*dict\[str,\s*str\]\s*=\s*\{(.*?)\}",
        text,
        re.DOTALL,
    )
    if match:
        block = match.group(1)
        return {m for m in re.findall(r':\s*"([a-z0-9_]+)"', block)}
    print(f"ERROR: Could not find CONSENT_PURPOSES or EVENT_CONSENT_PURPOSE in {path}", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    strict = "--strict" in sys.argv

    registry_purposes = load_registry_purposes()
    ts_purposes = extract_ts_purposes(TS_SOURCE)
    py_purposes = extract_py_purposes(PY_SOURCE)

    errors: list[str] = []

    only_in_ts = ts_purposes - registry_purposes
    only_in_py = py_purposes - registry_purposes
    only_in_registry_vs_ts = registry_purposes - ts_purposes
    only_in_registry_vs_py = registry_purposes - py_purposes

    if only_in_ts:
        errors.append(f"  In TS only (not in registry): {sorted(only_in_ts)}")
    if only_in_py:
        errors.append(f"  In Python only (not in registry): {sorted(only_in_py)}")
    if only_in_registry_vs_ts:
        errors.append(f"  In registry only (missing from TS): {sorted(only_in_registry_vs_ts)}")
    if only_in_registry_vs_py:
        errors.append(f"  In registry only (missing from Python): {sorted(only_in_registry_vs_py)}")

    if errors:
        print("DRIFT: ConsentPurpose registry out of sync:", file=sys.stderr)
        for e in errors:
            print(e, file=sys.stderr)
        print(f"\n  Registry: {REGISTRY_JSON}", file=sys.stderr)
        print(f"  TS:       {TS_SOURCE}", file=sys.stderr)
        print(f"  Python:   {PY_SOURCE}", file=sys.stderr)
        print("\nRun: python scripts/generate_contracts.py", file=sys.stderr)
        return 1

    print(f"OK: ConsentPurpose parity confirmed ({len(registry_purposes)} purposes in registry, TS, and Python)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
