"""Unit tests for scripts/validate_mobile_event_parity.py.

Exercises the core diff function (`diff_event_types`) directly against
in-memory event-type sets so the drift-detection path is covered without
depending on the live native SDK files (packages/ios/.../Aether.swift,
packages/android/.../Aether.kt) — those files may legitimately drift from
the canonical registry between reviews, and this test must not be sensitive
to that drift.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "validate_mobile_event_parity.py"


@pytest.fixture(scope="module")
def mep():
    spec = importlib.util.spec_from_file_location("validate_mobile_event_parity", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["validate_mobile_event_parity"] = module
    spec.loader.exec_module(module)
    return module


# --- diff_event_types (core diff function) ---------------------------------


def test_matching_sets_produce_no_drift(mep):
    registry_types = {"track", "page", "screen", "identify"}
    platform_types = {"track", "page", "screen", "identify"}
    assert mep.diff_event_types("iOS AetherEventType enum", registry_types, platform_types) == []


def test_platform_missing_registry_type_reports_drift(mep):
    """A type present in the canonical registry but absent from the native
    map (the real-world shape of the current iOS/Android drift) must be
    reported as missing-from-platform."""
    registry_types = {"track", "page", "message_received_observed"}
    platform_types = {"track", "page"}
    errors = mep.diff_event_types("Android EVENT_CONSENT_PURPOSE map", registry_types, platform_types)
    assert len(errors) == 1
    assert "In registry only" in errors[0]
    assert "message_received_observed" in errors[0]
    assert "Android EVENT_CONSENT_PURPOSE map" in errors[0]


def test_platform_extra_type_not_in_registry_reports_drift(mep):
    """A type present in the native map but not declared in the canonical
    registry must be reported as extra."""
    registry_types = {"track", "page"}
    platform_types = {"track", "page", "made_up_event_type"}
    errors = mep.diff_event_types("iOS eventConsentPurpose map", registry_types, platform_types)
    assert len(errors) == 1
    assert "only (not in registry)" in errors[0]
    assert "made_up_event_type" in errors[0]


def test_drift_in_both_directions_reports_both(mep):
    registry_types = {"track", "page", "missing_from_platform"}
    platform_types = {"track", "page", "extra_on_platform"}
    errors = mep.diff_event_types("Android EVENT_CONSENT_PURPOSE map", registry_types, platform_types)
    assert len(errors) == 2
    joined = "\n".join(errors)
    assert "missing_from_platform" in joined
    assert "extra_on_platform" in joined


# --- main() end-to-end over injected (non-live-file) data ------------------


def test_main_fails_on_injected_drift(mep, monkeypatch):
    """Full main() path with an injected drift case: canonical registry has
    one more type than every native structure reports. Must not depend on
    the live native files, so all extraction functions are monkeypatched."""
    registry_types = {"track", "page", "screen", "orphaned_type"}
    good_subset = {"track", "page", "screen"}

    monkeypatch.setattr(mep, "load_registry_types", lambda: registry_types)
    monkeypatch.setattr(mep, "extract_ios_enum_types", lambda path: set(good_subset))
    monkeypatch.setattr(mep, "extract_ios_consent_purpose_types", lambda path: set(good_subset))
    monkeypatch.setattr(mep, "extract_android_consent_purpose_types", lambda path: set(good_subset))

    assert mep.main() == 1


def test_main_passes_when_all_structures_match_registry(mep, monkeypatch):
    """Full main() path with an in-memory good case: registry and all three
    native structures agree exactly."""
    registry_types = {"track", "page", "screen", "identify"}

    monkeypatch.setattr(mep, "load_registry_types", lambda: registry_types)
    monkeypatch.setattr(mep, "extract_ios_enum_types", lambda path: set(registry_types))
    monkeypatch.setattr(mep, "extract_ios_consent_purpose_types", lambda path: set(registry_types))
    monkeypatch.setattr(mep, "extract_android_consent_purpose_types", lambda path: set(registry_types))

    assert mep.main() == 0


# --- extraction functions (regex parsing) over synthetic source snippets ---


def test_extract_ios_enum_types_parses_case_lists(mep, tmp_path):
    swift_src = tmp_path / "Aether.swift"
    swift_src.write_text(
        "public enum AetherEventType: String, Codable, CaseIterable {\n"
        "    case track, page, screen\n"
        "    // a comment line\n"
        "    case identify, consent\n"
        "}\n"
    )
    types = mep.extract_ios_enum_types(swift_src)
    assert types == {"track", "page", "screen", "identify", "consent"}


def test_extract_ios_consent_purpose_types_parses_dict_keys(mep, tmp_path):
    swift_src = tmp_path / "Aether.swift"
    swift_src.write_text(
        "private static let eventConsentPurpose: [AetherEventType: String] = [\n"
        "    .track: \"analytics\", .page: \"analytics\",\n"
        "    .consent: \"analytics\"\n"
        "]\n"
    )
    types = mep.extract_ios_consent_purpose_types(swift_src)
    assert types == {"track", "page", "consent"}


def test_extract_android_consent_purpose_types_parses_map_keys(mep, tmp_path):
    kotlin_src = tmp_path / "Aether.kt"
    kotlin_src.write_text(
        "private val EVENT_CONSENT_PURPOSE = mapOf(\n"
        "    \"track\" to \"analytics\", \"page\" to \"analytics\",\n"
        "    \"consent\" to \"analytics\"\n"
        ")\n"
    )
    types = mep.extract_android_consent_purpose_types(kotlin_src)
    assert types == {"track", "page", "consent"}


def test_extract_ios_enum_types_missing_enum_exits(mep, tmp_path):
    swift_src = tmp_path / "Aether.swift"
    swift_src.write_text("// no enum here\n")
    with pytest.raises(SystemExit) as exc_info:
        mep.extract_ios_enum_types(swift_src)
    assert exc_info.value.code == 1
