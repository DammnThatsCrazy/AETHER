#!/usr/bin/env python3
"""Derive the cross-SDK conformance matrix from actual SDK sources and tests.

This is NOT a hand-written claims document. ``packages/shared/sdk-parity.json``
declares capability claims with evidence references (``path#symbol``); its own
contract note requires that a validator fail whenever a cell claims a
capability whose evidence is absent. This script enforces that contract by
deriving every cell from the repository:

* the declared evidence file must exist and contain the declared symbol;
* each SDK's real test manifest (test files + test-case counts) is inventoried
  from disk, per-language;
* for every verified cell, the test files that actually reference the evidence
  symbol are recorded (an empty list is reported honestly — never invented).

Exit code is 1 when any claimed cell fails verification (fail-closed). The
emitted matrix is embedded in the release evidence bundle by
``scripts/release/collect_evidence.py`` and enforced as part of the SDK
runtime-parity gate (``scripts/validate_sdk_parity.py``) in repo_doctor.

Usage:
  python scripts/release/sdk_conformance.py             # JSON matrix to stdout
  python scripts/release/sdk_conformance.py --out FILE  # also write to FILE
  python scripts/release/sdk_conformance.py --quiet     # summary line only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PARITY_FILE = "packages/shared/sdk-parity.json"

# Statuses that assert real behavior and therefore require verifiable evidence.
CLAIMED_STATUSES = {"supported", "partial", "delegated_native"}

# Per-SDK test manifests: (glob patterns rooted at repo root, test-case regex).
# These are the real on-disk test corpora — no aspirational entries.
TEST_CORPUS: dict[str, tuple[tuple[str, ...], str]] = {
    "web": (("packages/web/test/**/*.test.ts", "packages/web/test/**/*.test.tsx"),
            r"\b(?:it|test)\s*\("),
    "server": (("packages/server/src/**/*.test.ts",), r"\b(?:it|test)\s*\("),
    "react-native": (("packages/react-native/src/**/*.test.ts",
                      "packages/react-native/src/**/*.test.tsx"),
                     r"\b(?:it|test)\s*\("),
    "ios": (("packages/ios/Tests/**/*.swift",), r"\bfunc\s+test"),
    "android": (("packages/android/src/test/**/*.kt",), r"@Test\b"),
    "python": (("packages/python/**/test_*.py",), r"\bdef\s+test_"),
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _test_manifest(root: Path) -> dict[str, dict]:
    """Inventory each SDK's real test files and test-case counts from disk."""
    manifest: dict[str, dict] = {}
    for sdk, (patterns, case_regex) in TEST_CORPUS.items():
        files: list[Path] = []
        for pattern in patterns:
            files.extend(
                f for f in root.glob(pattern)
                if f.is_file() and "node_modules" not in f.parts and "dist" not in f.parts
            )
        files = sorted(set(files))
        case_re = re.compile(case_regex)
        cases = sum(len(case_re.findall(_read(f))) for f in files)
        manifest[sdk] = {
            "test_files": len(files),
            "test_cases": cases,
            "files": [str(f.relative_to(root)) for f in files],
        }
    return manifest


def _verify_cell(root: Path, evidence: str) -> tuple[bool, str, str]:
    """Verify one ``path#symbol`` evidence ref. Returns (ok, reason, leaf)."""
    path_part, _, symbol = evidence.partition("#")
    target = root / path_part
    if not target.is_file():
        return False, f"evidence file missing: {path_part}", ""
    if not symbol:
        return False, f"evidence ref has no symbol: {evidence}", ""
    body = _read(target)
    leaf = symbol.split(".")[-1]
    if symbol not in body and leaf not in body:
        return False, f"symbol {symbol!r} not found in {path_part}", leaf
    return True, "", leaf


def build_matrix(root: Path | None = None) -> tuple[dict, list[str]]:
    """Derive the conformance matrix. Returns (matrix, failures)."""
    root = root or repo_root()
    failures: list[str] = []

    parity_path = root / PARITY_FILE
    if not parity_path.is_file():
        return {}, [f"{PARITY_FILE} not found"]
    try:
        parity = json.loads(parity_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {}, [f"{PARITY_FILE} is not valid JSON: {exc}"]

    sdks = parity.get("sdks") or []
    capabilities = parity.get("capabilities") or []
    if not sdks or not capabilities:
        return {}, [f"{PARITY_FILE} must declare 'sdks' and 'capabilities'"]

    manifest = _test_manifest(root)
    # Pre-read each SDK's test corpus once for symbol-reference lookups.
    corpus: dict[str, list[tuple[str, str]]] = {
        sdk: [(rel, _read(root / rel)) for rel in info["files"]]
        for sdk, info in manifest.items()
    }

    out_caps: list[dict] = []
    total = claimed = verified = 0
    for cap in capabilities:
        cap_id = cap.get("id", "?")
        cells: dict[str, dict] = {}
        for sdk, cell in (cap.get("matrix") or {}).items():
            total += 1
            status = cell.get("status")
            evidence = cell.get("evidence")
            derived: dict = {"status": status}
            if cell.get("note"):
                derived["note"] = cell["note"]

            if status in CLAIMED_STATUSES:
                claimed += 1
                if not evidence:
                    failures.append(f"{cap_id}/{sdk}: status {status!r} has no evidence ref")
                    derived["evidence_verified"] = False
                else:
                    ok, reason, leaf = _verify_cell(root, evidence)
                    derived["evidence"] = evidence
                    derived["evidence_verified"] = ok
                    if ok:
                        verified += 1
                        derived["test_references"] = sorted(
                            rel for rel, body in corpus.get(sdk, []) if leaf and leaf in body
                        )
                    else:
                        failures.append(f"{cap_id}/{sdk}: {reason}")
            elif status == "not_applicable":
                derived["evidence_verified"] = None
            else:
                failures.append(f"{cap_id}/{sdk}: unknown status {status!r}")
                derived["evidence_verified"] = False
            cells[sdk] = derived
        out_caps.append({
            "id": cap_id,
            "title": cap.get("title", ""),
            "spec": cap.get("spec", ""),
            "cells": cells,
        })

    matrix = {
        "generated_by": "scripts/release/sdk_conformance.py",
        "derivation": (
            "Every cell verified against SDK sources on disk (evidence file + "
            "symbol) and cross-referenced against real test manifests. "
            "Claims that do not verify fail this derivation."
        ),
        "source": PARITY_FILE,
        "sdk_parity_version": parity.get("version", ""),
        "sdks": {sdk: {"test_files": manifest[sdk]["test_files"],
                       "test_cases": manifest[sdk]["test_cases"]}
                 for sdk in sdks if sdk in manifest},
        "capabilities": out_caps,
        "summary": {
            "cells": total,
            "claimed": claimed,
            "verified": verified,
            "failed": len(failures),
        },
    }
    return matrix, failures


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=None, help="also write the JSON matrix to FILE")
    ap.add_argument("--quiet", action="store_true", help="print the summary line only")
    args = ap.parse_args()

    matrix, failures = build_matrix()
    text = json.dumps(matrix, indent=2, sort_keys=False)
    if not args.quiet:
        print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")

    summary = matrix.get("summary", {})
    if failures:
        print(f"SDK conformance derivation FAILED ({len(failures)} problem(s)):",
              file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print(
        "SDK conformance matrix derived: "
        f"{summary.get('verified', 0)}/{summary.get('claimed', 0)} claimed cells "
        f"verified across {len(matrix.get('sdks', {}))} SDKs "
        f"({summary.get('cells', 0)} cells total).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
