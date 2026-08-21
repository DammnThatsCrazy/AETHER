"""Command-contract tests: the repo-consistency spine cannot be silently bypassed.

These assert that public npm scripts delegate to the canonical Makefile targets,
that the agent-facing contract docs point at `make ci-check`, and that the
trusted-main docs-sync workflow keeps its read-only/write split. Deterministic,
no external services.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

try:  # PyYAML is a repo dev dependency; skip cleanly if unavailable.
    import yaml
except Exception:  # pragma: no cover
    yaml = None

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text()


# --------------------------------------------------------------------------- #
# package.json delegates public validation scripts to the Makefile
# --------------------------------------------------------------------------- #
def test_package_json_exists() -> None:
    assert (ROOT / "package.json").exists()


@pytest.mark.parametrize(
    "script, target",
    [
        ("test:docs", "make docs-check"),
        ("test:all", "make ci-check"),
        ("repo:doctor", "make repo-doctor"),
        ("repo:fix", "make repo-doctor-fix"),
        ("docs:fix", "make docs-fix"),
        ("validate:frontend-data-truth", "make frontend-data-truth"),
        ("validate:frontend-data-truth:bundles", "make frontend-data-truth-bundles"),
        ("validate:frontend-branding", "make frontend-branding"),
    ],
)
def test_npm_scripts_delegate_to_make(script: str, target: str) -> None:
    scripts = json.loads(_read("package.json"))["scripts"]
    assert script in scripts, f"missing npm script: {script}"
    assert scripts[script] == target, (
        f"{script} must delegate to '{target}', got '{scripts[script]}'"
    )


def test_test_docs_does_not_bypass_repo_doctor() -> None:
    scripts = json.loads(_read("package.json"))["scripts"]
    # Must not chain raw validators (the old bypass path).
    assert "validate_frontmatter.py" not in scripts["test:docs"]
    assert "docs_drift.py" not in scripts["test:docs"]


# --------------------------------------------------------------------------- #
# Makefile owns the canonical targets
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "target",
    [
        "repo-doctor",
        "repo-doctor-fix",
        "docs-check",
        "docs-fix",
        "ci-check",
        "release-gate",
        "frontend-data-truth",
        "frontend-data-truth-bundles",
        "frontend-branding",
    ],
)
def test_makefile_defines_canonical_targets(target: str) -> None:
    makefile = _read("Makefile")
    assert re.search(rf"(?m)^{re.escape(target)}:", makefile), (
        f"Makefile missing target: {target}"
    )


def test_ci_check_routes_through_repo_doctor() -> None:
    makefile = _read("Makefile")
    m = re.search(r"(?m)^ci-check:.*\n\t(.+)$", makefile)
    assert m and "repo_doctor.py --ci" in m.group(1)


def test_repo_doctor_enforces_frontend_data_truth_source_and_bundles() -> None:
    doctor = _read("scripts/repo_doctor.py")
    assert '[sys.executable, "scripts/validate_frontend_data_truth.py"]' in doctor
    assert (
        '[sys.executable, "scripts/validate_frontend_data_truth.py", "--build-bundles"]'
        in doctor
    )
    assert '[sys.executable, "scripts/validate_frontend_branding.py"]' in doctor


def test_repo_consistency_workflow_names_frontend_data_truth_guardrail() -> None:
    workflow = _read(".github/workflows/repo-consistency.yml")
    assert "npm run validate:frontend-data-truth" in workflow
    assert "npm run validate:frontend-branding" in workflow


# --------------------------------------------------------------------------- #
# Agent-facing contract docs
# --------------------------------------------------------------------------- #
def test_agents_md_is_full_operating_contract() -> None:
    agents = _read("AGENTS.md")
    assert "make ci-check" in agents
    assert "make docs-fix" in agents
    assert "python scripts/docs_drift.py --update" in agents


def test_claude_md_canonical_gate_is_ci_check() -> None:
    claude = _read("CLAUDE.md")
    assert "make ci-check" in claude
    assert "canonical completion gate" in claude.lower()
    # Must reference AGENTS.md as the operating contract.
    assert "AGENTS.md" in claude


def test_pr_template_mentions_canonical_workflow() -> None:
    template = _read(".github/pull_request_template.md")
    assert "make docs-fix" in template
    assert "make ci-check" in template
    assert "python scripts/docs_drift.py --update" in template


# --------------------------------------------------------------------------- #
# No stale hardcoded consent-purpose counts in authoritative docs
# --------------------------------------------------------------------------- #
def test_readme_has_no_stale_consent_purpose_count() -> None:
    readme = _read("README.md")
    assert not re.search(
        r"\b(five|eight|nine|\d+)\s+(canonical\s+)?consent\s+purposes\b", readme, re.I
    )
    assert not re.search(r"\b\d+\s+canonical\s+consent\s+purposes\b", readme, re.I)


def test_consent_registry_docs_validator_passes() -> None:
    from scripts import validate_consent_registry_docs as v

    assert v.main() == 0


# --------------------------------------------------------------------------- #
# sync_docs.py generator narrative describes the canonical workflow
# --------------------------------------------------------------------------- #
def test_sync_docs_generator_mentions_canonical_workflow() -> None:
    src = _read("scripts/sync_docs.py")
    assert "make ci-check" in src
    assert "repo_doctor.py" in src
    # The stale narrative must be gone.
    assert "cicd/aether-cicd/.github/workflows/" not in src


# --------------------------------------------------------------------------- #
# repo-health docs-sync stays trusted-main-only; PR jobs never gain write perms
# --------------------------------------------------------------------------- #
def test_repo_health_docs_sync_is_trusted_main_only() -> None:
    if yaml is None:
        pytest.skip("PyYAML not available")
    wf = yaml.safe_load(_read(".github/workflows/repo-health.yml"))
    jobs = wf["jobs"]

    docs_sync = jobs["docs-sync"]
    cond = docs_sync["if"]
    assert "github.event_name == 'push'" in cond
    assert "refs/heads/main" in cond
    # always() so a read-only lint failure does not skip the trusted auto-sync.
    assert "always()" in cond
    assert docs_sync["permissions"]["contents"] == "write"

    # The read-only PR-facing lint-docs job must NOT have write permissions.
    lint = jobs["lint-docs"]
    perms = lint.get("permissions", wf.get("permissions", {}))
    assert perms.get("contents", "read") == "read"


def test_top_level_workflow_permissions_are_read_only() -> None:
    if yaml is None:
        pytest.skip("PyYAML not available")
    wf = yaml.safe_load(_read(".github/workflows/repo-health.yml"))
    assert wf["permissions"]["contents"] == "read"
