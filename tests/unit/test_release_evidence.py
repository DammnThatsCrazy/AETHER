"""Release evidence bundle + derived SDK conformance matrix tests.

The evidence bundle must be assembled from real repo state and must never
fabricate or imply external certifications; the SDK conformance matrix must be
derived from SDK sources/test manifests and fail closed on unverifiable claims.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "release"))

import collect_evidence  # noqa: E402
from release_manifest import canonical  # noqa: E402
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


# ── Deployment/cost checks reach the bundle ────────────────────────────────


def test_bundle_inventory_includes_the_deployment_and_cost_checks():
    """The four validators that gate release-gate but never reached the bundle.

    A bundle that omits the checks deciding whether the infrastructure is
    correctly shaped and affordable can report a clean sweep while those
    questions went unasked.
    """
    names = {name for name, _ in collect_evidence.EVIDENCE_CHECKS}
    assert "cost_policy_terraform" in names
    assert "delivery_topology" in names
    assert "terraform_plan_policy" in names
    assert "cost_model" in names


def test_every_evidence_check_is_a_name_script_pair():
    for entry in collect_evidence.EVIDENCE_CHECKS:
        name, script = entry
        assert isinstance(name, str) and script.endswith(".py")
    names = [n for n, _ in collect_evidence.EVIDENCE_CHECKS]
    assert len(names) == len(set(names)), "duplicate evidence check name"


def test_checks_needing_arguments_declare_them():
    """check_cost_model refuses to run without a profile and an inventory."""
    args = collect_evidence.EVIDENCE_CHECK_ARGS
    assert "--profile" in args["cost_model"]
    assert "--inventory" in args["cost_model"]
    assert set(args) <= {n for n, _ in collect_evidence.EVIDENCE_CHECKS}


def test_a_missing_validator_script_is_absent_never_a_pass():
    """The check that does not exist must count against the bundle."""
    result = collect_evidence._run("scripts/release/check_does_not_exist.py")
    assert result["exit_code"] != 0
    assert result["status"] == "absent"
    assert "not present" in result["error"]


# ── release-evidence/ bundle layout ────────────────────────────────────────


def test_bundle_layout_declares_every_evidence_subdirectory():
    assert set(collect_evidence.BUNDLE_SUBDIRS) == {
        "profile", "terraform", "cost", "migrations", "smoke", "security",
        "isolation", "load", "rollback", "lifecycle", "observability", "scorecard",
    }
    assert collect_evidence.BUNDLE_ROOT == "release-evidence"


def test_write_bundle_layout_emits_manifest_and_checksum(tmp_path):
    bundle = tmp_path / "release-evidence"
    written = collect_evidence.write_bundle_layout(bundle, {"commit": "abc1234"})
    assert (bundle / "manifest.json").is_file()
    assert (bundle / "manifest.sha256").is_file()
    for name in collect_evidence.BUNDLE_SUBDIRS:
        assert (bundle / name).is_dir()
    # The checksum is over release_manifest.canonical(), not an ad-hoc dump.
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    expected = hashlib.sha256(canonical(manifest)).hexdigest()
    assert (bundle / "manifest.sha256").read_text(encoding="utf-8").strip() == expected
    assert written["sha256"] == expected


def test_an_empty_subdirectory_is_absent_never_an_empty_pass(tmp_path):
    bundle = tmp_path / "release-evidence"
    collect_evidence.write_bundle_layout(bundle, {"commit": "abc1234"})
    layout = collect_evidence.scan_bundle_layout(bundle)
    assert layout["file_count"] == 0
    for name, row in layout["subdirectories"].items():
        assert row["present"] is False, name
        assert row["exists"] is True, name   # the directory exists, the evidence does not
        assert row["files"] == []


def test_bundle_layout_records_a_digest_for_every_file(tmp_path):
    bundle = tmp_path / "release-evidence"
    collect_evidence.write_bundle_layout(bundle, {"commit": "abc1234"})
    (bundle / "load" / "load-result.json").write_text('{"rps": 40}', encoding="utf-8")
    layout = collect_evidence.scan_bundle_layout(bundle)
    assert layout["file_count"] == 1
    load = layout["subdirectories"]["load"]
    assert load["present"] is True
    row = load["files"][0]
    assert row["path"] == "load/load-result.json"
    assert row["sha256"] == hashlib.sha256(
        (bundle / "load/load-result.json").read_bytes()).hexdigest()
    assert layout["subdirectories"]["smoke"]["present"] is False


def test_unmaterialized_bundle_section_reports_absence_not_emptiness(tmp_path):
    section = collect_evidence.evidence_bundle_section(tmp_path / "nope", None)
    assert section["materialized"] is False
    assert section["manifest"] is None
    assert section["file_count"] == 0
    assert set(section["subdirectories"]) == set(collect_evidence.BUNDLE_SUBDIRS)
    assert all(not row["present"] for row in section["subdirectories"].values())
    assert "not been materialized" in section["note"]


def test_materialized_bundle_section_lists_absent_subdirectories(tmp_path):
    bundle = tmp_path / "release-evidence"
    written = collect_evidence.write_bundle_layout(bundle, {"commit": "abc1234"})
    (bundle / "cost" / "cost-report.json").write_text("{}", encoding="utf-8")
    section = collect_evidence.evidence_bundle_section(bundle, written)
    assert section["materialized"] is True
    assert section["manifest"] == "manifest.json"
    assert "cost" not in section["absent_subdirectories"]
    assert "load" in section["absent_subdirectories"]
    assert len(section["absent_subdirectories"]) == len(collect_evidence.BUNDLE_SUBDIRS) - 1


# ── The bundle is verified, not transcribed ───────────────────────────────


def _sealed(tmp_path, files: dict[str, str]) -> Path:
    bundle = tmp_path / "release-evidence"
    collect_evidence.write_bundle_layout(bundle, {"commit": "abc1234"})
    for rel, body in files.items():
        (bundle / rel).write_text(body, encoding="utf-8")
    collect_evidence.write_bundle_layout(bundle, {"commit": "abc1234"})
    return bundle


def test_a_sealed_bundle_verifies_by_recomputation(tmp_path):
    bundle = _sealed(tmp_path, {"cost/cost-report.json": '{"passed": true}'})
    verdict = collect_evidence.verify_bundle(bundle)
    assert verdict["verified"] is True
    assert verdict["files_checked"] == 1
    assert verdict["computed_sha256"] == verdict["recorded_sha256"]


def test_swapping_an_evidence_file_fails_verification(tmp_path):
    """The defect: per-file digests were written once and never re-derived.

    manifest.sha256 sealed the manifest, the manifest recorded the digests, and
    every later read returned the RECORDED digest — so a swapped file left the
    manifest and its checksum in perfect agreement with each other and in
    complete disagreement with the bundle.
    """
    bundle = _sealed(tmp_path, {"cost/cost-report.json": '{"passed": false}'})
    (bundle / "cost/cost-report.json").write_text('{"passed": true}', encoding="utf-8")
    verdict = collect_evidence.verify_bundle(bundle)
    assert verdict["verified"] is False
    assert "does not match its recorded digest" in verdict["reason"]


def test_editing_the_manifest_fails_verification(tmp_path):
    bundle = _sealed(tmp_path, {"load/load-result.json": '{"rps": 40}'})
    manifest = bundle / "manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["file_count"] = 99
    manifest.write_text(json.dumps(data), encoding="utf-8")
    verdict = collect_evidence.verify_bundle(bundle)
    assert verdict["verified"] is False
    assert "manifest.sha256 records" in verdict["reason"]


def test_deleting_an_evidence_file_fails_verification(tmp_path):
    bundle = _sealed(tmp_path, {"smoke/smoke-result.json": "{}"})
    (bundle / "smoke/smoke-result.json").unlink()
    verdict = collect_evidence.verify_bundle(bundle)
    assert verdict["verified"] is False
    assert "absent from disk" in verdict["reason"]


def test_adding_an_unlisted_file_fails_verification(tmp_path):
    """A file nothing vouches for is still in the bundle a reviewer is handed."""
    bundle = _sealed(tmp_path, {"security/security-result.json": "{}"})
    (bundle / "security/added-later.json").write_text('{"findings": []}',
                                                      encoding="utf-8")
    verdict = collect_evidence.verify_bundle(bundle)
    assert verdict["verified"] is False
    assert "not listed in the manifest" in verdict["reason"]


def test_an_absent_bundle_is_not_verified(tmp_path):
    verdict = collect_evidence.verify_bundle(tmp_path / "nowhere")
    assert verdict["verified"] is False
    assert "not materialized" in verdict["reason"]


def test_the_bundle_section_separates_the_claim_from_the_verification(tmp_path):
    bundle = _sealed(tmp_path, {"cost/cost-report.json": "{}"})
    section = collect_evidence.evidence_bundle_section(bundle, None)
    assert section["verification"]["verified"] is True
    assert section["sha256"] == section["recorded_sha256"]

    (bundle / "cost/cost-report.json").write_text('{"tampered": true}',
                                                  encoding="utf-8")
    tampered = collect_evidence.evidence_bundle_section(bundle, None)
    # The recorded digest is unchanged and still agrees with itself; only
    # recomputation tells the truth.
    assert tampered["sha256"] == section["sha256"]
    assert tampered["verification"]["verified"] is False


# ── A cost PASS may not be laundered out of a fixture ──────────────────────


def _inventory(path: Path, **extra) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"schema_version": 1, "profile": "production-lean", "resources": []}
    body.update(extra)
    path.write_text(json.dumps(body), encoding="utf-8")


def test_a_fixture_derived_inventory_is_refused_as_cost_input(tmp_path, monkeypatch):
    monkeypatch.setattr(collect_evidence, "repo_root", lambda: tmp_path)
    _inventory(tmp_path / collect_evidence.COST_INVENTORY,
               generated_from="tests/fixtures/terraform_plans/production-lean-valid.json",
               synthetic_input="tests/fixtures")
    reason = collect_evidence.synthetic_inventory_reason()
    assert reason and "test fixture" in reason
    assert "not reported as a pass" in reason


def test_a_missing_inventory_is_refused_as_cost_input(tmp_path, monkeypatch):
    monkeypatch.setattr(collect_evidence, "repo_root", lambda: tmp_path)
    reason = collect_evidence.synthetic_inventory_reason()
    assert reason and "absent" in reason


def test_an_inventory_from_a_real_plan_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(collect_evidence, "repo_root", lambda: tmp_path)
    _inventory(tmp_path / collect_evidence.COST_INVENTORY,
               generated_from="artifacts/reviewed.tfplan.json",
               synthetic_input=None)
    assert collect_evidence.synthetic_inventory_reason() is None


def test_the_bundle_records_a_guarded_check_as_unverifiable_never_as_a_pass(
        tmp_path, monkeypatch):
    """The laundering path: cost_model exit 0 PASS beside plan_policy exit 2 FAIL.

    Both checks describe the same deployment. One was pointed at a path a
    fixture never occupies and honestly failed; the other was pointed at the
    path `make validate-cost-model` writes the fixture-derived inventory to and
    reported a pass. The bundle then carried both lines side by side.
    """
    monkeypatch.setattr(collect_evidence, "repo_root", lambda: tmp_path)
    _inventory(tmp_path / collect_evidence.COST_INVENTORY,
               generated_from="tests/fixtures/terraform_plans/production-lean-valid.json",
               synthetic_input="fixture")
    ran: list[str] = []
    monkeypatch.setattr(collect_evidence, "_run",
                        lambda script, args=None: ran.append(script) or
                        {"script": script, "exit_code": 0})

    results = collect_evidence.run_evidence_checks()
    cost = results["cost_model"]
    assert cost["exit_code"] != 0
    assert cost["status"] == "unverifiable_input"
    assert "scripts/release/check_cost_model.py" not in ran, (
        "the cost gate must not be run at all against a fixture-derived inventory")
    # An unguarded check is untouched by this.
    assert results["cost_policy"]["exit_code"] == 0


def test_bundle_manifest_round_trips_through_the_shared_canonicaliser(tmp_path):
    """Two writes of identical content must produce an identical digest."""
    first = collect_evidence.write_bundle_layout(
        tmp_path / "a", {"commit": "abc1234"})["manifest"]
    second = collect_evidence.write_bundle_layout(
        tmp_path / "b", {"commit": "abc1234"})["manifest"]
    first.pop("generated_at"), second.pop("generated_at")
    first["root"] = second["root"]
    assert hashlib.sha256(canonical(first)).hexdigest() == \
        hashlib.sha256(canonical(second)).hexdigest()
