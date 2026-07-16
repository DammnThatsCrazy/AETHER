#!/usr/bin/env python3
"""
Generate TypeScript and Python artifacts from the unified-platform JSON registries.

Companion to scripts/generate_contracts.py (which owns the event/consent/metric
registries). This generator owns the platform-plane registries added by the
unified intelligence program; new registries plug into the REGISTRIES table.

Sources (read-only — canonical source of truth):
  packages/shared/contracts/temporal-policy-registry.json

Generated outputs:
  packages/shared/temporal-policy.ts
  Backend Architecture/aether-backend/shared/temporal/generated_policy.py
  docs/_generated/temporal-policy-table.md

Usage:
  python scripts/generate_platform_contracts.py           # write outputs in-place
  python scripts/generate_platform_contracts.py --check   # exit 1 on drift (CI gate)

Guarantees:
  - Idempotent: running twice produces identical output
  - Sorted: all lists and maps are emitted in sorted order
  - Validates: registry internal consistency before any write
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONTRACTS = ROOT / "packages" / "shared" / "contracts"
BACKEND = ROOT / "Backend Architecture" / "aether-backend"

TEMPORAL_POLICY_JSON = CONTRACTS / "temporal-policy-registry.json"
EVENT_REGISTRY_JSON = CONTRACTS / "event-registry.json"

TEMPORAL_POLICY_TS = ROOT / "packages" / "shared" / "temporal-policy.ts"
TEMPORAL_POLICY_PY = BACKEND / "shared" / "temporal" / "generated_policy.py"
TEMPORAL_POLICY_MD = ROOT / "docs" / "_generated" / "temporal-policy-table.md"

_SEVERITIES = ("error", "warning", "info")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def validate_temporal_policy(reg: dict, event_families: set[str]) -> None:
    dispositions = set(reg["dispositions"])
    codes_seen: set[str] = set()
    for entry in reg["reasonCodes"]:
        code = entry["code"]
        if code in codes_seen:
            _fail(f"duplicate temporal reason code {code!r}")
        codes_seen.add(code)
        if entry["severity"] not in _SEVERITIES:
            _fail(f"reason code {code!r} has unknown severity {entry['severity']!r}")
        if entry["disposition"] not in dispositions:
            _fail(f"reason code {code!r} has unknown disposition {entry['disposition']!r}")

    bounds_keys = {"maxFutureSkewMs", "warnSkewMs", "maxLatenessMs"}
    default = reg["defaultBounds"]
    if set(default) != bounds_keys:
        _fail(f"defaultBounds must define exactly {sorted(bounds_keys)}")
    for family, bounds in reg["familyBounds"].items():
        if family not in event_families:
            _fail(f"familyBounds references unknown event family {family!r}")
        unknown = set(bounds) - bounds_keys
        if unknown:
            _fail(f"familyBounds[{family!r}] has unknown keys {sorted(unknown)}")
        for key, value in bounds.items():
            if not isinstance(value, int) or value <= 0:
                _fail(f"familyBounds[{family!r}][{key}] must be a positive integer")
    resolved_default = {**default}
    if resolved_default["warnSkewMs"] >= resolved_default["maxFutureSkewMs"]:
        _fail("defaultBounds.warnSkewMs must be below maxFutureSkewMs")


def resolved_family_bounds(reg: dict, event_families: set[str]) -> dict[str, dict]:
    """Every event family resolves to complete bounds (default + override)."""
    default = reg["defaultBounds"]
    return {
        family: {**default, **reg["familyBounds"].get(family, {})}
        for family in sorted(event_families)
    }


# ---------------------------------------------------------------------------
# Emitters
# ---------------------------------------------------------------------------

def gen_temporal_policy_ts(reg: dict, families: dict[str, dict]) -> str:
    lines: list[str] = []
    lines.append("/**")
    lines.append(" * DO NOT EDIT — generated from packages/shared/contracts/temporal-policy-registry.json")
    lines.append(" * Run: python scripts/generate_platform_contracts.py")
    lines.append(" */")
    lines.append("")
    lines.append(f"export const temporalPolicyVersion = '{reg['policyVersion']}' as const;")
    lines.append("")
    modes = ", ".join(f"'{m}'" for m in reg["enforcementModes"])
    lines.append(f"export const temporalEnforcementModes = [{modes}] as const;")
    lines.append("export type TemporalEnforcementMode = typeof temporalEnforcementModes[number];")
    lines.append("")
    dispositions = ", ".join(f"'{d}'" for d in reg["dispositions"])
    lines.append(f"export const temporalDispositions = [{dispositions}] as const;")
    lines.append("export type TemporalDisposition = typeof temporalDispositions[number];")
    lines.append("")
    lines.append("/** Disposition applied to each stable temporal reason code. */")
    lines.append("export const temporalReasonDispositions = {")
    for entry in sorted(reg["reasonCodes"], key=lambda e: e["code"]):
        lines.append(f"  {entry['code']}: '{entry['disposition']}',")
    lines.append("} as const;")
    lines.append("")
    lines.append("export interface TemporalFamilyBounds {")
    lines.append("  maxFutureSkewMs: number;")
    lines.append("  warnSkewMs: number;")
    lines.append("  maxLatenessMs: number;")
    lines.append("}")
    lines.append("")
    lines.append("/** Complete (default-resolved) temporal bounds per event family. */")
    lines.append("export const temporalFamilyBounds: Record<string, TemporalFamilyBounds> = {")
    for family, bounds in families.items():
        lines.append(
            f"  {family}: {{ maxFutureSkewMs: {bounds['maxFutureSkewMs']}, "
            f"warnSkewMs: {bounds['warnSkewMs']}, maxLatenessMs: {bounds['maxLatenessMs']} }},"
        )
    lines.append("};")
    lines.append("")
    default = reg["defaultBounds"]
    lines.append(
        "export const temporalDefaultBounds: TemporalFamilyBounds = "
        f"{{ maxFutureSkewMs: {default['maxFutureSkewMs']}, "
        f"warnSkewMs: {default['warnSkewMs']}, maxLatenessMs: {default['maxLatenessMs']} }};"
    )
    lines.append("")
    return "\n".join(lines)


def gen_temporal_policy_py(reg: dict, families: dict[str, dict]) -> str:
    lines: list[str] = []
    lines.append("# DO NOT EDIT — generated from packages/shared/contracts/temporal-policy-registry.json")
    lines.append("# Run: python scripts/generate_platform_contracts.py")
    lines.append('"""Generated temporal enforcement policy (dispositions + per-family bounds)."""')
    lines.append("")
    lines.append("from __future__ import annotations")
    lines.append("")
    lines.append(f'TEMPORAL_POLICY_VERSION = "{reg["policyVersion"]}"')
    lines.append("")
    modes = ", ".join(f'"{m}"' for m in reg["enforcementModes"])
    lines.append(f"TEMPORAL_ENFORCEMENT_MODES: tuple[str, ...] = ({modes})")
    lines.append("")
    dispositions = ", ".join(f'"{d}"' for d in reg["dispositions"])
    lines.append(f"TEMPORAL_DISPOSITIONS: tuple[str, ...] = ({dispositions})")
    lines.append("")
    lines.append("# Disposition applied to each stable temporal reason code.")
    lines.append("TEMPORAL_REASON_DISPOSITIONS: dict[str, str] = {")
    for entry in sorted(reg["reasonCodes"], key=lambda e: e["code"]):
        lines.append(f'    "{entry["code"]}": "{entry["disposition"]}",')
    lines.append("}")
    lines.append("")
    lines.append("# Complete (default-resolved) temporal bounds per event family.")
    lines.append("TEMPORAL_FAMILY_BOUNDS: dict[str, dict[str, int]] = {")
    for family, bounds in families.items():
        lines.append(
            f'    "{family}": {{"maxFutureSkewMs": {bounds["maxFutureSkewMs"]}, '
            f'"warnSkewMs": {bounds["warnSkewMs"]}, "maxLatenessMs": {bounds["maxLatenessMs"]}}},'
        )
    lines.append("}")
    lines.append("")
    default = reg["defaultBounds"]
    lines.append(
        'TEMPORAL_DEFAULT_BOUNDS: dict[str, int] = {'
        f'"maxFutureSkewMs": {default["maxFutureSkewMs"]}, '
        f'"warnSkewMs": {default["warnSkewMs"]}, '
        f'"maxLatenessMs": {default["maxLatenessMs"]}}}'
    )
    lines.append("")
    lines.append("__all__ = [")
    lines.append('    "TEMPORAL_POLICY_VERSION",')
    lines.append('    "TEMPORAL_ENFORCEMENT_MODES",')
    lines.append('    "TEMPORAL_DISPOSITIONS",')
    lines.append('    "TEMPORAL_REASON_DISPOSITIONS",')
    lines.append('    "TEMPORAL_FAMILY_BOUNDS",')
    lines.append('    "TEMPORAL_DEFAULT_BOUNDS",')
    lines.append("]")
    lines.append("")
    return "\n".join(lines)


def gen_temporal_policy_md(reg: dict, families: dict[str, dict]) -> str:
    lines: list[str] = []
    lines.append("<!-- DO NOT EDIT — generated from packages/shared/contracts/temporal-policy-registry.json -->")
    lines.append("<!-- Run: python scripts/generate_platform_contracts.py -->")
    lines.append("")
    lines.append("# Temporal Policy Registry")
    lines.append("")
    lines.append(f"Policy version: `{reg['policyVersion']}`")
    lines.append("")
    lines.append(f"Enforcement modes: {', '.join(f'`{m}`' for m in reg['enforcementModes'])}")
    lines.append("")
    lines.append("## Reason codes")
    lines.append("")
    lines.append("| Code | Severity | Disposition | Description |")
    lines.append("|---|---|---|---|")
    for entry in sorted(reg["reasonCodes"], key=lambda e: e["code"]):
        lines.append(
            f"| `{entry['code']}` | {entry['severity']} | {entry['disposition']} | {entry['description']} |"
        )
    lines.append("")
    lines.append("## Per-family bounds (default-resolved)")
    lines.append("")
    lines.append("| Family | Max future skew (ms) | Warn skew (ms) | Max lateness (ms) |")
    lines.append("|---|---|---|---|")
    for family, bounds in families.items():
        lines.append(
            f"| `{family}` | {bounds['maxFutureSkewMs']} | {bounds['warnSkewMs']} | {bounds['maxLatenessMs']} |"
        )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Registry table + write/check machinery
# ---------------------------------------------------------------------------

def _apply(path: Path, content: str, check: bool, diffs: list[str]) -> None:
    if path.exists():
        current = path.read_text()
        if current == content:
            return
        if check:
            diffs.append(str(path.relative_to(ROOT)))
            return
    if not check:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        print(f"  written: {path.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if any generated file differs from the committed version (CI gate)",
    )
    args = parser.parse_args()

    event_reg = json.loads(EVENT_REGISTRY_JSON.read_text())
    event_families = {e["family"] for e in event_reg["events"]}

    temporal_reg = json.loads(TEMPORAL_POLICY_JSON.read_text())
    validate_temporal_policy(temporal_reg, event_families)
    families = resolved_family_bounds(temporal_reg, event_families)

    diffs: list[str] = []
    _apply(TEMPORAL_POLICY_TS, gen_temporal_policy_ts(temporal_reg, families), args.check, diffs)
    _apply(TEMPORAL_POLICY_PY, gen_temporal_policy_py(temporal_reg, families), args.check, diffs)
    _apply(TEMPORAL_POLICY_MD, gen_temporal_policy_md(temporal_reg, families), args.check, diffs)

    if diffs:
        print("DRIFT: generated files differ from committed versions:", file=sys.stderr)
        for d in diffs:
            print(f"  {d}", file=sys.stderr)
        print("Run: python scripts/generate_platform_contracts.py", file=sys.stderr)
        return 1

    print(
        f"OK: temporal policy v{temporal_reg['policyVersion']} — "
        f"{len(temporal_reg['reasonCodes'])} reason codes, {len(families)} families "
        f"— all artifacts up-to-date"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
