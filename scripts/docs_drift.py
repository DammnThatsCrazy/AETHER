#!/usr/bin/env python3
"""Detect documentation drift against repo source files.

For every authored doc with ``source_files:`` frontmatter, this script:

  1. Verifies each ``source_files:`` path exists in the repo. A missing
     path is a hard error — it usually means a referenced module was
     renamed or deleted without updating the doc.

  2. If the doc also declares ``last_synced_commit: <sha>``, compares
     against ``git log <sha>..HEAD -- <source_files>``. Any commit in
     that range means the doc is stale.

By default the script exits 0 even when staleness is detected — this is
the advisory phase. ``--strict`` promotes staleness to a fatal error
for use in CI once authors are stamping ``last_synced_commit`` on docs
they own. Hard errors (missing source paths) ALWAYS fail; those
indicate broken metadata regardless of rollout phase.

Modes:
  python scripts/docs_drift.py             # walk + report (advisory)
  python scripts/docs_drift.py --strict    # exit 1 on any drift
  python scripts/docs_drift.py --update    # rewrite last_synced_commit
                                           # on every doc with source_files
                                           # to the current HEAD SHA

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
BACKLOG_PATH = ROOT / "config" / "docs_review_backlog.yaml"


def load_review_backlog(path: Path = BACKLOG_PATH) -> dict[str, dict]:
    """Load the documented review backlog: docs known-stale pending real review.

    The registry is the honest ledger for docs whose sources moved after their
    last genuine content review (mechanical restamps do not count). A listed
    doc's staleness is reported but does not fail --strict; an UNLISTED stale
    doc does. Entries are shrink-only: a listed doc that is no longer stale
    must be removed, which strict mode enforces. Every entry requires path,
    reason, and owner so no doc sits in the backlog anonymously.
    """
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = data.get("docs")
    if not isinstance(entries, list):
        raise SystemExit(f"error: {path} must contain a top-level 'docs' list")
    backlog: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not all(
            entry.get(k) for k in ("path", "reason", "owner")
        ):
            raise SystemExit(
                f"error: backlog entry needs path/reason/owner — bad entry: {entry!r}"
            )
        backlog[str(entry["path"])] = entry
    return backlog
DOCS_ROOT = ROOT / "docs"

SKIP_DIRS = {
    DOCS_ROOT / "archive",
    DOCS_ROOT / "_generated",
    DOCS_ROOT / "_templates",
    DOCS_ROOT / "diagrams",
    DOCS_ROOT / "examples",
    DOCS_ROOT / "source-of-truth",
}

# Managed by scripts/sync_docs.py; their freshness is enforced by
# repo_doctor's diff-after-sync check. last_synced_commit stamps on these
# are meaningless (commit 9b8116d removed them by hand after a stamp pass
# added them) — exclude them so --update cannot reintroduce the churn.
SYNC_MANAGED = {
    DOCS_ROOT / "AUTOMATION.md",
    DOCS_ROOT / "REPO-INDEX.md",
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
        if path in SYNC_MANAGED:
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


def commits_touching_after(declared: str, paths: list[str]) -> list[str] | None:
    """Return short SHAs of commits that touched any of `paths` after `declared`.

    Uses ``git log <declared>..HEAD -- <paths>``. Returns ``None`` when
    ``declared`` cannot be resolved in this clone. That case must NOT be
    treated as fresh: a stamp git cannot see (a pre-squash branch commit, a
    force-pushed-away SHA, or plain garbage) proves nothing about review
    recency, and treating it as clean quietly exempted the doc from drift
    detection forever — the exact fail-open this validator exists to prevent.
    The two answers a caller can act on are therefore "these commits came
    after the stamp" and "the stamp is unverifiable"; only a resolvable stamp
    with no newer commits is clean.
    """
    if not paths or not declared:
        return []
    cmd = ["git", "log", f"{declared}..HEAD", "--format=%h", "--"] + paths
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    if result.returncode != 0:
        return None
    return [line for line in result.stdout.splitlines() if line]


def latest_commit_touching_after(declared: str, paths: list[str]) -> str | None:
    """Return latest full SHA touching paths after declared, or None."""
    if not paths or not declared:
        return None
    result = subprocess.run(
        ["git", "log", "-1", f"{declared}..HEAD", "--format=%H", "--", *paths],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def is_ancestor(older: str, newer: str) -> bool:
    """Return True when older is the same as, or an ancestor of, newer."""
    if older == newer:
        return True
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", older, newer],
        cwd=ROOT,
    ).returncode == 0


def commit_touches_paths(sha: str, paths: list[str]) -> bool:
    """Return True when ``sha`` changes at least one path in ``paths``.

    A squash merge produces a new commit that contains the net changes from
    the review branch, while the branch's stamped SHA disappears from the
    target branch.  This helper lets the drift check recognize that final
    commit as the review boundary when it changed both the documented source
    and the source-linked doc together.
    """
    if not paths:
        return False
    result = subprocess.run(
        # `-m` makes this work for GitHub's synthetic PR merge commit too.
        # Without it, diff-tree reports no paths for a merge commit and the
        # squash/merge-safe boundary is treated as unverifiable even when the
        # final merge contains both the source and its reviewed document.
        ["git", "diff-tree", "-m", "--no-commit-id", "--name-only", "-r", sha, "--", *paths],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def squash_merge_reviewed_at_tip(doc_rel: str, source_paths: list[str]) -> bool:
    """Recognize a reviewed source/doc pair collapsed by a squash merge.

    The pre-merge ``last_synced_commit`` can be unreachable after squash
    merging.  It is safe to accept that boundary only when the current tip
    changed both the source and the doc; otherwise an unknown stamp remains a
    strict failure.
    """
    # A pull_request workflow commonly checks out a synthetic merge commit.
    # That tip may contain only the PR's follow-up changes, while the actual
    # squash merge that changed the source and authored doc is its first-parent
    # ancestor. Find the newest source-changing first-parent boundary and prove
    # that the same boundary changed this doc too. This avoids accepting an
    # arbitrary old merge merely because it once touched the same paths.
    source_tip = subprocess.run(
        ["git", "log", "--first-parent", "-1", "--format=%H", "HEAD", "--", *source_paths],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    if source_tip.returncode != 0:
        return False
    sha = source_tip.stdout.strip()
    return bool(sha) and commit_touches_paths(sha, source_paths) and commit_touches_paths(sha, [doc_rel])


def _commit_is_restamp_only(sha: str, doc_rel: str) -> bool:
    """True when the commit's change to this doc touches only its stamp line.

    A mechanical ``last_synced_commit`` bump is bookkeeping, not review — if it
    counted as review, any restamp (or typo edit) would silently clear real
    staleness, which is exactly the hole that hid the 87-doc review backlog.
    """
    proc = subprocess.run(
        ["git", "show", sha, "--format=", "--unified=0", "--", doc_rel],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return False
    changed = [
        line
        for line in proc.stdout.splitlines()
        if (line.startswith("+") or line.startswith("-"))
        and not line.startswith(("+++", "---"))
    ]
    return bool(changed) and all("last_synced_commit" in line for line in changed)


def doc_reviewed_after_sources(declared: str, doc_path: Path, source_paths: list[str]) -> bool:
    """Return True when the doc was REVIEWED in the same range at/after sources.

    This prevents false positives for PR commits that update source files and
    their reviewed source-linked docs in the same commit. Future source-only
    commits still become stale because their latest source commit will no longer
    be an ancestor of the latest doc commit in the range. A doc commit that only
    bumps ``last_synced_commit`` is not evidence of review and is skipped.
    """
    try:
        doc_rel = str(doc_path.relative_to(ROOT))
    except ValueError:
        doc_rel = str(doc_path)
    latest_source = latest_commit_touching_after(declared, source_paths)
    if not latest_source:
        return False
    proc = subprocess.run(
        ["git", "log", f"{declared}..HEAD", "--format=%H", "--", doc_rel],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return False
    doc_commits = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    latest_doc = next(
        (sha for sha in doc_commits if not _commit_is_restamp_only(sha, doc_rel)),
        None,
    )
    if not latest_doc:
        return False
    return is_ancestor(latest_source, latest_doc)


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
        if newer is None:
            if not squash_merge_reviewed_at_tip(str(rel), present_sources):
                stale = True
                detail = (
                    f"last_synced_commit={declared} cannot be resolved in this "
                    "clone, so review recency is unverifiable. Re-review the doc "
                    "against its source_files and restamp with a commit that "
                    "exists on the branch."
                )
        elif newer and not doc_reviewed_after_sources(declared, path, present_sources):
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


def head_sha() -> str | None:
    """Return the abbreviated SHA of the current HEAD, or None on error."""
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def stamp_doc(path: Path, sha: str) -> bool:
    """Write ``last_synced_commit: <sha>`` into the frontmatter of one doc.

    Returns True if the file was modified. No-op (returns False) if the
    doc has no frontmatter, no ``source_files`` block, or already has
    the correct ``last_synced_commit:`` line.
    """
    text = path.read_text(encoding="utf-8")
    fm = extract_frontmatter(text)
    if fm is None:
        return False
    if not fm.get("source_files"):
        return False
    if fm.get("last_synced_commit") == sha:
        return False

    # Locate the frontmatter block bounds (already known to start with `---\n`).
    end = text.find("\n---", 4)
    if end < 0:
        return False
    fm_text = text[4:end]
    rest = text[end:]  # starts with the trailing `\n---`

    # Quote the sha: an all-digit abbreviated hash (e.g. 1757948) would
    # otherwise YAML-parse as an int and fail frontmatter validation.
    new_line = f'last_synced_commit: "{sha}"'
    if "last_synced_commit:" in fm_text:
        # Replace the existing line.
        import re as _re
        fm_text = _re.sub(
            r"^last_synced_commit:.*$",
            new_line,
            fm_text,
            count=1,
            flags=_re.MULTILINE,
        )
    else:
        # Append after the last frontmatter line.
        fm_text = fm_text.rstrip() + "\n" + new_line + "\n"
        # Normalise — the closing `\n---` will be prefixed by stamped fm_text.
        fm_text = fm_text.rstrip("\n")

    path.write_text("---\n" + fm_text + rest, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 on any drift (default: missing paths only).",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help=(
            "Rewrite last_synced_commit: <HEAD> on every doc with "
            "source_files. Use after a focused authoring pass to stamp "
            "each updated doc."
        ),
    )
    args = parser.parse_args()

    if args.update:
        sha = head_sha()
        if not sha:
            print("error: cannot read HEAD SHA — is this a git repo?", file=sys.stderr)
            return 1
        # Only re-stamp docs whose source files have actually changed since their
        # current last_synced_commit. Stamping clean docs to HEAD is what causes
        # 60+ last_synced_commit conflicts on every rebase — both branches update
        # the same field to different SHAs on every docs-drift pass.
        backlog = load_review_backlog()
        updated = 0
        skipped = 0
        backlogged = 0
        for path in tracked_docs():
            report = check_doc(path)
            if report["stale"]:
                if report["path"] in backlog:
                    # A backlogged doc is cleared only by a real content
                    # review plus removal from the registry — stamping it
                    # here would mint exactly the false review claim the
                    # backlog exists to record.
                    backlogged += 1
                    continue
                if stamp_doc(path, sha):
                    updated += 1
                    print(f"  stamped {path.relative_to(ROOT)} -> {sha}")
            else:
                skipped += 1
        print(
            f"docs_drift --update: stamped {updated} docs at {sha} "
            f"({skipped} already clean, {backlogged} in the review backlog — "
            "review + remove from config/docs_review_backlog.yaml to clear)."
        )
        return 0

    backlog = load_review_backlog()
    reports = [check_doc(p) for p in tracked_docs()]

    missing_reports = [r for r in reports if r["missing_paths"]]
    stale_reports = [r for r in reports if r["stale"] and r["path"] not in backlog]
    backlogged_reports = [r for r in reports if r["stale"] and r["path"] in backlog]
    clean_count = (
        len(reports) - len(missing_reports) - len(stale_reports) - len(backlogged_reports)
    )

    # Shrink-only: a backlog entry whose doc is clean (someone reviewed it) or
    # untracked must be removed, or the registry rots into a permanent bypass.
    report_paths = {r["path"] for r in reports}
    stale_backlogged = {r["path"] for r in backlogged_reports}
    dead_entries = sorted(
        p for p in backlog
        if p not in stale_backlogged
    )

    print(
        f"docs_drift: {len(reports)} docs scanned, "
        f"{clean_count} clean, "
        f"{len(stale_reports)} stale (advisory), "
        f"{len(backlogged_reports)} in the documented review backlog, "
        f"{len(missing_reports)} with missing source paths."
    )

    if stale_reports:
        print()
        print("STALE (advisory):")
        for r in stale_reports:
            print(f"  - {r['path']}: {r['stale_detail']}")

    if backlogged_reports:
        print()
        print("REVIEW BACKLOG (documented in config/docs_review_backlog.yaml):")
        for r in backlogged_reports:
            print(f"  - {r['path']} (owner: {backlog[r['path']].get('owner')})")

    if dead_entries:
        print()
        print("BACKLOG ENTRIES TO REMOVE (doc reviewed/clean or no longer tracked):")
        for p in dead_entries:
            note = "untracked" if p not in report_paths else "no longer stale"
            print(f"  - {p} ({note})")

    if missing_reports:
        print()
        print("MISSING SOURCE PATHS (always fatal):")
        for r in missing_reports:
            for mp in r["missing_paths"]:
                print(f"  - {r['path']}: source_files entry {mp!r} does not exist")
        return 1

    if args.strict and (stale_reports or dead_entries):
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
