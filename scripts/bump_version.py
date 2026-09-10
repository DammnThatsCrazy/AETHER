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
    - package.json (root, packages/web, packages/react-native, apps/kyber,
      Data Ingestion Layer, Data Lake Architecture)
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
    ROOT / "packages" / "shared" / "package.json",
    ROOT / "packages" / "config" / "package.json",
    ROOT / "packages" / "web" / "package.json",
    ROOT / "packages" / "react-native" / "package.json",
    ROOT / "packages" / "mobile-core" / "package.json",
    ROOT / "packages" / "mobile-ui" / "package.json",
    ROOT / "packages" / "server" / "package.json",
    ROOT / "apps" / "aether-mobile" / "package.json",
    ROOT / "apps" / "kyber-mobile" / "package.json",
    ROOT / "frontend" / "aether" / "package.json",
    ROOT / "frontend" / "kyber" / "package.json",
    ROOT / "frontend" / "shared" / "package.json",
    ROOT / "frontend" / "docs" / "package.json",
    ROOT / "frontend" / "demo" / "package.json",
    ROOT / "frontend" / "olympus-marketing" / "package.json",
    ROOT / "frontend" / "aether-marketing" / "package.json",
    ROOT / "Data Ingestion Layer" / "package.json",
    ROOT / "Data Ingestion Layer" / "packages" / "common" / "package.json",
    ROOT / "Data Ingestion Layer" / "packages" / "auth" / "package.json",
    ROOT / "Data Ingestion Layer" / "packages" / "cache" / "package.json",
    ROOT / "Data Ingestion Layer" / "packages" / "events" / "package.json",
    ROOT / "Data Ingestion Layer" / "packages" / "logger" / "package.json",
    ROOT / "Data Ingestion Layer" / "services" / "ingestion" / "package.json",
    ROOT / "Data Lake Architecture" / "aether-Datalake-backend" / "package.json",
    ROOT / "Data Lake Architecture" / "aether-Datalake-backend" / "packages" / "auth" / "package.json",
    ROOT / "Data Lake Architecture" / "aether-Datalake-backend" / "packages" / "cache" / "package.json",
    ROOT / "Data Lake Architecture" / "aether-Datalake-backend" / "packages" / "common" / "package.json",
    ROOT / "Data Lake Architecture" / "aether-Datalake-backend" / "packages" / "events" / "package.json",
    ROOT / "Data Lake Architecture" / "aether-Datalake-backend" / "packages" / "logger" / "package.json",
    ROOT / "Data Lake Architecture" / "aether-Datalake-backend" / "services" / "data-lake" / "package.json",
    ROOT / "Data Lake Architecture" / "aether-Datalake-backend" / "services" / "ingestion" / "package.json",
]

# Native SDK version files (different format than package.json)
IOS_PACKAGE_SWIFT = ROOT / "packages" / "ios" / "Package.swift"
ANDROID_BUILD_GRADLE = ROOT / "packages" / "android" / "build.gradle.kts"
PACKAGE_LOCKS = [
    ROOT / "package-lock.json",
    ROOT / "Data Ingestion Layer" / "package-lock.json",
    ROOT / "Data Lake Architecture" / "aether-Datalake-backend" / "package-lock.json",
]
EXPO_APP_JSONS = [
    ROOT / "apps" / "aether-mobile" / "app.json",
    ROOT / "apps" / "kyber-mobile" / "app.json",
]

TEXT_VERSION_SURFACES = [
    (ROOT / "packages" / "ios" / "AetherSDK.podspec", r'(s\.version\s*=\s*")[^"]+(".*)', r"\g<1>{version}\g<2>"),
    (ROOT / "packages" / "android" / "gradle.properties", r'(?m)^(sdkVersion=).+$', r"\g<1>{version}"),
    (ROOT / "packages" / "shared" / "sdk-version.ts", r"(SDK_VERSION = ')[^']+(')", r"\g<1>{version}\g<2>"),
    (ROOT / "packages" / "web" / "src" / "index.ts", r"(SDK_VERSION = ')[^']+(')", r"\g<1>{version}\g<2>"),
    (ROOT / "packages" / "web" / "src" / "core" / "event-queue.ts", r"(SDK_VERSION = ')[^']+(')", r"\g<1>{version}\g<2>"),
    (ROOT / "packages" / "web" / "src" / "health" / "sdk-health-agent.ts", r"(SDK_VERSION = ')[^']+(')", r"\g<1>{version}\g<2>"),
    (ROOT / "packages" / "react-native" / "src" / "modules" / "HealthAgent.ts", r"(SDK_VERSION = ')[^']+(')", r"\g<1>{version}\g<2>"),
    (ROOT / "packages" / "react-native" / "src" / "context" / "SemanticContext.ts", r"(version: ')[^']+(')", r"\g<1>{version}\g<2>"),
    (ROOT / "packages" / "shared" / "events-registry.test.ts", r"(SDK_VERSION is )[^']+(')", r"\g<1>{version}\g<2>"),
    (ROOT / "packages" / "shared" / "events-registry.test.ts", r"(expect\(SDK_VERSION\)\.toBe\(')[^']+(')", r"\g<1>{version}\g<2>"),
    (ROOT / "packages" / "react-native" / "src" / "__tests__" / "Observe.test.ts", r"(name: 'aether-react-native', version: ')[^']+(')", r"\g<1>{version}\g<2>"),
]

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
    ROOT / "docs" / "ROLLBACK-RUNBOOK.md",
    ROOT / "docs" / "MIGRATION-RUNBOOK.md",
    ROOT / "docs" / "SMOKE-TEST-CHECKLIST.md",
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

