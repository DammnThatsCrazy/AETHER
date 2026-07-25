#!/usr/bin/env python3
"""Finalize the historical frontend data-truth inventory deterministically.

The PR1 inventory is an append-only record of every original search finding.
This generator preserves those findings, records their terminal disposition,
and adds the currently retained test-only fixture files. Runtime cleanliness is
enforced separately by ``validate_frontend_data_truth.py``; a green generated
inventory can never substitute for that source and bundle gate.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "docs" / "_generated" / "frontend-data-truth-inventory.json"
TEST_PARTS = {"test", "tests", "test-support", "__tests__"}
FIXTURE_PARTS = {"fixtures", "mocks"}


def _is_test_path(path: Path) -> bool:
    return bool(set(path.parts) & TEST_PARTS) or any(
        marker in path.name for marker in (".test.", ".spec.", ".stories.")
    )


def _retained_test_fixture_paths() -> list[str]:
    paths: list[str] = []
    for app in ("aether", "kyber", "demo"):
        root = ROOT / "frontend" / app
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if (
                path.is_file()
                and _is_test_path(path.relative_to(ROOT))
                and (
                    bool(set(path.parts) & FIXTURE_PARTS)
                    or "fixture" in path.name.lower()
                )
            ):
                paths.append(path.relative_to(ROOT).as_posix())
    return sorted(set(paths))


def _terminal_status(finding: dict[str, object]) -> str:
    path = Path(str(finding.get("path", "")))
    classification = str(finding.get("classification", "")).lower()
    if _is_test_path(path):
        return "retained test-only fixture"
    if "static product metadata" in classification:
        return "reviewed and retained static product metadata"
    if "ui copy" in classification or "false positive" in classification:
        return "reviewed and retained non-operational source"
    if "test-only" in classification:
        return "retained test-only fixture"
    return "remediated in combined live-empty and backend-seed program"


def main() -> int:
    if not OUTPUT.is_file():
        raise FileNotFoundError(f"historical inventory is missing: {OUTPUT}")
    payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
    historical = list(payload.get("findings", []))

    for finding in historical:
        finding["target_pr"] = "PR1 + combined final PR"
        finding["final_status"] = _terminal_status(finding)

    known_paths = {str(finding.get("path", "")) for finding in historical}
    for relative in _retained_test_fixture_paths():
        if relative in known_paths:
            continue
        app = relative.split("/")[1] if relative.startswith("frontend/") else "shared"
        historical.append(
            {
                "path": relative,
                "line": 1,
                "symbol": "test-only fixture module",
                "application": app,
                "domain": "automated test support",
                "classification": "test-only fixture",
                "remediation": "retain under the narrow test-path allowlist",
                "target_pr": "PR1 + combined final PR",
                "final_status": "retained test-only fixture",
            }
        )

    historical.sort(
        key=lambda item: (
            str(item.get("path", "")),
            int(item.get("line", 0)),
            str(item.get("symbol", "")),
        )
    )
    retained = sum(
        1 for finding in historical if str(finding["final_status"]).startswith("retained")
    )
    reviewed = sum(
        1 for finding in historical if str(finding["final_status"]).startswith("reviewed")
    )
    remediated = len(historical) - retained - reviewed
    output = {
        "generated_by": "scripts/docs_extract/extract_frontend_data_truth_inventory.py",
        "baseline_finding_count": int(payload.get("baseline_finding_count", payload.get("total_findings", 0))),
        "total_findings": len(historical),
        "disposition_counts": {
            "remediated": remediated,
            "reviewed_non_operational": reviewed,
            "retained_test_only": retained,
            "pending": 0,
        },
        "runtime_validator": "scripts/validate_frontend_data_truth.py",
        "findings": historical,
    }
    OUTPUT.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(
        "generated frontend-data-truth-inventory.json "
        f"({len(historical)} findings, 0 pending)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
