"""TS <-> Python parity for the harness task-profile registry.

`packages/shared/task-profile.ts` and
`shared/model_governance/generated_task_profiles.py` are generated twins of
`packages/shared/contracts/task-profile-registry.json`. This test fails on
drift in the version, the four enum vocabularies, the profile catalog (12
canonical keys per profile, per-index scalar and nested-list parity), routing
consistency, and if the TS module is not exported from the barrel.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from shared.model_governance.generated_task_profiles import (  # noqa: E402
    GUARDRAIL_KINDS,
    MODEL_ROLES,
    OUTPUT_KINDS,
    ROUTING_MODES,
    TASK_PROFILE_REGISTRY_VERSION,
    TASK_PROFILES,
)

TS_PATH = REPO_ROOT / "packages" / "shared" / "task-profile.ts"
REGISTRY_PATH = REPO_ROOT / "packages" / "shared" / "contracts" / "task-profile-registry.json"

_PROFILE_KEYS = frozenset(
    {
        "profileId",
        "version",
        "purpose",
        "modelRole",
        "defaultRoutingMode",
        "allowedRoutingModes",
        "outputKind",
        "guardrails",
        "evidenceRequired",
        "maxTokens",
        "timeoutMs",
        "maxRetries",
    }
)

def _const_array(name: str) -> list[str]:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(rf"{name}[^\[]*\[(.*?)\]\s*as const", text, re.S)
    assert m, f"const array {name!r} not found in task-profile.ts"
    return re.findall(r"'([a-z0-9_]+)'", m.group(1))


def _const_version() -> str:
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(r"taskProfileRegistryVersion\s*=\s*'([^']+)'", text)
    assert m, "taskProfileRegistryVersion not found in task-profile.ts"
    return m.group(1)


def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _profile_objects() -> list[str]:
    """Each TS `{...}` profile literal from the `taskProfiles` block."""
    text = TS_PATH.read_text(encoding="utf-8")
    m = re.search(r"taskProfiles[^\[]*\[(.*?)\]\s*as const", text, re.S)
    assert m, "taskProfiles block not found in task-profile.ts"
    return re.findall(r"\{[^{}]*\}", m.group(1), re.S)


def _field(obj: str, field: str, pattern: str) -> str:
    m = re.search(rf"{field}:\s*({pattern})", obj, re.S)
    assert m, f"field {field!r} not found in TS profile object"
    # The outer `({pattern})` wrapping group plus any captures inside the
    # pattern means the innermost group holds the actual value (e.g. for the
    # `'([^']+)'` string pattern it is the unquoted text).
    return m.groups()[-1]


def _parse_profile_object(obj: str) -> dict:
    def _str(field: str) -> str:
        return _field(obj, field, r"'([^']+)'")

    def _int(field: str) -> int:
        return int(_field(obj, field, r"(\d+)"))

    def _bool(field: str) -> bool:
        return _field(obj, field, r"(true|false)") == "true"

    def _arr(field: str) -> tuple[str, ...]:
        inner = _field(obj, field, r"\[(.*?)\]")
        return tuple(re.findall(r"'([a-z0-9_]+)'", inner))

    return {
        "profileId": _str("profileId"),
        "version": _int("version"),
        "purpose": _str("purpose"),
        "modelRole": _str("modelRole"),
        "defaultRoutingMode": _str("defaultRoutingMode"),
        "allowedRoutingModes": _arr("allowedRoutingModes"),
        "outputKind": _str("outputKind"),
        "guardrails": _arr("guardrails"),
        "evidenceRequired": _bool("evidenceRequired"),
        "maxTokens": _int("maxTokens"),
        "timeoutMs": _int("timeoutMs"),
        "maxRetries": _int("maxRetries"),
    }


def _json_profiles() -> dict[str, dict]:
    """Canonical projection of the JSON `profiles` array keyed by profileId."""
    projection = {}
    for profile in _registry()["profiles"]:
        entry = dict(profile)
        for key in ("allowedRoutingModes", "guardrails"):
            entry[key] = tuple(profile[key])
        projection[profile["profileId"]] = entry
    return projection


def test_task_profile_version_parity():
    assert _const_version() == TASK_PROFILE_REGISTRY_VERSION
    assert TASK_PROFILE_REGISTRY_VERSION == _registry()["contractVersion"]


def test_model_roles_parity():
    assert set(_const_array("modelRoles")) == set(MODEL_ROLES)
    assert _registry()["modelRoles"] == list(MODEL_ROLES)


def test_routing_modes_parity():
    assert set(_const_array("routingModes")) == set(ROUTING_MODES)
    assert _registry()["routingModes"] == list(ROUTING_MODES)


def test_guardrail_kinds_parity():
    assert set(_const_array("guardrailKinds")) == set(GUARDRAIL_KINDS)
    assert _registry()["guardrailKinds"] == list(GUARDRAIL_KINDS)


def test_output_kinds_parity():
    assert set(_const_array("outputKinds")) == set(OUTPUT_KINDS)
    assert _registry()["outputKinds"] == list(OUTPUT_KINDS)


def test_profiles_count():
    assert len(TASK_PROFILES) == 4
    assert len(_profile_objects()) == 4


def test_profile_fields_parity():
    """Per-index: TS profile literal matches the PY dict on all 12 fields."""
    ts_objects = _profile_objects()
    assert len(ts_objects) == len(TASK_PROFILES)
    for i, obj in enumerate(ts_objects):
        ts_keys = set(re.findall(r"^\s*([A-Za-z][A-Za-z0-9]*):", obj, re.M))
        py_keys = set(TASK_PROFILES[i].keys())
        assert ts_keys == _PROFILE_KEYS, (
            f"profile[{i}] TS key drift: TS-only={ts_keys - _PROFILE_KEYS}, "
            f"missing={_PROFILE_KEYS - ts_keys}"
        )
        assert py_keys == _PROFILE_KEYS, (
            f"profile[{i}] PY key drift: PY-only={py_keys - _PROFILE_KEYS}, "
            f"missing={_PROFILE_KEYS - py_keys}"
        )
        parsed = _parse_profile_object(obj)
        for key in _PROFILE_KEYS:
            if key in ("allowedRoutingModes", "guardrails"):
                # nested list fields: order-insensitive
                assert set(parsed[key]) == set(TASK_PROFILES[i][key]), (
                    f"profile[{i}].{key} drift: "
                    f"TS={parsed[key]!r} PY={TASK_PROFILES[i][key]!r}"
                )
            else:
                assert parsed[key] == TASK_PROFILES[i][key], (
                    f"profile[{i}].{key} drift: TS={parsed[key]!r} PY={TASK_PROFILES[i][key]!r}"
                )


def test_generated_profiles_match_registry():
    """Generated Python profiles mirror the JSON registry (regen if this fails)."""
    py_by_id = {p["profileId"]: dict(p) for p in TASK_PROFILES}
    assert py_by_id == _json_profiles()


def test_routing_mode_consistency():
    for profile in TASK_PROFILES:
        assert profile["defaultRoutingMode"] in profile["allowedRoutingModes"], (
            f"profile {profile['profileId']!r} defaultRoutingMode not in allowedRoutingModes"
        )


def test_barrel_exports_task_profile():
    index = (REPO_ROOT / "packages" / "shared" / "index.ts").read_text(encoding="utf-8")
    assert "export * from './task-profile';" in index
