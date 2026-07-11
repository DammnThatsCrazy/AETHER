#!/usr/bin/env python3
"""Generate ``docs/_generated/dimension-registry.json`` from the canonical
dimension-state contract + the per-dimension expectation registry.

Sources:
- ``packages/shared/dimension-state.ts`` — the DimensionState union, the
  best->worst precedence, and the reason codes (parsed).
- ``services/reconciliation/expectations.py`` — the per-dimension min-events
  and freshness SLAs (loaded by file path, no package-init side effects).

Schema::

    {
      "version": "8.12.0",
      "generated_from": ["packages/shared/dimension-state.ts",
                          ".../services/reconciliation/expectations.py"],
      "states": ["ready", ...],
      "precedence": ["ready", ..., "error"],
      "reason_codes": ["ok", ...],
      "expectations": [
        {"dimension": "wallets", "min_events": 1,
         "freshness_sla_seconds": 604800, "source_method": "wallets",
         "depends_on": []},
        ...
      ]
    }

Determinism: states/reason codes appear in TS source order; expectations in
registry order. Same input produces byte-identical output.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DIM_TS = ROOT / "packages" / "shared" / "dimension-state.ts"
EXPECTATIONS_PY = (
    ROOT / "Backend Architecture" / "aether-backend"
    / "services" / "reconciliation" / "expectations.py"
)
OUTPUT = ROOT / "docs" / "_generated" / "dimension-registry.json"


def _const_array(text: str, name: str) -> list[str]:
    m = re.search(rf"{name}[^\[]*\[(.*?)\]\s*as const", text, re.S)
    if not m:
        raise SystemExit(f"const array {name!r} not found in dimension-state.ts")
    return re.findall(r"'([a-z_]+)'", m.group(1))


def _load_expectations() -> list[dict]:
    spec = importlib.util.spec_from_file_location("_dim_expectations", EXPECTATIONS_PY)
    assert spec and spec.loader, "could not load expectations.py"
    mod = importlib.util.module_from_spec(spec)
    # Register before exec: @dataclass resolves annotations via
    # sys.modules[cls.__module__], which must exist during class creation.
    sys.modules["_dim_expectations"] = mod
    spec.loader.exec_module(mod)
    return list(mod.registry_snapshot())


def read_version() -> str:
    pyproject = ROOT / "pyproject.toml"
    for line in pyproject.read_text(encoding="utf-8").splitlines():
        m = re.match(r'\s*version\s*=\s*"([^"]+)"', line)
        if m:
            return m.group(1)
    raise SystemExit("could not read version from pyproject.toml")


def build_payload() -> dict:
    text = DIM_TS.read_text(encoding="utf-8")
    return {
        "version": read_version(),
        "generated_from": [
            "packages/shared/dimension-state.ts",
            "Backend Architecture/aether-backend/services/reconciliation/expectations.py",
        ],
        "states": _const_array(text, "dimensionStates"),
        "precedence": _const_array(text, "dimensionStatePrecedence"),
        "reason_codes": _const_array(text, "dimensionReasonCodes"),
        "expectations": _load_expectations(),
    }


def main() -> int:
    payload = build_payload()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({len(payload['expectations'])} dimensions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
