"""Deployment-readiness scorecard tests — the scorecard must not be gameable.

The scorecard exists to stop a readiness percentage from drifting away from the
evidence underneath it, so these tests are mostly attacks on it: a control with
no evidence, a control whose evidence exists but does not validate, a synthetic
artifact dressed up as a credentialed one, an expired exception, a tampered
bundle, and a control table edited to claim more than the conditions allow.
Each one must produce a lower number or a hard failure, never a pass.

The three reported numbers — code-complete, externally-verified and the
evidence gap — must also stay separate. Merging them is the specific
misreporting this whole mechanism is built to prevent.
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "release"))

import check_deployment_readiness as dr  # noqa: E402
import collect_evidence  # noqa: E402
from release_manifest import canonical  # noqa: E402

CONFIG_PATH = ROOT / "config/deployment_readiness.yaml"

PASS_RUNNER = lambda path, args: (0, "")            # noqa: E731
FAIL_RUNNER = lambda path, args: (1, "validator said no")  # noqa: E731


# ── Fixtures: a synthetic control table we can attack ──────────────────────


def _provenance(**over) -> dict:
    """A STRUCTURALLY valid provenance block, self-declared and nothing more.

    Every field here was typed into this file. That is the point: a block like
    this is exactly what an operator (or an agent) writes when it wants a
    scorecard to go up, and fifteen of them used to take the overall verified
    score from 20 to 95. It must earn nothing.
    """
    base = {
        "credentialed": True,
        "aws_account_id": "402910375561",
        "region": "us-east-1",
        "terraform_version": "1.9.8",
        "captured_at": "2026-07-25T13:00:00+00:00",
        "commit_sha": "a1b2c3d4e5f6",
        "source": "s3://aether-terraform-state/production-lean/plan.json",
    }
    base.update(over)
    return base


# The kind a test-registered verifier answers to. Nothing in the repository
# declares it, and no verifier is registered outside the fixture below.
TEST_ATTESTATION_KIND = "test-double-verifier"


def _attested(**over) -> dict:
    """Provenance carrying an attestation a REGISTERED verifier would accept.

    Only meaningful inside the `attestation_verifier` fixture. Without a
    verifier registered for its kind, this is still self-declared and still
    earns nothing — which is asserted directly.
    """
    return _provenance(attestation={"kind": TEST_ATTESTATION_KIND,
                                    "run": "https://example.invalid/run/1"},
                       **over)


@pytest.fixture
def attestation_verifier(monkeypatch):
    """Register a verifier, so the mechanism is exercised in BOTH directions.

    Without this, every test would agree that nothing verifies and none of them
    would notice if verification had simply been hardcoded to False.
    """
    monkeypatch.setitem(dr.ATTESTATION_VERIFIERS, TEST_ATTESTATION_KIND,
                        lambda data: [])
    return TEST_ATTESTATION_KIND


def _condition(cid: str, kind: str, evidence: str, blocks: list, **over) -> dict:
    row = {"id": cid, "description": cid, "kind": kind, "evidence": evidence,
           "blocks_controls": blocks}
    row.update(over)
    return row


CREDENTIALED_CONDITIONS = {
    "COND-STAGING-WAKE-APPLIED": "release-evidence/lifecycle/staging-wake.json",
    "COND-STAGING-TWO-REHEARSALS": "release-evidence/lifecycle/rehearsal-history.json",
    "COND-LEAN-PLAN-CREDENTIALED": "release-evidence/terraform/lean-plan-provenance.json",
    "COND-LOAD-VALIDATED": "release-evidence/load/load-result.json",
    "COND-ROLLBACK-VALIDATED": "release-evidence/rollback/rollback-result.json",
    "COND-MIGRATION-REHEARSED": "release-evidence/migrations/migration-result.json",
    "COND-SMOKE-PASSED": "release-evidence/smoke/smoke-result.json",
    "COND-SECURITY-VALIDATED": "release-evidence/security/security-result.json",
    "COND-SLEEP-RESIDUAL": "release-evidence/lifecycle/sleep-residual.json",
    "COND-OBSERVABILITY-LIVE": "release-evidence/observability/alarm-evidence.json",
    "COND-PROMOTION-INTEGRITY": "release-evidence/terraform/promotion-provenance.json",
}


def _all_conditions(blocks: dict | None = None) -> list[dict]:
    """All seventeen conditions, so config integrity is satisfied."""
    blocks = blocks or {}
    rows = [_condition(cid, "credentialed_artifact", path, blocks.get(cid, []))
            for cid, path in CREDENTIALED_CONDITIONS.items()]
    rows.append(_condition("COND-COST-OBSERVED-7D", "credentialed_artifact",
                           "release-evidence/cost/observed-cost.json",
                           blocks.get("COND-COST-OBSERVED-7D", []), minimum_days=7))
    rows.append(_condition("COND-COST-RECONCILED", "credentialed_artifact",
                           "release-evidence/cost/reconciliation.json",
                           blocks.get("COND-COST-RECONCILED", []), tolerance_percent=25))
    rows.append(_condition("COND-NO-UNRESOLVED-P0", "ledger_severity",
                           "config/implementation_ledger.yaml", [], severity="P0"))
    rows.append(_condition("COND-NO-UNRESOLVED-P1", "ledger_severity",
                           "config/implementation_ledger.yaml", [], severity="P1"))
    rows.append(_condition("COND-NO-EXPIRED-EXCEPTIONS", "exception_expiry",
                           "config/deployment_readiness.yaml", []))
    rows.append(_condition("COND-BUNDLE-CHECKSUM", "bundle_checksum",
                           "release-evidence/manifest.sha256", []))
    assert {r["id"] for r in rows} == set(dr.REQUIRED_CONDITION_IDS)
    return rows


def _control(cid: str, profile: str, weight: int, evidence: list, **over) -> dict:
    external = any(e.get("external") for e in evidence)
    base = {
        "id": cid, "profile": profile, "description": f"{cid} control",
        "weight": weight, "required_evidence": evidence,
        "status": "implemented", "last_verified_commit": None,
        "last_verified_at": None, "evidence_path": f"release-evidence/{profile}/",
        "external_dependency": {"required": external,
                                "what": "an AWS account" if external else None},
        "exception": None,
    }
    base.update(over)
    return base


def _config(controls: list[dict], exceptions: list | None = None,
            blocks: dict | None = None) -> dict:
    return {
        "schema_version": 1,
        "release_train": "FOUNDING_TENANT_PRODUCTION",
        "evidence_bundle": {"root": "release-evidence"},
        "scorecards": {
            "overall": {"title": "overall", "total": 100, "gate": 90,
                        "gate_basis": "externally_verified"},
            "production-lean": {"title": "lean", "total": 100, "gate": 92,
                                "gate_basis": "externally_verified"},
            "staging": {"title": "staging", "total": 100, "gate": 95,
                        "gate_basis": "externally_verified"},
        },
        "gate_conditions": _all_conditions(blocks),
        "exceptions": exceptions if exceptions is not None else [],
        "controls": controls,
    }


def _one_per_profile(evidence: list, **over) -> list[dict]:
    """One 100-point control per scorecard, so weights total correctly."""
    return [_control(f"CTRL-{p}", p, 100, copy.deepcopy(evidence), **over)
            for p in dr.PROFILES]


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")


def _clean_ledger(root: Path) -> None:
    """A ledger with nothing outstanding, so the P0/P1 conditions can be met."""
    _write(root / "config/implementation_ledger.yaml", "")
    (root / "config/implementation_ledger.yaml").write_text(
        yaml.safe_dump({"items": [
            {"id": "X-1", "severity": "P0", "status": "verified_complete"},
            {"id": "X-2", "severity": "P1", "status": "full_gate_pass"},
        ]}), encoding="utf-8")


def _satisfy_all_external(root: Path, attested: bool = False) -> None:
    """Materialise every credentialed artifact the conditions look for."""
    payloads = {
        "release-evidence/lifecycle/staging-wake.json": {
            "woke_at": "2026-07-25T12:00:00+00:00", "apply_result": "success"},
        "release-evidence/lifecycle/rehearsal-history.json": {"rehearsals": [1, 2]},
        "release-evidence/lifecycle/sleep-residual.json": {
            "slept_at": "2026-07-25T20:00:00+00:00", "residual_daily_usd": 0.4},
        "release-evidence/lifecycle/deployed-artifacts.json": {
            "manifest_sha256": "a" * 64, "deployed_digests": {}},
        "release-evidence/terraform/lean-plan-provenance.json": {
            "profile": "production-lean", "plan_sha256": "b" * 64,
            "state_key": "profiles/production-lean/terraform.tfstate"},
        "release-evidence/terraform/promotion-provenance.json": {
            "reviewed_plan_sha256": "b" * 64, "applied_plan_sha256": "b" * 64,
            "lock_sha256": "c" * 64, "state_key": "k"},
        "release-evidence/cost/observed-cost.json": {
            "profile": "production-lean", "days": 9, "daily_usd": [3.1] * 9},
        "release-evidence/cost/reconciliation.json": {
            "projected_usd": 97.67, "observed_usd": 104.2, "variance_percent": 6.7},
        "release-evidence/load/load-result.json": {
            "duration_s": 900, "rps": 40, "p95_ms": 210, "error_rate": 0.001},
        "release-evidence/rollback/rollback-result.json": {
            "executed_at": "2026-07-25T14:00:00+00:00",
            "restored_at": "2026-07-25T14:06:00+00:00"},
        "release-evidence/migrations/migration-result.json": {
            "forward": "ok", "rollback": "ok"},
        "release-evidence/smoke/smoke-result.json": {
            "suite": "staging", "passed": 42, "failed": 0},
        "release-evidence/security/security-result.json": {"probes": 11, "findings": []},
        "release-evidence/isolation/isolation-result.json": {
            "tenants": 2, "cross_tenant_reads": 0},
        "release-evidence/observability/alarm-evidence.json": {
            "alarms": 6, "observed_transitions": 2},
    }
    provenance = _attested() if attested else _provenance()
    for rel, body in payloads.items():
        _write(root / rel, {**body, "provenance": copy.deepcopy(provenance)})


def _seal_bundle(root: Path, attested: bool = False) -> None:
    """Write a valid manifest + checksum over whatever is in the bundle.

    `attested` additionally stamps the manifest with an attestation, because a
    bundle this repository sealed for itself proves only that nothing changed
    after it was sealed.
    """
    bundle = root / "release-evidence"
    collect_evidence.write_bundle_layout(bundle, {"commit": "abc123"})
    if not attested:
        return
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    manifest["provenance"] = _attested()
    payload = canonical(manifest)
    (bundle / "manifest.json").write_bytes(payload)
    (bundle / "manifest.sha256").write_text(
        hashlib.sha256(payload).hexdigest() + "\n", encoding="utf-8")


# ── A control earns its weight only from evidence that actually validates ──


def test_control_with_no_evidence_file_scores_zero(tmp_path):
    config = _config(_one_per_profile([
        {"id": "e", "kind": "repo_file", "path": "docs/NOTHING.md", "external": False},
    ]))
    report = dr.build_report(tmp_path, config, runner=PASS_RUNNER)
    for card in report["scorecards"].values():
        assert card["code_complete_score"] == 0
        assert card["externally_verified_score"] == 0
    assert all("file is absent" in c["unmet"][0] for c in report["controls"])


def test_control_whose_evidence_exists_but_fails_validation_scores_zero(tmp_path):
    """Present is not passing. The file is there and the validator rejects it."""
    _write(tmp_path / "artifacts/result.json", {"profile": "production-lean"})
    config = _config(_one_per_profile([
        {"id": "e", "kind": "json_artifact", "path": "artifacts/result.json",
         "require_keys": ["profile", "passed"], "external": False},
    ]))
    report = dr.build_report(tmp_path, config, runner=PASS_RUNNER)
    for card in report["scorecards"].values():
        assert card["code_complete_score"] == 0
    assert all("missing required key 'passed'" in c["unmet"][0]
               for c in report["controls"])


def test_control_whose_validator_script_exits_nonzero_scores_zero(tmp_path):
    _write(tmp_path / "scripts/release/check_thing.py", "print('x')")
    config = _config(_one_per_profile([
        {"id": "e", "kind": "check_script",
         "path": "scripts/release/check_thing.py", "external": False},
    ]))
    passing = dr.build_report(tmp_path, config, runner=PASS_RUNNER)
    failing = dr.build_report(tmp_path, config, runner=FAIL_RUNNER)
    assert passing["scorecards"]["overall"]["code_complete_score"] == 100
    assert failing["scorecards"]["overall"]["code_complete_score"] == 0


def test_require_true_rejects_a_falsy_pass_flag(tmp_path):
    _write(tmp_path / "reports/cost/cost-report.json",
           {"profile": "production-lean", "passed": False})
    config = _config(_one_per_profile([
        {"id": "e", "kind": "json_artifact", "path": "reports/cost/cost-report.json",
         "require_keys": ["profile"], "require_true": ["passed"], "external": False},
    ]))
    report = dr.build_report(tmp_path, config, runner=PASS_RUNNER)
    assert report["scorecards"]["overall"]["code_complete_score"] == 0


def test_a_control_declaring_no_internal_evidence_is_never_code_complete(tmp_path):
    """Completeness cannot be asserted on an empty set of in-repo claims."""
    _satisfy_all_external(tmp_path)
    config = _config(_one_per_profile([
        {"id": "e", "kind": "credentialed_artifact",
         "path": "release-evidence/load/load-result.json", "external": True},
    ]))
    report = dr.build_report(tmp_path, config, runner=PASS_RUNNER)
    for card in report["scorecards"].values():
        assert card["code_complete_score"] == 0
        assert card["externally_verified_score"] == 0


# ── Credentialed provenance cannot be produced by a repository ─────────────


@pytest.mark.parametrize("override, fragment", [
    ({"credentialed": False}, "credentialed is not true"),
    ({"aws_account_id": "123456789012"}, "placeholder account"),
    ({"aws_account_id": "42"}, "12-digit AWS account id"),
    ({"region": "moon-1"}, "not an AWS region"),
    ({"terraform_version": "latest"}, "not a version"),
    ({"captured_at": "2026-07-25T13:00:00"}, "timezone-aware"),
    ({"commit_sha": "nothex!"}, "hex commit"),
    ({"source": "/tmp/scratch/lean.json"}, "never becomes credentialed evidence"),
    ({"source": "reports/cost/synthetic-plan.json"}, "never becomes credentialed evidence"),
])
def test_provenance_rejects_uncredentialed_artifacts(override, fragment):
    reasons = dr.validate_provenance({"provenance": _provenance(**override)})
    assert any(fragment in r for r in reasons), reasons


def test_provenance_requires_a_provenance_block_at_all():
    assert dr.validate_provenance({"days": 7}) == ["no `provenance` block"]


def test_credentialed_evidence_without_provenance_scores_zero(tmp_path):
    """A plausible artifact with no provenance earns nothing."""
    _write(tmp_path / "docs/D.md", "documented")
    _write(tmp_path / "release-evidence/cost/observed-cost.json",
           {"profile": "production-lean", "days": 7, "daily_usd": [1] * 7})
    config = _config(_one_per_profile([
        {"id": "doc", "kind": "repo_file", "path": "docs/D.md", "external": False},
        {"id": "cost", "kind": "credentialed_artifact",
         "path": "release-evidence/cost/observed-cost.json",
         "require_keys": ["days"], "external": True},
    ]))
    report = dr.build_report(tmp_path, config, runner=PASS_RUNNER)
    card = report["scorecards"]["overall"]
    assert card["code_complete_score"] == 100
    assert card["externally_verified_score"] == 0


# ── The three numbers stay three numbers ───────────────────────────────────


def test_code_complete_and_verified_are_reported_separately_and_never_merged(tmp_path):
    _write(tmp_path / "docs/D.md", "documented")
    config = _config(_one_per_profile([
        {"id": "doc", "kind": "repo_file", "path": "docs/D.md", "external": False},
        {"id": "plan", "kind": "credentialed_artifact",
         "path": "release-evidence/terraform/lean-plan-provenance.json",
         "external": True},
    ]))
    report = dr.build_report(tmp_path, config, runner=PASS_RUNNER)
    for card in report["scorecards"].values():
        assert card["code_complete_score"] == 100
        assert card["externally_verified_score"] == 0
        assert card["evidence_gap"] == 100
        # No single conflated "score" key may exist to be quoted instead.
        assert "score" not in card
        assert card["code_complete_score"] != card["externally_verified_score"]


def test_evidence_gap_is_the_difference_and_is_never_negative(tmp_path):
    _clean_ledger(tmp_path)
    _satisfy_all_external(tmp_path)
    _seal_bundle(tmp_path)
    _write(tmp_path / "docs/D.md", "documented")
    config = _config(_one_per_profile([
        {"id": "doc", "kind": "repo_file", "path": "docs/D.md", "external": False},
        {"id": "load", "kind": "credentialed_artifact",
         "path": "release-evidence/load/load-result.json", "external": True},
    ]))
    report = dr.build_report(tmp_path, config, runner=PASS_RUNNER)
    for card in report["scorecards"].values():
        assert card["evidence_gap"] == (card["code_complete_score"]
                                        - card["externally_verified_score"])
        assert card["evidence_gap"] >= 0


# ── The condition ceiling caps a score the conditions do not support ───────


def test_verified_score_cannot_reach_100_while_an_external_control_is_unmet(tmp_path):
    _write(tmp_path / "docs/D.md", "documented")
    blocks = {"COND-LOAD-VALIDATED": [f"CTRL-{p}" for p in dr.PROFILES]}
    config = _config(_one_per_profile([
        {"id": "doc", "kind": "repo_file", "path": "docs/D.md", "external": False},
        {"id": "load", "kind": "credentialed_artifact",
         "path": "release-evidence/load/load-result.json", "external": True},
    ]), blocks=blocks)
    report = dr.build_report(tmp_path, config, runner=PASS_RUNNER)
    for card in report["scorecards"].values():
        assert card["externally_verified_score"] < 100
        assert card["max_attainable_verified_score"] == 0
    assert report["deployment_ready"] is False


def test_invariant_fires_when_a_control_outscores_its_condition_ceiling(
        tmp_path, attestation_verifier):
    """The tamper detector: evidence on disk and the control table disagree.

    The control earns its weight from an attested artifact that exists, while a
    different condition governing it is still unmet, so the ceiling is 0. The
    scorecard must refuse the number rather than print it.
    """
    _write(tmp_path / "docs/D.md", "documented")
    _write(tmp_path / "release-evidence/rollback/rollback-result.json",
           {"executed_at": "2026-07-25T14:00:00+00:00", "provenance": _attested()})
    blocks = {"COND-LOAD-VALIDATED": [f"CTRL-{p}" for p in dr.PROFILES]}
    config = _config(_one_per_profile([
        {"id": "doc", "kind": "repo_file", "path": "docs/D.md", "external": False},
        {"id": "rollback", "kind": "credentialed_artifact",
         "path": "release-evidence/rollback/rollback-result.json", "external": True},
    ]), blocks=blocks)
    report = dr.build_report(tmp_path, config, runner=PASS_RUNNER)
    for card in report["scorecards"].values():
        assert card["externally_verified_score"] == 100
        assert card["max_attainable_verified_score"] == 0
    reporter = dr.Reporter("invariants")
    dr.check_invariants(report["scorecards"], report["gate_conditions"]["results"], reporter)
    assert reporter.finish() != 0
    assert any("exceeds the 0 attainable" in f for f in reporter.failures)


def test_all_seventeen_conditions_must_be_declared(tmp_path):
    config = _config(_one_per_profile([
        {"id": "doc", "kind": "repo_file", "path": "docs/D.md", "external": False},
    ]))
    config["gate_conditions"] = [c for c in config["gate_conditions"]
                                 if c["id"] != "COND-LOAD-VALIDATED"]
    reporter = dr.Reporter("integrity")
    dr.check_integrity(config, reporter)
    assert reporter.finish() != 0
    assert any("COND-LOAD-VALIDATED" in f for f in reporter.failures)


def test_the_repo_declares_exactly_seventeen_gate_conditions():
    assert len(dr.REQUIRED_CONDITION_IDS) == 17
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    assert {c["id"] for c in config["gate_conditions"]} == set(dr.REQUIRED_CONDITION_IDS)


# ── Release gates are real thresholds, in both directions ──────────────────


def test_release_gates_are_enforced_at_90_92_and_95(tmp_path, attestation_verifier):
    """Gates fail below the line and pass above it — proving they are read.

    Every artifact here is ATTESTED, via a verifier registered only for this
    test. That is the only way this suite is allowed to reach a passing gate:
    with the repository's own hand-written provenance it must not, and the test
    below asserts exactly that.
    """
    _clean_ledger(tmp_path)
    _satisfy_all_external(tmp_path, attested=True)
    _seal_bundle(tmp_path, attested=True)
    _write(tmp_path / "docs/D.md", "documented")
    evidence = [
        {"id": "doc", "kind": "repo_file", "path": "docs/D.md", "external": False},
        {"id": "load", "kind": "credentialed_artifact",
         "path": "release-evidence/load/load-result.json", "external": True},
    ]
    # Everything verified: each gate is met and the run is release-ready.
    full = dr.build_report(tmp_path, _config(_one_per_profile(evidence)),
                           runner=PASS_RUNNER)
    assert full["gate_conditions"]["all_met"] is True
    for profile, card in full["scorecards"].items():
        assert card["externally_verified_score"] == 100
        assert card["gate_met"] is True, profile
    assert full["deployment_ready"] is True

    # Split each scorecard so only the sub-gate share verifies. 90/92/95 all
    # sit above 89, so every gate must reject it.
    split = []
    for profile in dr.PROFILES:
        split.append(_control(f"CTRL-{profile}-A", profile, 89, copy.deepcopy(evidence)))
        split.append(_control(f"CTRL-{profile}-B", profile, 11, [
            {"id": "doc", "kind": "repo_file", "path": "docs/D.md", "external": False},
            {"id": "gone", "kind": "credentialed_artifact",
             "path": "release-evidence/load/absent.json", "external": True},
        ]))
    under = dr.build_report(tmp_path, _config(split), runner=PASS_RUNNER)
    for profile, card in under["scorecards"].items():
        assert card["externally_verified_score"] == 89
        assert card["gate_met"] is False, profile
    assert under["deployment_ready"] is False


def test_gate_thresholds_in_the_repo_config_are_90_92_and_95():
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    gates = {p: card["gate"] for p, card in config["scorecards"].items()}
    assert gates == {"overall": 90, "production-lean": 92, "staging": 95}
    for card in config["scorecards"].values():
        assert card["gate_basis"] == "externally_verified"


# ── Exceptions expire, and expiry is a failure rather than a lapse ─────────


def test_an_expired_exception_fails(tmp_path):
    yesterday = (dr._today() - datetime.timedelta(days=1)).isoformat()
    grant = {"id": "DR-EX-OLD", "reason": "r", "owner": "a@x", "approver": "b@x",
             "created": "2026-01-01", "expires": yesterday, "mitigation": "m",
             "follow_up": "FT-1"}
    config = _config(
        _one_per_profile([{"id": "doc", "kind": "repo_file", "path": "docs/D.md",
                           "external": False}]),
        exceptions=[grant],
    )
    assert dr._expired_exceptions(tmp_path, config) == [
        f"{dr.CONFIG_REL}:DR-EX-OLD expired on {yesterday}"
    ]
    report = dr.build_report(tmp_path, config, runner=PASS_RUNNER)
    expiry = next(c for c in report["gate_conditions"]["results"]
                  if c["id"] == "COND-NO-EXPIRED-EXCEPTIONS")
    assert expiry["met"] is False
    assert "DR-EX-OLD" in expiry["reason"]


def test_an_unexpired_exception_passes(tmp_path):
    future = (dr._today() + datetime.timedelta(days=30)).isoformat()
    config = _config(
        _one_per_profile([{"id": "doc", "kind": "repo_file", "path": "docs/D.md",
                           "external": False}]),
        exceptions=[{"id": "DR-EX-OK", "owner": "a@x", "approver": "b@x",
                     "expires": future}],
    )
    assert dr._expired_exceptions(tmp_path, config) == []


def test_an_exception_with_no_expiry_is_rejected(tmp_path):
    """There is no way to write down a permanent grant."""
    config = _config(
        _one_per_profile([{"id": "doc", "kind": "repo_file", "path": "docs/D.md",
                           "external": False}]),
        exceptions=[{"id": "DR-EX-FOREVER", "owner": "a@x", "approver": "b@x"}],
    )
    assert any("no parseable `expires`" in r
               for r in dr._expired_exceptions(tmp_path, config))
    reporter = dr.Reporter("integrity")
    dr.check_integrity(config, reporter)
    assert reporter.finish() != 0


def test_repo_exceptions_are_all_unexpired_today():
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    assert dr._expired_exceptions(ROOT, config) == []


# ── Bundle checksum: both tampering directions are caught ──────────────────


def test_a_sealed_bundle_verifies(tmp_path):
    _write(tmp_path / "release-evidence/load/load-result.json", {"rps": 40})
    _seal_bundle(tmp_path)
    verdict = dr.verify_bundle_checksum(tmp_path)
    assert verdict["verified"] is True
    assert verdict["files_checked"] == 1


def test_a_tampered_evidence_file_fails_checksum_validation(tmp_path):
    _write(tmp_path / "release-evidence/load/load-result.json", {"rps": 40})
    _seal_bundle(tmp_path)
    _write(tmp_path / "release-evidence/load/load-result.json", {"rps": 4000})
    verdict = dr.verify_bundle_checksum(tmp_path)
    assert verdict["verified"] is False
    assert "does not match its recorded digest" in verdict["reason"]


def test_a_tampered_manifest_fails_checksum_validation(tmp_path):
    _write(tmp_path / "release-evidence/load/load-result.json", {"rps": 40})
    _seal_bundle(tmp_path)
    manifest = tmp_path / "release-evidence/manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["file_count"] = 99
    manifest.write_text(json.dumps(data), encoding="utf-8")
    verdict = dr.verify_bundle_checksum(tmp_path)
    assert verdict["verified"] is False
    assert "bundle tampered" in verdict["reason"]


def test_a_deleted_evidence_file_fails_checksum_validation(tmp_path):
    _write(tmp_path / "release-evidence/load/load-result.json", {"rps": 40})
    _seal_bundle(tmp_path)
    (tmp_path / "release-evidence/load/load-result.json").unlink()
    verdict = dr.verify_bundle_checksum(tmp_path)
    assert verdict["verified"] is False
    assert "absent" in verdict["reason"]


def test_an_absent_bundle_is_absent_not_verified(tmp_path):
    verdict = dr.verify_bundle_checksum(tmp_path)
    assert verdict["verified"] is False
    assert "bundle is absent" in verdict["reason"]


# ── Condition thresholds are numeric, not decorative ───────────────────────


def test_fewer_than_seven_days_of_observed_cost_does_not_meet_the_condition(
        tmp_path, attestation_verifier):
    _write(tmp_path / "release-evidence/cost/observed-cost.json",
           {"days": 3, "daily_usd": [1, 1, 1], "provenance": _attested()})
    config = _config(_one_per_profile([
        {"id": "doc", "kind": "repo_file", "path": "docs/D.md", "external": False}]))
    rows = {c["id"]: c for c in dr.evaluate_conditions(tmp_path, config)}
    assert rows["COND-COST-OBSERVED-7D"]["met"] is False
    assert "7 required" in rows["COND-COST-OBSERVED-7D"]["reason"]


def test_cost_reconciliation_outside_tolerance_does_not_meet_the_condition(
        tmp_path, attestation_verifier):
    _write(tmp_path / "release-evidence/cost/reconciliation.json",
           {"projected_usd": 100, "observed_usd": 300, "variance_percent": 200,
            "provenance": _attested()})
    config = _config(_one_per_profile([
        {"id": "doc", "kind": "repo_file", "path": "docs/D.md", "external": False}]))
    rows = {c["id"]: c for c in dr.evaluate_conditions(tmp_path, config)}
    assert rows["COND-COST-RECONCILED"]["met"] is False
    assert "exceeds the 25% reconciliation tolerance" in rows["COND-COST-RECONCILED"]["reason"]


def test_outstanding_p0_items_block_the_ledger_conditions(tmp_path):
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config/implementation_ledger.yaml").write_text(
        yaml.safe_dump({"items": [
            {"id": "BAD", "severity": "P0", "status": "not_started"}]}),
        encoding="utf-8")
    met, reason = dr._outstanding_ledger_items(tmp_path, "P0")
    assert met is False and "BAD" in reason


# ── Control-table integrity mirrors the implementation ledger's rules ──────


def test_externally_blocked_requires_an_exception(tmp_path):
    config = _config(_one_per_profile(
        [{"id": "doc", "kind": "repo_file", "path": "docs/D.md", "external": False}],
        status="externally_blocked"))
    reporter = dr.Reporter("integrity")
    dr.check_integrity(config, reporter)
    assert reporter.finish() != 0
    assert any("externally_blocked requires an exception" in f for f in reporter.failures)


def test_verified_complete_requires_a_verified_commit(tmp_path):
    config = _config(_one_per_profile(
        [{"id": "doc", "kind": "repo_file", "path": "docs/D.md", "external": False}],
        status="verified_complete"))
    reporter = dr.Reporter("integrity")
    dr.check_integrity(config, reporter)
    assert reporter.finish() != 0
    assert any("last_verified_commit" in f for f in reporter.failures)


def test_a_declared_external_dependency_needs_external_evidence(tmp_path):
    config = _config(_one_per_profile(
        [{"id": "doc", "kind": "repo_file", "path": "docs/D.md", "external": False}],
        external_dependency={"required": True, "what": "AWS"}))
    reporter = dr.Reporter("integrity")
    dr.check_integrity(config, reporter)
    assert reporter.finish() != 0
    assert any("no evidence entry is marked external" in f for f in reporter.failures)


def test_weights_that_do_not_total_the_scorecard_fail_integrity(tmp_path):
    controls = _one_per_profile(
        [{"id": "doc", "kind": "repo_file", "path": "docs/D.md", "external": False}])
    controls[0]["weight"] = 60
    reporter = dr.Reporter("integrity")
    dr.check_integrity(_config(controls), reporter)
    assert reporter.finish() != 0
    assert any("expected 100" in f for f in reporter.failures)


def test_a_control_with_no_required_evidence_fails_integrity(tmp_path):
    controls = _one_per_profile(
        [{"id": "doc", "kind": "repo_file", "path": "docs/D.md", "external": False}])
    controls[0]["required_evidence"] = []
    controls[0]["external_dependency"] = {"required": False, "what": None}
    reporter = dr.Reporter("integrity")
    dr.check_integrity(_config(controls), reporter)
    assert reporter.finish() != 0
    assert any("can never be earned" in f for f in reporter.failures)


# ── The shipped config, scored against this repository ─────────────────────


def test_repo_config_passes_integrity():
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    reporter = dr.Reporter("integrity")
    dr.check_integrity(config, reporter)
    assert reporter.finish() == 0, reporter.failures


def test_every_repo_control_carries_the_full_schema():
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    required = {"id", "profile", "description", "weight", "required_evidence",
                "status", "last_verified_commit", "last_verified_at",
                "evidence_path", "external_dependency", "exception"}
    for control in config["controls"]:
        assert required <= set(control), control.get("id")
        assert isinstance(control["external_dependency"], dict)
        assert "required" in control["external_dependency"]
        for entry in control["required_evidence"]:
            assert entry["kind"] in dr.EVIDENCE_KINDS
            assert entry["path"]


def test_this_repo_cannot_report_a_verified_score_it_has_not_earned():
    """The end-to-end honesty property, asserted against real repo state.

    No AWS account is reachable here, so every externally-dependent control
    must be unproven, every gate must be unmet, and deployment_ready must be
    false — regardless of how much of the code is finished.
    """
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    report = dr.build_report(ROOT, config, runner=PASS_RUNNER)
    assert report["gate_conditions"]["all_met"] is False
    assert report["deployment_ready"] is False
    assert report["evidence_bundle"]["verified"] is False
    for profile, card in report["scorecards"].items():
        assert card["gate_met"] is False, profile
        assert card["externally_verified_score"] < card["gate"]
        assert card["externally_verified_score"] <= card["max_attainable_verified_score"]
    # EVERY control, not only the ones that declare an external dependency.
    # Guarding this loop on `external_dependency.required` exempted exactly the
    # three controls that produced the whole reported verified score, so the
    # assertion held while the number it was defending was wrong.
    for control in report["controls"]:
        assert control["externally_verified"] is False, control["id"]


def test_repo_report_states_the_environment_limitation_in_plain_language():
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    report = dr.build_report(ROOT, config, runner=PASS_RUNNER)
    note = report["environment_note"]
    assert "No AWS credentials" in note
    assert "code-complete score is not a readiness figure" in note


# ── Attack 1: all([]) promoted a control with no external evidence ─────────


def test_a_control_with_no_external_evidence_is_never_verified(tmp_path):
    """`all([])` is True, so zero external entries used to mean "all verified".

    That was not an edge case: it was 100% of the shipped verified score.
    OVR-LEAN-TOPOLOGY (15) + OVR-CROSS-PROFILE-PARITY (5) and
    LEAN-RUNTIME-TOPOLOGY (20) each declare no external evidence at all, so the
    tool printed "externally-verified 20" directly beside a note saying no AWS
    is reachable — both statements produced by the same run.
    """
    _write(tmp_path / "docs/D.md", "documented")
    config = _config(_one_per_profile([
        {"id": "doc", "kind": "repo_file", "path": "docs/D.md", "external": False},
    ]))
    report = dr.build_report(tmp_path, config, runner=PASS_RUNNER)
    for profile, card in report["scorecards"].items():
        assert card["code_complete_score"] == 100, profile
        assert card["externally_verified_score"] == 0, profile
        assert card["unverifiable_weight"] == 100, profile
        assert card["controls_without_external_evidence"] == [f"CTRL-{profile}"]
    for control in report["controls"]:
        assert control["externally_verifiable"] is False
        assert control["external_evidence_entries"] == 0
        assert control["externally_verified"] is False


def test_the_repo_controls_that_produced_the_verified_score_no_longer_do():
    """The three specific controls the audit named, asserted by id."""
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    report = dr.build_report(ROOT, config, runner=PASS_RUNNER)
    rows = {c["id"]: c for c in report["controls"]}
    for cid in ("OVR-LEAN-TOPOLOGY", "OVR-CROSS-PROFILE-PARITY",
                "LEAN-RUNTIME-TOPOLOGY"):
        assert rows[cid]["external_evidence_entries"] == 0, cid
        assert rows[cid]["externally_verified"] is False, cid


# ── Attack 2: a weight edit moved the score AND its ceiling ────────────────


def test_editing_a_control_weight_in_yaml_is_an_integrity_failure(tmp_path):
    """A weight edit alone took lean verified 20 → 95, gate met, exit 0.

    The ceiling was `total - sum(weight of blocked controls)`, so moving weight
    off a blocked control and onto an unblocked one raised the ceiling and the
    score together. Weights are pinned in code now: a weight is not evidence,
    and the file being scored does not get to choose it.
    """
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    edited = copy.deepcopy(config)
    by_id = {c["id"]: c for c in edited["controls"]}
    by_id["LEAN-FORBIDDEN-EXCLUSION"]["weight"] = 5
    by_id["LEAN-RUNTIME-TOPOLOGY"]["weight"] = 40
    reporter = dr.Reporter("integrity")
    dr.check_integrity(edited, reporter)
    assert reporter.finish() != 0
    assert any("pinned weight" in f for f in reporter.failures)


def test_a_weight_edit_moves_neither_the_score_nor_the_ceiling():
    """Beyond failing integrity, the edited weights must not be scored from."""
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    honest = dr.build_report(ROOT, config, runner=PASS_RUNNER)

    edited = copy.deepcopy(config)
    by_id = {c["id"]: c for c in edited["controls"]}
    by_id["LEAN-FORBIDDEN-EXCLUSION"]["weight"] = 5
    by_id["LEAN-RUNTIME-TOPOLOGY"]["weight"] = 40
    tampered = dr.build_report(ROOT, edited, runner=PASS_RUNNER)

    for profile in dr.PROFILES:
        before, after = honest["scorecards"][profile], tampered["scorecards"][profile]
        assert after["code_complete_score"] == before["code_complete_score"], profile
        assert after["externally_verified_score"] == before["externally_verified_score"]
        assert (after["max_attainable_verified_score"]
                == before["max_attainable_verified_score"]), profile


def test_a_control_id_that_is_not_pinned_cannot_be_added_in_yaml(tmp_path):
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    edited = copy.deepcopy(config)
    edited["controls"].append({
        "id": "OVR-INVENTED", "profile": "overall", "description": "d",
        "weight": 0, "required_evidence": [
            {"id": "doc", "kind": "repo_file", "path": "README.md", "external": False}],
        "status": "implemented", "last_verified_commit": None,
        "last_verified_at": None, "evidence_path": "release-evidence/profile/",
        "external_dependency": {"required": False, "what": None}, "exception": None,
    })
    reporter = dr.Reporter("integrity")
    dr.check_integrity(edited, reporter)
    assert reporter.finish() != 0
    assert any("PINNED_CONTROL_WEIGHTS" in f for f in reporter.failures)


# ── Attack 3: conditions were pinned by id, and evaluated from YAML ────────


def test_rewriting_every_condition_kind_does_not_make_them_met(tmp_path):
    """17/17 met with release-evidence/ absent, from a YAML edit alone.

    Deleting a condition was caught. Editing one was not: `evaluate_conditions`
    read `kind` and `evidence` straight out of the file it was scoring, so
    rewriting all seventeen kinds to `ledger_severity` with a severity no item
    carries satisfied every one of them.
    """
    _clean_ledger(tmp_path)
    config = _config(_one_per_profile([
        {"id": "doc", "kind": "repo_file", "path": "docs/D.md", "external": False}]))
    for row in config["gate_conditions"]:
        row["kind"] = "ledger_severity"
        row["evidence"] = "config/implementation_ledger.yaml"
        row["severity"] = "P9-NONEXISTENT"

    rows = {c["id"]: c for c in dr.evaluate_conditions(tmp_path, config)}
    met = sorted(cid for cid, row in rows.items() if row["met"])
    # Only the three that are genuinely met here: a clean ledger has no
    # outstanding P0/P1 items, and an empty config has no expired exceptions.
    # Every condition that needs an artifact stays unmet with none on disk.
    assert met == ["COND-NO-EXPIRED-EXCEPTIONS", "COND-NO-UNRESOLVED-P0",
                   "COND-NO-UNRESOLVED-P1"], met
    # The evaluation used the pinned definitions, not the rewritten ones.
    assert rows["COND-LOAD-VALIDATED"]["kind"] == "credentialed_artifact"
    assert rows["COND-LOAD-VALIDATED"]["evidence"] == (
        "release-evidence/load/load-result.json")


def test_a_rewritten_condition_definition_is_an_integrity_failure():
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    edited = copy.deepcopy(config)
    for row in edited["gate_conditions"]:
        if row["id"] == "COND-LOAD-VALIDATED":
            row["kind"] = "ledger_severity"
            row["severity"] = "P9-NONEXISTENT"
    reporter = dr.Reporter("integrity")
    dr.check_integrity(edited, reporter)
    assert reporter.finish() != 0
    assert any("drifted from the pinned table" in f for f in reporter.failures)


def test_moving_a_conditions_evidence_path_is_an_integrity_failure():
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    edited = copy.deepcopy(config)
    for row in edited["gate_conditions"]:
        if row["id"] == "COND-COST-OBSERVED-7D":
            row["evidence"] = "README.md"
            row["minimum_days"] = 0
    reporter = dr.Reporter("integrity")
    dr.check_integrity(edited, reporter)
    assert reporter.finish() != 0
    assert any("COND-COST-OBSERVED-7D.evidence" in f for f in reporter.failures)


def test_the_repo_conditions_match_the_pinned_table_exactly():
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    for row in config["gate_conditions"]:
        pinned = dr.REQUIRED_CONDITIONS[row["id"]]
        for field, expected in pinned.items():
            assert row[field] == expected, f"{row['id']}.{field}"


# ── Attack 4: self-declared provenance is not attestation ──────────────────


def test_hand_written_provenance_earns_no_verified_point(tmp_path):
    """Fifteen hand-written JSONs took overall verified 20 → 95.

    The payloads were lifted from this very file's `_provenance()` helper, which
    is the point: every field a "credentialed" artifact declares is typed by
    whoever writes it, so the verified score was a text-editing exercise.
    """
    _clean_ledger(tmp_path)
    _satisfy_all_external(tmp_path)      # structurally perfect, self-declared
    _seal_bundle(tmp_path)
    _write(tmp_path / "docs/D.md", "documented")
    config = _config(_one_per_profile([
        {"id": "doc", "kind": "repo_file", "path": "docs/D.md", "external": False},
        {"id": "load", "kind": "credentialed_artifact",
         "path": "release-evidence/load/load-result.json", "external": True},
    ]))
    report = dr.build_report(tmp_path, config, runner=PASS_RUNNER)
    for profile, card in report["scorecards"].items():
        assert card["code_complete_score"] == 100, profile
        assert card["externally_verified_score"] == 0, profile
    assert report["deployment_ready"] is False
    unmet = [c for c in report["gate_conditions"]["results"] if not c["met"]]
    # Every artifact-backed condition: the thirteen credentialed ones plus the
    # bundle checksum. Only the ledger and expiry conditions can be met here.
    assert len(unmet) == 14, [c["id"] for c in unmet]
    assert all("self-declared" in c["reason"] for c in unmet
               if c["kind"] == "credentialed_artifact")
    assert dr.ATTESTATION_VERIFIERS == {}, (
        "no attestation verifier ships with this repository, and the report "
        "must say so rather than implying verification happened")
    assert "self-declared" in report["attestation"]["note"] or \
        "no attestation verifier" in report["attestation"]["note"].lower()


def test_the_whole_audit_forgery_still_produces_zero(tmp_path):
    """Fifteen artifacts + the repo's own seal + a clean ledger reached 100/100/100."""
    _clean_ledger(tmp_path)
    _satisfy_all_external(tmp_path)
    _seal_bundle(tmp_path)
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    report = dr.build_report(tmp_path, config, runner=PASS_RUNNER)
    for profile, card in report["scorecards"].items():
        assert card["externally_verified_score"] == 0, profile
        assert card["gate_met"] is False, profile
    assert report["deployment_ready"] is False
    assert report["gate_conditions"]["all_met"] is False


