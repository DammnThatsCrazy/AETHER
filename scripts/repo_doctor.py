#!/usr/bin/env python3
"""Aether Platform — Repo Doctor.

Single orchestrator for repo consistency gates used by humans, agents, and CI.

Supported CLI contract::

    python scripts/repo_doctor.py --check
    python scripts/repo_doctor.py --fix
    python scripts/repo_doctor.py --ci
    python scripts/repo_doctor.py --check --docs-only
    python scripts/repo_doctor.py --fix --docs-only

``--check``, ``--fix``, and ``--ci`` are mutually exclusive execution modes.
``--docs-only`` is an independent scope flag.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parent.parent
GENERATED_DOC_PATHS = ["docs/_generated", "docs/REPO-INDEX.md", "docs/AUTOMATION.md"]


@dataclass
class CheckResult:
    name: str
    passed: bool
    command: str = ""
    skipped: bool = False
    detail: str = ""
    remediation: str = ""


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aether repo consistency suite")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Validate; no mutations")
    mode.add_argument("--fix", action="store_true", help="Regenerate derived docs, then validate")
    mode.add_argument("--ci", action="store_true", help="CI-safe full path; fails on generated diffs")
    parser.add_argument(
        "--docs-only",
        action="store_true",
        help="Limit scope to docs/version/frontmatter/drift/generated-doc checks",
    )
    parser.add_argument("--continue-on-error", action="store_true", help="Collect all failures")
    return parser.parse_args(argv)


def _command_text(cmd: Sequence[str]) -> str:
    return " ".join(str(c) for c in cmd)


def run(
    cmd: list[str],
    *,
    name: str,
    results: list[CheckResult],
    stop_on_failure: bool,
    remediation: str = "",
    cwd: Path = ROOT,
) -> bool:
    command = _command_text(cmd)
    print(f"\n{'=' * 70}")
    print(f"CHECK: {name}")
    print(f"  CMD: {command}")
    print("=" * 70)
    proc = subprocess.run(cmd, cwd=cwd)
    passed = proc.returncode == 0
    results.append(
        CheckResult(
            name=name,
            passed=passed,
            command=command,
            remediation=remediation,
        )
    )
    if passed:
        print(f"\n[PASS] {name}")
        return True

    print(f"\n[FAIL] {name}")
    if remediation:
        print(f"Required fix: {remediation}")
    if stop_on_failure:
        _print_summary(results)
        sys.exit(1)
    return False


def skip(name: str, reason: str, results: list[CheckResult]) -> None:
    print(f"\n[SKIP] {name}: {reason}")
    results.append(CheckResult(name=name, passed=True, skipped=True, detail=reason))


def _print_generated_diff(paths: Sequence[str]) -> None:
    print("\nGenerated/synced diff summary:")
    subprocess.run(["git", "diff", "--stat", "--", *paths], cwd=ROOT)
    print("\nChanged generated/synced files:")
    subprocess.run(["git", "diff", "--name-only", "--", *paths], cwd=ROOT)
    print("\nInspect with:")
    print(f"  git diff -- {' '.join(paths)}")
    print("Remediate with:")
    print("  make repo-doctor-fix")
    print("  git add docs/_generated docs/REPO-INDEX.md docs/AUTOMATION.md")


def _check_clean(
    paths: list[str],
    *,
    name: str,
    results: list[CheckResult],
    stop_on_failure: bool,
) -> bool:
    command = f"git diff --exit-code -- {' '.join(paths)}"
    print(f"\n{'=' * 70}")
    print(f"CHECK: {name}")
    print(f"  CMD: {command}")
    print("=" * 70)
    proc = subprocess.run(["git", "diff", "--exit-code", "--", *paths], cwd=ROOT)
    passed = proc.returncode == 0
    remediation = "make repo-doctor-fix && commit regenerated/synced docs"
    if passed:
        print(f"\n[PASS] {name}")
    else:
        print(f"\n[FAIL] {name} — uncommitted diff detected")
        _print_generated_diff(paths)
    results.append(CheckResult(name=name, passed=passed, command=command, remediation=remediation))
    if not passed and stop_on_failure:
        _print_summary(results)
        sys.exit(1)
    return passed


def _report_stale_docs() -> bool:
    """Print stale docs details without stamping authored docs."""
    print(textwrap.dedent("""
        ┌─────────────────────────────────────────────────────────────────┐
        │  SOURCE-LINKED DOCS DRIFT REPORT                                │
        │                                                                 │
        │  repo_doctor --fix does NOT stamp authored docs automatically.  │
        │  If this report shows stale docs, review each listed doc against│
        │  its source_files, update content, then stamp intentionally with │
        │  python scripts/docs_drift.py --update.                         │
        └─────────────────────────────────────────────────────────────────┘
    """))
    proc = subprocess.run(["python", "scripts/docs_drift.py", "--strict"], cwd=ROOT)
    return proc.returncode == 0


def _load_package_scripts() -> dict[str, str]:
    pkg_path = ROOT / "package.json"
    if not pkg_path.exists():
        return {}
    return json.loads(pkg_path.read_text(encoding="utf-8")).get("scripts", {})


def _print_summary(results: list[CheckResult]) -> None:
    print("\n" + "=" * 70)
    print("REPO DOCTOR SUMMARY")
    print("=" * 70)
    width = max((len(r.name) for r in results), default=40) + 2
    for r in results:
        if r.skipped:
            status = "SKIP"
            suffix = f" ({r.detail})"
        elif r.passed:
            status = "PASS"
            suffix = ""
        else:
            status = "FAIL"
            suffix = ""
        print(f"  [{status}] {r.name:<{width}}{suffix}")
        if not r.passed and not r.skipped:
            if r.command:
                print(f"         Failed command: {r.command}")
            if r.remediation:
                print(f"         Required fix: {r.remediation}")
    failed = [r for r in results if not r.passed and not r.skipped]
    print("-" * 70)
    print(f"  Gates: {len(results) - len(failed)} passed, {len(failed)} failed")
    if failed:
        print("\nLikely root causes and next commands:")
        for r in failed:
            print(f"  - {r.name}: {r.remediation or 'run the failed command locally and fix the reported mismatch'}")
        print("\nFiles likely needing commit after generated-doc failures:")
        subprocess.run(["git", "diff", "--name-only", "--", *GENERATED_DOC_PATHS], cwd=ROOT)
    print("=" * 70)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    stop = not args.continue_on_error
    results: list[CheckResult] = []

    run(
        ["python", "scripts/bump_version.py", "--check"],
        name="Version alignment (pyproject.toml is canonical)",
        results=results,
        stop_on_failure=stop,
        remediation="python scripts/bump_version.py <canonical-version>",
    )

    run(
        ["python", "scripts/docs_extract/run_all.py"],
        name="Regenerate docs/_generated artifacts",
        results=results,
        stop_on_failure=stop,
        remediation="fix the generator failure, then rerun make repo-doctor-fix",
    )

    run(
        ["python", "scripts/generate_ml_manifest.py"],
        name="Regenerate ML implementation manifest (docs/_generated/ml-implementation-manifest.json)",
        results=results,
        stop_on_failure=stop,
        remediation="fix common/model_registry.py or common/feature_contracts.py, then rerun make repo-doctor-fix",
    )

    if args.ci or args.check:
        _check_clean(
            ["docs/_generated"],
            name="Generated artifacts — no uncommitted diff",
            results=results,
            stop_on_failure=stop,
        )

    run(
        ["python", "scripts/sync_docs.py"],
        name="Sync generated docs (REPO-INDEX, AUTOMATION)",
        results=results,
        stop_on_failure=stop,
        remediation="fix scripts/sync_docs.py or stale inputs, then rerun make docs-fix",
    )

    if args.ci or args.check:
        _check_clean(
            ["docs/REPO-INDEX.md", "docs/AUTOMATION.md"],
            name="Synced docs (REPO-INDEX, AUTOMATION) — no uncommitted diff",
            results=results,
            stop_on_failure=stop,
        )

    docs_gates = [
        (["python", "scripts/validate_docs.py"], "Docs version drift validation", "python scripts/bump_version.py <canonical-version>"),
        (["python", "scripts/validate_frontmatter.py"], "Docs frontmatter validity", "fix the reported frontmatter errors"),
    ]
    for cmd, name, remediation in docs_gates:
        run(cmd, name=name, results=results, stop_on_failure=stop, remediation=remediation)

    if args.fix:
        clean = _report_stale_docs()
        results.append(
            CheckResult(
                name="Source-linked docs drift (strict review report)",
                passed=clean,
                command="python scripts/docs_drift.py --strict",
                remediation="review stale docs, update content, then run python scripts/docs_drift.py --update",
            )
        )
        if not clean and stop:
            _print_summary(results)
            sys.exit(1)
    else:
        run(
            ["python", "scripts/docs_drift.py", "--strict"],
            name="Source-linked docs drift (strict)",
            results=results,
            stop_on_failure=stop,
            remediation="review listed docs against source_files, update content, then run python scripts/docs_drift.py --update",
        )

    run(
        ["python", "scripts/validate_contracts.py"],
        name="Contract / event / consent alignment",
        results=results,
        stop_on_failure=stop,
        remediation="update contracts, event schemas, consent docs, and SDK surfaces together",
    )
    run(
        ["python", "scripts/validate_sdk_release_alignment.py"],
        name="SDK release alignment",
        results=results,
        stop_on_failure=stop,
        remediation="align SDK versions/endpoints/public exports/docs, then rerun validation",
    )
    run(
        ["python", "scripts/validate_consistency_ownership.py"],
        name="Source-of-truth ownership map enforcement",
        results=results,
        stop_on_failure=stop,
        remediation="update the derived surfaces required by docs/source-of-truth/repo_consistency_ownership.json",
    )
    run(
        ["python", "scripts/validate_ts_public_exports.py"],
        name="TypeScript public export/package boundary validation",
        results=results,
        stop_on_failure=stop,
        remediation="export public declaration types from package barrels and fix package.json exports",
    )

    if not args.docs_only:
        if (ROOT / "package-lock.json").exists():
            run(["npm", "ci", "--ignore-scripts"], name="npm ci (lockfile integrity)", results=results, stop_on_failure=stop, remediation="update package-lock.json with npm install")
        else:
            skip("npm ci", "no package-lock.json at root", results)

        # Build packages/shared before typecheck — its dist/ is gitignored and required
        # by Kyber/Aether TypeScript imports of @aether/shared. Mirrors what the
        # dedicated typescript CI job does (npm run build --workspace=packages/shared).
        shared_pkg = ROOT / "packages" / "shared"
        if shared_pkg.exists():
            run(
                ["npm", "run", "build", "--workspace=packages/shared"],
                name="npm build @aether/shared (pre-typecheck)",
                results=results,
                stop_on_failure=stop,
                remediation="fix TypeScript compilation errors in packages/shared",
            )

        scripts = _load_package_scripts()
        for script_name, label, remediation in [
            ("typecheck", "npm typecheck", "fix TypeScript errors and package export drift"),
            ("build", "npm build", "fix build output or declaration generation"),
            ("test", "npm test", "fix failing workspace tests"),
        ]:
            if script_name in scripts:
                run(["npm", "run", script_name], name=label, results=results, stop_on_failure=stop, remediation=remediation)
            else:
                skip(label, f"no {script_name} script in root package.json", results)

        run(
            ["python", "-m", "pytest", "tests/", "-v", "--tb=short"],
            name="Python tests (core)",
            results=results,
            stop_on_failure=stop,
            remediation="install dev dependencies with pip install -e '.[dev,security,backend,agent,ml]' and fix failing tests",
        )
        ml_tests_dir = Path("ML Models/aether-ml/tests")
        if ml_tests_dir.exists():
            missing_ml_deps: list[str] = []
            for module_name in ["joblib", "sklearn"]:
                probe = subprocess.run(["python", "-c", f"import {module_name}"], cwd=ROOT)
                if probe.returncode != 0:
                    missing_ml_deps.append(module_name)
            if missing_ml_deps:
                skip(
                    "Python tests (ML)",
                    "missing optional ML test dependencies "
                    + ", ".join(missing_ml_deps)
                    + "; install with pip install -e '.[ml,dev]'",
                    results,
                )
            else:
                run(
                    ["python", "-m", "pytest", str(ml_tests_dir), "-v", "--tb=short"],
                    name="Python tests (ML)",
                    results=results,
                    stop_on_failure=stop,
                    remediation="install ML dependencies with pip install -e '.[ml,dev]' and fix failing tests",
                )
        else:
            skip("Python tests (ML)", f"{ml_tests_dir} not found", results)

        # ML registry consistency — CI gate
        ml_registry_script = ROOT / "scripts" / "validate_ml_registry.py"
        if ml_registry_script.exists():
            run(
                ["python", str(ml_registry_script)],
                name="ML registry consistency",
                results=results,
                stop_on_failure=stop,
                remediation="fix common/model_registry.py, common/feature_contracts.py, or training/configs/model_configs.py",
            )

    _print_summary(results)
    failed = [r for r in results if not r.passed and not r.skipped]
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
