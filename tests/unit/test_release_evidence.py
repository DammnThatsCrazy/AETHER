"""Release evidence bundle + derived SDK conformance matrix tests.

The evidence bundle must be assembled from real repo state and must never
fabricate or imply external certifications; the SDK conformance matrix must be
derived from SDK sources/test manifests and fail closed on unverifiable claims.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "release"))

import collect_evidence  # noqa: E402
from sdk_conformance import build_matrix  # noqa: E402


# ── SDK conformance matrix — derived from code, fail-closed ────────────────


def test_conformance_matrix_derives_cleanly_from_this_repo():
    matrix, failures = build_matrix(REPO_ROOT)
    assert failures == []
    summary = matrix["summary"]
    assert summary["cells"] > 0
    assert summary["claimed"] > 0
    assert summary["verified"] == summary["claimed"]
    assert summary["failed"] == 0


def test_conformance_matrix_covers_every_declared_sdk_with_real_tests():
    matrix, _ = build_matrix(REPO_ROOT)
    parity = json.loads(
        (REPO_ROOT / "packages/shared/sdk-parity.json").read_text(encoding="utf-8")
    )
    assert set(matrix["sdks"]) == set(parity["sdks"])
    for sdk, counts in matrix["sdks"].items():
        assert counts["test_files"] > 0, f"{sdk} has no discovered test files"
        assert counts["test_cases"] > 0, f"{sdk} has no discovered test cases"


def test_conformance_matrix_records_test_references_for_verified_cells():
    matrix, _ = build_matrix(REPO_ROOT)
    referenced = 0
    for cap in matrix["capabilities"]:
        for cell in cap["cells"].values():
            if cell.get("evidence_verified"):
                assert "test_references" in cell
                referenced += len(cell["test_references"])
    # The parity capabilities are exercised by tests somewhere across SDKs.
    assert referenced > 0


def _write_parity(root: Path, evidence: str) -> None:
    parity = {
        "version": "0.0.0",
        "sdks": ["web"],
        "capabilities": [
            {
                "id": "observe",
                "title": "observe",
                "spec": "2.6",
                "matrix": {"web": {"status": "supported", "evidence": evidence}},
            }
        ],
    }
    target = root / "packages/shared/sdk-parity.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(parity), encoding="utf-8")


def test_conformance_fails_closed_when_evidence_file_is_missing(tmp_path):
    _write_parity(tmp_path, "packages/web/src/index.ts#observe")
    _, failures = build_matrix(tmp_path)
    assert any("evidence file missing" in f for f in failures)


def test_conformance_fails_closed_when_symbol_is_absent(tmp_path):
    _write_parity(tmp_path, "packages/web/src/index.ts#observe")
    src = tmp_path / "packages/web/src/index.ts"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("export const somethingElse = 1;", encoding="utf-8")
    _, failures = build_matrix(tmp_path)
    assert any("not found" in f for f in failures)


def test_conformance_verifies_when_evidence_resolves(tmp_path):
    _write_parity(tmp_path, "packages/web/src/index.ts#observe")
    src = tmp_path / "packages/web/src/index.ts"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("export function observe(event) {}", encoding="utf-8")
    matrix, failures = build_matrix(tmp_path)
    assert failures == []
    cell = matrix["capabilities"][0]["cells"]["web"]
    assert cell["evidence_verified"] is True


# ── Evidence bundle sections — real repo state, no fabricated claims ───────


def test_bundle_check_inventory_includes_ledger_and_sdk_conformance():
    names = {name for name, _ in collect_evidence.EVIDENCE_CHECKS}
    assert "implementation_ledger" in names
    assert "sdk_conformance" in names
    assert "storage_policies" in names
    assert "cost_policy" in names
    assert "route_registry" in names


def test_ledger_section_reports_external_attestation_without_claims():
    section = collect_evidence.ledger_section()
    external = section["external_attestation"]
    assert external["ledger_id"] == "FT-EXT-ATTESTATION"
    # The bundle reports exactly what the ledger records — an external action —
    # and never claims a certification.
    assert external["status"] == "externally_blocked"
    assert external["certifications_claimed"] == []
    assert "No external certification" in external["note"]
    assert section["total_items"] == len(section["items"])
    assert sum(section["by_status"].values()) == section["total_items"]


def test_consent_section_is_registry_derived():
    section = collect_evidence.consent_section()
    registry = json.loads(
        (REPO_ROOT / "packages/shared/contracts/consent-registry.json").read_text(
            encoding="utf-8"
        )
    )
    assert section["purpose_count"] == len(registry["purposes"])
    assert len(section["purpose_ids"]) == section["purpose_count"]
    assert section["contract_version"] == registry["contractVersion"]


def test_route_registry_section_reports_default_deny_stats():
    section = collect_evidence.route_registry_section()
    assert section["default_decision"] == "deny"
    assert section["known_prefixes"] > 0
    assert "kyber" in section["sensitive_domains"]
    assert "kyber" in section["high_risk_domains"]


def test_ci_check_summary_is_never_fabricated_without_a_log():
    section = collect_evidence.ci_check_section(None)
    assert section["captured"] is False
    assert "gates_passed" not in section


def test_ci_check_summary_parses_a_real_gates_line(tmp_path):
    log = tmp_path / "ci.log"
    log.write_text(
        "REPO DOCTOR SUMMARY\n  Gates: 12 passed, 1 failed\n"
        "...\n  Gates: 34 passed, 0 failed\n",
        encoding="utf-8",
    )
    section = collect_evidence.ci_check_section(str(log))
    assert section["captured"] is True
    # The final summary line wins.
    assert section["gates_passed"] == 34
    assert section["gates_failed"] == 0


def test_ci_check_summary_reports_unparseable_log_honestly(tmp_path):
    log = tmp_path / "ci.log"
    log.write_text("no summary here", encoding="utf-8")
    section = collect_evidence.ci_check_section(str(log))
    assert section["captured"] is False
    assert "error" in section
