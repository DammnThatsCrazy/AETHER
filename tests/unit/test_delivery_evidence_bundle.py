from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("delivery_evidence", ROOT / "scripts/release/evidence_bundle.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def bundle(**updates):
    value = {
        "schema_version": 1, "release_candidate_id": "rc-1", "status": "READY",
        "commit_sha": "1234567", "artifact_digest": "sha256:" + "a" * 64,
        "deployment_profile": "gamma",
        "checks": {name: "PASS" for name in (
            "code_correctness", "contract_compatibility", "infrastructure_preflight",
            "migration", "tenant_activation", "golden_journeys", "security",
            "operability", "rollback")},
        "known_degradations": [], "evidence": ["s3://evidence/rc-1"],
        "timestamps": {"created": "2026-08-31T00:00:00Z"},
    }
    value.update(updates)
    return value


def test_ready_bundle_is_valid_and_five_journeys_are_registered():
    assert MODULE.validate_bundle(bundle()) == []
    assert MODULE.validate_journey_registry() == []


def test_ready_cannot_hide_a_blocker():
    value = bundle()
    value["checks"]["migration"] = "BLOCKED"
    assert any("READY is forbidden" in item for item in MODULE.validate_bundle(value))


def test_degradation_requires_explanation():
    assert any("known degradation" in item for item in MODULE.validate_bundle(bundle(status="PASS_WITH_DEGRADATION")))


def test_kyber_projection_preserves_authoritative_disposition_and_blockers():
    value = bundle(status="BLOCKED")
    value["checks"]["infrastructure_preflight"] = "BLOCKED"
    projection = MODULE.kyber_projection(value)
    assert projection["disposition"] == "BLOCKED"
    assert projection["blockers"] == [{"check": "infrastructure_preflight", "status": "BLOCKED"}]
    assert "repair blockers" in projection["action"]


def test_committed_golden_journeys_have_a_registry_only_gate():
    result = subprocess.run(
        [sys.executable, "scripts/release/evidence_bundle.py", "--check-registry"],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "PASS"
