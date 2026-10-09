"""Canonical environments map onto existing profiles; capabilities are flags, not profiles."""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/release"))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


profile_check = _load("check_profile_config", "scripts/release/check_profile_config.py")
overlays = _load("validate_capability_overlays", "scripts/validate_capability_overlays.py")
PROFILES = yaml.safe_load((ROOT / "config/deployment_profiles.yaml").read_text(encoding="utf-8"))


class _Reporter:
    def __init__(self):
        self.failures: list[str] = []

    def require(self, ok, good, bad):
        if not ok:
            self.failures.append(bad)

    def fail(self, message):
        self.failures.append(message)


def _failures(mutate=None):
    data = copy.deepcopy(PROFILES)
    if mutate:
        mutate(data)
    r = _Reporter()
    profile_check._check_canonical_environments(r, data, data["profiles"])
    return r.failures


def test_the_committed_environment_mapping_is_valid():
    assert _failures() == []


def test_every_profile_is_mapped_exactly_once_or_explicitly_unmapped():
    mapped = [p for e in PROFILES["canonical_environments"].values() for p in e["profiles"]]
    assert sorted(mapped + PROFILES["unmapped_profiles"]) == sorted(PROFILES["profiles"])


def test_an_unmapped_profile_is_caught():
    assert any("unmapped profiles" in f for f in _failures(lambda d: d["canonical_environments"]["preview"].update(profiles=[])))


def test_a_profile_in_two_environments_is_caught():
    def dup(d):
        d["canonical_environments"]["production"]["profiles"].append("staging")
    assert any("more than one environment" in f for f in _failures(dup))


def test_pilot_prod_cannot_silently_alias_the_staging_pilot_lane():
    def alias(d):
        d["canonical_environments"]["pilot-prod"] = {"profiles": ["staging"]}
    failures = _failures(alias)
    assert any("approvals and rollback_source" in f for f in failures)
    assert any("must not reuse a staging or production profile" in f for f in failures)


def test_pilot_prod_stays_explicitly_undefined_until_it_is_defined():
    def blank(d):
        d["canonical_environments"]["pilot-prod"] = {"profiles": []}
    assert any("status: undefined" in f for f in _failures(blank))


def test_staging_lanes_must_match_the_profile():
    def lanes(d):
        d["canonical_environments"]["staging"]["lanes"] = ["full"]
    assert any("staging lanes" in f for f in _failures(lanes))


def test_the_committed_overlay_registry_is_valid():
    assert overlays.validate() == []


def _overlay_errors(tmp_path, spec, name="enable-thing"):
    reg = tmp_path / "overlays.yaml"
    reg.write_text(
        yaml.safe_dump({
            "schema_version": 1,
            "flags_source": "services/backend/config/settings.py",
            "overlays": {name: spec},
        }),
        encoding="utf-8",
    )
    return overlays.validate(reg, ROOT / "config/deployment_profiles.yaml", ROOT)


def test_a_capability_cannot_be_a_deployment_profile(tmp_path):
    errors = _overlay_errors(tmp_path, {"class": "beta", "status": "unbound", "note": "n", "flags": []}, name="staging")
    assert any("must not be a deployment profile" in e for e in errors)
    assert any("must start with enable-" in e for e in errors)


def test_a_bound_flag_must_exist_in_settings(tmp_path):
    errors = _overlay_errors(tmp_path, {"class": "beta", "status": "bound", "flags": ["AETHER_NO_SUCH_FLAG"]})
    assert any("does not exist" in e for e in errors)


def test_an_unbound_overlay_cannot_list_flags_and_needs_a_note(tmp_path):
    errors = _overlay_errors(tmp_path, {"class": "beta", "status": "unbound", "flags": ["AETHER_COMMS_GRAPH_ENABLED"]})
    assert any("must not list flags" in e for e in errors)
    assert any("needs a note" in e for e in errors)
