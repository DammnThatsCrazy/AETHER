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
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "release"))

import check_deployment_readiness as dr  # noqa: E402
import collect_evidence  # noqa: E402

CONFIG_PATH = ROOT / "config/deployment_readiness.yaml"

PASS_RUNNER = lambda path, args: (0, "")            # noqa: E731
FAIL_RUNNER = lambda path, args: (1, "validator said no")  # noqa: E731


# ── Fixtures: a synthetic control table we can attack ──────────────────────


def _provenance(**over) -> dict:
    """A provenance block that would be valid if it came from a real run.

    Tests are allowed to construct one; that is the point of testing the
    validator. Nothing in the repository's own evidence does.
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


def _satisfy_all_external(root: Path) -> None:
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
    for rel, body in payloads.items():
        _write(root / rel, {**body, "provenance": _provenance()})


def _seal_bundle(root: Path) -> None:
    """Write a valid manifest + checksum over whatever is in the bundle."""
    collect_evidence.write_bundle_layout(root / "release-evidence", {"commit": "abc123"})


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


def test_invariant_fires_when_a_control_outscores_its_condition_ceiling(tmp_path):
    """The tamper detector: evidence on disk and the control table disagree.

    The control is rewritten to earn its weight from a file anyone can create,
    while the condition that governs it still reads real provenance from disk
    and is still unmet. The scorecard must refuse the number rather than print
    it.
    """
    _write(tmp_path / "docs/D.md", "documented")
    blocks = {"COND-LOAD-VALIDATED": [f"CTRL-{p}" for p in dr.PROFILES]}
    config = _config(_one_per_profile([
        {"id": "doc", "kind": "repo_file", "path": "docs/D.md", "external": False},
    ]), blocks=blocks)
    report = dr.build_report(tmp_path, config, runner=PASS_RUNNER)
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


def test_release_gates_are_enforced_at_90_92_and_95(tmp_path):
    """Gates fail below the line and pass above it — proving they are read."""
    _clean_ledger(tmp_path)
    _satisfy_all_external(tmp_path)
    _seal_bundle(tmp_path)
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


def test_fewer_than_seven_days_of_observed_cost_does_not_meet_the_condition(tmp_path):
    _write(tmp_path / "release-evidence/cost/observed-cost.json",
           {"days": 3, "daily_usd": [1, 1, 1], "provenance": _provenance()})
    config = _config(_one_per_profile([
        {"id": "doc", "kind": "repo_file", "path": "docs/D.md", "external": False}]))
    rows = {c["id"]: c for c in dr.evaluate_conditions(tmp_path, config)}
    assert rows["COND-COST-OBSERVED-7D"]["met"] is False
    assert "7 required" in rows["COND-COST-OBSERVED-7D"]["reason"]


def test_cost_reconciliation_outside_tolerance_does_not_meet_the_condition(tmp_path):
    _write(tmp_path / "release-evidence/cost/reconciliation.json",
           {"projected_usd": 100, "observed_usd": 300, "variance_percent": 200,
            "provenance": _provenance()})
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
    # Controls that need a real cloud account never contribute to verified.
    for control in report["controls"]:
        if control["external_dependency"].get("required"):
            assert control["externally_verified"] is False, control["id"]


def test_repo_report_states_the_environment_limitation_in_plain_language():
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    report = dr.build_report(ROOT, config, runner=PASS_RUNNER)
    note = report["environment_note"]
    assert "No AWS credentials" in note
    assert "code-complete score is not a readiness figure" in note
