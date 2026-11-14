#!/usr/bin/env python3
"""Static identity-continuity checks (CI V2 port of Gates 1 and 6).

Ported from the retired identity-continuity-gates workflow so the same
invariants run under `ci / verdict`:

  Gate 1  every identity contract exists, parses as JSON, and index.json lists
          the expected contracts.
  Gate 6  the frontend identity surfaces exist and the backend explainability
          service and routes still expose the documented endpoints.

Exit status is non-zero with every failure listed; nothing is skipped silently.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CONTRACT_DIR = "packages/shared/contracts/identity"
CONTRACT_FILES = [
    "index", "source-system", "source-identity", "identity-claim", "canonical-entity",
    "identity-edge", "identity-decision", "identity-conflict", "identity-graph-version",
    "projection-restatement-job", "sdk-contract",
]
INDEXED_CONTRACTS = {
    "source-system", "source-identity", "identity-claim", "canonical-entity", "identity-edge",
    "identity-decision", "identity-conflict", "identity-graph-version", "projection-restatement-job",
}
FRONTEND_DIR = "apps/aether-web/src/features/identity"
FRONTEND_FILES = [
    "TenantActivationDashboard.tsx", "Profile360IdentityPanel.tsx", "IdentityReviewQueue.tsx",
    "ConflictDetail.tsx", "MergeSplitAudit.tsx", "SdkHealth.tsx", "index.ts",
]
EXPLAINABILITY = "services/api/identity/identity/explainability.py"
ROUTES = "services/api/identity/identity/routes.py"
EXPLAINABILITY_MARKERS = ["get_profile_identity_explanation", "get_decision_details", "review_queue", "activation_status"]
ROUTE_MARKERS = ["review-queue", "activation-status", "identity/explanation"]


def gate1(root: Path) -> list[str]:
    errors: list[str] = []
    base = root / CONTRACT_DIR
    for path in sorted(base.glob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"gate1: {path.relative_to(root)} is not valid JSON: {exc}")
    for name in CONTRACT_FILES:
        if not (base / f"{name}.json").is_file():
            errors.append(f"gate1: missing {CONTRACT_DIR}/{name}.json")
    index = base / "index.json"
    if index.is_file():
        try:
            names = {c["name"] for c in json.loads(index.read_text(encoding="utf-8")).get("contracts", [])}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"gate1: index.json manifest unreadable: {exc}")
        else:
            missing = INDEXED_CONTRACTS - names
            if missing:
                errors.append(f"gate1: index.json missing contracts: {sorted(missing)}")
    return errors


def _read(root: Path, rel: str) -> str | None:
    path = root / rel
    return path.read_text(encoding="utf-8") if path.is_file() else None


def gate6(root: Path) -> list[str]:
    errors = [
        f"gate6: missing {FRONTEND_DIR}/{name}"
        for name in FRONTEND_FILES
        if not (root / FRONTEND_DIR / name).is_file()
    ]
    for rel, markers in ((EXPLAINABILITY, EXPLAINABILITY_MARKERS), (ROUTES, ROUTE_MARKERS)):
        text = _read(root, rel)
        if text is None:
            errors.append(f"gate6: missing {rel}")
            continue
        errors += [f"gate6: {rel} no longer contains {m!r}" for m in markers if m not in text]
    return errors


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    args = ap.parse_args(argv)
    errors = gate1(args.root) + gate6(args.root)
    for e in errors:
        print(f"FAIL {e}", file=sys.stderr)
    print("identity continuity static checks:", "FAILED" if errors else "PASSED (gate 1 contracts, gate 6 surfaces)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