def test_a_registered_attestation_verifier_can_earn_a_point(
        tmp_path, attestation_verifier):
    """The mechanism must work in both directions, or it is hardcoded to False."""
    _write(tmp_path / "docs/D.md", "documented")
    _write(tmp_path / "release-evidence/load/load-result.json",
           {"rps": 40, "provenance": _attested()})
    evidence = [
        {"id": "doc", "kind": "repo_file", "path": "docs/D.md", "external": False},
        {"id": "load", "kind": "credentialed_artifact",
         "path": "release-evidence/load/load-result.json", "external": True},
    ]
    config = _config(_one_per_profile(evidence))
    report = dr.build_report(tmp_path, config, runner=PASS_RUNNER)
    for card in report["scorecards"].values():
        assert card["externally_verified_score"] == 100

    # ...and a verifier that rejects the artifact takes the point straight back.
    dr.ATTESTATION_VERIFIERS[attestation_verifier] = lambda data: ["run id not found"]
    rejected = dr.build_report(tmp_path, config, runner=PASS_RUNNER)
    for card in rejected["scorecards"].values():
        assert card["externally_verified_score"] == 0
    assert any("run id not found" in c["unmet"][0] for c in rejected["controls"])


def test_an_unknown_attestation_kind_is_still_self_declared():
    reasons = dr.verify_attestation(
        {"provenance": _provenance(attestation={"kind": "trust-me"})})
    assert any("no verifier this tool can execute" in r for r in reasons)


