#!/usr/bin/env python3
"""Generate ``docs/_generated/doc-manifest.json`` from docs frontmatter.

Walks every ``docs/**/*.{md,mdx}`` file, extracts YAML frontmatter, and
emits a structured manifest.  The frontend uses this for navigation and
doc-index rendering without having to parse or bundle the raw docs.

Schema of the output::

    {
      "version": "8.9.0",
      "generated_from": "docs/**/*.{md,mdx}",
      "docs": [
        {
          "path": "docs/ARCHITECTURE.md",
          "title": "Architecture",
          "slug": "architecture/overview",
          "section": "architecture",
          "visibility": "P",
          "audience": ["dev-senior", "architect"],
          "status": "stable",
          "estimated_read_minutes": 10
        },
        ...
      ]
    }
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
DOCS_DIR = ROOT / "docs"
OUT = ROOT / "docs" / "_generated" / "doc-manifest.json"
SKIP_DIRS = {"_generated", "_templates", "archive"}

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)

# Ordered tuple — sets have non-deterministic iteration order which
# would break the byte-identical-output guarantee that the drift gate
# depends on. Don't change to a set.
KEPT_KEYS = (
    "title", "slug", "section", "visibility", "audience", "status",
    "since_version", "estimated_read_minutes", "toc_depth",
    "canonical_owner", "flags",
)


def _read_frontmatter(path: Path) -> dict | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return None
    m = FRONTMATTER_RE.match(raw)
    if not m:
        return None
    try:
        fm = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None
    return fm if isinstance(fm, dict) else None


def _git_tracked_docs() -> set[str]:
    """Return the set of git-tracked ``docs/**/*.{md,mdx}`` paths.

    The manifest is a committed artifact consumed by the frontend and the
    drift gate; it must describe only docs that exist in the committed tree.
    Untracked files (e.g. docs from another in-flight branch sitting in the
    working tree) must not be indexed — including them would make the
    regenerated manifest diverge from the committed one and fail the gate.
    Mirrors ``scripts/sync_docs.py`` which already counts tracked files only.
    """
    proc = subprocess.run(
        ["git", "ls-files", "docs/"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return {
        line
        for line in proc.stdout.splitlines()
        if line and line.endswith((".md", ".mdx"))
    }


def main() -> int:
    version_path = ROOT / "package.json"
    try:
        pkg = json.loads(version_path.read_text(encoding="utf-8"))
        version = pkg.get("version", "unknown")
    except Exception:
        version = "unknown"

    docs: list[dict] = []
    tracked = _git_tracked_docs()
    for path in sorted(DOCS_DIR.rglob("*.md")) + sorted(DOCS_DIR.rglob("*.mdx")):
        # Skip _generated, _templates, archive subtrees
        parts = path.relative_to(DOCS_DIR).parts
        if any(p in SKIP_DIRS for p in parts):
            continue
        if str(path.relative_to(ROOT)) not in tracked:
            continue  # untracked docs (other branches / WIP) must not be indexed
        fm = _read_frontmatter(path)
        if not fm:
            continue
        entry: dict = {"path": str(path.relative_to(ROOT))}
        for key in KEPT_KEYS:
            if key in fm:
                entry[key] = fm[key]
        docs.append(entry)

    result = {
        "version": version,
        "generated_from": "docs/**/*.{md,mdx}",
        "docs": docs,
    }

    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"extract_doc_manifest: {len(docs)} docs written to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
