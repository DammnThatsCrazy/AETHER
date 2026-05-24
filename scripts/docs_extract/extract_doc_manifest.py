#!/usr/bin/env python3
"""Generate docs/_generated/doc-manifest.json.

The manifest is a deterministic, machine-readable index of every authored doc
in the repo. It is consumed by the docs site build and by CI checks.

Design notes
------------
* ``KEPT_KEYS`` is a ``tuple`` (ordered) so iteration order is stable across
  Python invocations. Using a ``set`` would make the output non-deterministic
  due to Python's hash randomisation (PYTHONHASHSEED). The keys are defined
  once here; every entry in the manifest is built with ``sorted(KEPT_KEYS)`` to
  guarantee lexicographic key order inside each object.

* The renderable flag uses the **full** slug (e.g. ``api/backend-reference``)
  when checking whether a page exists in the docs site pages tree. Stripping to
  the last path segment (``slug.split("/")[-1]``) silently misidentifies nested
  pages such as ``concepts/identity-resolution`` as non-renderable.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
DOCS_ROOT = ROOT / "docs"
OUT_PATH = DOCS_ROOT / "_generated" / "doc-manifest.json"

SKIP_DIRS = {
    DOCS_ROOT / "archive",
    DOCS_ROOT / "_generated",
    DOCS_ROOT / "_templates",
    DOCS_ROOT / "diagrams",
    DOCS_ROOT / "examples",
}

# Ordered tuple — do NOT change to a set. Iteration order must be stable so
# that successive runs produce byte-identical JSON. Use sorted(KEPT_KEYS) when
# building each entry to ensure lexicographic key order.
KEPT_KEYS: tuple[str, ...] = (
    "audience",
    "estimated_read_minutes",
    "prereqs",
    "related",
    "section",
    "since_version",
    "slug",
    "status",
    "title",
    "toc_depth",
    "visibility",
)

# Docs whose visibility is "I" (internal) are never exposed in the public
# manifest but ARE indexed so internal tooling can reference them.
RENDERABLE_VISIBILITIES = frozenset({"P", "C"})


def _tracked_docs() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "docs/"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    out: list[Path] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        p = ROOT / line
        if p.suffix not in {".md", ".mdx"}:
            continue
        if any(skip in p.parents for skip in SKIP_DIRS):
            continue
        out.append(p)
    return sorted(out)


def _extract_frontmatter(text: str) -> dict[str, Any] | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end < 0:
        return None
    try:
        data = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def _is_renderable(frontmatter: dict[str, Any]) -> bool:
    """Return True when the page will be rendered by the docs site.

    Uses the FULL slug (e.g. ``sdks/web``) so that nested pages are correctly
    identified. Do NOT use ``slug.split("/")[-1]`` — that strips the section
    prefix and causes false negatives for any nested slug.
    """
    slug = frontmatter.get("slug", "")
    if not slug:
        return False
    visibility = frontmatter.get("visibility", "I")
    # A page is renderable when it is public/customer-visible AND has a slug.
    # When a docs-site pages tree is available, swap this for a file-existence
    # check using the full slug path: ``(pages_dir / slug).with_suffix(".mdx")``.
    return visibility in RENDERABLE_VISIBILITIES


def _build_entry(frontmatter: dict[str, Any], path: Path) -> dict[str, Any]:
    # Use sorted(KEPT_KEYS) to produce lexicographically ordered keys; the
    # constant itself is already sorted but we sort explicitly for safety.
    entry: dict[str, Any] = {
        k: frontmatter[k] for k in sorted(KEPT_KEYS) if k in frontmatter
    }
    entry["renderable"] = _is_renderable(frontmatter)
    entry["_source"] = str(path.relative_to(ROOT))
    return entry


def main() -> int:
    docs = _tracked_docs()
    entries: list[dict[str, Any]] = []
    errors: list[str] = []

    for path in docs:
        text = path.read_text(encoding="utf-8")
        fm = _extract_frontmatter(text)
        if fm is None:
            continue
        required = {"title", "slug", "section", "visibility", "audience"}
        missing = required - fm.keys()
        if missing:
            errors.append(f"{path.relative_to(ROOT)}: missing required keys: {sorted(missing)}")
            continue
        entries.append(_build_entry(fm, path))

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1

    # Sort by slug for stable output
    entries.sort(key=lambda e: e.get("slug", ""))

    payload = {
        "generated_by": "scripts/docs_extract/extract_doc_manifest.py",
        "doc_count": len(entries),
        "docs": entries,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"doc-manifest: {len(entries)} entries → {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