# ── Attack 5: the bundle seal is produced in-repo by construction ──────────


def test_sealing_the_bundle_in_repo_does_not_meet_the_checksum_condition(tmp_path):
    """collect_evidence.py seals whatever is on disk, so integrity is free.

    One of the seventeen "conditions for a 100% result" needed no AWS at all:
    running the repo's own collector produced a manifest that hashed to its own
    checksum, and the condition went green.
    """
    _write(tmp_path / "release-evidence/load/load-result.json", {"rps": 40})
    _seal_bundle(tmp_path)
    assert dr.verify_bundle_checksum(tmp_path)["verified"] is True, (
        "integrity itself still holds — that is not what is being questioned")

    config = _config(_one_per_profile([
        {"id": "doc", "kind": "repo_file", "path": "docs/D.md", "external": False}]))
    row = next(c for c in dr.evaluate_conditions(tmp_path, config)
               if c["id"] == "COND-BUNDLE-CHECKSUM")
    assert row["met"] is False
    assert "self-sealed" in row["reason"]


def test_an_attested_manifest_meets_the_checksum_condition(
        tmp_path, attestation_verifier):
    _write(tmp_path / "release-evidence/load/load-result.json", {"rps": 40})
    _seal_bundle(tmp_path, attested=True)
    config = _config(_one_per_profile([
        {"id": "doc", "kind": "repo_file", "path": "docs/D.md", "external": False}]))
    row = next(c for c in dr.evaluate_conditions(tmp_path, config)
               if c["id"] == "COND-BUNDLE-CHECKSUM")
    assert row["met"] is True, row["reason"]


