#!/usr/bin/env python3
"""Intelligence Projection architecture validator CLI (P0.8).

Thin CLI over ``scripts/lib/intelligence_projection_validation.py``. Loads the
canonical intelligence-projection registry, runs every rule group
(registry_schema, dependency_dag, cross_registry, inventory, ownership,
surface_honesty, metric_honesty), and exits:

  0  — zero ``severity=="error"`` violations. Warnings (e.g. the real
       registry's documented optional-edge dependency-cycle warnings) do NOT
       fail the CLI.
  1  — at least one error.
  2  — unexpected internal failure (traceback printed to stderr).

The registry is a declaration of existing work, not a placeholder list: every
in_flight projection's legacyBindings must resolve against real routes,
surfaces and services (the tetris inventory gate), and unresolved cross-
registry refs must be declared in pendingAuthority / pendingReference.

Usage:
  python scripts/validate_intelligence_projections.py [--check] [--json PATH] [--verbose]
  cd scripts && python -m validate_intelligence_projections [--check]

Options:
  --check         CI gate — exit 0 on zero errors, 1 otherwise (same exit
                  contract as the default mode). This CLI is a standalone /
                  CI-artifact tool: ``make repo-doctor`` and ``make ci-check``
                  currently enforce the projection registry through the
                  generator's ``validate_intelligence_projection_registry()``
                  (scripts/generate_platform_contracts.py REGISTRIES loop), not
                  through this script. Wired-in repo-doctor/Makefile
                  enforcement lands with the CI workstream, not here.
  --json PATH     Write machine-readable evidence to PATH (non-gating CI
                  artifact): {"ok", "violations", "projections",
                  "implemented", "resolvedRefs", "pending", "inventory"}.
  --verbose       Print warnings as well as errors (default: errors only).
  --registry PATH Override the registry JSON (default
                  packages/shared/contracts/intelligence-projection-registry.json).
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]

# Same sys.path pattern as generate_platform_contracts.py / repo_doctor.py:
# insert the repo root so `scripts.lib...` is importable whether invoked as
# `python scripts/validate_intelligence_projections.py` (sys.path[0] == scripts/)
# or `python -m validate_intelligence_projections` from the scripts/ directory.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.intelligence_projection_validation import (  # noqa: E402
    Violation,
    load_context,
    validate_all,
)

DEFAULT_REGISTRY = ROOT / "packages" / "shared" / "contracts" / "intelligence-projection-registry.json"


def _evidence(reg: dict, ctx: dict, violations: list[Violation]) -> dict:
    """Machine-readable evidence fields derived from the registry + violations.

    - ``projections`` — number of registry entries;
    - ``implemented`` — entries with implementationState == "implemented";
    - ``pending`` — pending declarations across all entries
      (pendingAuthority + pendingReference);
    - ``resolvedRefs`` — declared cross-registry references (surfaceIds +
      metricRefs) that resolve against their registries;
    - ``inventory`` — whether the inventory rule group produced zero errors
      (the tetris honesty gate).
    """
    projections = reg.get("projections", [])
    surface_ids = ctx.get("surface_ids", set())
    metric_names = ctx.get("metric_names", set())

    implemented = sum(
        1 for p in projections if p.get("implementationState") == "implemented"
    )
    pending = sum(
        len(p.get("pendingAuthority", [])) + len(p.get("pendingReference", []))
        for p in projections
    )
    resolved_surfaces = sum(
        1 for p in projections for s in p.get("surfaceIds", []) if s in surface_ids
    )
    resolved_metrics = sum(
        1 for p in projections for m in p.get("metricRefs", []) if m in metric_names
    )
    errors = [v for v in violations if v.severity == "error"]
    return {
        "projections": len(projections),
        "implemented": implemented,
        "pending": pending,
        "resolvedRefs": resolved_surfaces + resolved_metrics,
        "inventory": not any(v.rule == "inventory" for v in errors),
    }


def _summarize(reg: dict, ctx: dict, violations: list[Violation]) -> str:
    evidence = _evidence(reg, ctx, violations)
    errors = [v for v in violations if v.severity == "error"]
    warnings = [v for v in violations if v.severity == "warning"]
    return (
        f"intelligence projections: {evidence['projections']} projections, "
        f"{evidence['implemented']} implemented, {evidence['pending']} pending, "
        f"{evidence['resolvedRefs']} resolved refs, {len(errors)} errors, "
        f"{len(warnings)} warnings"
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
        help="Registry JSON to validate (default: packages/shared/contracts/"
        "intelligence-projection-registry.json)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)

    registry_path = Path(args.registry)
    reg = json.loads(registry_path.read_text(encoding="utf-8"))
    ctx = load_context()
    violations = validate_all(reg, ctx)
    errors = [v for v in violations if v.severity == "error"]

    print(_summarize(reg, ctx, violations))

    displayed = violations if args.verbose else errors
    for v in displayed:
        scope = v.projection or "<registry>"
        print(f"[{v.rule}:{v.severity}] {scope}: {v.message}", file=sys.stderr)

    if args.json:
        payload = {
            "ok": not errors,
            "violations": [
                {
                    "rule": v.rule,
                    "severity": v.severity,
                    "projection": v.projection,
                    "message": v.message,
                }
                for v in violations
            ],
            **_evidence(reg, ctx, violations),
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
