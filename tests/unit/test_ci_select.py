from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import ci_select

RULES, SUITES = ci_select.load()
PR = {i for i, s in SUITES.items() if s["lane"] == "pr"}


def sel(*paths: str) -> dict:
    return ci_select.select(list(paths), RULES, SUITES)


def test_docs_only_selects_only_docs_suite() -> None:
    r = sel("README.md", "docs/engineering/ci-v2/baseline.md")
    assert r["mode"] == "docs-only"
    assert list(r["suites"]) == ["docs"]


def test_frontend_component_selects_app_suites_and_critical_not_backend_matrix() -> None:
    r = sel("apps/kyber-web/src/components/Button.tsx")
    assert {"frontend-kyber", "frontend-kyber-component"} <= set(r["suites"])
    assert set(RULES["critical"]) <= set(r["suites"])
    assert "backend-value" not in r["suites"]
    assert r["mode"] == "targeted"


def test_auth_change_selects_identity_group() -> None:
    r = sel("services/api/identity/identity/service.py")
    assert {"backend-identity", "root-unit-security", "compliance"} <= set(r["suites"])


def test_sdk_change_selects_sdk_and_ingestion_contract() -> None:
    r = sel("packages/sdk/web/src/index.ts")
    assert {"sdk-web", "functionality-proof-ts", "backend-ingestion"} <= set(r["suites"])


@pytest.mark.parametrize("path", ["package-lock.json", "pyproject.toml", "Makefile",
                                  ".github/workflows/ci.yml", "scripts/anything.py",
                                  "packages/shared/src/x.ts", "config/ci/ownership.yaml"])
def test_fanout_paths_select_every_pr_suite(path: str) -> None:
    r = sel(path)
    assert r["mode"] == "broad-safe"
    assert PR <= set(r["suites"])


def test_unknown_executable_path_fails_closed_to_broad() -> None:
    r = sel("brand_new_dir/thing.py")
    assert r["mode"] == "broad-safe"
    assert PR <= set(r["suites"])
    assert any("unclassified" in x for x in r["reasons"])


def test_text_mixed_with_code_is_not_docs_only() -> None:
    r = sel("README.md", "apps/status/src/a.ts")
    assert r["mode"] == "targeted"
    assert "docs" in r["suites"] and "frontend-status" in r["suites"]


def test_conflicting_paths_union_suites() -> None:
    r = sel("apps/status/src/a.ts", "services/api/billing/x.py")
    assert {"frontend-status", "backend-value"} <= set(r["suites"])


def test_empty_diff_is_explicit_not_silent() -> None:
    assert sel()["mode"] == "empty"


def test_unknown_suite_in_rules_is_an_error() -> None:
    bad = {**RULES, "critical": ["does-not-exist"]}
    with pytest.raises(ValueError):
        ci_select.select(["apps/status/a.ts"], bad, SUITES)


def test_regression_lane_suites_never_selected_for_pr() -> None:
    assert not (set(sel("scripts/x.py")["suites"]) & {"root", "backend", "datalake-backend"})


def test_workers_group_by_profile_and_runtime() -> None:
    r = sel("apps/status/src/a.ts")
    ws = ci_select.workers(r, SUITES)
    assert all(w["suite_ids"] for w in ws)
    assert {sid for w in ws for sid in w["suite_ids"]} == set(r["suites"])


def _git(cwd: Path, *a: str) -> None:
    subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)


def test_rename_and_delete_contribute_old_and_new_paths(tmp_path: Path, monkeypatch) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "old.py").write_text("print('x')\n" * 20)
    (tmp_path / "gone.py").write_text("y=1\n")
    _git(tmp_path, "add", "-A"); _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "checkout", "-qb", "feat")
    _git(tmp_path, "mv", "old.py", "new.py"); _git(tmp_path, "rm", "-q", "gone.py")
    _git(tmp_path, "commit", "-qm", "change")
    monkeypatch.setattr(ci_select, "ROOT", tmp_path)
    assert ci_select.changed_paths("main", "feat") == ["gone.py", "new.py", "old.py"]


