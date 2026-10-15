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
