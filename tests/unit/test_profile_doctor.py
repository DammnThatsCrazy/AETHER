"""Tests for the per-profile deployment readiness doctor (§27) and its
deployment certificate (§28).

The doctor's honesty rules are the invariants under test:
  * a cloud profile is CREDENTIAL_WAITING only while every in-repo check passes —
    the moment an in-repo check fails (e.g. the staging env template drifts
    back to EVENT_BROKER=kafka) the profile falls to INVALID, never "almost";
  * external evidence rows are pending_external pre-AWS by construction, and
    cannot be talked into passed from inside this repository;
  * detectable AWS credentials advance the state to CLOUD_REHEARSAL_REQUIRED,
    never past it (a credential is not a rehearsal).

As with the parity tests, the mutation cases are the point: a readiness state
machine that has never been shown to FAIL on a real regression is weak evidence.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "scripts" / "release"

# The 5-value certificate result vocabulary (§28).
RESULT_VOCABULARY = {
    "passed", "failed", "not_applicable", "pending_external", "not_run",
}

VALID_READINESS = {
    "invalid", "development_only", "integration_ready", "credential_waiting",
    "cloud_rehearsal_required", "production_candidate", "production_certified",
}


def _load(name: str):
    if str(RELEASE) not in sys.path:
        sys.path.insert(0, str(RELEASE))
    spec = importlib.util.spec_from_file_location(name, RELEASE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _build_report(mod, profile: str, data=None):
    data = data or yaml.safe_load(
        (ROOT / "config" / "deployment_profiles.yaml").read_text()
    )
    contracts = yaml.safe_load(
        (ROOT / "config" / "terraform_resource_contracts.yaml").read_text()
    )
    runtime = yaml.safe_load((ROOT / "config" / "runtime_deployment.yaml").read_text())
    readiness = yaml.safe_load((ROOT / "config" / "deployment_readiness.yaml").read_text())
    return mod.build_profile_report(
        ROOT, profile, data=data, contracts=contracts,
        runtime=runtime, readiness=readiness, spine_rows=[],
    )


def test_staging_is_credential_waiting_with_evidence():
    """The §46 objective: STAGING: CREDENTIAL_WAITING with the honest gap."""
    proc = subprocess.run(
        [sys.executable, str(RELEASE / "profile_doctor.py"), "staging"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert "STAGING: CREDENTIAL_WAITING" in proc.stdout
    assert "pending credentialed runs" in proc.stdout
    # Every in-repo check passed; the only non-passed rows are pending_external.
    doc = json.loads(
        subprocess.run(
            [sys.executable, str(RELEASE / "profile_doctor.py"), "staging", "--json"],
            cwd=ROOT, capture_output=True, text=True,
        ).stdout
    )
    assert doc["readiness_state"] == "credential_waiting"
    # Every APPLICABLE in-repo check passed (not_applicable rows are allowed).
    assert all(c["result"] in ("passed", "not_applicable") for c in doc["checks"])
    assert doc["external_evidence"]["credentials_available"] is False
    assert doc["external_evidence"]["all_validated"] is False
    assert doc["deployable"] is False


def test_all_profiles_report_a_valid_state():
    """Every canonical profile sits somewhere on the ladder."""
    proc = subprocess.run(
        [sys.executable, str(RELEASE / "profile_doctor.py"), "--all", "--json"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    docs = json.loads(proc.stdout)
    states = {d["profile"]: d["readiness_state"] for d in docs}
    assert len(states) == 8
    assert set(states) == {"local", "local-full", "demo", "preview",
                           "staging", "production-lean", "production-scale",
                           "enterprise-isolated"}
    assert states["local"] == "development_only"
    assert states["local-full"] == "development_only"
    assert states["demo"] == "integration_ready"
    assert states["preview"] == "integration_ready"
    for cloud in ("staging", "production-lean", "production-scale", "enterprise-isolated"):
        assert states[cloud] == "credential_waiting", cloud


def test_unknown_profile_is_invalid():
    proc = subprocess.run(
        [sys.executable, str(RELEASE / "profile_doctor.py"), "not-a-profile"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "INVALID" in proc.stdout


def test_certificate_result_vocabulary_is_closed():
    """Every check result is one of the five §28 values."""
    mod = _load("profile_doctor")
    report = _build_report(mod, "staging")
    for row in report["checks"] + report["external_evidence_checks"]:
        assert row["result"] in RESULT_VOCABULARY, row
    assert report["summary"]["pending_external"] == report["external_evidence"]["contract_rows"]


def test_certificate_carries_machine_readable_schema():
    mod = _load("profile_doctor")
    report = _build_report(mod, "production-lean")
    for key in ("schema_version", "profile", "profile_class", "readiness_state",
                "readiness_rank", "generated_at", "commit_sha", "checks",
                "summary", "external_evidence", "conclusion", "deployable"):
        assert key in report, key
    assert report["schema_version"] == 1
    assert report["readiness_rank"] == 3  # credential_waiting


def test_env_template_drift_knocks_staging_to_invalid(monkeypatch, tmp_path):
    """Reintroduce the historical staging drift and the doctor must FAIL it."""
    mod = _load("profile_doctor")
    drifted = tmp_path / "staging.env"
    drifted.write_text(
        "DEPLOYMENT_PROFILE=staging\n"
        "EVENT_BROKER=kafka\n"        # the historical worst line
        "REDIS_HOST=\n"
        "NEPTUNE_ENDPOINT=\n"
    )
    monkeypatch.setattr(mod, "ENV_TEMPLATES", {"staging": str(drifted)})
    report = _build_report(mod, "staging")
    parity = next(c for c in report["checks"] if c["id"] == "env-template-parity")
    assert parity["result"] == "failed"
    # A failed in-repo check must make the state INVALID, not "almost ready".
    assert report["readiness_state"] == "invalid"


def test_profile_removed_from_config_is_invalid(monkeypatch):
    mod = _load("profile_doctor")
    data = yaml.safe_load((ROOT / "config" / "deployment_profiles.yaml").read_text())
    del data["profiles"]["staging"]
    report = _build_report(mod, "staging", data=data)
    assert report["readiness_state"] == "invalid"


def test_detectable_credentials_advance_state_to_rehearsal_required(monkeypatch):
    """AWS env vars present ≠ rehearsed: state advances exactly one rung."""
    mod = _load("profile_doctor")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIATEST0000000000")
    report = _build_report(mod, "staging")
    assert report["external_evidence"]["credentials_available"] is True
    assert report["readiness_state"] == "cloud_rehearsal_required"
    assert report["deployable"] is False


def test_strict_gate_exit_codes():
    mod = _load("profile_doctor")
    # All cloud profiles at credential_waiting -> strict passes.
    assert mod.run(["--all", "--strict"]) == 0
    # An explicitly-named unknown profile is INVALID -> fails regardless.
    assert mod.run(["not-a-profile"]) == 1


def test_spine_gates_pass_and_become_evidence():
    proc = subprocess.run(
        [sys.executable, str(RELEASE / "profile_doctor.py"), "production-lean", "--gate", "--json"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    doc = json.loads(proc.stdout)
    spine = doc["spine_gates"]
    assert len(spine) == 5
    assert all(s["result"] == "passed" for s in spine)
