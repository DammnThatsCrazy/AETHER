#!/usr/bin/env python3
"""
Aether Platform — Repo Doctor

Single orchestrator for the complete repo consistency suite.

Usage:
    python scripts/repo_doctor.py --check          # validate, no mutations
    python scripts/repo_doctor.py --fix            # regenerate generated docs + sync
    python scripts/repo_doctor.py --docs-only      # docs/version/frontmatter/drift checks only
    python scripts/repo_doctor.py --ci             # CI-safe full path; fails on any generated diff

Options:
    --continue-on-error    Do not stop on first failure (collect all failures)

Exit codes:
    0   all checks passed
    1   one or more checks failed
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Check result
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    name: str
    passed: bool
    skipped: bool = False
    detail: str = ""


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run(
    cmd: list[str],
    *,
    name: str,
    results: list[CheckResult],
    stop_on_failure: bool,
    cwd: Path = ROOT,
) -> bool:
    """Run a command, record result, print output. Returns True on success."""
    print(f"\n{'='*70}")
    print(f"CHECK: {name}")
    print(f"  CMD: {' '.join(str(c) for c in cmd)}")
    print("=" * 70)
    proc = subprocess.run(cmd, cwd=cwd)
    passed = proc.returncode == 0
    results.append(CheckResult(name=name, passed=passed))
    if not passed:
        print(f"\n[FAIL] {name}")
        if stop_on_failure:
            _print_summary(results)
            sys.exit(1)
    else:
        print(f"\n[PASS] {name}")
    return passed


def skip(name: str, reason: str, results: list[CheckResult]) -> None:
    print(f"\n[SKIP] {name}: {reason}")
    results.append(CheckResult(name=name, passed=True, skipped=True, detail=reason))


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _print_summary(results: list[CheckResult]) -> None:
    print("\n" + "=" * 70)
    print("REPO DOCTOR — SUMMARY")
    print("=" * 70)
    width = max((len(r.name) for r in results), default=40) + 2
    for r in results:
        if r.skipped:
            status = "SKIP"
            suffix = f"  ({r.detail})"
        elif r.passed:
            status = "PASS"
            suffix = ""
        else:
            status = "FAIL"
            suffix = ""
        print(f"  [{status}]  {r.name:<{width}}{suffix}")
    failed = [r for r in results if not r.passed and not r.skipped]
    print("-" * 70)
    print(f"  {len(results) - len(failed)} passed, {len(failed)} failed")
    print("=" * 70)


# ---------------------------------------------------------------------------
# Git diff check
# ---------------------------------------------------------------------------

def _check_clean(
    paths: list[str],
    *,
    name: str,
    results: list[CheckResult],
    stop_on_failure: bool,
) -> bool:
    print(f"\n{'='*70}")
    print(f"CHECK: {name}")
    print(f"  CMD: git diff --exit-code -- {' '.join(paths)}")
    print("=" * 70)
    proc = subprocess.run(
        ["git", "diff", "--exit-code", "--", *paths],
        cwd=ROOT,
    )
    passed = proc.returncode == 0
    if not passed:
        print(f"\n[FAIL] {name} — uncommitted diff detected")
        subprocess.run(["git", "diff", "--stat", "--", *paths], cwd=ROOT)
    else:
        print(f"\n[PASS] {name}")
    results.append(CheckResult(name=name, passed=passed))
    if not passed and stop_on_failure:
        _print_summary(results)
        sys.exit(1)
    return passed


# ---------------------------------------------------------------------------
# Stale source-linked docs report (--fix mode)
# ---------------------------------------------------------------------------

def _report_stale_docs() -> None:
    """Print a structured report of stale source-linked docs without stamping."""
    print(textwrap.dedent("""
        ┌─────────────────────────────────────────────────────────────────┐
        │  SOURCE-LINKED DOCS DRIFT REPORT                                │
        │                                                                 │
        │  The following docs reference source files that changed after   │
        │  their last_synced_commit stamp.                                │
        │                                                                 │
        │  Required action:                                               │
        │    1. Review each stale doc against its linked source files.    │
        │    2. Update the authored doc content as needed.                │
        │    3. Run: python scripts/docs_drift.py --update                │
        │       ONLY after the review is complete.                        │
        └─────────────────────────────────────────────────────────────────┘
    """))
    subprocess.run(["python", "scripts/docs_drift.py", "--strict"], cwd=ROOT)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Aether repo consistency suite")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Validate; no mutations")
    mode.add_argument("--fix", action="store_true", help="Regenerate generated docs + sync")
    mode.add_argument("--docs-only", action="store_true", help="Docs/version/frontmatter/drift only")
    mode.add_argument("--ci", action="store_true", help="CI-safe full path")
    parser.add_argument("--continue-on-error", action="store_true", help="Collect all failures")
    args = parser.parse_args()

    stop = not args.continue_on_error
    results: list[CheckResult] = []

    # ------------------------------------------------------------------
    # 1. Version alignment
    # ------------------------------------------------------------------
    run(
        ["python", "scripts/bump_version.py", "--check"],
        name="Version alignment (pyproject.toml is canonical)",
        results=results,
        stop_on_failure=stop,
    )

    # ------------------------------------------------------------------
    # 2. Regenerate generated docs
    # ------------------------------------------------------------------
    if args.fix or args.ci or args.check or args.docs_only:
        run(
            ["python", "scripts/docs_extract/run_all.py"],
            name="Regenerate docs/_generated artifacts",
            results=results,
            stop_on_failure=stop,
        )

    # ------------------------------------------------------------------
    # 3. Check generated diff (after regeneration)
    # ------------------------------------------------------------------
    if args.ci or args.check or args.docs_only:
        _check_clean(
            ["docs/_generated/"],
            name="Generated artifacts — no uncommitted diff",
            results=results,
            stop_on_failure=stop,
        )

    # ------------------------------------------------------------------
    # 4. Sync generated docs (REPO-INDEX.md, AUTOMATION.md)
    # ------------------------------------------------------------------
    if args.fix or args.ci or args.check or args.docs_only:
        run(
            ["python", "scripts/sync_docs.py"],
            name="Sync generated docs (REPO-INDEX, AUTOMATION)",
            results=results,
            stop_on_failure=stop,
        )

    # ------------------------------------------------------------------
    # 5. Check sync diff
    # ------------------------------------------------------------------
    if args.ci or args.check or args.docs_only:
        _check_clean(
            ["docs/REPO-INDEX.md", "docs/AUTOMATION.md"],
            name="Synced docs (REPO-INDEX, AUTOMATION) — no uncommitted diff",
            results=results,
            stop_on_failure=stop,
        )

    # ------------------------------------------------------------------
    # 6. Validate docs metadata / version drift
    # ------------------------------------------------------------------
    run(
        ["python", "scripts/validate_docs.py"],
        name="Docs version drift validation",
        results=results,
        stop_on_failure=stop,
    )

    # ------------------------------------------------------------------
    # 7. Validate authored docs frontmatter
    # ------------------------------------------------------------------
    run(
        ["python", "scripts/validate_frontmatter.py"],
        name="Docs frontmatter validity",
        results=results,
        stop_on_failure=stop,
    )

    # ------------------------------------------------------------------
    # 8. Source-linked docs drift
    # ------------------------------------------------------------------
    if args.fix:
        _report_stale_docs()
        results.append(CheckResult(
            name="Source-linked docs drift (review report printed)",
            passed=True,
        ))
    else:
        run(
            ["python", "scripts/docs_drift.py", "--strict"],
            name="Source-linked docs drift (strict)",
            results=results,
            stop_on_failure=stop,
        )

    # ------------------------------------------------------------------
    # 9. Contract / event / consent alignment
    # ------------------------------------------------------------------
    run(
        ["python", "scripts/validate_contracts.py"],
        name="Contract / event / consent alignment",
        results=results,
        stop_on_failure=stop,
    )

    # ------------------------------------------------------------------
    # 10. SDK release alignment
    # ------------------------------------------------------------------
    run(
        ["python", "scripts/validate_sdk_release_alignment.py"],
        name="SDK release alignment",
        results=results,
        stop_on_failure=stop,
    )

    # ------------------------------------------------------------------
    # 11-13. Node / JS checks (skip for docs-only)
    # ------------------------------------------------------------------
    if not args.docs_only:
        if (ROOT / "package-lock.json").exists():
            run(
                ["npm", "ci", "--ignore-scripts"],
                name="npm ci (lockfile integrity)",
                results=results,
                stop_on_failure=stop,
            )
        else:
            skip("npm ci", "no package-lock.json at root", results)

        pkg = {}
        pkg_path = ROOT / "package.json"
        if pkg_path.exists():
            import json
            pkg = json.loads(pkg_path.read_text())

        scripts = pkg.get("scripts", {})

        if "build" in scripts:
            run(["npm", "run", "build"], name="npm build", results=results, stop_on_failure=stop)
        else:
            skip("npm build", "no build script in root package.json", results)

        if "test" in scripts:
            run(["npm", "run", "test"], name="npm test", results=results, stop_on_failure=stop)
        else:
            skip("npm test", "no test script in root package.json", results)

        if "typecheck" in scripts:
            run(["npm", "run", "typecheck"], name="npm typecheck", results=results, stop_on_failure=stop)
        else:
            skip("npm typecheck", "no typecheck script in root package.json", results)

        # ------------------------------------------------------------------
        # 14. Python tests — run separately to avoid conftest module
        #     name collision between tests/ and ML Models/.../tests/
        # ------------------------------------------------------------------
        run(
            ["python", "-m", "pytest", "tests/", "-v", "--tb=short"],
            name="Python tests (core)",
            results=results,
            stop_on_failure=stop,
        )
        ml_tests_dir = Path("ML Models/aether-ml/tests")
        if ml_tests_dir.exists():
            run(
                ["python", "-m", "pytest", str(ml_tests_dir), "-v", "--tb=short"],
                name="Python tests (ML)",
                results=results,
                stop_on_failure=stop,
            )
        else:
            skip("Python tests (ML)", f"{ml_tests_dir} not found", results)

    # ------------------------------------------------------------------
    # Final summary
    # ------------------------------------------------------------------
    _print_summary(results)
    failed = [r for r in results if not r.passed and not r.skipped]
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