# ── Attack 6: evidence_path was required, stored, and read by nothing ──────


def test_evidence_path_must_name_a_declared_evidence_class():
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    edited = copy.deepcopy(config)
    edited["controls"][0]["evidence_path"] = "docs/"
    reporter = dr.Reporter("integrity")
    dr.check_integrity(edited, reporter)
    assert reporter.finish() != 0
    assert any("evidence classes" in f for f in reporter.failures)


def test_external_evidence_must_live_inside_the_bundle():
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    edited = copy.deepcopy(config)
    control = next(c for c in edited["controls"]
                   if any(e.get("external") for e in c["required_evidence"]))
    entry = next(e for e in control["required_evidence"] if e.get("external"))
    entry["path"] = "reports/cost/cost-report.json"
    reporter = dr.Reporter("integrity")
    dr.check_integrity(edited, reporter)
    assert reporter.finish() != 0
    assert any("never sealed into the evidence bundle" in f
               for f in reporter.failures)


def test_evidence_path_is_read_and_reported(tmp_path):
    """It is load-bearing now: the report lists what was collected under it."""
    _write(tmp_path / "docs/D.md", "documented")
    _write(tmp_path / "release-evidence/load/load-result.json", {"rps": 40})
    config = _config(_one_per_profile(
        [{"id": "doc", "kind": "repo_file", "path": "docs/D.md", "external": False}],
        evidence_path="release-evidence/load/"))
    report = dr.build_report(tmp_path, config, runner=PASS_RUNNER)
    for control in report["controls"]:
        assert control["evidence_files"] == ["release-evidence/load/load-result.json"]