# Packages with intentionally independent versioning. These are checked for
# existence but are not forced to the pyproject.toml platform version.
INDEPENDENT_PACKAGE_JSONS = {
    ROOT / "Smart Contracts" / "package.json",
    ROOT / "playground" / "package.json",
}



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
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    old = data.get("version", "?")
    text = re.sub(r'("version"\s*:\s*")[^"]+("\s*,)', rf'\g<1>{new_version}\g<2>', text, count=1)
    def replace_internal_dependency(match: re.Match[str]) -> str:
        prefix, value, suffix = match.groups()
        if value == "*" or value.startswith(("workspace:", "file:")):
            replacement = value
        elif value.startswith("^"):
            replacement = f"^{new_version}"
        elif value.startswith(">="):
            replacement = f">={new_version} <1.0.0"
        else:
            replacement = new_version
        return f"{prefix}{replacement}{suffix}"

    text = re.sub(
        r'("@aether/[^"]+"\s*:\s*")([^"]+)("\s*[,}])',
        replace_internal_dependency,
        text,
    )
    json.loads(text)
    path.write_text(text, encoding="utf-8")
    print(f"  Updated: {_rel(path)} ({old} -> {new_version})")


def update_expo_app(path: Path, new_version: str) -> None:
    """Update Expo's top-level app version without reformatting app.json."""
    text = path.read_text(encoding="utf-8")
    updated = re.sub(r'("version"\s*:\s*")[^"]+("\s*,)', rf'\g<1>{new_version}\g<2>', text, count=1)
    json.loads(updated)
    path.write_text(updated, encoding="utf-8")
    print(f"  Updated: {_rel(path)} -> {new_version}")


def update_package_lock(path: Path, new_version: str) -> None:
    """Synchronize repo-owned workspace entries in npm's lockfile."""
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = new_version
    packages = data.get("packages", {})
    for key, package in packages.items():
        if key == "" or (isinstance(package, dict) and str(package.get("name", "")).startswith("@aether/")):
            package["version"] = new_version
        if not isinstance(package, dict):
            continue
        for field in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            for name, value in package.get(field, {}).items():
                if not name.startswith("@aether/") or not isinstance(value, str):
                    continue
                if value == "*" or value.startswith(("workspace:", "file:")):
                    continue
                if value.startswith("^"):
                    package[field][name] = f"^{new_version}"
                elif value.startswith(">="):
                    package[field][name] = f">={new_version} <1.0.0"
                else:
                    package[field][name] = new_version
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  Updated: {path.relative_to(ROOT)} -> {new_version}")


