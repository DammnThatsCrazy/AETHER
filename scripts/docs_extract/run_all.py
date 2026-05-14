#!/usr/bin/env python3
"""Run every documentation generator and emit JSON artifacts under
``docs/_generated/``.

This is the single entry point that ``make extract-docs`` and CI call.
Adding a new generator just means appending one line to ``GENERATORS``
below; tests + drift detection follow automatically.

Determinism: each generator is required to produce byte-identical output
on the same input. The CI ``extract-docs-drift`` step relies on this — it
re-runs all generators and fails if anything under ``docs/_generated/``
changed without a matching commit.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PKG = ROOT / "scripts" / "docs_extract"

# Order matters only for the human-readable log; outputs are independent.
GENERATORS = [
    "extract_env",
    "extract_events",
]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PKG / f"{name}.py")
    assert spec and spec.loader, f"could not load {name}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    failures: list[str] = []
    for name in GENERATORS:
        mod = _load(name)
        rc = mod.main()
        if rc != 0:
            failures.append(name)

    if failures:
        print(f"\nFAILED: {', '.join(failures)}", file=sys.stderr)
        return 1

    print(f"\nAll {len(GENERATORS)} generators succeeded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
