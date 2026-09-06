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
import tempfile
import textwrap
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parent.parent
GENERATED_DOC_PATHS = ["docs/_generated", "docs/REPO-INDEX.md", "docs/AUTOMATION.md"]


@contextmanager
def readonly_generation_workspace(enabled: bool):
    """Yield an isolated mirror for generators in validation modes.

    Generators historically wrote into the caller's checkout and relied on a
    later ``git diff`` to detect drift.  That made ``--check`` surprisingly
    mutating.  A temporary local clone plus the caller's complete worktree
    patch gives generators the exact inputs being reviewed without allowing
    them to touch the source checkout.
    """
    if not enabled:
        yield ROOT
        return
    with tempfile.TemporaryDirectory(prefix="aether-doctor-") as directory:
        mirror = Path(directory) / "repo"
        subprocess.run(
            ["git", "clone", "--quiet", "--shared", "--no-checkout", str(ROOT), str(mirror)],
            check=True,
        )
        subprocess.run(["git", "checkout", "--quiet", "HEAD", "--"], cwd=mirror, check=True)
        patch = subprocess.run(
            ["git", "diff", "--binary", "HEAD", "--"], cwd=ROOT,
            check=True, capture_output=True,
        ).stdout
        if patch:
            subprocess.run(["git", "apply", "--binary", "-"], cwd=mirror, input=patch, check=True)
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=ROOT,
            check=True, capture_output=True,
        ).stdout.split(b"\0")
        for raw_path in filter(None, untracked):
            relative = Path(raw_path.decode("utf-8", errors="surrogateescape"))
            source, target = ROOT / relative, mirror / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target, dirs_exist_ok=True)
            else:
                shutil.copy2(source, target)
        subprocess.run(["git", "add", "-A"], cwd=mirror, check=True)
        subprocess.run(
            ["git", "-c", "user.name=Aether Doctor", "-c", "user.email=doctor@invalid",
             "commit", "--quiet", "--allow-empty", "-m", "validation baseline"],
            cwd=mirror, check=True,
        )
        yield mirror


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
    """Record a tolerated skip: never counts as a failure, in any mode.

    For registry-driven suite skips that must NOT be tolerated in --ci (a
    skip_policy: never suite skipped for a reason repo_doctor didn't
    override), use hard_fail_skip instead.
    """
    print(f"\n[SKIP] {name}: {reason}")
    results.append(CheckResult(name=name, passed=True, skipped=True, detail=reason))


def hard_fail_skip(
    name: str,
    reason: str,
    remediation: str,
    results: list[CheckResult],
    *,
    stop_on_failure: bool,
) -> None:
    """Record a skip that IS a failure.

    Fixes the historical defect where skip() unconditionally set
    passed=True, making every skip -- tolerated or not -- invisible to the
    exit code. This is for a suite declared skip_policy: never that could
    not be run (e.g. required deps missing) while the current mode does not
    tolerate that: the skip is real (nothing ran), but it must fail the gate.
    """
    print(f"\n[FAIL] {name} (skipped, not tolerated in this mode): {reason}")
    if remediation:
        print(f"Required fix: {remediation}")
    results.append(CheckResult(name=name, passed=False, skipped=True, detail=reason, remediation=remediation))
    if stop_on_failure:
        _print_summary(results)
        sys.exit(1)


def _registry_environment(args: argparse.Namespace) -> str:
    """Map repo_doctor's CLI mode to a test_suites.yaml environment.

    --ci is the strict gate (environment "ci"); --check and --fix are both
    local developer/CI-fix invocations (environment "local"). There is no
    repo_doctor mode corresponding to environment "release" -- that's for
    other release-oriented tooling (e.g. make release-gate) to consume the
    same registry with.
    """
    return "ci" if args.ci else "local"


def ci_python_suites():
    """The pytest-runner suites repo_doctor's --ci mode processes.

    Exists as an importable seam for scripts/validate_test_suite_coverage.py,
    which checks that no ci-scoped suite is silently missing from this
    invocation set without needing to execute pytest itself.
    """
    from scripts.lib.test_suites import is_pytest_suite, load_suites, suites_for

    suites = load_suites(str(ROOT / "config" / "test_suites.yaml"))
    return [s for s in suites_for(suites, "ci") if is_pytest_suite(s)]


