"""The README repository map must describe the tree that actually exists.

It drifted silently: tracked root folders (.artifacts/, .claude/, .codex/,
.devcontainer/) and folders under services/api/, tests/, docs/ and
packages/sdk/ were missing. Every folder under the mapped parents (and every
allowed root folder) must appear in its section of the map, and every folder
the map names must exist.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Parents whose immediate folders the map lists in full.
MAPPED_PARENTS = ("apps", "packages", "packages/sdk", "packages/ui", "services",
                  "services/api", "infra", "tests", "docs")
TOKEN = re.compile(r"(?<![\w.-])([.\w-]+)/(?![\w])")


def _map_lines() -> list[str]:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    block = text[text.index("## Repository map"):].split("```text\n", 1)[1].split("```", 1)[0]
    # Skip 'aether/' and the bare '│' spacer lines.
    return [line for line in block.splitlines()[1:] if any(ch.isalnum() for ch in line)]


def _depth(line: str) -> int:
    """0 for root entries ('├── apps/'), +1 per four-column tree level."""
    return next(i for i, ch in enumerate(line) if ch.isalnum() or ch in "._(") // 4 - 1


def _section_tokens(parent: str) -> set[str]:
    """Tokens on the parent's own line and on the deeper lines beneath it."""
    lines = _map_lines()
    names = parent.split("/")
    start, depth = 0, -1
    for name in names:  # walk down the tree, one level per path segment
        for i in range(start, len(lines)):
            if _depth(lines[i]) == depth + 1 and re.search(rf"(?<![\w.-]){re.escape(name)}/", lines[i]):
                start, depth = i, depth + 1
                break
        else:
            raise AssertionError(f"README repository map has no entry for {parent}/")
    section = [lines[start]]
    for line in lines[start + 1:]:
        if _depth(line) <= depth:
            break
        section.append(line)
    return {t for line in section for t in TOKEN.findall(line)}


def _tracked_dirs(parent: str = "") -> set[str]:
    ref = f"HEAD:{parent}" if parent else "HEAD"
    out = subprocess.run(["git", "ls-tree", "-d", "--name-only", ref],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return {line for line in out.splitlines() if line}


def test_every_folder_under_mapped_parents_is_listed():
    unlisted = sorted(f"{parent}/{d}" for parent in MAPPED_PARENTS
                      for d in _tracked_dirs(parent) if d not in _section_tokens(parent))
    assert not unlisted, f"README repository map is missing folders: {unlisted}"


def test_every_allowed_root_folder_is_listed():
    spec = importlib.util.spec_from_file_location("validate_root_layout", ROOT / "scripts/validate_root_layout.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    top = {t for line in _map_lines() if _depth(line) == 0 for t in TOKEN.findall(line)}
    missing = sorted(d for d in module.ALLOWED_ROOT_DIRS if d not in top)
    assert not missing, f"README repository map is missing root folders: {missing}"


def test_every_mapped_folder_exists():
    known = _tracked_dirs() | {d for parent in MAPPED_PARENTS for d in _tracked_dirs(parent)}
    named = {t for line in _map_lines() for t in TOKEN.findall(line)}
    # Paths quoted inside descriptions (e.g. packages/shared/contracts/) are
    # checked as paths, not as single folder names.
    quoted = {m for line in _map_lines() for m in re.findall(r"\(([\w./-]+)/\)", line)}
    ghosts = sorted(n for n in named if n not in known and not any(q.endswith(n) for q in quoted))
    assert not ghosts, f"README repository map names folders that do not exist: {ghosts}"
    missing_paths = sorted(q for q in quoted if not (ROOT / q).is_dir())
    assert not missing_paths, f"README repository map quotes paths that do not exist: {missing_paths}"
