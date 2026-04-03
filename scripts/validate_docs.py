#!/usr/bin/env python3
"""
Aether Platform — Documentation Validation Script

Checks for version drift, missing changelog entries, and stale doc headers.
Run as a pre-commit hook or CI check to prevent documentation from falling
out of sync with code.

Usage:
    python scripts/validate_docs.py          # check everything
    python scripts/validate_docs.py --fix    # report only, suggest fixes

Exit codes:
    0 = all checks pass
    1 = drift detected (with details)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_PATTERN = re.compile(r"v?(\d+\.\d+\.\d+)")

errors: list[str] = []
warnings: list[str] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def read_version_from_pyproject() -> str:
    """Read the canonical version from root pyproject.toml."""
    pyproject = ROOT / "pyproject.toml"
    if not pyproject.exists():
        errors.append("pyproject.toml not found at repo root")
        return "0.0.0"
    text = pyproject.read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        errors.append("Could not find version in pyproject.toml")
        return "0.0.0"
    return match.group(1)


def check_package_json(path: Path, expected: str) -> None:
    """Check that a package.json has the expected version."""
    if not path.exists():
        warnings.append(f"package.json not found: {path.relative_to(ROOT)}")
        return
    data = json.loads(path.read_text())
    actual = data.get("version", "?")
    if actual != expected:
        errors.append(
            f"{path.relative_to(ROOT)}: version is {actual}, expected {expected}"
        )


def check_changelog_has_version(path: Path, version: str) -> None:
    """Check that a CHANGELOG mentions the version."""
    if not path.exists():
        warnings.append(f"CHANGELOG not found: {path.relative_to(ROOT)}")
        return
    text = path.read_text()
    # Look for the version in a heading (## [8.3.1] or ## v8.3.1)
    pattern = re.compile(rf"##.*{re.escape(version)}")
    if not pattern.search(text):
        errors.append(
            f"{path.relative_to(ROOT)}: no entry for version {version}"
        )


def check_doc_header_version(path: Path, current: str, previous: str) -> None:
    """Check that a doc header contains the current version."""
    if not path.exists():
        return  # optional files
    text = path.read_text()
    lines = text.split("\n")[:5]  # check first 5 lines
    for line in lines:
        if line.startswith("#"):
            match = VERSION_PATTERN.search(line)
            if match:
                found = match.group(1)
                if found != current:
                    errors.append(
                        f"{path.relative_to(ROOT)}: header says v{found}, "
                        f"expected v{current}. "
                        f"Fix: python scripts/bump_version.py {current}"
                    )
            return


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def run_checks() -> None:
    version = read_version_from_pyproject()
    # Compute "previous" version for comparison (e.g. 8.3.1 -> 8.3.0)
    parts = version.split(".")
    prev_patch = max(0, int(parts[2]) - 1) if len(parts) == 3 else 0
    previous = f"{parts[0]}.{parts[1]}.{prev_patch}"

    print(f"Validating docs for version: {version}")
    print(f"  (allowing previous: {previous})")
    print()

    # 1. package.json versions
    print("1. Checking package.json versions...")
    for pj in [
        ROOT / "package.json",
        ROOT / "RootPackageSDK.json",
        ROOT / "packages" / "web" / "package.json",
        ROOT / "packages" / "react-native" / "package.json",
        ROOT / "Data Ingestion Layer" / "package.json",
        ROOT / "Data Ingestion Layer" / "packages" / "common" / "package.json",
        ROOT / "Data Ingestion Layer" / "packages" / "auth" / "package.json",
        ROOT / "Data Ingestion Layer" / "packages" / "cache" / "package.json",
        ROOT / "Data Ingestion Layer" / "packages" / "events" / "package.json",
        ROOT / "Data Ingestion Layer" / "packages" / "logger" / "package.json",
        ROOT / "Data Ingestion Layer" / "services" / "ingestion" / "package.json",
        ROOT / "Data Lake Architecture" / "aether-Datalake-backend" / "package.json",
    ]:
        check_package_json(pj, version)

    # 2. CHANGELOG entries
    print("2. Checking CHANGELOG entries...")
    check_changelog_has_version(ROOT / "CHANGELOG.md", version)
    check_changelog_has_version(ROOT / "docs" / "CHANGELOG.md", version)

    # 3. Doc headers
    print("3. Checking doc headers...")
    doc_files = list((ROOT / "docs").glob("*.md"))
    for doc in doc_files:
        if doc.name == "CHANGELOG.md" or doc.name == "MIGRATION-v7.md":
            continue
        check_doc_header_version(doc, version, previous)

    # 4. README headers in subdirectories
    print("4. Checking README headers...")
    for readme in ROOT.glob("*/README.md"):
        if readme.parent.name in ("node_modules", ".git", "dist"):
            continue
        check_doc_header_version(readme, version, previous)

    # Report
    print()
    if errors:
        print(f"ERRORS ({len(errors)}):")
        for e in errors:
            print(f"  {e}")
    if warnings:
        print(f"WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"  {w}")

    if not errors and not warnings:
        print("All checks passed.")

    if errors:
        print(f"\nFix with: python scripts/bump_version.py {version}")
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    run_checks()
