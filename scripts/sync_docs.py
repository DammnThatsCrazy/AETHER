#!/usr/bin/env python3
"""Generate lightweight repository documentation artifacts from the current tree.

This script gives the repo a deterministic, machine-generated documentation
surface that can be checked in CI. It is intentionally conservative: it does
not attempt to rewrite authored architecture docs, but it does keep a living
index of important areas and the automation that protects them.

Uses `git ls-files` to count only tracked files, ensuring deterministic output
regardless of build artifacts, caches, or virtual environments.
"""

from __future__ import annotations

import subprocess
from collections import defaultdict
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
INDEX_PATH = DOCS / "REPO-INDEX.md"
AUTOMATION_PATH = DOCS / "AUTOMATION.md"

TOP_LEVEL_DOC_FOCUS = {
    "security",
    "scripts",
    "docs",
    "tests",
    "cicd",
    "ML Models",
    "Agent Layer",
    "Data Ingestion Layer",
    "Smart Contracts",
    "AWS Deployment",
    "GDPR & SOC2",
}


def _git_tracked_files() -> list[str]:
    """Return all git-tracked file paths relative to ROOT."""
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return [line for line in result.stdout.splitlines() if line]


def collect_counts(area: str, tracked: list[str]) -> tuple[int, int]:
    """Count directories and files under a top-level area using git-tracked files."""
    prefix = area + "/"
    files = 0
    dirs: set[str] = set()
    for fpath in tracked:
        if not fpath.startswith(prefix):
            continue
        files += 1
        parent = str(PurePosixPath(fpath).parent)
        if parent != area:
            dirs.add(parent)
            # Add intermediate directories
            parts = PurePosixPath(fpath).parts
            for i in range(2, len(parts)):
                dirs.add(str(PurePosixPath(*parts[:i])))
    return len(dirs), files


def top_level_summary(tracked: list[str]) -> list[tuple[str, int, int]]:
    rows: list[tuple[str, int, int]] = []
    for area in sorted(TOP_LEVEL_DOC_FOCUS, key=str.lower):
        dirs, files = collect_counts(area, tracked)
        if files > 0:
            rows.append((area, dirs, files))
    return rows


def authored_docs() -> dict[str, list[str]]:
    """Group authored docs for REPO-INDEX coverage.

    Most authored docs live at ``docs/*.md``. Product-domain slices may also
    introduce narrowly scoped nested docs (for example
    ``docs/semantic-sentiment/`` and its runbooks). Include those nested docs
    explicitly so ``sync_docs.py`` is deterministic in CI without sweeping in
    archive/source-of-truth trees owned by separate documentation validators.
    """
    groups: dict[str, list[str]] = defaultdict(list)
    paths = list(DOCS.glob("*.md"))
    paths.extend((DOCS / "semantic-sentiment").glob("*.md"))
    paths.extend((DOCS / "runbooks" / "semantic-sentiment").glob("*.md"))
    for path in sorted(paths):
        rel = path.relative_to(DOCS)
        if path.name in {INDEX_PATH.name, AUTOMATION_PATH.name, "CHANGELOG.md"}:
            continue
        doc_ref = rel.as_posix()
        stem = path.stem
        if rel.parts[0] == "runbooks":
            groups["Runbooks"].append(doc_ref)
        elif rel.parts[0] == "semantic-sentiment":
            groups["Product Domains"].append(doc_ref)
        elif stem.startswith("SDK-"):
            groups["SDKs"].append(doc_ref)
        elif stem in {"ARCHITECTURE", "BACKEND-API", "INTELLIGENCE-GRAPH", "AGENT-CONTROLLER"}:
            groups["Platform"].append(doc_ref)
        else:
            groups["Specialized"].append(doc_ref)
    return dict(sorted(groups.items()))


def _frontmatter(
    title: str,
    slug: str,
    section: str,
    audience: list[str],
    source_files: list[str],
    minutes: int,
) -> list[str]:
    """Render the canonical frontmatter block for an auto-generated doc.

    Generated docs declare ``visibility: I`` (internal) — they describe the
    repository's own automation surface and are not customer-facing.
    """
    lines = [
        "---",
        f"title: {title}",
        f"slug: {slug}",
        f"section: {section}",
        "visibility: I",
        "audience: [" + ", ".join(audience) + "]",
        "status: stable",
        'since_version: "8.8.0"',
        "source_files:",
    ]
    for sf in source_files:
        lines.append(f"  - {sf}")
    lines += [
        "canonical_owner: platform@aether",
        f"estimated_read_minutes: {minutes}",
        "toc_depth: 3",
        "---",
        "",
    ]
    return lines


