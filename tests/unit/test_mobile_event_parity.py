"""Unit tests for scripts/validate_mobile_event_parity.py.

Exercises the core diff functions (`diff_event_types`, `diff_purpose_values`)
directly against in-memory event-type/purpose sets so the drift-detection path
is covered without depending on the live native SDK files
(packages/ios/.../Aether.swift, packages/android/.../Aether.kt). The native
event-type + consent-purpose regions are now marker-delimited generated regions
(scripts/generate_contracts.py, WS-A6) and are byte-stable between reviews;
these tests stay in-memory so the unit suite is never sensitive to a mid-review
region change. The region generator itself is covered end-to-end by
tests/unit/test_native_event_codegen.py.
"""

from __future__ import annotations

import importlib.util
import json
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


def _monkeypatch_full_parity(monkeypatch, mep, registry_types, platform_map):
    """Point every registry/extraction seam main() touches at in-memory data so
    the full main() path is exercised without the live native files. The
    platform's declared key set is derived from the map so a caller can inject
    type-set drift (map missing a registry event) and/or value drift."""
    registry_purposes = {t: "analytics" for t in registry_types}
    key_set = set(platform_map)
    monkeypatch.setattr(mep, "load_registry_types", lambda: set(registry_types))
    monkeypatch.setattr(mep, "load_registry_purposes", lambda: dict(registry_purposes))
    monkeypatch.setattr(mep, "extract_ios_enum_types", lambda path: set(key_set))
    monkeypatch.setattr(mep, "extract_ios_consent_purpose_types", lambda path: set(key_set))
    monkeypatch.setattr(mep, "extract_android_consent_purpose_types", lambda path: set(key_set))
    monkeypatch.setattr(mep, "extract_ios_consent_purpose_map", lambda path: dict(platform_map))
    monkeypatch.setattr(mep, "extract_android_consent_purpose_map", lambda path: dict(platform_map))


def test_main_fails_on_injected_type_drift(mep, monkeypatch):
    """Full main() path with an injected drift case: canonical registry has one
    more type than every native structure reports. All seams monkeypatched, so
    the test never depends on the live native files."""
    registry_types = {"track", "page", "screen", "orphaned_type"}
    platform_map = {"track": "analytics", "page": "analytics", "screen": "analytics"}

    _monkeypatch_full_parity(monkeypatch, mep, registry_types, platform_map)

    assert mep.main() == 1


def test_main_passes_when_all_structures_match_registry(mep, monkeypatch):
    """Full main() path with an in-memory good case: registry and all three
    native structures agree exactly on keys and per-event purpose."""
    registry_types = {"track", "page", "screen", "identify"}
    platform_map = {t: "analytics" for t in registry_types}

    _monkeypatch_full_parity(monkeypatch, mep, registry_types, platform_map)

    assert mep.main() == 0


def test_main_fails_on_injected_purpose_value_drift(mep, monkeypatch):
    """Regression test for the WS-A6 value-drift class: a native map re-gates a
    single event to a laxer purpose (e.g. ``agent`` instead of
    ``financial_activity``) while every type key is present. The type-set diff
    cannot see this; the purpose-value diff must make main() fail."""
    registry_types = {"track", "page", "screen", "agent_trade_order_observed"}
    good_purposes = {
        "track": "analytics",
        "page": "analytics",
        "screen": "analytics",
        "agent_trade_order_observed": "financial_activity",
    }
    lax_map = dict(good_purposes)
    lax_map["agent_trade_order_observed"] = "agent"  # the 5-event bug shape

    _monkeypatch_full_parity(monkeypatch, mep, registry_types, lax_map)
    monkeypatch.setattr(mep, "load_registry_purposes", lambda: dict(good_purposes))

    assert mep.main() == 1


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


# --- purpose-value extraction + diff (WS-A6 value-aware backstop) -----------


def test_extract_ios_consent_purpose_map_parses_type_purpose_values(mep, tmp_path):
    swift_src = tmp_path / "Aether.swift"
    swift_src.write_text(
        "private static let eventConsentPurpose: [AetherEventType: String] = [\n"
        "    // grouped comment\n"
        "    .track: \"analytics\",\n"
        "    .agent_trade_order_observed: \"financial_activity\",\n"
        "    .consent: \"analytics\"\n"
        "]\n"
    )
    assert mep.extract_ios_consent_purpose_map(swift_src) == {
        "track": "analytics",
        "agent_trade_order_observed": "financial_activity",
        "consent": "analytics",
    }


def test_extract_android_consent_purpose_map_parses_type_purpose_values(mep, tmp_path):
    kotlin_src = tmp_path / "Aether.kt"
    kotlin_src.write_text(
        "private val EVENT_CONSENT_PURPOSE = mapOf(\n"
        "    \"track\" to \"analytics\",\n"
        "    \"agent_trade_order_observed\" to \"financial_activity\"\n"
        ")\n"
    )
    assert mep.extract_android_consent_purpose_map(kotlin_src) == {
        "track": "analytics",
        "agent_trade_order_observed": "financial_activity",
    }


def test_purpose_values_matching_produce_no_drift(mep):
    registry = {"track": "analytics", "consent": "analytics"}
    platform = {"track": "analytics", "consent": "analytics"}
    assert mep.diff_purpose_values("iOS eventConsentPurpose map", registry, platform) == []


def test_purpose_value_drift_reported(mep):
    """The concrete WS-A6 bug: an event gated ``agent`` in the native map while
    the registry primary purpose is ``financial_activity``."""
    registry = {"agent_trade_order_observed": "financial_activity"}
    platform = {"agent_trade_order_observed": "agent"}
    errors = mep.diff_purpose_values("Android EVENT_CONSENT_PURPOSE map", registry, platform)
    assert len(errors) == 1
    assert "agent_trade_order_observed" in errors[0]
    assert "'agent'" in errors[0]
    assert "financial_activity" in errors[0]


def test_purpose_value_ignores_platform_extra_events(mep):
    """Events present only on the platform (not in the registry) are reported by
    the type-set diff, never the purpose-value diff."""
    registry = {"track": "analytics"}
    platform = {"track": "analytics", "ghost_event": "analytics"}
    assert mep.diff_purpose_values("iOS eventConsentPurpose map", registry, platform) == []


def test_load_registry_purposes_defaults_empty_to_analytics(mep, monkeypatch, tmp_path):
    """The registry-purpose loader must apply the SAME primary-purpose rule as
    scripts/generate_contracts.py._primary_purpose (requiredPurposes[0],
    defaulting to analytics) so the value backstop and the generator can never
    disagree about an event's consent gating."""
    fake_registry = tmp_path / "event-registry.json"
    fake_registry.write_text(
        json.dumps(
            {
                "events": [
                    {"type": "with_primary", "requiredPurposes": ["financial_activity", "analytics"]},
                    {"type": "empty_list", "requiredPurposes": []},
                    {"type": "missing_key"},
                ]
            }
        )
    )
    monkeypatch.setattr(mep, "REGISTRY_JSON", fake_registry)
    assert mep.load_registry_purposes() == {
        "with_primary": "financial_activity",
        "empty_list": "analytics",
        "missing_key": "analytics",
    }