# ── Attack 7 & the fixture-derived code-complete score ─────────────────────


def test_an_artifact_derived_from_a_fixture_earns_nothing(tmp_path):
    """`make validate-cost-model` against the committed fixture moved the score.

    The code-complete half was path-dependent on gitignored directories: a
    clean checkout scored 60 overall, and running one make target against the
    committed fixture took it to 100. Two engineers, same commit, different
    readiness numbers.
    """
    _write(tmp_path / "artifacts/profile-policy-result.json", {
        "profile": "production-lean", "passed": True, "violations": [],
        "checks_total": 59,
        "plan_json": "/repo/tests/fixtures/terraform_plans/production-lean-valid.json",
        "synthetic_input": "tests/fixtures"})
    _write(tmp_path / "reports/cost/cost-report.json", {
        "profile": "production-lean", "gated_amount": 187.13,
        "effective_ceiling": 200.0, "passed": True,
        "inventory_path": "artifacts/profile-resource-inventory.json",
        "inventory_source": {
            "generated_from": "tests/fixtures/terraform_plans/production-lean-valid.json",
            "synthetic_input": "tests/fixtures"}})
    config = _config(_one_per_profile([
        {"id": "plan", "kind": "json_artifact",
         "path": "artifacts/profile-policy-result.json",
         "require_keys": ["profile", "passed"], "require_true": ["passed"],
         "external": False},
        {"id": "cost", "kind": "json_artifact",
         "path": "reports/cost/cost-report.json",
         "require_keys": ["profile", "gated_amount"], "external": False},
    ]))
    report = dr.build_report(tmp_path, config, runner=PASS_RUNNER)
    for card in report["scorecards"].values():
        assert card["code_complete_score"] == 0
    reasons = " ".join(c["unmet"][0] for c in report["controls"])
    assert "test fixture" in reasons


