#!/usr/bin/env python3
"""Fail when deprecated product language appears outside the archive.

Canonical terms live in docs/reference/source-of-truth/naming-truth.md.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DEPRECATED_TERMS = (
    "Audience Intelligence",
    "Economic 360",
    "Business Value",
    "Audience Traits",
    "Graph Snapshot",
)
# Too common in code prose to ban repo-wide; checked only in user-facing docs/UI.
SCOPED_TERMS = {"Segments": ("docs/", "apps/")}

ALLOWED_PREFIXES = ("docs/archive/",)
ALLOWED_FILES = frozenset(
    {
        "docs/reference/source-of-truth/naming-truth.md",
        "docs/product/language-system/deprecated-language.md",
        "scripts/check_deprecated_language.py",
        "tests/unit/test_root_layout_and_language.py",
    }
)
SKIP_SUFFIXES = (".lock", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2", ".pdf")
SKIP_NAMES = frozenset({"package-lock.json", "pnpm-lock.yaml"})


def scan_text(path: str, text: str) -> list[str]:
    if path in ALLOWED_FILES or path.startswith(ALLOWED_PREFIXES):
        return []
    hits: list[str] = []
    terms = list(DEPRECATED_TERMS) + [t for t, scopes in SCOPED_TERMS.items() if path.startswith(scopes)]
    for lineno, line in enumerate(text.splitlines(), start=1):
        for term in terms:
            if re.search(rf"(?<![\w]){re.escape(term)}(?![\w])", line):
                hits.append(f"{path}:{lineno}: deprecated term '{term}'")
    return hits


def main() -> int:
    paths = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, check=True, capture_output=True, text=True
    ).stdout.splitlines()
    violations: list[str] = []
    for path in paths:
        if path.endswith(SKIP_SUFFIXES) or Path(path).name in SKIP_NAMES:
            continue
        try:
            text = (REPO_ROOT / path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        violations.extend(scan_text(path, text))
    if violations:
        print("Deprecated language validation FAILED:")
        for v in violations:
            print(f"  - {v}")
        print("Use the canonical term from docs/reference/source-of-truth/naming-truth.md, "
              "or move legacy material under docs/archive/.")
        return 1
    print("Deprecated language validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
