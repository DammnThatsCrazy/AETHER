#!/usr/bin/env python3
"""
Aether Platform — Version Bump Script

Updates the version number across ALL files in the monorepo atomically.
The single source of truth is `pyproject.toml` at the repo root.

Usage:
    python scripts/bump_version.py 8.4.0
    python scripts/bump_version.py --check     # just print current version

Files updated:
    - pyproject.toml (root)
    - package.json (root, packages/web, packages/react-native)
    - All docs/*.md headers containing version numbers
    - EXTRACTION_DEFENSE_AUDIT.md
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Files to update
# ---------------------------------------------------------------------------

PACKAGE_JSONS = [
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
]

# Native SDK version files (different format than package.json)
IOS_PACKAGE_SWIFT = ROOT / "packages" / "ios" / "Package.swift"
ANDROID_BUILD_GRADLE = ROOT / "packages" / "android" / "build.gradle.kts"

# Doc files where the FIRST heading contains a version like "v8.3.1" or "v8.3.0"
DOC_HEADERS = [
    ROOT / "docs" / "ARCHITECTURE.md",
    ROOT / "docs" / "BACKEND-API.md",
    ROOT / "docs" / "SDK-WEB.md",
    ROOT / "docs" / "SDK-IOS.md",
    ROOT / "docs" / "SDK-ANDROID.md",
    ROOT / "docs" / "SDK-REACT-NATIVE.md",
    ROOT / "docs" / "IDENTITY-RESOLUTION.md",
    ROOT / "docs" / "INTELLIGENCE-GRAPH.md",
    ROOT / "docs" / "MODEL-EXTRACTION-DEFENSE.md",
    ROOT / "docs" / "AGENT-CONTROLLER.md",
    ROOT / "docs" / "PRODUCTION-READINESS.md",
    ROOT / "docs" / "OPERATIONS-RUNBOOK.md",
    ROOT / "EXTRACTION_DEFENSE_AUDIT.md",
]

# README files with version in the first heading
README_HEADERS = [
    ROOT / "Agent Layer" / "README.md",
    ROOT / "Backend Architecture" / "README.md",
    ROOT / "Data Ingestion Layer" / "README.md",
    ROOT / "Data Lake Architecture" / "README.md",
    ROOT / "AWS Deployment" / "aether-aws" / "README.md",
    ROOT / "cicd" / "aether-cicd" / "README.md",
    ROOT / "GDPR & SOC2" / "aether-compliance" / "README.md",
]

VERSION_PATTERN = re.compile(r"v?\d+\.\d+\.\d+")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def read_current_version() -> str:
    """Read the current version from pyproject.toml."""
    pyproject = ROOT / "pyproject.toml"
    text = pyproject.read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if not match:
        print("ERROR: Could not find version in pyproject.toml")
        sys.exit(1)
    return match.group(1)


def update_pyproject(new_version: str) -> None:
    """Update version in root pyproject.toml."""
    path = ROOT / "pyproject.toml"
    text = path.read_text()
    updated = re.sub(
        r'^(version\s*=\s*)"[^"]+"',
        f'\\1"{new_version}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    path.write_text(updated)
    print(f"  Updated: pyproject.toml -> {new_version}")


def update_package_json(path: Path, new_version: str) -> None:
    """Update version in a package.json file."""
    if not path.exists():
        print(f"  SKIP (not found): {path.relative_to(ROOT)}")
        return
    data = json.loads(path.read_text())
    old = data.get("version", "?")
    data["version"] = new_version
    path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"  Updated: {path.relative_to(ROOT)} ({old} -> {new_version})")


def update_doc_header(path: Path, new_version: str) -> None:
    """Update the version in the first heading of a markdown doc."""
    if not path.exists():
        print(f"  SKIP (not found): {path.relative_to(ROOT)}")
        return
    text = path.read_text()
    lines = text.split("\n")

    # Find the first line that looks like a heading with a version
    for i, line in enumerate(lines):
        if line.startswith("#") and VERSION_PATTERN.search(line):
            old_match = VERSION_PATTERN.search(line)
            if old_match:
                old = old_match.group()
                # Preserve the "v" prefix if present
                prefix = "v" if old.startswith("v") else ""
                lines[i] = VERSION_PATTERN.sub(f"{prefix}{new_version}", line, count=1)
                path.write_text("\n".join(lines))
                print(f"  Updated: {path.relative_to(ROOT)} ({old} -> {prefix}{new_version})")
                return

    print(f"  SKIP (no version in heading): {path.relative_to(ROOT)}")


def update_ios_version(new_version: str) -> None:
    """Update version comment in Package.swift."""
    path = IOS_PACKAGE_SWIFT
    if not path.exists():
        print(f"  SKIP (not found): {path.relative_to(ROOT)}")
        return
    text = path.read_text()
    updated = VERSION_PATTERN.sub(new_version, text, count=1)
    if updated != text:
        path.write_text(updated)
        print(f"  Updated: {path.relative_to(ROOT)} -> {new_version}")
    else:
        print(f"  SKIP (no version found): {path.relative_to(ROOT)}")


def update_android_version(new_version: str) -> None:
    """Update version in build.gradle.kts (both Maven publish and buildConfigField)."""
    path = ANDROID_BUILD_GRADLE
    if not path.exists():
        print(f"  SKIP (not found): {path.relative_to(ROOT)}")
        return
    text = path.read_text()
    changes = 0

    # Update Maven publication version: version = "X.Y.Z"
    updated = re.sub(r'version\s*=\s*"[^"]+"', f'version = "{new_version}"', text, count=1)
    if updated != text:
        changes += 1
        text = updated

    # Update buildConfigField version: AETHER_SDK_VERSION
    updated = re.sub(
        r'buildConfigField\("String",\s*"AETHER_SDK_VERSION",\s*"\\"[^"]*\\""\)',
        f'buildConfigField("String", "AETHER_SDK_VERSION", "\\"{new_version}\\"")',
        text,
        count=1,
    )
    if updated != text:
        changes += 1
        text = updated

    if changes > 0:
        path.write_text(text)
        print(f"  Updated: {path.relative_to(ROOT)} -> {new_version} ({changes} locations)")
    else:
        print(f"  SKIP (no version found): {path.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Current version: {read_current_version()}")
        print(f"Usage: python {sys.argv[0]} <new-version>")
        print(f"       python {sys.argv[0]} --check")
        sys.exit(1)

    if sys.argv[1] == "--check":
        print(f"Current version: {read_current_version()}")
        sys.exit(0)

    new_version = sys.argv[1].lstrip("v")

    # Validate format
    if not re.match(r"^\d+\.\d+\.\d+$", new_version):
        print(f"ERROR: Invalid version format: {new_version}")
        print("Expected: MAJOR.MINOR.PATCH (e.g., 8.4.0)")
        sys.exit(1)

    old_version = read_current_version()
    print(f"Bumping version: {old_version} -> {new_version}")
    print()

    # 1. Root pyproject.toml
    print("1. pyproject.toml:")
    update_pyproject(new_version)

    # 2. package.json files
    print("\n2. package.json files:")
    for pj in PACKAGE_JSONS:
        update_package_json(pj, new_version)

    # 3. Doc headers
    print("\n3. Doc headers:")
    for doc in DOC_HEADERS:
        update_doc_header(doc, new_version)

    # 4. README headers
    print("\n4. README headers:")
    for readme in README_HEADERS:
        update_doc_header(readme, new_version)

    # 5. Native SDK versions
    print("\n5. Native SDK versions:")
    update_ios_version(new_version)
    update_android_version(new_version)

    print(f"\nDone. Version bumped to {new_version} across all files.")
    print("Remember to update CHANGELOG.md with release notes.")


if __name__ == "__main__":
    main()
