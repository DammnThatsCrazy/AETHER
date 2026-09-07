#!/usr/bin/env python3
"""Validate that the iOS and Android event/consent-purpose regions are in sync
with the canonical event-registry.json.

The iOS ``AetherEventType`` enum, the iOS ``eventConsentPurpose`` dict, and the
Android ``EVENT_CONSENT_PURPOSE`` map are marker-delimited regions inside the
hand-authored Aether.swift/Aether.kt, generated from the event registry by
``scripts/generate_contracts.py`` (WS-A6). ``generate_contracts.py --check`` is
the primary drift gate over them. This script is the set + per-event
primary-purpose-value parity backstop over the same three surfaces: it diffs
each region's declared event-type set AND each event's consent purpose against
the canonical registry and fails CI when they disagree, independent of the
generator path. The purpose-value comparison exists because the canonical gate
(repo-doctor) does not itself invoke the generator --check, so a hand-edit that
re-gates a single event to a laxer purpose (e.g. ``agent`` instead of
``financial_activity``) must still be caught here.

Checked structures:
  - iOS   packages/ios/Sources/AetherSDK/Aether.swift
          `enum AetherEventType` cases
          `eventConsentPurpose` dictionary keys + values
  - Android packages/android/src/main/java/com/aether/sdk/Aether.kt
          `EVENT_CONSENT_PURPOSE` map keys + values

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


def load_registry_purposes() -> dict[str, str]:
    """Primary consent purpose per event, using the SAME derivation rule as
    scripts/generate_contracts.py._primary_purpose: requiredPurposes[0],
    defaulting to \"analytics\" when the list is empty or absent."""
    data = json.loads(REGISTRY_JSON.read_text())
    return {e["type"]: (e.get("requiredPurposes") or ["analytics"])[0] for e in data["events"]}


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


def extract_ios_consent_purpose_map(path: Path) -> dict[str, str]:
    """Extract the full ``event`` -> purpose mapping from the iOS
    ``eventConsentPurpose`` dictionary body (each entry is one
    ``.type: "purpose",`` line)."""
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
    mapping = {m: p for m, p in re.findall(r"\.([a-zA-Z0-9_]+)\s*:\s*\"([^\"]+)\"", block)}
    if not mapping:
        print(f"ERROR: `eventConsentPurpose` map in {path} yielded no entries", file=sys.stderr)
        sys.exit(1)
    return mapping


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


def extract_android_consent_purpose_map(path: Path) -> dict[str, str]:
    """Extract the full ``"type" -> purpose`` mapping from the Android
    ``EVENT_CONSENT_PURPOSE`` mapOf body (each entry is one
    ``"type" to "purpose",`` line)."""
    text = path.read_text()
    match = re.search(r"EVENT_CONSENT_PURPOSE\s*=\s*mapOf\(\s*(.*?)\n\s*\)", text, re.DOTALL)
    if not match:
        print(f"ERROR: Could not find `EVENT_CONSENT_PURPOSE` map in {path}", file=sys.stderr)
        sys.exit(1)
    block = match.group(1)
    mapping = dict(re.findall(r'"([a-z0-9_]+)"\s+to\s+"([^"]+)"', block))
    if not mapping:
        print(f"ERROR: `EVENT_CONSENT_PURPOSE` map in {path} yielded no entries", file=sys.stderr)
        sys.exit(1)
    return mapping


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


def diff_purpose_values(
    label: str, registry_purposes: dict[str, str], platform_purposes: dict[str, str]
) -> list[str]:
    """Compare each platform-side event's primary consent purpose against the
    registry. Only events present in the registry are compared (membership drift
    is already reported by diff_event_types); a mismatch means the event would be
    gated under the wrong purpose at runtime. Returns drift-description lines."""
    errors: list[str] = []
    for event in sorted(platform_purposes):
        expected = registry_purposes.get(event)
        if expected is None:
            continue  # membership drift reported by the type-set diff
        actual = platform_purposes[event]
        if actual != expected:
            errors.append(
                f"  [{label}] {event}: purpose '{actual}' != registry primary '{expected}'"
            )
    return errors


def main() -> int:
    registry_types = load_registry_types()
    registry_purposes = load_registry_purposes()
    ios_enum_types = extract_ios_enum_types(IOS_SOURCE)
    ios_purpose_types = extract_ios_consent_purpose_types(IOS_SOURCE)
    android_purpose_types = extract_android_consent_purpose_types(ANDROID_SOURCE)
    ios_purpose_map = extract_ios_consent_purpose_map(IOS_SOURCE)
    android_purpose_map = extract_android_consent_purpose_map(ANDROID_SOURCE)

    platforms = [
        ("iOS AetherEventType enum", ios_enum_types),
        ("iOS eventConsentPurpose map", ios_purpose_types),
        ("Android EVENT_CONSENT_PURPOSE map", android_purpose_types),
    ]

    errors: list[str] = []
    for label, platform_types in platforms:
        errors.extend(diff_event_types(label, registry_types, platform_types))
    for label, platform_purposes in [
        ("iOS eventConsentPurpose map", ios_purpose_map),
        ("Android EVENT_CONSENT_PURPOSE map", android_purpose_map),
    ]:
        errors.extend(diff_purpose_values(label, registry_purposes, platform_purposes))

    if errors:
        print("DRIFT: mobile event/consent-purpose parity out of sync:", file=sys.stderr)
        for e in errors:
            print(e, file=sys.stderr)
        print(f"\n  Registry: {REGISTRY_JSON}", file=sys.stderr)
        print(f"  iOS:      {IOS_SOURCE}", file=sys.stderr)
        print(f"  Android:  {ANDROID_SOURCE}", file=sys.stderr)
        print(
            "\nThe iOS AetherEventType enum, iOS eventConsentPurpose map, and Android "
            "EVENT_CONSENT_PURPOSE map are generated regions: scripts/generate_contracts.py "
            "splices them from packages/shared/contracts/event-registry.json. Re-run\n"
            "  python scripts/generate_contracts.py\nto regenerate them; hand-editing the "
            "regions is not supported.",
            file=sys.stderr,
        )
        return 1

    print(
        f"OK: mobile event-type + consent-purpose parity confirmed "
        f"({len(registry_types)} types in registry; iOS enum, iOS eventConsentPurpose, "
        f"and Android EVENT_CONSENT_PURPOSE all match on keys and per-event purpose)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
