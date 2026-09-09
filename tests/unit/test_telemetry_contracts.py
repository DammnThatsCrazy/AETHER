from __future__ import annotations

import pytest

from scripts.lib.telemetry import (
    TelemetryContractError,
    load_registry,
    validate_envelope,
)


def _route_payload() -> dict:
    return {
        "changed_files": ["scripts/impact_graph.py"],
        "affected_domains": ["delivery"],
        "minimum_lane": "pr",
        "selected_lane": "pr",
        "followup_required": False,
        "selected_checks": ["toolchain"],
        "affected_tests": ["root"],
        "global_change": False,
    }


def test_canonical_telemetry_registry_builds_a_deterministic_valid_envelope():
    registry = load_registry()
    envelope = registry.build_event(
        "verification.route.evaluated",
        _route_payload(),
        event_id_value="tel_test_route",
        occurred_at="2026-09-07T20:00:00+00:00",
    )
    validate_envelope(envelope, registry)
    assert envelope["producer"] == "scripts/check_router.py"
    assert envelope["data"] == _route_payload()


def test_telemetry_rejects_unknown_and_missing_fields():
    registry = load_registry()
    with pytest.raises(TelemetryContractError, match="unknown field"):
        registry.validate_payload(
            "verification.route.evaluated", {**_route_payload(), "secret": "nope"}
        )
    with pytest.raises(TelemetryContractError, match="missing required"):
        registry.validate_payload("verification.route.evaluated", {"changed_files": []})


def test_telemetry_rejects_invalid_enum_and_envelope_fields():
    registry = load_registry()
    with pytest.raises(TelemetryContractError, match="must be one of"):
        registry.validate_payload(
            "verification.route.evaluated", {**_route_payload(), "selected_lane": "unknown"}
        )
    with pytest.raises(TelemetryContractError, match="unknown key"):
        validate_envelope(
            {
                "schema_version": 1,
                "event_name": "verification.route.evaluated",
                "data": {},
                "extra": True,
            },
            registry,
        )


def test_telemetry_rejects_unregistered_producer_override():
    registry = load_registry()
    with pytest.raises(TelemetryContractError, match="producer override"):
        registry.build_event(
            "verification.route.evaluated",
            _route_payload(),
            producer="untrusted-script.py",
        )