def resolve_runner_argv(argv: list[str]) -> list[str]:
    """Resolve a registry runner's portable "python" argv[0] to the gate's own
    interpreter.

    Registry runners declare ``python`` so the declaration stays portable, but
    executing that literally can fall back to a system python whose
    site-packages the toolchain gate has already rejected. Non-python runners
    (npm, bash, hardhat) pass through untouched.
    """
    if argv and argv[0] == "python":
        return [sys.executable, *argv[1:]]
    return list(argv)


def run_registry_python_suites(
    results: list[CheckResult],
    *,
    environment: str,
    stop_on_failure: bool,
) -> None:
    """Replace the old two hardcoded pytest invocations with every applicable
    pytest-runner suite from config/test_suites.yaml.

    Per suite, in order: documented_quarantine and local_only-out-of-scope
    suites are always a tolerated skip; missing required python_packages is a
    tolerated skip in `local` but, for a skip_policy: never suite, a hard
    failure in `ci` (see hard_fail_skip); otherwise the suite actually runs.
    """
    # Invoked as `python scripts/repo_doctor.py`, sys.path[0] is scripts/ —
    # the repo root must be present for the scripts.lib package import.
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from scripts.lib.test_suites import TestSuiteConfigError, build_command, is_pytest_suite, load_suites, suites_for

    registry_path = ROOT / "config" / "test_suites.yaml"
    try:
        suites = load_suites(str(registry_path))
    except TestSuiteConfigError as exc:
        results.append(CheckResult(
            name="Test-suite registry (config/test_suites.yaml)",
            passed=False,
            remediation="fix the reported field in config/test_suites.yaml",
            detail=str(exc),
        ))
        print(f"\n[FAIL] Test-suite registry (config/test_suites.yaml): {exc}")
        if stop_on_failure:
            _print_summary(results)
            sys.exit(1)
        return

    applicable = [s for s in suites_for(suites, environment) if is_pytest_suite(s)]
    for suite in applicable:
        name = f"Python tests ({suite.id})"
        remediation = (
            f"install dev dependencies with pip install -e '.[dev,security,backend,agent,ml]', "
            f"then rerun {' '.join(build_command(suite))}"
        )

        if suite.skip_policy == "documented_quarantine":
            q = suite.quarantine
            skip(name, f"documented_quarantine: {q.reason} (owner={q.owner}, expires={q.expires})", results)
            continue
        if suite.skip_policy == "local_only" and environment != "local":
            skip(name, f"skip_policy=local_only; not run in environment={environment!r}", results)
            continue

        missing = [
            pkg for pkg in suite.requires.python_packages
            if subprocess.run([sys.executable, "-c", f"import {pkg}"], cwd=ROOT).returncode != 0
        ]
        if missing:
            reason = f"missing required python package(s): {', '.join(missing)}"
            if suite.skip_policy == "never" and environment == "ci":
                hard_fail_skip(
                    name,
                    reason,
                    f"install the missing package(s) ({', '.join(missing)}) so this "
                    f"skip_policy=never suite can run in ci",
                    results,
                    stop_on_failure=stop_on_failure,
                )
            else:
                skip(name, reason + "; install them to run this suite locally", results)
            continue

        run(
            resolve_runner_argv(build_command(suite)),
            name=name,
            results=results,
            stop_on_failure=stop_on_failure,
            remediation=remediation,
        )


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
    cwd: Path = ROOT,
) -> bool:
    command = f"git diff --exit-code -- {' '.join(paths)}"
    print(f"\n{'=' * 70}")
    print(f"CHECK: {name}")
    print(f"  CMD: {command}")
    print("=" * 70)
    proc = subprocess.run(["git", "diff", "--exit-code", "--", *paths], cwd=cwd)
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
    proc = subprocess.run([sys.executable, "scripts/docs_drift.py", "--strict"], cwd=ROOT)
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
        if r.skipped and r.passed:
            status = "SKIP"
            suffix = f" ({r.detail})"
        elif r.skipped and not r.passed:
            # A skip that IS a failure: skipped=True no longer implies
            # passed=True (see hard_fail_skip) -- distinct status so it can
            # never be mistaken for a tolerated skip.
            status = "FAIL(skip)"
            suffix = f" ({r.detail})"
        elif r.passed:
            status = "PASS"
            suffix = ""
        else:
            status = "FAIL"
            suffix = ""
        print(f"  [{status}] {r.name:<{width}}{suffix}")
        if not r.passed:
            if r.command:
                print(f"         Failed command: {r.command}")
            if r.remediation:
                print(f"         Required fix: {r.remediation}")
    failed = [r for r in results if not r.passed]
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
        [sys.executable, "scripts/validate_toolchain.py"],
        name="Toolchain preflight",
        results=results,
        stop_on_failure=stop,
        remediation="run make bootstrap for the repository toolchain",
    )

    run(
        [sys.executable, "scripts/validate_makefile.py"],
        name="Makefile command registry",
        results=results,
        stop_on_failure=stop,
        remediation="merge or rename duplicate concrete Make targets",
    )

    run(
        [sys.executable, "scripts/test_inventory.py", "--summary"],
        name="Test ownership, dependency, and quarantine inventory",
        results=results,
        stop_on_failure=stop,
        remediation="complete config/test_inventory.yaml metadata and repair expired quarantines",
    )

    run(
        [sys.executable, "scripts/validate_delivery_profiles.py", "--check-registry"],
        name="Deployment-profile and runtime-fallback policy",
        results=results,
        stop_on_failure=stop,
        remediation="repair config/deployment_profile_compatibility.yaml or config/runtime_fallbacks.yaml",
    )

    run(
        [sys.executable, "scripts/validate_delivery_registries.py"],
        name="Fallback implementation and golden-journey execution registry",
        results=results,
        stop_on_failure=stop,
        remediation="bind fallbacks to real implementations and keep unimplemented journeys explicitly BLOCKED",
    )

    run(
        [sys.executable, "scripts/release/evidence_bundle.py", "--check-registry"],
        name="Golden product journey registry",
        results=results,
        stop_on_failure=stop,
        remediation="register all five owned golden journeys with meaningful assertions",
    )

    run(
        [sys.executable, "scripts/bump_version.py", "--check"],
        name="Version alignment (pyproject.toml is canonical)",
        results=results,
        stop_on_failure=stop,
        remediation="python scripts/bump_version.py <canonical-version>",
    )

    with readonly_generation_workspace(args.check or args.ci) as generation_root:
        run(
            [sys.executable, "scripts/docs_extract/run_all.py"],
            name="Regenerate docs/_generated artifacts",
            results=results,
            stop_on_failure=stop,
            remediation="fix the generator failure, then rerun make repo-doctor-fix", cwd=generation_root,
        )

        run(
            [sys.executable, "scripts/generate_ml_manifest.py"],
            name="Regenerate ML implementation manifest (docs/_generated/ml-implementation-manifest.json)",
            results=results,
            stop_on_failure=stop,
            remediation="fix common/model_registry.py or common/feature_contracts.py, then rerun make repo-doctor-fix", cwd=generation_root,
        )

        run(
            [sys.executable, "scripts/generate_platform_contracts.py"],
            name="Regenerate unified-platform contract artifacts (platform registries)",
            results=results,
            stop_on_failure=stop,
            remediation="fix packages/shared/contracts/*-registry.json or the generator, then rerun make repo-doctor-fix", cwd=generation_root,
        )

        if args.ci or args.check:
            _check_clean(
                ["docs/_generated"],
                name="Generated artifacts — no uncommitted diff",
                results=results,
                stop_on_failure=stop, cwd=generation_root,
            )
            _check_clean(
                [
                    "packages/shared/temporal-policy.ts",
                    "Backend Architecture/aether-backend/shared/temporal/generated_policy.py",
                    "packages/shared/interaction-contract.ts",
                    "Backend Architecture/aether-backend/shared/product/generated_vocabulary.py",
                    "packages/shared/context-capsule.ts",
                    "Backend Architecture/aether-backend/shared/context_capsule/generated_taxonomy.py",
                    "packages/shared/graph-mutation.ts",
                    "Backend Architecture/aether-backend/shared/graph/generated_mutation_taxonomy.py",
                    "packages/shared/filter-fields.ts",
                    "Backend Architecture/aether-backend/shared/exploration/generated_fields.py",
                    "packages/shared/surface-capabilities.ts",
                    "Backend Architecture/aether-backend/shared/exploration/generated_surfaces.py",
                    "packages/shared/comparison-contract.ts",
                    "Backend Architecture/aether-backend/services/intelligence/comparison/generated_vocabulary.py",
                    "Backend Architecture/aether-backend/services/silver/generated_ownership.py",
                    "packages/shared/intelligence-projections_generated.ts",
                    "Backend Architecture/aether-backend/shared/intelligence_projections/generated_registry.py",
                    "packages/shared/lenses_generated.ts",
                    "Backend Architecture/aether-backend/shared/projection_engine/generated_lenses.py",
                    "packages/shared/outcome-types_generated.ts",
                    "Backend Architecture/aether-backend/shared/measurement/generated_outcome_types.py",
                    "packages/shared/relationship-predicate-registry.ts",
                    "Backend Architecture/aether-backend/shared/relationship_spine/generated_relationship_predicate_registry.py",
                    "packages/shared/relationship-motif-registry.ts",
                    "Backend Architecture/aether-backend/shared/relationship_spine/generated_relationship_motif_registry.py",
                    "packages/shared/social-provider-capability-vocabulary.ts",
                    "Backend Architecture/aether-backend/shared/social_provider/generated_social_provider_capability_vocabulary.py",
                    "packages/shared/spine-registry.ts",
                    "Backend Architecture/aether-backend/shared/spine/generated_spine_registry.py",
                ],
                name="Unified-platform generated contracts — no uncommitted diff",
                results=results,
                stop_on_failure=stop, cwd=generation_root,
            )

        run(
            [sys.executable, "scripts/sync_docs.py"],
            name="Sync generated docs (REPO-INDEX, AUTOMATION)",
            results=results,
            stop_on_failure=stop,
            remediation="fix scripts/sync_docs.py or stale inputs, then rerun make docs-fix", cwd=generation_root,
        )

        if args.ci or args.check:
            _check_clean(
                ["docs/REPO-INDEX.md", "docs/AUTOMATION.md"],
                name="Synced docs (REPO-INDEX, AUTOMATION) — no uncommitted diff",
                results=results,
                stop_on_failure=stop, cwd=generation_root,
            )


    docs_gates = [
        ([sys.executable, "scripts/validate_docs.py"], "Docs version drift validation", "python scripts/bump_version.py <canonical-version>"),
        ([sys.executable, "scripts/validate_frontmatter.py"], "Docs frontmatter validity", "fix the reported frontmatter errors"),
        ([sys.executable, "scripts/validate_consent_registry_docs.py"], "Consent-purpose docs are registry-derived (no hardcoded count)", "use registry-derived language; canonical source is packages/shared/contracts/consent-registry.json"),
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
            [sys.executable, "scripts/docs_drift.py", "--strict"],
            name="Source-linked docs drift (strict)",
            results=results,
            stop_on_failure=stop,
            remediation="review listed docs against source_files, update content, then run python scripts/docs_drift.py --update",
        )

    run(
        [sys.executable, "scripts/validate_contracts.py"],
        name="Contract / event / consent alignment",
        results=results,
        stop_on_failure=stop,
        remediation="update contracts, event schemas, consent docs, and SDK surfaces together",
    )
    run(
        [sys.executable, "scripts/validate_readiness_vocabulary.py"],
        name="Readiness vocabulary (Python enum / TS union / contract / evidence schema)",
        results=results,
        stop_on_failure=stop,
        remediation="align readiness.py, capability-state.ts, readiness-vocabulary.json, and evidence-manifest.schema.json membership/ranks",
    )
    run(
        [sys.executable, "scripts/release/check_reward_rail_matrix.py"],
        name="Reward rail matrix (adapters ↔ classification ↔ senders)",
        results=results,
        stop_on_failure=stop,
        remediation="align services/rewards/{rails,rail_matrix,senders}.py and regenerate docs/_generated/reward-rail-matrix.json",
    )
    run(
        [sys.executable, "scripts/validate_signal_use_matrix.py"],
        name="Signal-use matrix (exact purpose per signal; no broad-consent fallback)",
        results=results,
        stop_on_failure=stop,
        remediation="align packages/shared/contracts/signal-use-matrix.json with consent-registry.json",
    )
    run(
        [sys.executable, "scripts/validate_policy_decisions.py"],
        name="Consent PolicyDecision evidence service (present, matrix-driven, wired)",
        results=results,
        stop_on_failure=stop,
        remediation="keep services/policy/ decision fields + signal-use-matrix wiring intact",
    )
    run(
        [sys.executable, "scripts/validate_kyber_seams.py"],
        name="Kyber cross-package seam integrity (declared calls still resolve)",
        results=results,
        stop_on_failure=stop,
        remediation="fix the caller, or update services/kyber/seams.py if a seam legitimately moved",
    )
    run(
        [sys.executable, "scripts/generate_feature_surface_manifest.py"],
        name="Kyber feature-surface coverage (every Aether surface classified)",
        results=results,
        stop_on_failure=stop,
        remediation=(
            "classify the new Aether route: python scripts/generate_feature_surface_manifest.py --write, "
            "then give any parity exception a written reason"
        ),
    )
    run(
        [sys.executable, "scripts/validate_tenant_mirror_parity.py"],
        name="Kyber Tenant Mirror parity (mirror recomputes nothing tenant-visible)",
        results=results,
        stop_on_failure=stop,
        remediation=(
            "give the parity-required surface a mirror resolver, or route the value through "
            "the shared path Aether already uses instead of recomputing it in the mirror"
        ),
    )
    run(
        [sys.executable, "scripts/validate_sdk_release_alignment.py"],
        name="SDK release alignment",
        results=results,
        stop_on_failure=stop,
        remediation="align SDK versions/endpoints/public exports/docs, then rerun validation",
    )
    run(
        [sys.executable, "scripts/validate_consistency_ownership.py"],
        name="Source-of-truth ownership map enforcement",
        results=results,
        stop_on_failure=stop,
        remediation="update the derived surfaces required by docs/source-of-truth/repo_consistency_ownership.json",
    )
    run(
        [sys.executable, "scripts/validate_canonical_ingestion_trees.py"],
        name="Canonical ingestion-tree ownership (single-owner registration; no new duplicate trees)",
        results=results,
        stop_on_failure=stop,
        remediation="route new tree units into the canonical tree (Backend Architecture/aether-backend, packages/*) or register them in scripts/allowlists/repo_tree_ownership.json with architect review; never extend deprecated legacy trees",
    )
    run(
        [sys.executable, "scripts/validate_ts_public_exports.py"],
        name="TypeScript public export/package boundary validation",
        results=results,
        stop_on_failure=stop,
        remediation="export public declaration types from package barrels and fix package.json exports",
    )
    run(
        [sys.executable, "scripts/validate_temporal_integrity.py"],
        name="Temporal integrity static gates (naive datetimes, ad-hoc frontend formatting, CH DateTime64, single Alembic head)",
        results=results,
        stop_on_failure=stop,
        remediation="use shared/temporal (Py) or frontend/shared/src/time (TS); shrink scripts/allowlists/* only",
    )
    run(
        [sys.executable, "scripts/validate_computation_substrate.py"],
        name="Computation substrate governance (registry parity + version discipline, active-def owner/tests, inventory consistency, money-as-float ban)",
        results=results,
        stop_on_failure=stop,
        remediation="regenerate the registry twin (python scripts/generate_computation_registry.py), keep config/computation_inventory.yaml consistent, and shrink scripts/allowlists/computation_money_float.json only",
    )
    run(
        [sys.executable, "scripts/validate_graph_write_paths.py"],
        name="Graph write-path freeze (direct writers pending mutation-gateway migration)",
        results=results,
        stop_on_failure=stop,
        remediation="route graph writes through the canonical mutation gateway; shrink scripts/allowlists/graph_write_paths.json only",
    )
    run(
        [sys.executable, "scripts/validate_graph_scoped_reads.py"],
        name="Graph scoped-read gate (no scan-then-filter-by-tenant global reads in services/)",
        results=results,
        stop_on_failure=stop,
        remediation="answer per-tenant questions with GraphClient.get_vertices_for_tenant; shrink scripts/allowlists/graph_global_reads.json only",
    )
    run(
        [sys.executable, "scripts/validate_reference_packs.py"],
        name="Agent-access reference packs (schema, unique pack ids, grounded reference packs)",
        results=results,
        stop_on_failure=stop,
        remediation="fix the reported fields in config/agent_access_reference_packs/*.yaml; the schema is owned by services/agent_access_intelligence/reference_packs.py::pack_violations",
    )
    run(
        [sys.executable, "scripts/validate_projector_ownership.py"],
        name="Silver projector ownership (registry == dispatcher; one activity owner per event type)",
        results=results,
        stop_on_failure=stop,
        remediation="align packages/shared/contracts/projector-ownership-registry.json with services/silver/dispatcher.py, then regenerate via make repo-doctor-fix",
    )
    run(
        [sys.executable, "scripts/validate_social360_guardrails.py"],
        name="Social360 static guardrails (predicate-registry honesty vs live EdgeTypes + no legacy fabricated defaults)",
        results=results,
        stop_on_failure=stop,
        remediation="REGISTERED predicates must name live EdgeTypes present in shared.graph.relationship_layers; remove any fabricated followers=0 / influence='low' / fixed audience_overlap idioms from the governed social surfaces (services/social, services/silver, services/exploration/adapters/social360.py, services/relationship_fidelity, shared/social360)",
    )
    run(
        [sys.executable, "scripts/validate_intelligence_projections.py"],
        name="Intelligence projection architecture (registry, DAG, cross-registry, inventory, order-resilience)",
        results=results,
        stop_on_failure=stop,
        remediation="align packages/shared/contracts/intelligence-projection-registry.json with the shared contracts, generated artifacts, and real routes/surfaces/services; declare unresolved cross-registry refs in pendingAuthority/pendingReference",
    )
    run(
        [sys.executable, "scripts/validate_spine_registry.py"],
        name="Spine Composition Kernel registry (schema, conformance, cross-registry, lifecycle, ownership, inventory)",
        results=results,
        stop_on_failure=stop,
        remediation="align packages/shared/contracts/spine-registry.json with the shared contracts, generated artifacts, and the real routes/surfaces/services its rows bind; declare unresolved bindings pending in unresolvedRefs with a reason and resolving milestone (ADR-011 D1/D2)",
    )
    run(
        [sys.executable, "scripts/validate_financial_value_semantics.py"],
        name="Financial value semantics (USD-first contract + no cross-currency sums)",
        results=results,
        stop_on_failure=stop,
        remediation="use services.value.safe_rollup and the canonical value contract; see docs/source-of-truth/FINANCIAL_VALUE_SEMANTICS.md",
    )
    run(
        [sys.executable, "scripts/validate_universal_financial_assets.py"],
        name="Universal financial-asset normalization (namespaced ids, Decimal money, immutable valuation, observe-only)",
        results=results,
        stop_on_failure=stop,
        remediation="keep canonical asset/valuation surfaces on the namespaced Decimal immutable observe-only model; see docs/source-of-truth/FINANCIAL_NORMALIZATION.md",
    )
    run(
        [sys.executable, "scripts/validate_frontend_value_display.py"],
        name="Frontend value-display guardrail (canonical ValueDisplay/formatUSD)",
        results=results,
        stop_on_failure=stop,
        remediation="render financial values via frontend/shared ValueDisplay/formatUSD; update the allowlist in scripts/validate_frontend_value_display.py",
    )
    run(
        [sys.executable, "scripts/validate_cross360_monetary_fx.py"],
        name="Cross-360 monetary/FX guard (context-360 + composition seam stay on the canonical value/FX path)",
        results=results,
        stop_on_failure=stop,
        remediation="keep the context-360 family, exploration path, and cross-360 composition seam monetary-free; consume economic360/services.value pre-priced content with canonical FX provenance; shrink scripts/allowlists/cross360_monetary_fx.json only",
    )
    run(
        [sys.executable, "scripts/validate_event_schema_parity.py"],
        name="EventType parity (TypeScript ↔ Python CANONICAL_EVENT_TYPES)",
        results=results,
        stop_on_failure=stop,
        remediation="sync CANONICAL_EVENT_TYPES in services/ingestion/batch.py with EventType union in packages/shared/events.ts",
    )
    run(
        [sys.executable, "scripts/validate_mobile_event_parity.py"],
        name="Mobile event parity",
        results=results,
        stop_on_failure=stop,
        remediation=(
            "hand-edit AetherEventType/eventConsentPurpose in packages/ios/Sources/AetherSDK/Aether.swift "
            "and/or EVENT_CONSENT_PURPOSE in packages/android/src/main/java/com/aether/sdk/Aether.kt so their "
            "event-type sets match packages/shared/contracts/event-registry.json; native registries are never "
            "code-generated (see scripts/validate_sdk_parity.py's documented non-goal)"
        ),
    )
    run(
        [sys.executable, "scripts/validate_meter_names.py"],
        name="Canonical meter names (ingestion/connector paths)",
        results=results,
        stop_on_failure=stop,
        remediation="rename non-canonical metrics.increment() names or add them to CANONICAL_NAMES in scripts/validate_meter_names.py",
    )
    run(
        [sys.executable, "scripts/release/check_storage_policies.py"],
        name="Storage policy registry (schema + per-persistent-type coverage)",
        results=results,
        stop_on_failure=stop,
        remediation="add a policy for every persistent resource type to config/storage_policies.yaml (inventory: repositories/repos.py stores + alembic-created tables)",
    )
    run(
        [sys.executable, "scripts/release/validate_delivery_safety.py"],
        name="Delivery safety validator (D11 unsafe-delivery patterns)",
        results=results,
        stop_on_failure=stop,
        remediation="fix the reported delivery-path violation (direct adapter dispatch, fire-and-forget critical task, unconfigured router, zero-channel success, or unguarded simulated receipt) in services/delivery/** or services/notification_intelligence/**",
    )
    run(
        [sys.executable, "scripts/release/check_profile_parity.py"],
        name="Profile parity (docs count, cloud subset, Terraform selectability, contracts, runtime, env templates)",
        results=results,
        stop_on_failure=stop,
        remediation=(
            "align every profile-stating surface with config/deployment_profiles.yaml "
            "(docs count phrases, cloud-class subset, profiles/*.tfvars, variables.tf "
            "validation, terraform_resource_contracts.yaml, runtime_deployment.yaml, "
            "env templates); run python scripts/release/check_profile_parity.py to see "
            "which surface drifted"
        ),
    )
    run(
        [sys.executable, "scripts/release/check_delivery_compose_parity.py"],
        name="Delivery compose parity (no compose file claims the staging profile)",
        results=results,
        stop_on_failure=stop,
        remediation=(
            "a compose file is presenting itself as the canonical staging profile "
            "(provisions forbidden MSK/ElastiCache/Prometheus). The stale stack must "
            "stay quarantined under deploy/legacy-staging/ with the LEGACY marker; "
            "canonical staging is Terraform (profiles/staging.tfvars)"
        ),
    )
    run(
        [sys.executable, "scripts/release/profile_doctor.py", "--all", "--strict"],
        name="Profile readiness doctor (states, no cloud profile below credential_waiting)",
        results=results,
        stop_on_failure=stop,
        remediation=(
            "a cloud profile is below CREDENTIAL_WAITING or an in-repo check failed; "
            "run python scripts/release/profile_doctor.py --all to see which check "
            "broke and which profile regressed"
        ),
    )
    run(
        [sys.executable, "scripts/staging_capability_matrix.py"],
        name="Deploy-profile capability matrix + join layer (facet references resolve; bidirectional coverage)",
        results=results,
        stop_on_failure=stop,
        remediation=(
            "align config/capability_matrix.yaml with config/deploy_profile.yaml and its "
            "facets (route_registry, roles.py, founding_tenant_release, deployment_readiness); "
            "never delete a facet key to silence a dangling reference"
        ),
    )
    run(
        [sys.executable, "scripts/validate_sdk_contracts.py"],
        name="SDK ingestion contract (shared TS ↔ backend /v1/batch)",
        results=results,
        stop_on_failure=stop,
        remediation="align packages/shared/ingestion-contract.ts with services/ingestion/batch.py (endpoint, idempotency key, batch bounds)",
    )
    run(
        [sys.executable, "scripts/validate_sdk_import_boundary.py"],
        name="SDK import boundary (client SDK surfaces must not import backend/legacy internals)",
        results=results,
        stop_on_failure=stop,
        remediation="keep SDK client surfaces thin — talk to api.aether.io / ingest.aether.so; never import aether-backend, Data Ingestion Layer, or Data Lake Architecture internals (shrink scripts/allowlists/sdk_internal_import_allowlist.json only)",
    )
    run(
        [sys.executable, "scripts/validate_model_governance.py"],
        name="Model governance (consent-scoped training + inference gates)",
        results=results,
        stop_on_failure=stop,
        remediation="ensure services/model_governance gates exist, reuse the consent engine, and are wired into ml_serving/routes.py; see docs/source-of-truth/MODEL_GOVERNANCE.md",
    )
    run(
        [sys.executable, "scripts/validate_consent_purpose_reconciliation.py"],
        name="Consent-purpose reconciliation (compliance enum ↔ 12-purpose registry)",
        results=results,
        stop_on_failure=stop,
        remediation="reconcile ConsentPurpose in GDPR & SOC2/aether-compliance/config/compliance_config.py with packages/shared/contracts/consent-registry.json",
    )
    run(
        [sys.executable, "scripts/validate_sdk_parity.py"],
        name="SDK runtime parity (observe / manifest-verify / batch-health across SDKs)",
        results=results,
        stop_on_failure=stop,
        remediation="expose canonical observe(), iOS/Android manifest signature verification, and batch health metrics; see docs/source-of-truth/SDK_RUNTIME_PARITY.md",
    )
    run(
        [sys.executable, "scripts/check_version_consistency.py"],
        name="Version/workspace consistency aggregate",
        results=results,
        stop_on_failure=stop,
        remediation="run python scripts/bump_version.py <version> or fix root package.json workspaces coverage",
    )

    if not args.docs_only:
        run(
            [sys.executable, "scripts/validate_frontend_data_truth.py"],
            name="Frontend data-truth source guardrail (Aether/Kyber)",
            results=results,
            stop_on_failure=stop,
            remediation=(
                "remove runtime mock/fixture imports, mock-mode branches, synthetic "
                "identifiers, and public browser workers; keep fixtures only in the "
                "validator's narrow test-only paths"
            ),
        )
        run(
            [sys.executable, "scripts/validate_frontend_branding.py"],
            name="Frontend brand migration guardrail (canonical shell/provider seams)",
            results=results,
            stop_on_failure=stop,
            remediation=(
                "replace deprecated navigation glyphs, feature-local provider/brand "
                "artwork, raw motion/shadow values, and unnamed icon-only controls "
                "on the validator's declared migration targets; use an exact documented "
                "PATH:RULE:REASON exception only for a temporary migration dependency"
            ),
        )
        run(
            ["python", "scripts/validate_frontend_route_state_matrix.py", "--enforce"],
            name="Frontend route-state coverage (Aether/Kyber)",
            results=results,
            stop_on_failure=stop,
            remediation=(
                "add evidence-backed successful-empty coverage for at least 90% "
                "of data routes and empty/error coverage for every critical route"
            ),
        )

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

        run(
            [sys.executable, "scripts/validate_frontend_data_truth.py", "--build-bundles"],
            name="Frontend data-truth production bundle build and scan (Aether/Kyber)",
            results=results,
            stop_on_failure=stop,
            remediation=(
                "fix Aether/Kyber production builds and remove emitted legacy worker, "
                "mock-token, demo-tenant, and synthetic-record literals"
            ),
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

        run_registry_python_suites(
            results,
            environment=_registry_environment(args),
            stop_on_failure=stop,
        )

        # ML registry consistency — CI gate
        ml_registry_script = ROOT / "scripts" / "validate_ml_registry.py"
        if ml_registry_script.exists():
            run(
                [sys.executable, str(ml_registry_script)],
                name="ML registry consistency",
                results=results,
                stop_on_failure=stop,
                remediation="fix common/model_registry.py, common/feature_contracts.py, or training/configs/model_configs.py",
            )

    _print_summary(results)
    failed = [r for r in results if not r.passed]
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