def write_index(tracked: list[str]) -> None:
    rows = top_level_summary(tracked)
    lines = _frontmatter(
        title="Repository Index",
        slug="reference/repo-index",
        section="reference",
        audience=["dev-senior", "ops", "architect"],
        source_files=["scripts/sync_docs.py"],
        minutes=2,
    )
    lines += [
        "# Repository Index",
        "",
        "_Generated by `python scripts/sync_docs.py`. Do not edit by hand._",
        "",
        "## Top-level subsystem inventory",
        "",
        "| Area | Directories | Files |",
        "| --- | ---: | ---: |",
    ]
    for name, dirs, files in rows:
        lines.append(f"| `{name}` | {dirs} | {files} |")

    lines.extend(
        [
            "",
            "## Authored documentation coverage",
            "",
            "The following authored docs are expected to stay aligned with code changes:",
            "",
        ]
    )
    for group, docs in authored_docs().items():
        lines.append(f"### {group}")
        for doc in docs:
            lines.append(f"- `{doc}`")
        lines.append("")

    lines.extend(
        [
            "## Operational rule",
            "",
            "Any code change that modifies subsystem behavior must update at least one authored doc or explicitly document why no authored doc changed in the pull request.",
            "",
        ]
    )
    INDEX_PATH.write_text("\n".join(lines))


def write_automation() -> None:
    lines = _frontmatter(
        title="Documentation Automation",
        slug="operations/doc-automation",
        section="operations",
        audience=["ops", "dev-senior"],
        source_files=["scripts/sync_docs.py", "scripts/validate_docs.py"],
        minutes=2,
    )
    lines += [
        "# Documentation Automation",
        "",
        "_Generated by `python scripts/sync_docs.py`. This file is machine-managed — "
        "do not edit it by hand; update the generator strings in `scripts/sync_docs.py` "
        "if this policy changes._",
        "",
        "## Canonical consistency system",
        "",
        "`scripts/repo_doctor.py` and the root `Makefile` are the single source of "
        "truth for repository consistency. All checks flow through them:",
        "",
        "- `make repo-doctor` — full consistency check, no mutations.",
        "- `make repo-doctor-fix` — regenerate generated docs + sync, then validate.",
        "- `make docs-fix` — regenerate and sync docs only.",
        "- `make frontend-data-truth` — enforce Aether/Kyber production-source "
        "mock and fixture boundaries.",
        "- `make frontend-data-truth-bundles` — create explicit production builds "
        "and scan emitted bundles for prohibited synthetic literals.",
        "- `make ci-check` — **canonical PR completion gate**; fails if generators produce a diff.",
        "- `make release-gate` — `ci-check` + strict production status + ops readiness (release claims only).",
        "",
        "## Generated vs authored docs",
        "",
        "1. Generated docs are machine-managed: `docs/_generated/**` (from "
        "`scripts/docs_extract/run_all.py`), and `docs/REPO-INDEX.md` + "
        "`docs/AUTOMATION.md` (from `scripts/sync_docs.py`). Never hand-edit them.",
        "2. Authored source-linked docs (those with `source_files:` frontmatter) "
        "require review when their linked sources change. Run "
        "`python scripts/docs_drift.py --update` **only after** reviewing each doc — "
        "stamping is not a substitute for review.",
        "3. Consent behavior is registry-derived: "
        "`packages/shared/contracts/consent-registry.json` is canonical. Do not "
        "hardcode a consent-purpose count in any doc or validator.",
        "",
        "## Required workflow",
        "",
        "- Regenerate: `make docs-fix`.",
        "- Review any stale source-linked docs reported by "
        "`python scripts/docs_drift.py --strict`, then stamp with "
        "`python scripts/docs_drift.py --update`.",
        "- Final gate: `make ci-check`. Weaker commands (`npm run test:docs`, "
        "partial pytest runs, docs-only checks, `make repo-doctor` alone) are not "
        "sufficient proof of PR completion.",
        "- The canonical gate runs both frontend data-truth checks. "
        "`npm run validate:frontend-data-truth` is also a named read-only workflow "
        "step so source violations are directly visible in pull requests.",
        "",
        "## Workflow enforcement",
        "",
        "- `.github/workflows/repo-health.yml` runs read-only consistency checks on "
        "every push and pull request; PR-head jobs have no write permissions.",
        "- On trusted pushes to `main` only, a separate write-capable `docs-sync` "
        "job regenerates and auto-commits generated documentation so the branch "
        "stays self-healing.",
        "",
    ]
    AUTOMATION_PATH.write_text("\n".join(lines))


if __name__ == "__main__":
    DOCS.mkdir(exist_ok=True)
    tracked = _git_tracked_files()
    write_index(tracked)
    write_automation()
    print(f"Updated {INDEX_PATH.relative_to(ROOT)}")
    print(f"Updated {AUTOMATION_PATH.relative_to(ROOT)}")
