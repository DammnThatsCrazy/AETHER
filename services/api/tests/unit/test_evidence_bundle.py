"""Determinism + coverage tests for the Credential-Turnkey Evidence Bundle.

Covers the guarantees the program (sec30.C) requires of
``scripts/build_credential_turnkey_evidence.py``:

* determinism — two builds in the same checkout are byte-identical (same
  root SHA-256, same canonical serialization, same on-disk file);
* required sections — the manifest captures every section the bundle must
  cover and fails loudly if one is missing;
* root checksum — the sealed checksum recomputes by canonicalizing the
  document with the ``root_checksum`` block removed;
* no time-varying fields — no timestamp/generated-at keys sneak in (the
  determinism contract forbids them).
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT = REPO_ROOT / "scripts" / "build_credential_turnkey_evidence.py"

# Guard: if the generator script is renamed/moved, this test fails loudly.
assert SCRIPT.is_file(), f"evidence bundle generator missing: {SCRIPT}"


def _load_module():
    spec = importlib.util.spec_from_file_location("credential_turnkey_evidence", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()


def _all_keys(obj) -> list[str]:
    keys: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.append(str(k))
            keys.extend(_all_keys(v))
    elif isinstance(obj, list):
        for item in obj:
            keys.extend(_all_keys(item))
    return keys


def test_required_sections_all_present():
    document = MODULE.build_evidence_bundle(phase="pre-staging")
    sections = document["sections"]
    for section in MODULE.REQUIRED_SECTIONS:
        assert section in sections, f"required evidence section missing: {section}"
    assert len(sections) == len(MODULE.REQUIRED_SECTIONS)


def test_determinism_two_builds_identical():
    first = MODULE.build_evidence_bundle(phase="pre-staging")
    second = MODULE.build_evidence_bundle(phase="pre-staging")
    assert first == second
    assert first["root_checksum"]["value"] == second["root_checksum"]["value"]
    assert MODULE._canonical_json(first) == MODULE._canonical_json(second)


def test_root_checksum_recomputes_from_document():
    document = MODULE.build_evidence_bundle(phase="pre-staging")
    verify = {k: v for k, v in document.items() if k != "root_checksum"}
    expected = MODULE._sha256_bytes(MODULE._canonical_json(verify))
    assert document["root_checksum"]["value"] == expected
    assert document["root_checksum"]["algorithm"] == "sha256"


def test_no_time_varying_keys():
    """Determinism contract: no timestamp/generated-at/created-at keys.

    Every dict key must be stable across runs in the same checkout; a
    key that names a clock would break byte-identical regeneration.
    """
    document = MODULE.build_evidence_bundle(phase="pre-staging")
    pattern = re.compile(r"(generated_at|timestamp|created_at|last_.*_at)$", re.IGNORECASE)
    offenders = [k for k in _all_keys(document) if pattern.search(k)]
    assert not offenders, f"time-varying keys leak into the bundle: {offenders}"


def test_write_is_byte_deterministic(tmp_path):
    document = MODULE.build_evidence_bundle(phase="pre-staging")
    out_a = tmp_path / "bundle-a.json"
    out_b = tmp_path / "bundle-b.json"
    MODULE.write_bundle(document, out_a)
    MODULE.write_bundle(document, out_b)
    assert out_a.read_bytes() == out_b.read_bytes()
    json.loads(out_a.read_text())  # must round-trip as JSON
    assert "root_checksum" in json.loads(out_a.read_text())


def test_default_output_path_shape():
    out = MODULE.default_output("staging")
    assert out.name == f"{MODULE.BUNDLE_NAME}-staging.json"
    assert out.parent.name == "release-evidence"


def test_pending_evidence_is_honest():
    """Environment-controlled evidence is recorded as pending, never fabricated.

    Live terraform validation and test pass/fail counts must appear as
    ``status == "pending"`` with a reason, not as fabricated results.
    """
    document = MODULE.build_evidence_bundle(phase="pre-staging")
    pending = document["pending_evidence"]
    items = {p["item"]: p for p in pending}
    assert items["infrastructure:terraform_validate"]["status"] == "pending"
    assert items["infrastructure:terraform_plan"]["status"] == "pending"
    assert items["infrastructure:terraform_apply"]["status"] == "pending"
    assert any(i.startswith("test-suite:") for i in items)
    assert all(p["status"] == "pending" for p in pending)


@pytest.mark.parametrize(
    "section",
    [
        "manifests",
        "certification",
        "test_suites",
        "fault_tests",
        "migration_state",
        "worker_topology",
        "infrastructure_validation",
        "entitlement_registry",
        "meter_registry",
        "storage_policies",
        "readiness_state",
    ],
)
def test_each_section_carries_evidence(section):
    """Every required section is non-empty (populated from a registry)."""
    document = MODULE.build_evidence_bundle(phase="pre-staging")
    data = document["sections"][section]
    assert isinstance(data, dict) and data, f"section {section} is empty"
