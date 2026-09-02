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


def _has_aws_credentials() -> bool:
    """Mirror the doctor's own credential detection for env-aware assertions."""
    return any(os.environ.get(v) for v in (
        "AWS_ACCESS_KEY_ID", "AWS_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN", "AWS_PROFILE", "AWS_SHARED_CREDENTIALS_FILE",
    ))


def test_staging_readiness_with_evidence():
    """Staging reaches at least CREDENTIAL_WAITING once all in-repo checks pass.
    With AWS credentials present it advances to CLOUD_REHEARSAL_REQUIRED."""
    proc = subprocess.run(
        [sys.executable, str(RELEASE / "profile_doctor.py"), "staging"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    if _has_aws_credentials():
        expected = "cloud_rehearsal_required"
        assert "STAGING: CLOUD_REHEARSAL_REQUIRED" in proc.stdout
    else:
        expected = "credential_waiting"
        assert "STAGING: CREDENTIAL_WAITING" in proc.stdout
    assert "credential" in proc.stdout.lower()
    doc = json.loads(
        subprocess.run(
            [sys.executable, str(RELEASE / "profile_doctor.py"), "staging", "--json"],
            cwd=ROOT, capture_output=True, text=True,
        ).stdout
    )
    assert doc["readiness_state"] == expected
    assert all(c["result"] in ("passed", "not_applicable") for c in doc["checks"])
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
    # demo/preview reach CREDENTIAL_WAITING once their ephemeral lifecycle is
    # fully realized (declared budget + cost policy, selectable Terraform,
    # runtime topology, TTL guard). The assertion only passes after that
    # lifecycle lands in config/ and the guard files exist; the mutation test
    # below proves the same state machine never hands it out early.
    assert states["demo"] == "credential_waiting"
    assert states["preview"] == "credential_waiting"
    expected_cloud = "cloud_rehearsal_required" if _has_aws_credentials() else "credential_waiting"
    for cloud in ("staging", "production-lean", "production-scale", "enterprise-isolated"):
        assert states[cloud] == expected_cloud, cloud


def test_demo_preview_lifecycle_contract_gates_credential_waiting(tmp_path):
    """demo/preview are CREDENTIAL_WAITING only when the full ephemeral lifecycle
    exists; the state machine never hands the rung out early.

    The lifecycle contract is: declared budget + cost_policy, selectable
    Terraform (tfvars + variables.tf), a runtime topology, and the ephemeral TTL
    guard wired to the profile's matrix. Two kinds of gap are distinguished:

      * a SOFT gap (no cost_policy, or a missing/unwired guard) keeps the
        profile at INTEGRATION_READY — never INVALID, never credential_waiting;
      * a HARD gap (no budget, no tfvars, not selectable, no runtime topology)
        is independently failed by a gate and knocks the profile to INVALID,
        which is the same scrutiny cloud profiles already receive.
    """
    mod = _load("profile_doctor")

    def realized_fixture(sub: Path):
        """A fully realized demo in a synthetic repo root."""
        data = yaml.safe_load((ROOT / "config" / "deployment_profiles.yaml").read_text())
        demo = data["profiles"]["demo"]
        demo["cost_policy"] = {
            "required_resources": ["cloudfront_s3_frontends", "alb", "dynamodb", "sqs_sns"],
            "forbidden_resources": ["msk"],
        }
        demo["budget"] = {
            "currency": "USD",
            "region": "us-east-1",
            "target_monthly_spend": 10,
            "hard_monthly_spend": 25,
        }
        tf_dir = sub / "AWS Deployment" / "aether-aws" / "terraform"
        (tf_dir / "profiles").mkdir(parents=True, exist_ok=True)
        (tf_dir / "profiles" / "demo.tfvars").write_text(
            'deployment_profile = "demo"\n', encoding="utf-8")
        (tf_dir / "variables.tf").write_text(
            'variable "deployment_profile" {\n'
            "  validation {\n"
            '    condition = contains(["staging", "production-lean", "demo", "preview"], var.deployment_profile)\n'
            "  }\n"
            "}\n", encoding="utf-8")
        guard_py = sub / "scripts" / "release"
        guard_py.mkdir(parents=True, exist_ok=True)
        (guard_py / "ephemeral_ttl_guard.py").write_text(
            '"""ephemeral TTL guard fixture"""\n', encoding="utf-8")
        workflows = sub / ".github" / "workflows"
        workflows.mkdir(parents=True, exist_ok=True)
        (workflows / "ephemeral-ttl-guard.yml").write_text(
            "name: Ephemeral TTL guard\n"
            "on:\n  schedule:\n    - cron: '17 * * * *'\n"
            "jobs:\n  guard:\n    strategy:\n"
            "      matrix:\n        profile:\n          - demo\n          - preview\n"
            "    runs-on: ubuntu-latest\n", encoding="utf-8")
        runtime = yaml.safe_load((ROOT / "config" / "runtime_deployment.yaml").read_text())
        runtime["profiles"]["demo"] = {
            "execution_mode": "consolidated",
            "services": {"api": {"roles": ["api"]}},
        }
        return data, runtime, tf_dir, guard_py, workflows

    contracts = yaml.safe_load(
        (ROOT / "config" / "terraform_resource_contracts.yaml").read_text())
    readiness = yaml.safe_load((ROOT / "config" / "deployment_readiness.yaml").read_text())

    def report_for(root: Path, data: dict, runtime: dict) -> dict:
        return mod.build_profile_report(
            root, "demo", data=data, contracts=contracts,
            runtime=runtime, readiness=readiness, spine_rows=[],
        )

    # Fully realized -> CREDENTIAL_WAITING, with every applicable check green.
    realized = tmp_path / "realized"
    data, runtime, tf_dir, guard_py, workflows = realized_fixture(realized)
    report = report_for(realized, data, runtime)
    assert report["readiness_state"] == "credential_waiting", report["conclusion"]
    assert all(c["result"] in ("passed", "not_applicable") for c in report["checks"])

    # SOFT gaps: each one alone must leave the profile at INTEGRATION_READY —
    # never INVALID, never credential_waiting.
    soft_mutations = (
        ("no cost_policy", lambda d, rt: d["profiles"]["demo"].pop("cost_policy")),
        ("no guard py", lambda d, rt: (guard_py / "ephemeral_ttl_guard.py").unlink()),
        ("no guard workflow", lambda d, rt: (workflows / "ephemeral-ttl-guard.yml").unlink()),
        ("not in guard matrix", lambda d, rt: (workflows / "ephemeral-ttl-guard.yml").write_text(
            "jobs:\n  guard:\n    strategy:\n"
            "      matrix:\n        profile:\n          - preview\n", encoding="utf-8")),
    )
    for label, mutate in soft_mutations:
        sub = tmp_path / f"soft_{label.replace(' ', '_')}"
        data, runtime, tf_dir, guard_py, workflows = realized_fixture(sub)
        mutate(data, runtime)
        report = report_for(sub, data, runtime)
        assert report["readiness_state"] == "integration_ready", (
            f"soft mutation {label!r} produced {report['readiness_state']}: "
            f"{report['conclusion']}")
        assert all(c["result"] in ("passed", "not_applicable") for c in report["checks"]), label

    # HARD gaps: each is independently failed by a gate, so the profile falls to
    # INVALID (the same scrutiny cloud profiles receive) rather than resting at
    # integration_ready.
    hard_mutations = (
        ("no budget", lambda d, rt: d["profiles"]["demo"].pop("budget"),
         "budget-declared"),
        ("no tfvars", lambda d, rt: (tf_dir / "profiles" / "demo.tfvars").unlink(),
         "terraform-selectable"),
        ("not terraform-selectable",
         lambda d, rt: (tf_dir / "variables.tf").write_text(
             'variable "deployment_profile" {\n'
             "  validation {\n"
             '    condition = contains(["staging", "production-lean"], var.deployment_profile)\n'
             "  }\n"
             "}\n", encoding="utf-8"),
         "terraform-selectable"),
        ("no runtime topology", lambda d, rt: rt["profiles"].pop("demo"),
         "runtime-topology"),
    )
    for label, mutate, failing_check in hard_mutations:
        sub = tmp_path / f"hard_{label.replace(' ', '_')}"
        data, runtime, tf_dir, guard_py, workflows = realized_fixture(sub)
        mutate(data, runtime)
        report = report_for(sub, data, runtime)
        assert report["readiness_state"] == "invalid", (
            f"hard mutation {label!r} produced {report['readiness_state']}: "
            f"{report['conclusion']}")
        failing = next(c for c in report["checks"] if c["id"] == failing_check)
        assert failing["result"] == "failed", (label, failing)


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
    expected_rank = 4 if _has_aws_credentials() else 3
    assert report["readiness_rank"] == expected_rank


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
