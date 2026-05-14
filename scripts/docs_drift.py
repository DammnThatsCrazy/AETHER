#!/usr/bin/env python3
"""Detect documentation drift against repo source files.

For every authored doc with ``source_files:`` frontmatter, this script:

  1. Verifies each ``source_files:`` path exists in the repo. A missing
     path is a hard error — it usually means a referenced module was
     renamed or deleted without updating the doc.

  2. If the doc also declares ``last_synced_commit: <sha>``, compares
     that SHA against the most-recent git SHA that touched the
     declared source files. If the source has been modified since,
     the doc is stale.

By default the script exits 0 even when staleness is detected — this is
the advisory phase. A follow-up change will introduce ``--strict`` and
wire it into CI once authors have stamped ``last_synced_commit`` on the
docs they own. Hard errors (missing source paths) ALWAYS fail; those
indicate broken metadata regardless of rollout phase.

Modes:
  python scripts/docs_drift.py            # walk + report (advisory)
  python scripts/docs_drift.py --strict   # exit 1 on any drift

Exit codes:
  0  no missing paths; staleness reported as warnings (or strict mode passed)
  1  one or more docs reference paths that don't exist, OR strict-mode drift
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
DOCS_ROOT = ROOT / "docs"

SKIP_DIRS = {
    DOCS_ROOT / "archive",
    DOCS_ROOT / "_generated",
    DOCS_ROOT / "_templates",
    DOCS_ROOT / "diagrams",
    DOCS_ROOT / "examples",
    DOCS_ROOT / "source-of-truth",
}


class DriftError(Exception):
    """A doc references a path that doesn't exist (always fatal)."""


def tracked_docs() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "docs/**.md", "docs/**.mdx", "docs/*.md", "docs/*.mdx"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    out: list[Path] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        path = ROOT / line
        if any(skip in path.parents for skip in SKIP_DIRS):
            continue
        out.append(path)
    return sorted(out)


def extract_frontmatter(text: str) -> dict[str, Any] | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end < 0:
        return None
    body = text[4:end]
    try:
        data = yaml.safe_load(body)
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def commits_touching_after(declared: str, paths: list[str]) -> list[str]:
    """Return short SHAs of commits that touched any of `paths` after `declared`.

    Uses ``git log <declared>..HEAD -- <paths>``. If `declared` is unknown
    to git (e.g. force-push removed it), returns an empty list so the
    caller can skip drift detection rather than false-positive.
    """
    if not paths or not declared:
        return []
    cmd = ["git", "log", f"{declared}..HEAD", "--format=%h", "--"] + paths
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line]


def check_doc(path: Path) -> dict:
    """Return a report dict for one doc.

    Keys:
      missing_paths: list[str]   — paths declared in source_files that don't exist
      stale: bool                — sources have new commits since last_synced_commit
      stale_detail: str | None   — human-readable explanation when stale
    """
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        rel = path
    text = path.read_text(encoding="utf-8")
    fm = extract_frontmatter(text)
    if fm is None:
        # validate_frontmatter.py owns this case; drift detector skips.
        return {"path": str(rel), "missing_paths": [], "stale": False, "stale_detail": None}

    sources = fm.get("source_files") or []
    if not isinstance(sources, list):
        return {"path": str(rel), "missing_paths": [], "stale": False, "stale_detail": None}

    missing = [s for s in sources if not (ROOT / s).exists()]

    stale = False
    detail: str | None = None
    declared = fm.get("last_synced_commit")
    if declared and not missing:
        # Drift = any commit touched a declared source AFTER the sync stamp.
        # Equality is the wrong check: `last_synced_commit` is the commit
        # the doc was reviewed at, not necessarily the most recent commit
        # that touched the sources. A freshly-stamped doc whose sources
        # are older than the stamp should NOT be flagged stale.
        present_sources = [s for s in sources if (ROOT / s).exists()]
        newer = commits_touching_after(declared, present_sources)
        if newer:
            stale = True
            detail = (
                f"last_synced_commit={declared}; sources have been modified "
                f"in {len(newer)} commit(s) since: "
                f"{', '.join(newer[:3])}{'...' if len(newer) > 3 else ''}. "
                f"Re-review and update last_synced_commit."
            )

    return {
        "path": str(rel),
        "missing_paths": missing,
        "stale": stale,
        "stale_detail": detail,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 on any drift (default: missing paths only).",
    )
    args = parser.parse_args()

    reports = [check_doc(p) for p in tracked_docs()]

    missing_reports = [r for r in reports if r["missing_paths"]]
    stale_reports = [r for r in reports if r["stale"]]
    clean_count = len(reports) - len(missing_reports) - len(stale_reports)

    print(
        f"docs_drift: {len(reports)} docs scanned, "
        f"{clean_count} clean, "
        f"{len(stale_reports)} stale (advisory), "
        f"{len(missing_reports)} with missing source paths."
    )

    if stale_reports:
        print()
        print("STALE (advisory):")
        for r in stale_reports:
            print(f"  - {r['path']}: {r['stale_detail']}")

    if missing_reports:
        print()
        print("MISSING SOURCE PATHS (always fatal):")
        for r in missing_reports:
            for mp in r["missing_paths"]:
                print(f"  - {r['path']}: source_files entry {mp!r} does not exist")
        return 1

    if args.strict and stale_reports:
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