def test_an_artifact_from_a_real_plan_still_earns_its_point(tmp_path):
    """The rejection must be about provenance, not about the artifact's shape."""
    _write(tmp_path / "artifacts/profile-policy-result.json", {
        "profile": "production-lean", "passed": True, "violations": [],
        "checks_total": 59, "plan_json": "artifacts/reviewed.tfplan.json",
        "synthetic_input": None})
    config = _config(_one_per_profile([
        {"id": "plan", "kind": "json_artifact",
         "path": "artifacts/profile-policy-result.json",
         "require_keys": ["profile", "passed"], "require_true": ["passed"],
         "external": False},
    ]))
    report = dr.build_report(tmp_path, config, runner=PASS_RUNNER)
    for card in report["scorecards"].values():
        assert card["code_complete_score"] == 100


def test_the_six_reported_numbers_are_the_ones_this_repo_earns():
    """All six numbers pinned, measured with the REAL validators.

    Every other repo-state test in this file uses PASS_RUNNER, so a validator
    that started failing would not move any of them. This one runs the actual
    check scripts, which is what the CLI does and therefore what anyone quoting
    a readiness number is quoting.

    Changing these numbers is a deliberate act: update this test in the same
    commit as the change that moved them, and say why.
    """
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    report = dr.build_report(ROOT, config)
    measured = {
        profile: (card["code_complete_score"], card["externally_verified_score"])
        for profile, card in report["scorecards"].items()
    }
    assert measured == {
        "overall": (60, 0),
        "production-lean": (45, 0),
        # The guarded first-admin bootstrap is code-complete, but it does not
        # create external rehearsal evidence; the real staging score remains
        # 75/100 until a credentialed wake produces that evidence.
        "staging": (75, 0),
    }, measured
    # Verified is zero for a reason that is stated, not merely absent.
    assert report["attestation"]["verifiers_registered"] == []


