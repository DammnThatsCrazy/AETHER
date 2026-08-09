"""Tests for the credential-turnkey capability matrix + strict gate
(``scripts/credential_turnkey_gate.py``, program sec24).

Asserts the two properties that make the gate honest and usable:

* a COMPLETE capability (full evidence) PASSES the strict gate (exit 0);
* an OBVIOUSLY-INCOMPLETE capability FAILS it (exit 1), and each of the strict
  gate's MUST-FAIL conditions — scaffolding-only provider, hardcoded secrets,
  unsupervised worker, health that can report false success, undeclared
  metering/entitlement, live-readiness claim without evidence — maps to a
  FAILing matrix row.

The matrix evaluation is pure over the evidence dict, so the tests exercise the
gate logic without touching the live repo (no secret scan, no backend imports).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "credential_turnkey_gate", ROOT / "scripts" / "credential_turnkey_gate.py"
)
gate = importlib.util.module_from_spec(_spec)
sys.modules["credential_turnkey_gate"] = gate
_spec.loader.exec_module(gate)

# The 38 matrix rows the gate must expose (sec24 list + the two strict-gate
# honesty rows: health_honest and live_readiness_evidence).
EXPECTED_ROWS = {
    "canonical_provider_manifest", "credential_slots_declared",
    "credential_authority_integrated", "tenant_scoped", "environment_scoped",
    "secret_safe", "transport_implemented", "payload_normalization",
    "storage_persistent", "migrations", "idempotency", "cursor_checkpoint",
    "retry", "dead_letter", "reconciliation", "repair", "worker_supervised",
    "heartbeat", "readiness_exposed", "health_honest",
    "missing_credential_explicit", "invalid_credential_explicit",
    "provider_outage_explicit", "empty_vs_failure_preserved",
    "unknown_vs_zero_preserved", "credential_rotation_tested",
    "automatic_readiness_demotion", "tenant_diagnostics",
    "operator_diagnostics", "usage_meter_defined", "entitlement_key_defined",
    "storage_policy_defined", "offline_conformance_fixtures",
    "fault_injection_suite", "infra_dependency_declared",
    "documentation_current", "ci_green", "live_readiness_evidence",
}


def _row(matrix: dict, row_id: str) -> dict:
    for r in matrix["rows"]:
        if r["id"] == row_id:
            return r
    raise AssertionError(f"row {row_id!r} not present in matrix")


def test_matrix_shape_and_required_rows():
    matrix = gate.evaluate_matrix(gate.complete_evidence())
    ids = [r["id"] for r in matrix["rows"]]
    assert len(ids) == len(gate.MATRIX_ROWS) == len(EXPECTED_ROWS)
    assert set(ids) == EXPECTED_ROWS
    assert len(set(ids)) == len(ids)  # no duplicate ids
    assert matrix["schema_version"] == 1
    assert matrix["summary"]["total"] == len(ids)


def test_complete_evidence_passes_strict_gate():
    matrix = gate.evaluate_matrix(gate.complete_evidence())
    assert matrix["summary"]["fail"] == 0
    assert matrix["summary"]["strict_pass"] is True
    assert gate.strict_exit_code(matrix) == 0


def test_incomplete_evidence_fails_strict_gate():
    ev = dict(gate.complete_evidence())
    # Obvious incompleteness: a provider is scaffolding-only.
    ev["scaffolded_providers"] = [
        {"domain": "payments", "provider": "privy", "state": "scaffolded"}
    ]
    matrix = gate.evaluate_matrix(ev)
    assert gate.strict_exit_code(matrix) == 1
    assert matrix["summary"]["strict_pass"] is False
    assert matrix["summary"]["fail"] >= 1
    assert _row(matrix, "canonical_provider_manifest")["status"] == "fail"


def test_scaffolding_only_provider_fails_canonical_manifest_row():
    ev = dict(gate.complete_evidence())
    ev["scaffolded_providers"] = [
        {"domain": "derivatives", "provider": "dydx", "state": "scaffolded"}
    ]
    row = _row(gate.evaluate_matrix(ev), "canonical_provider_manifest")
    assert row["status"] == "fail"
    assert "SCAFFOLDED" in row["detail"]


def test_hardcoded_secret_fails_secret_safe():
    ev = dict(gate.complete_evidence())
    ev["secret_findings"] = [("services/x402/service.py", 12, "sk_live_AB...")]
    ev["secret_scan_ran"] = True
    row = _row(gate.evaluate_matrix(ev), "secret_safe")
    assert row["status"] == "fail"
    assert "hardcoded" in row["detail"]


def test_unsupervised_worker_fails_worker_supervised():
    ev = dict(gate.complete_evidence())
    ev["workers_unsupervised"] = ["settlement_sweeper", "approval_sweeper"]
    row = _row(gate.evaluate_matrix(ev), "worker_supervised")
    assert row["status"] == "fail"
    assert "not supervised" in row["detail"]


def test_false_success_health_fails_health_honest():
    ev = dict(gate.complete_evidence())
    ev["health_false_success"] = True
    row = _row(gate.evaluate_matrix(ev), "health_honest")
    assert row["status"] == "fail"
    assert "false success" in row["detail"]


def test_undeclared_metering_and_entitlement_fail():
    ev = dict(gate.complete_evidence())
    ev["usage_meter_defined"] = False
    ev["entitlement_key_defined"] = False
    matrix = gate.evaluate_matrix(ev)
    assert _row(matrix, "usage_meter_defined")["status"] == "fail"
    assert _row(matrix, "entitlement_key_defined")["status"] == "fail"


def test_live_readiness_claim_without_evidence_fails():
    ev = dict(gate.complete_evidence())
    ev["dishonest_readiness_claims"] = [
        {"domain": "payments", "provider": "privy", "state": "partner_live"}
    ]
    row = _row(gate.evaluate_matrix(ev), "live_readiness_evidence")
    assert row["status"] == "fail"
    assert "lack evidence" in row["detail"]


def test_rotation_untested_is_external_blocker_not_pass():
    ev = dict(gate.complete_evidence())
    ev["rotation_method_declared"] = False
    ev["rotation_tests"] = False
    ev["rotation_live_verified"] = False
    ev["live_evidence_present"] = False
    row = _row(gate.evaluate_matrix(ev), "credential_rotation_tested")
    assert row["status"] == "fail"
    assert row["external_blocker"] is True


def test_warn_rows_do_not_fail_strict_gate():
    """A WARN-only matrix must still PASS the strict gate (WARN is never a
    blocker); the report shows it honestly but does not overclaim PASS."""
    ev = dict(gate.complete_evidence())
    ev["docs_current"] = False  # documentation row → WARN
    ev["ci_verified"] = False  # ci_green → WARN (gate declared but not verified here)
    ev["ci_gate_declared"] = True
    matrix = gate.evaluate_matrix(ev)
    assert matrix["summary"]["fail"] == 0
    assert matrix["summary"]["warn"] >= 2
    assert gate.strict_exit_code(matrix) == 0


def test_evaluation_is_deterministic():
    ev = dict(gate.complete_evidence())
    assert gate.evaluate_matrix(ev) == gate.evaluate_matrix(ev)
