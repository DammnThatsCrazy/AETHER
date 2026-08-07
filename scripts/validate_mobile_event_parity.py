#!/usr/bin/env python3
"""Validate that the hand-maintained iOS and Android event/consent-purpose maps
are in sync with the canonical event-registry.json.

This is a *parity* gate, not a codegen step: per scripts/validate_sdk_parity.py's
documented non-goal ("no generated native registries"), native SDK source files
are never written by tooling here. iOS (Swift) and Android (Kotlin) event maps
stay hand-maintained; this script only diffs their declared event-type sets
against the canonical registry and fails CI when they drift.

Checked structures:
  - iOS   packages/ios/Sources/AetherSDK/Aether.swift
          `enum AetherEventType` cases
          `eventConsentPurpose` dictionary keys
  - Android packages/android/src/main/java/com/aether/sdk/Aether.kt
          `EVENT_CONSENT_PURPOSE` map keys

Mirrors scripts/validate_event_schema_parity.py's extraction/diff/CLI style.

Exits 0 on success, 1 on drift.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

REGISTRY_JSON = ROOT / "packages" / "shared" / "contracts" / "event-registry.json"
IOS_SOURCE = ROOT / "packages" / "ios" / "Sources" / "AetherSDK" / "Aether.swift"
ANDROID_SOURCE = ROOT / "packages" / "android" / "src" / "main" / "java" / "com" / "aether" / "sdk" / "Aether.kt"


def load_registry_types() -> set[str]:
    data = json.loads(REGISTRY_JSON.read_text())
    return {e["type"] for e in data["events"]}


def _strip_line_comment(line: str) -> str:
    return line.split("//", 1)[0]


def extract_ios_enum_types(path: Path) -> set[str]:
    """Extract case identifiers from `enum AetherEventType: String, Codable,
    CaseIterable { ... }`. Each body line is either a `case a, b, c` list or a
    `//` comment; there are no nested braces inside the enum body, so the first
    `\n}` after the opening brace closes it."""
    text = path.read_text()
    match = re.search(r"enum AetherEventType[^{]*\{(.*?)\n\}", text, re.DOTALL)
    if not match:
        print(f"ERROR: Could not find `enum AetherEventType` in {path}", file=sys.stderr)
        sys.exit(1)
    block = match.group(1)
    types: set[str] = set()
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line.startswith("case "):
            continue
        line = _strip_line_comment(line)
        rest = line[len("case "):]
        for part in rest.split(","):
            part = part.strip().rstrip(",")
            if part:
                types.add(part)
    if not types:
        print(f"ERROR: `enum AetherEventType` in {path} yielded no cases", file=sys.stderr)
        sys.exit(1)
    return types


def extract_ios_consent_purpose_types(path: Path) -> set[str]:
    """Extract keys from `private static let eventConsentPurpose: [AetherEventType:
    String] = [ .type: "purpose", ... ]`."""
    text = path.read_text()
    match = re.search(
        r"eventConsentPurpose\s*:\s*\[AetherEventType\s*:\s*String\]\s*=\s*\[(.*?)\n\s*\]",
        text,
        re.DOTALL,
    )
    if not match:
        print(f"ERROR: Could not find `eventConsentPurpose` map in {path}", file=sys.stderr)
        sys.exit(1)
    block = match.group(1)
    types = {m.strip() for m in re.findall(r"\.([a-zA-Z0-9_]+)\s*:", block)}
    if not types:
        print(f"ERROR: `eventConsentPurpose` map in {path} yielded no keys", file=sys.stderr)
        sys.exit(1)
    return types


def extract_android_consent_purpose_types(path: Path) -> set[str]:
    """Extract keys from `private val EVENT_CONSENT_PURPOSE = mapOf("type" to
    "purpose", ...)`."""
    text = path.read_text()
    match = re.search(r"EVENT_CONSENT_PURPOSE\s*=\s*mapOf\(\s*(.*?)\n\s*\)", text, re.DOTALL)
    if not match:
        print(f"ERROR: Could not find `EVENT_CONSENT_PURPOSE` map in {path}", file=sys.stderr)
        sys.exit(1)
    block = match.group(1)
    types = set(re.findall(r'"([a-z0-9_]+)"\s+to\s+"', block))
    if not types:
        print(f"ERROR: `EVENT_CONSENT_PURPOSE` map in {path} yielded no keys", file=sys.stderr)
        sys.exit(1)
    return types


def diff_event_types(label: str, registry_types: set[str], platform_types: set[str]) -> list[str]:
    """Core diff: compare one platform-side event-type set against the
    canonical registry set in both directions. Returns a list of
    drift-description lines (empty when the two sets match)."""
    errors: list[str] = []
    only_in_platform = platform_types - registry_types
    only_in_registry = registry_types - platform_types
    if only_in_platform:
        errors.append(f"  [{label}] In {label} only (not in registry): {sorted(only_in_platform)}")
    if only_in_registry:
        errors.append(f"  [{label}] In registry only (missing from {label}): {sorted(only_in_registry)}")
    return errors


def main() -> int:
    registry_types = load_registry_types()
    ios_enum_types = extract_ios_enum_types(IOS_SOURCE)
    ios_purpose_types = extract_ios_consent_purpose_types(IOS_SOURCE)
    android_purpose_types = extract_android_consent_purpose_types(ANDROID_SOURCE)

    platforms = [
        ("iOS AetherEventType enum", ios_enum_types),
        ("iOS eventConsentPurpose map", ios_purpose_types),
        ("Android EVENT_CONSENT_PURPOSE map", android_purpose_types),
    ]

    errors: list[str] = []
    for label, platform_types in platforms:
        errors.extend(diff_event_types(label, registry_types, platform_types))

    if errors:
        print("DRIFT: mobile event-type parity out of sync:", file=sys.stderr)
        for e in errors:
            print(e, file=sys.stderr)
        print(f"\n  Registry: {REGISTRY_JSON}", file=sys.stderr)
        print(f"  iOS:      {IOS_SOURCE}", file=sys.stderr)
        print(f"  Android:  {ANDROID_SOURCE}", file=sys.stderr)
        print(
            "\nThis gate does NOT generate native code (see scripts/validate_sdk_parity.py's "
            "documented non-goal: no generated native registries). Hand-edit the iOS "
            "enum/eventConsentPurpose map and/or the Android EVENT_CONSENT_PURPOSE map so "
            "their event-type sets match packages/shared/contracts/event-registry.json, "
            "then rerun this script.",
            file=sys.stderr,
        )
        return 1

    print(
        f"OK: mobile event-type parity confirmed ({len(registry_types)} types in registry; "
        f"iOS enum, iOS eventConsentPurpose, and Android EVENT_CONSENT_PURPOSE all match)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
