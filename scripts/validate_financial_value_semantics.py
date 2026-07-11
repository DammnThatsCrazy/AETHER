#!/usr/bin/env python3
"""Validate canonical financial value semantics across TS + Python.

Enforces the release-blocking invariants:
  - the canonical value contract exists (packages/shared/value.ts) and exports
    the required types;
  - the backend mirror exists (services/value) with matching MetricKind values;
  - Profile360 no longer sums raw cross-currency floats — the unsafe pattern must
    not reappear, and the safe rollup engine must be used.

This is a static/contract gate — no services required.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALUE_TS = ROOT / "packages" / "shared" / "value.ts"
VALUE_MODELS_PY = ROOT / "Backend Architecture" / "aether-backend" / "services" / "value" / "models.py"
ROLLUPS_PY = ROOT / "Backend Architecture" / "aether-backend" / "services" / "value" / "rollups.py"
AGGREGATOR_PY = ROOT / "Backend Architecture" / "aether-backend" / "services" / "profile" / "aggregator.py"

ERRORS: list[str] = []


def fail(msg: str) -> None:
    ERRORS.append(msg)


def main() -> int:
    # 1. Canonical TS contract exists with the required exports.
    if not VALUE_TS.exists():
        fail(f"missing canonical value contract {VALUE_TS.relative_to(ROOT)}")
        return _report()
    ts = VALUE_TS.read_text()
    for sym in ("MetricKind", "AetherValue", "USDValuation", "NativeValue", "RollupResult"):
        if f"export type {sym}" not in ts and f"export interface {sym}" not in ts:
            fail(f"packages/shared/value.ts missing export {sym}")

    # 2. Backend mirror exists with MetricKind parity.
    if not VALUE_MODELS_PY.exists():
        fail(f"missing backend value mirror {VALUE_MODELS_PY.relative_to(ROOT)}")
    if not ROLLUPS_PY.exists():
        fail(f"missing safe rollup engine {ROLLUPS_PY.relative_to(ROOT)}")

    if VALUE_MODELS_PY.exists():
        py = VALUE_MODELS_PY.read_text()
        # TS union: `export type MetricKind = 'a' | 'b' | ...;`
        m = re.search(r"export type MetricKind =([^;]+);", ts)
        ts_kinds = set(re.findall(r"'([a-z_]+)'", m.group(1))) if m else set()
        py_m = re.search(r"METRIC_KINDS = frozenset\(\{([^}]+)\}\)", py)
        py_kinds = set(re.findall(r'"([a-z_]+)"', py_m.group(1))) if py_m else set()
        if ts_kinds and py_kinds and ts_kinds != py_kinds:
            fail(
                "MetricKind drift between TS and Python: "
                f"TS-only={sorted(ts_kinds - py_kinds)} Python-only={sorted(py_kinds - ts_kinds)}"
            )

    # 3. Profile360 must not reintroduce raw cross-currency float summation.
    if AGGREGATOR_PY.exists():
        agg = AGGREGATOR_PY.read_text()
        unsafe_patterns = [
            r"inflow \+= amount",
            r"outflow \+= amount",
            r"settled \+= float\(",
            r"inflow = sum\(_safe_float\(t\.get\(\"amount\"\)\)",
        ]
        for pat in unsafe_patterns:
            if re.search(pat, agg):
                fail(
                    "services/profile/aggregator.py reintroduced an unsafe raw "
                    f"cross-currency sum (pattern: {pat!r}); use services.value.safe_rollup"
                )
        if "safe_rollup" not in agg:
            fail("services/profile/aggregator.py no longer uses safe_rollup for financial rollups")

    return _report()


def _report() -> int:
    if ERRORS:
        print("financial value semantics validation FAILED:")
        for e in ERRORS:
            print(f"  - {e}")
        print(
            "\nFinancial values are canonical & USD-first. See "
            "docs/source-of-truth/FINANCIAL_VALUE_SEMANTICS.md."
        )
        return 1
    print("financial value semantics validation OK (contract present; no unsafe cross-currency sums).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