def test_the_numbers_do_not_depend_on_gitignored_local_artifacts(tmp_path):
    """The score must reflect the commit, not what happens to be on the disk."""
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    baseline = dr.build_report(ROOT, config, runner=PASS_RUNNER)

    # Whatever a local `make validate-cost-model` leaves behind, it is derived
    # from the committed fixture and must not move a single point.
    for row in baseline["controls"]:
        for entry in row["evidence"]:
            if entry["path"].startswith(("artifacts/", "reports/")):
                assert not entry["satisfied"] or entry.get("synthetic") is None
    artifacts = ROOT / "artifacts/profile-policy-result.json"
    if artifacts.is_file():
        data = json.loads(artifacts.read_text(encoding="utf-8"))
        assert dr.synthetic_artifact_reason(data), (
            "the committed fixture pipeline must stamp its output as synthetic")


# ── Exit codes are asserted, not assumed ──────────────────────────────────


def test_run_exits_zero_but_refuses_the_readiness_claim_under_require_gates(capsys):
    """`run()` was never invoked by this suite, so no exit code was ever tested."""
    assert dr.run([]) == dr.EXIT_OK
    assert dr.run(["--require-gates"]) == dr.EXIT_GATE
    out = capsys.readouterr()
    assert "deployment_ready: False" in out.out


def test_run_writes_a_canonical_json_report(tmp_path):
    out = tmp_path / "readiness.json"
    assert dr.run(["--out", str(out)]) == dr.EXIT_OK
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["deployment_ready"] is False
    assert all(card["externally_verified_score"] == 0
               for card in report["scorecards"].values())


def test_integrity_failure_exits_one(tmp_path, monkeypatch):
    """A tampered control table voids the score, whatever the score says."""
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    edited = copy.deepcopy(config)
    next(c for c in edited["controls"]
         if c["id"] == "LEAN-RUNTIME-TOPOLOGY")["weight"] = 40
    next(c for c in edited["controls"]
         if c["id"] == "LEAN-COST-CEILING")["weight"] = 0
    path = tmp_path / "deployment_readiness.yaml"
    path.write_text(yaml.safe_dump(edited, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(dr, "CONFIG_REL", path.name)
    monkeypatch.setattr(dr, "repo_root", lambda: tmp_path)
    assert dr.run([]) == dr.EXIT_INTEGRITY