def update_text_version_surfaces(new_version: str) -> None:
    for path, pattern, replacement in TEXT_VERSION_SURFACES:
        text = path.read_text(encoding="utf-8")
        updated, count = re.subn(pattern, replacement.format(version=new_version), text, count=1)
        if count != 1:
            raise RuntimeError(f"could not update {_rel(path)}")
        path.write_text(updated, encoding="utf-8")
        print(f"  Updated: {path.relative_to(ROOT)} -> {new_version}")


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


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def check_version_alignment() -> int:
    """Validate every repo-owned version surface against pyproject.toml."""
    canonical = read_current_version()
    errors: list[str] = []
    warnings: list[str] = []

    print(f"Current version: {canonical}")
    print("Checking package.json versions against pyproject.toml...")
    for package_json in PACKAGE_JSONS:
        if not package_json.exists():
            warnings.append(f"listed package file missing: {_rel(package_json)}")
            continue
        data = json.loads(package_json.read_text(encoding="utf-8"))
        version = data.get("version")
        if version != canonical:
            errors.append(f"{_rel(package_json)} version {version!r} != {canonical!r}")
        for dep_field in ["dependencies", "devDependencies", "peerDependencies"]:
            deps = data.get(dep_field, {})
            if not isinstance(deps, dict):
                continue
            for dep_name, dep_version in deps.items():
                if not dep_name.startswith("@aether/") or not isinstance(dep_version, str):
                    continue
                if dep_version == "*" or dep_version.startswith(("workspace:", "file:")):
                    continue
                if dep_version.startswith("^"):
                    expected = f"^{canonical}"
                elif dep_version.startswith(">="):
                    expected = f">={canonical} <1.0.0"
                else:
                    expected = canonical
                if dep_version != expected:
                    errors.append(f"{_rel(package_json)} {dep_field}.{dep_name} {dep_version!r} != {expected!r}")

    for package_json in sorted(INDEPENDENT_PACKAGE_JSONS):
        if package_json.exists():
            data = json.loads(package_json.read_text(encoding="utf-8"))
            print(f"  independent package: {_rel(package_json)} version {data.get('version', '<missing>')}")

    print("Checking documented version headings...")
    for doc in DOC_HEADERS + README_HEADERS:
        if not doc.exists():
            warnings.append(f"listed doc missing: {_rel(doc)}")
            continue
        first_version_heading = None
        for line in doc.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") and VERSION_PATTERN.search(line):
                first_version_heading = line
                break
        if first_version_heading is None:
            warnings.append(f"listed doc has no versioned heading: {_rel(doc)}")
            continue
        found = VERSION_PATTERN.search(first_version_heading)
        if found and found.group().lstrip("v") != canonical:
            errors.append(f"{_rel(doc)} heading version {found.group()!r} != {canonical!r}")

    native_expectations = {
        ROOT / "packages" / "ios" / "AetherSDK.podspec": [f's.version      = "{canonical}"', f's.version         = "{canonical}"'],
        ROOT / "packages" / "android" / "gradle.properties": [f"sdkVersion={canonical}"],
        ROOT / "packages" / "web" / "src" / "index.ts": [f"SDK_VERSION = '{canonical}'"],
        ROOT / "packages" / "shared" / "sdk-version.ts": [f"SDK_VERSION = '{canonical}'"],
        ROOT / "packages" / "web" / "src" / "core" / "event-queue.ts": [f"SDK_VERSION = '{canonical}'"],
        ROOT / "packages" / "web" / "src" / "health" / "sdk-health-agent.ts": [f"SDK_VERSION = '{canonical}'"],
        ROOT / "packages" / "react-native" / "src" / "modules" / "HealthAgent.ts": [f"SDK_VERSION = '{canonical}'"],
        ROOT / "packages" / "react-native" / "src" / "context" / "SemanticContext.ts": [f"version: '{canonical}'"],
        ROOT / "packages" / "shared" / "events-registry.test.ts": [f"SDK_VERSION is {canonical}", f"toBe('{canonical}')"],
        ROOT / "packages" / "react-native" / "src" / "__tests__" / "Observe.test.ts": [f"name: 'aether-react-native', version: '{canonical}'"],
    }
    print("Checking SDK/native version constants...")
    for path, needles in native_expectations.items():
        if not path.exists():
            warnings.append(f"listed version surface missing: {_rel(path)}")
            continue
        body = path.read_text(encoding="utf-8")
        if not any(needle in body for needle in needles):
            errors.append(f"{_rel(path)} missing synchronized version {canonical}")

    for app_json in EXPO_APP_JSONS:
        version = json.loads(app_json.read_text(encoding="utf-8")).get("expo", {}).get("version")
        if version != canonical:
            errors.append(f"{_rel(app_json)} Expo version {version!r} != {canonical!r}")

    for package_lock in PACKAGE_LOCKS:
        lock = json.loads(package_lock.read_text(encoding="utf-8"))
        if lock.get("version") != canonical or lock.get("packages", {}).get("", {}).get("version") != canonical:
            errors.append(f"{_rel(package_lock)} root version is not synchronized to {canonical!r}")

    for warning in warnings:
        print(f"  warning: {warning}")
    if errors:
        print("Version alignment check failed:")
        for error in errors:
            print(f"  - {error}")
        print(f"\nFix with: python scripts/bump_version.py {canonical}")
        return 1
    print("Version alignment check passed: pyproject.toml, package metadata, docs metadata, and SDK constants are synchronized.")
    return 0


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
        sys.exit(check_version_alignment())

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
    for package_lock in PACKAGE_LOCKS:
        update_package_lock(package_lock, new_version)

    print("\n3. Expo application metadata:")
    for app_json in EXPO_APP_JSONS:
        update_expo_app(app_json, new_version)

    # 3. Doc headers
    print("\n4. Doc headers:")
    for doc in DOC_HEADERS:
        update_doc_header(doc, new_version)

    # 4. README headers
    print("\n5. README headers:")
    for readme in README_HEADERS:
        update_doc_header(readme, new_version)

    # 5. Native SDK versions
    print("\n6. Native SDK versions:")
    update_ios_version(new_version)
    update_android_version(new_version)
    update_text_version_surfaces(new_version)

    print(f"\nDone. Version bumped to {new_version} across all files.")
    print("Remember to update CHANGELOG.md with release notes.")


if __name__ == "__main__":
    main()
