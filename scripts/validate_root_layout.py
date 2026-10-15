#!/usr/bin/env python3
"""Fail when the repository root drifts from the canonical layout.

Only tracked root entries are checked. New root entries require a deliberate
edit to the allowlists below (and to docs/reference/source-of-truth/repo-truth.md).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

ALLOWED_ROOT_DIRS = frozenset(
    {".artifacts", ".claude", ".codex", ".devcontainer", ".github", "apps", "config",
     "docs", "infra", "packages", "scripts", "services", "tests"}
)

ALLOWED_ROOT_FILES = frozenset(
    {".dockerignore", ".gitignore", ".npmrc", ".pre-commit-config.yaml", "AGENTS.md",
     "ARCHITECTURE.md", "CHANGELOG.md", "CLAUDE.md", "CONTRIBUTING.md", "DEVELOPMENT.md",
     "LICENSE", "Makefile", "README.md", "RELEASES.md", "SECURITY.md", "VERSION",
     "amplify.yml", "eslint.config.mjs", "package-lock.json", "package.json",
     "pnpm-lock.yaml", "pnpm-workspace.yaml", "pnpm.config.cjs", "pnpm.config.yaml",
     "pyproject.toml", "tsconfig.json", "vitest.config.fps.ts"}
)

REQUIRED_ROOT_FILES = frozenset(
    {"README.md", "VERSION", "CHANGELOG.md", "RELEASES.md", "ARCHITECTURE.md",
     "CONTRIBUTING.md", "DEVELOPMENT.md", "SECURITY.md", "LICENSE", "Makefile"}
)

FORBIDDEN_ROOT_DIRS = frozenset(
    {"Backend Architecture", "Data Ingestion Layer", "Data Lake Architecture",
     "AWS Deployment", "ML Models", "Smart Contracts", "GDPR & SOC2", "contracts", "frontend"}
)


def classify(paths: list[str]) -> tuple[set[str], set[str]]:
    dirs = {p.split("/", 1)[0] for p in paths if "/" in p}
    files = {p for p in paths if "/" not in p}
    return dirs, files


def find_violations(paths: list[str], version_file: str | None, canonical_version: str | None) -> list[str]:
    dirs, files = classify(paths)
    errors = [f"forbidden root directory: {d}/ (legacy material belongs in docs/archive/)"
              for d in sorted(dirs & FORBIDDEN_ROOT_DIRS)]
    errors += [f"unexpected root directory: {d}/" for d in sorted(dirs - ALLOWED_ROOT_DIRS - FORBIDDEN_ROOT_DIRS)]
    errors += [f"unexpected root file: {f}" for f in sorted(files - ALLOWED_ROOT_FILES)]
    errors += [f"missing required root file: {f}" for f in sorted(REQUIRED_ROOT_FILES - files)]
    if version_file is not None and canonical_version is not None and version_file != canonical_version:
        errors.append(f"VERSION ({version_file}) does not match pyproject.toml ({canonical_version})")
    return errors


def _canonical_version() -> str | None:
    for line in (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        if line.startswith("version"):
            return line.split("=", 1)[1].strip().strip('"')
    return None


def main() -> int:
    paths = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout.splitlines()
    version_path = REPO_ROOT / "VERSION"
    version = version_path.read_text(encoding="utf-8").strip() if version_path.exists() else None
    errors = find_violations(paths, version, _canonical_version())
    if errors:
        print("Root layout validation FAILED:")
        for e in errors:
            print(f"  - {e}")
        print("Fix the root, or update the allowlists in scripts/validate_root_layout.py "
              "and docs/reference/source-of-truth/repo-truth.md together.")
        return 1
    print("Root layout validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
