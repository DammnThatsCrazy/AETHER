"""Unit tests for the WS-A6 native event-type / consent-purpose codegen.

scripts/generate_contracts.py emits three native regions from
packages/shared/contracts/event-registry.json: the iOS ``AetherEventType`` enum,
the iOS ``eventConsentPurpose`` dict, and the Android ``EVENT_CONSENT_PURPOSE``
map. These tests hold the emitters honest without depending on the live native
SDK files (which are byte-stable between reviews now that they are generated):
each generated section, wrapped in the surrounding hand-authored declaration the
generator splices into, must parse with validate_mobile_event_parity.py's
extractors to exactly the canonical registry's event set and per-event primary
purpose. The suite also pins byte-stability, registry-order preservation, the
``analytics`` default for events with no required purposes, and the marker
splice mechanics (_splice_region + the three _apply_* writers).
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
REGISTRY_JSON = ROOT / "packages" / "shared" / "contracts" / "event-registry.json"
GEN_SCRIPT = ROOT / "scripts" / "generate_contracts.py"
PARITY_SCRIPT = ROOT / "scripts" / "validate_mobile_event_parity.py"


def _load_module(script: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gen():
    return _load_module(GEN_SCRIPT, "generate_contracts")


@pytest.fixture(scope="module")
def parity():
    return _load_module(PARITY_SCRIPT, "validate_mobile_event_parity")


@pytest.fixture(scope="module")
def event_reg():
    return json.loads(REGISTRY_JSON.read_text())


def _registry_set(event_reg) -> set[str]:
    return {e["type"] for e in event_reg["events"]}


def _registry_purposes(event_reg) -> dict[str, str]:
    """Canonical primary purpose derivation, written out independently of the
    generator/validator so a drift in either implementation fails here."""
    return {e["type"]: (e.get("requiredPurposes") or ["analytics"])[0] for e in event_reg["events"]}


# --- generator output satisfies the parity gate (real registry) -------------


def _wrap_ios(gen, event_reg) -> str:
    return (
        "public enum AetherEventType: String, Codable, CaseIterable {\n"
        + gen.gen_ios_event_enum_section(event_reg)
        + "}\n"
        "private static let eventConsentPurpose: [AetherEventType: String] = [\n"
        + gen.gen_ios_consent_map_section(event_reg)
        + "]\n"
    )


def _wrap_android(gen, event_reg) -> str:
    return (
        "private val EVENT_CONSENT_PURPOSE = mapOf(\n"
        + gen.gen_android_consent_map_section(event_reg)
        + ")\n"
    )


def test_ios_regions_parse_to_registry_keys_and_purposes(gen, parity, event_reg, tmp_path):
    swift_src = tmp_path / "Aether.swift"
    swift_src.write_text(_wrap_ios(gen, event_reg))

    expected_set = _registry_set(event_reg)
    assert parity.extract_ios_enum_types(swift_src) == expected_set
    assert parity.extract_ios_consent_purpose_types(swift_src) == expected_set
    assert parity.extract_ios_consent_purpose_map(swift_src) == _registry_purposes(event_reg)


def test_android_region_parses_to_registry_keys_and_purposes(gen, parity, event_reg, tmp_path):
    kotlin_src = tmp_path / "Aether.kt"
    kotlin_src.write_text(_wrap_android(gen, event_reg))

    assert parity.extract_android_consent_purpose_types(kotlin_src) == _registry_set(event_reg)
    assert parity.extract_android_consent_purpose_map(kotlin_src) == _registry_purposes(event_reg)


def test_generated_regions_are_byte_stable(gen, event_reg):
    ios_enum = gen.gen_ios_event_enum_section(event_reg)
    ios_map = gen.gen_ios_consent_map_section(event_reg)
    android_map = gen.gen_android_consent_map_section(event_reg)
    for _ in range(2):
        assert gen.gen_ios_event_enum_section(event_reg) == ios_enum
        assert gen.gen_ios_consent_map_section(event_reg) == ios_map
        assert gen.gen_android_consent_map_section(event_reg) == android_map


def _grouped_registry_order(gen, event_reg) -> list[str]:
    """The order the generator actually emits: family first-seen (registry)
    order, and registry order within each family. The raw registry array is NOT
    family-contiguous (28 switches across 25 families), so this grouped
    flattening — not the raw array — is the byte-stable ordering contract."""
    family_order, by_family = gen._registry_family_groups(event_reg["events"])
    return [e["type"] for family in family_order for e in by_family[family]]


def test_ios_enum_case_order_matches_grouped_registry_order(gen, event_reg):
    """Case rows pack events in grouped registry order with no loss or dup."""
    section = gen.gen_ios_event_enum_section(event_reg)
    tokens: list[str] = []
    for line in section.splitlines():
        if line.startswith("    case "):
            tokens.extend(t.strip() for t in line[len("    case "):].split(","))
    assert tokens == _grouped_registry_order(gen, event_reg)


def test_map_entry_order_matches_grouped_registry_order(gen, event_reg):
    expected = _grouped_registry_order(gen, event_reg)

    ios_keys: list[str] = []
    for line in gen.gen_ios_consent_map_section(event_reg).splitlines():
        m = re.match(r"\s+\.([a-zA-Z0-9_]+)\s*:", line)
        if m:
            ios_keys.append(m.group(1))
    assert ios_keys == expected

    android_keys: list[str] = []
    for line in gen.gen_android_consent_map_section(event_reg).splitlines():
        m = re.match(r'\s+"([a-z0-9_]+)"\s+to\s+"', line)
        if m:
            android_keys.append(m.group(1))
    assert android_keys == expected


def test_family_comments_appear_in_registry_family_order(gen, event_reg):
    family_order, _ = gen._registry_family_groups(event_reg["events"])

    for section_gen, marker in [
        (gen.gen_ios_event_enum_section, "    // "),
        (gen.gen_ios_consent_map_section, "        // "),
        (gen.gen_android_consent_map_section, "        // "),
    ]:
        seen: list[str] = []
        for line in section_gen(event_reg).splitlines():
            if line.startswith(marker):
                seen.append(line[len(marker):].strip())
        assert seen == family_order


# --- synthetic registry: default purpose + small-case parity -----------------


def test_primary_purpose_rule_and_analytics_default(gen):
    assert gen._primary_purpose({"requiredPurposes": ["financial_activity"]}) == "financial_activity"
    assert gen._primary_purpose({"requiredPurposes": ["financial_activity", "analytics"]}) == "financial_activity"
    assert gen._primary_purpose({"requiredPurposes": []}) == "analytics"
    assert gen._primary_purpose({"type": "no_purposes"}) == "analytics"


def test_synthetic_regions_parse_parity_green(gen, parity, tmp_path):
    """Small controlled registry exercises the analytics default and proves the
    generator output and the parity extractors agree on a tiny surface."""
    reg = {
        "contractVersion": "9.0.0",
        "events": [
            {"type": "alpha", "family": "core", "requiredPurposes": ["analytics"]},
            {"type": "beta", "family": "core", "requiredPurposes": ["financial_activity", "analytics"]},
            {"type": "gamma", "family": "privacy", "requiredPurposes": []},
        ],
    }

    swift_src = tmp_path / "Aether.swift"
    swift_src.write_text(_wrap_ios(gen, reg))
    kotlin_src = tmp_path / "Aether.kt"
    kotlin_src.write_text(_wrap_android(gen, reg))

    expected = {"alpha": "analytics", "beta": "financial_activity", "gamma": "analytics"}
    assert parity.extract_ios_enum_types(swift_src) == {"alpha", "beta", "gamma"}
    assert parity.extract_ios_consent_purpose_map(swift_src) == expected
    assert parity.extract_android_consent_purpose_map(kotlin_src) == expected
    assert "Contract version: 9.0.0" in swift_src.read_text()


# --- marker splice mechanics -------------------------------------------------


def test_splice_region_replaces_body_between_markers(gen):
    current = (
        "public enum AetherEventType: String, Codable, CaseIterable {\n"
        "// @generated-start t\n"
        "        case stale, drift\n"
        "// @generated-end t\n"
        "}\n"
    )
    updated = gen._splice_region(current, "// @generated-start t", "// @generated-end t", "    case fresh\n", "enum")
    assert updated == (
        "public enum AetherEventType: String, Codable, CaseIterable {\n"
        "// @generated-start t\n"
        "    case fresh\n"
        "// @generated-end t\n"
        "}\n"
    )


def test_splice_region_missing_marker_exits(gen):
    with pytest.raises(SystemExit) as exc_info:
        gen._splice_region("// nothing here\n", "// @generated-start t", "// @generated-end t", "x\n", "enum")
    assert exc_info.value.code == 1


def test_splice_region_misordered_markers_exit(gen):
    current = "// @generated-end t\n// @generated-start t\n"
    with pytest.raises(SystemExit) as exc_info:
        gen._splice_region(current, "// @generated-start t", "// @generated-end t", "x\n", "enum")
    assert exc_info.value.code == 1


def test_apply_writers_splice_real_registry_and_are_idempotent(gen, parity, event_reg, tmp_path, monkeypatch):
    """End-to-end writer path: seeded marker regions with a stale body get
    replaced by the real-registry output, and a follow-up --check run is clean."""
    ios = tmp_path / "Aether.swift"
    ios.write_text(
        "public enum AetherEventType: String, Codable, CaseIterable {\n"
        f"{gen.IOS_EVENT_ENUM_START}\n        case stale\n{gen.IOS_EVENT_ENUM_END}\n"
        "}\n"
        "private static let eventConsentPurpose: [AetherEventType: String] = [\n"
        f"{gen.IOS_CONSENT_MAP_START}\n        .stale: \"analytics\"\n{gen.IOS_CONSENT_MAP_END}\n"
        "]\n"
    )
    android = tmp_path / "Aether.kt"
    android.write_text(
        "private val EVENT_CONSENT_PURPOSE = mapOf(\n"
        f"{gen.ANDROID_CONSENT_MAP_START}\n        \"stale\" to \"analytics\"\n{gen.ANDROID_CONSENT_MAP_END}\n"
        ")\n"
    )
    monkeypatch.setattr(gen, "IOS_AETHER_SWIFT", ios)
    monkeypatch.setattr(gen, "ANDROID_AETHER_KT", android)
    # _apply_* print the written file via .relative_to(ROOT); point ROOT at the
    # tmp dir so the tmp files are inside it (in production ROOT owns them).
    monkeypatch.setattr(gen, "ROOT", tmp_path)

    diffs: list[str] = []
    gen._apply_ios_event_enum(event_reg, check=False, diffs=diffs)
    gen._apply_ios_consent_map(event_reg, check=False, diffs=diffs)
    gen._apply_android_consent_map(event_reg, check=False, diffs=diffs)
    assert diffs == []

    expected_set = _registry_set(event_reg)
    expected_purposes = _registry_purposes(event_reg)
    assert parity.extract_ios_enum_types(ios) == expected_set
    assert parity.extract_ios_consent_purpose_map(ios) == expected_purposes
    assert parity.extract_android_consent_purpose_map(android) == expected_purposes

    ios_text = ios.read_text()
    assert "case stale" not in ios_text
    assert ".stale:" not in ios_text
    assert gen.IOS_EVENT_ENUM_START in ios_text and gen.IOS_EVENT_ENUM_END in ios_text
    assert gen.IOS_CONSENT_MAP_START in ios_text and gen.IOS_CONSENT_MAP_END in ios_text
    assert '"stale" to "analytics"' not in android.read_text()

    # Idempotent: --check over the just-written regions reports nothing.
    diffs2: list[str] = []
    gen._apply_ios_event_enum(event_reg, check=True, diffs=diffs2)
    gen._apply_ios_consent_map(event_reg, check=True, diffs=diffs2)
    gen._apply_android_consent_map(event_reg, check=True, diffs=diffs2)
    assert diffs2 == []
