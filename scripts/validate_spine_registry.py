#!/usr/bin/env python3
"""Spine Registry architecture validator CLI (Spine P0, Wave 2A).

Thin CLI over ``scripts/lib/spine_registry_validation.py``. Loads the canonical
spine registry, runs every rule group (registry_schema, dependency_dag,
cross_registry, conformance_gate, lifecycle_honesty, ownership,
inventory_honesty), and exits:

  0  — zero ``severity=="error"`` violations. Warnings (advisory findings such
       as legacy service paths absent from the current checkout) do NOT fail
       the CLI.
  1  — at least one error.
  2  — unexpected internal failure (traceback printed to stderr).

The registry is a declaration of existing work, not a placeholder list: every
spine row references — never re-defines — the ids owned by the surface,
readiness, consent, metric, graph-mutation, event, evidence and projection
registries, and every unresolved reference is declared in ``unresolvedRefs``.

Usage:
  python scripts/validate_spine_registry.py [--check] [--json PATH] [--verbose]
  cd scripts && python -m validate_spine_registry [--check]

Options:
  --check         CI gate — exit 0 on zero errors, 1 otherwise (same exit
                  contract as the default mode). This CLI is a standalone /
                  CI-artifact tool: ``make repo-doctor`` and ``make ci-check``
                  enforcement of the spine registry lands with the CI
                  workstream, not here.
  --json PATH     Write machine-readable evidence to PATH (non-gating CI
                  artifact): {"ok", "violations", "spines", "state_counts", ...}.
  --verbose       Print warnings as well as errors (default: errors only).
  --registry PATH Override the registry JSON (default
                  packages/shared/contracts/spine-registry.json).
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from collections import Counter
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]

# Same sys.path pattern as generate_platform_contracts.py / repo_doctor.py:
# insert the repo root so `scripts.lib...` is importable whether invoked as
# `python scripts/validate_spine_registry.py` (sys.path[0] == scripts/)
# or `python -m validate_spine_registry` from the scripts/ directory.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.spine_registry_validation import (  # noqa: E402
    Violation,
    load_context,
    validate_all,
)

DEFAULT_REGISTRY = ROOT / "packages" / "shared" / "contracts" / "spine-registry.json"


def _evidence(reg: dict, violations: list[Violation]) -> dict:
    """Machine-readable evidence fields derived from the registry + violations.

    - ``spines`` — number of registry entries;
    - ``state_counts`` — entries by implementationState;
    - ``kind_counts`` — entries by spineKind;
    - ``conformance_verified`` — entries whose conformance map is entirely
      ``"verified"`` (non-program_capability spines only);
    - ``errors`` / ``warnings`` — violation counts by severity.
    """
    spines = reg.get("spines", [])
    states = Counter(s.get("implementationState") for s in spines)
    kinds = Counter(s.get("spineKind") for s in spines)
    errors = [v for v in violations if v.severity == "error"]
    warnings = [v for v in violations if v.severity == "warning"]
    return {
        "spines": len(spines),
        "state_counts": dict(sorted(states.items())),
        "kind_counts": dict(sorted(kinds.items())),
        "conformance_verified": sum(
            1
            for s in spines
            if s.get("spineKind") != "program_capability"
            and isinstance(s.get("conformance"), dict)
            and s["conformance"]
            and all(v == "verified" for v in s["conformance"].values())
        ),
        "errors": len(errors),
        "warnings": len(warnings),
    }


def _summarize(reg: dict, violations: list[Violation]) -> str:
    evidence = _evidence(reg, violations)
    errors = [v for v in violations if v.severity == "error"]
    warnings = [v for v in violations if v.severity == "warning"]
    return (
        f"spine registry: {evidence['spines']} spines, "
        f"{len(errors)} errors, {len(warnings)} warnings"
    )


def _parse_args(argv: Optional[list[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="CI gate — exit 0 on zero errors, 1 otherwise (standalone tool; "
        "repo-doctor/Makefile wiring lands with CI enforcement)",
    )
    parser.add_argument(
        "--json",
        metavar="PATH",
        help="Write machine-readable evidence to PATH (non-gating CI artifact)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print warnings as well as errors (default: errors only)",
    )
    parser.add_argument(
        "--registry",
        metavar="PATH",
        default=str(DEFAULT_REGISTRY),
        help="Registry JSON to validate (default: packages/shared/contracts/spine-registry.json)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)

    registry_path = Path(args.registry)
    reg = json.loads(registry_path.read_text(encoding="utf-8"))
    ctx = load_context()
    violations = validate_all(reg, ctx)
    errors = [v for v in violations if v.severity == "error"]

    print(_summarize(reg, violations))

    displayed = violations if args.verbose else errors
    for v in displayed:
        scope = v.spine_id or "<registry>"
        print(f"[{v.id}:{v.severity}] {scope}: {v.message}", file=sys.stderr)

    if args.json:
        payload = {
            "ok": not errors,
            "violations": [
                {
                    "id": v.id,
                    "rule": v.rule,
                    "severity": v.severity,
                    "spine_id": v.spine_id,
                    "message": v.message,
                }
                for v in violations
            ],
            **_evidence(reg, violations),
        }
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"JSON report written to {args.json}")

    return 1 if errors else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception:
        traceback.print_exc()
        sys.exit(2)