def test_workers_shard_long_groups_without_mixing_profiles() -> None:
    r = sel("scripts/x.py")  # broad-safe: every PR-lane suite
    ws = ci_select.workers(r, SUITES)
    ids = [sid for w in ws for sid in w["suite_ids"]]
    assert sorted(ids) == sorted(set(ids)) == sorted(r["suites"])  # no loss, no duplicates
    assert len({w["id"] for w in ws}) == len(ws)
    for w in ws:
        assert {(SUITES[s]["dependency_profile"], SUITES[s]["runtime_class"]) for s in w["suite_ids"]} == {
            (w["dependency_profile"], w["runtime_class"])
        }
    backend = [w for w in ws if w["dependency_profile"] == "python-backend"]
    assert len(backend) > 1, "17 backend suites must not run serially in one worker"
    for w in backend:
        total = sum(SUITES[s]["expected_runtime_seconds"] for s in w["suite_ids"])
        assert total <= ci_select.SHARD_TARGET_SECONDS + max(
            SUITES[s]["expected_runtime_seconds"] for s in w["suite_ids"]
        )


def test_kyber_change_selects_e2e_check_but_not_aether_typecheck() -> None:
    ids = [c["id"] for c in sel("apps/kyber-web/src/a.tsx")["checks"]]
    assert ids == ["kyber-web-e2e"]


def test_broad_safe_selects_every_check() -> None:
    ids = {c["id"] for c in sel("scripts/x.py")["checks"]}
    assert ids == {c["id"] for c in RULES["checks"]}


def test_docs_only_selects_no_checks() -> None:
    assert sel("README.md")["checks"] == []


def test_malformed_check_rule_is_an_error() -> None:
    bad = {**RULES, "checks": [{"id": "x", "include": ["a/**"]}]}  # no `run`
    with pytest.raises(ValueError):
        ci_select.select(["a/b.ts"], bad, SUITES)


def test_identity_change_selects_python_backed_identity_check() -> None:
    r = sel("services/api/identity/identity/routes.py")
    chk = {c["id"]: c for c in r["checks"]}
    assert "identity-continuity" in chk
    assert chk["identity-continuity"]["node"] is False
    assert chk["identity-continuity"]["python_extra"] == "dev,backend"
    assert "backend-identity" in r["suites"]  # the suite and the check both run


def test_provider_identity_evidence_tests_trigger_the_check() -> None:
    ids = [c["id"] for c in sel("services/api/tests/providers/test_identity_evidence.py")["checks"]]
    assert "identity-continuity" in ids


def test_node_checks_still_default_to_node() -> None:
    c = {c["id"]: c for c in sel("apps/kyber-web/src/a.tsx")["checks"]}["kyber-web-e2e"]
    assert c["node"] is True and c["python_extra"] is None


def test_no_check_command_mixes_pytest_conftest_trees() -> None:
    """services/api/tests and tests/ conftest files cannot share one pytest session."""
    for check in RULES["checks"]:
        for cmd in check["run"]:
            if "pytest" not in cmd:
                continue
            roots = {a.split("/")[0] + ("/" + a.split("/")[1] if a.startswith("services/") else "")
                     for a in cmd.split() if a.startswith(("tests/", "services/"))}
            assert len(roots) <= 1, f"{check['id']}: one pytest call spans {sorted(roots)}"


def test_proof_package_change_selects_pnpm_check() -> None:
    c = {c["id"]: c for c in sel("tests/e2e/proof/packages/reporting/src/markdown.ts")["checks"]}
    assert c["identity-proof-packages"]["pnpm"] is True
    assert c["identity-proof-packages"]["node"] is False
    assert sel("apps/kyber-web/src/a.tsx")["checks"][0]["pnpm"] is False
