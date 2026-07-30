"""Unit tests for scripts/docs_drift.py.

Covers frontmatter extraction (positive, negative, malformed) and the
per-doc check that surfaces missing source paths.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "docs_drift.py"


@pytest.fixture(scope="module")
def dd():
    spec = importlib.util.spec_from_file_location("docs_drift", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["docs_drift"] = module
    spec.loader.exec_module(module)
    return module


# --- extract_frontmatter ----------------------------------------------------


def test_extract_frontmatter_basic(dd):
    text = "---\ntitle: T\nslug: s\n---\n\nbody"
    assert dd.extract_frontmatter(text) == {"title": "T", "slug": "s"}


def test_extract_frontmatter_returns_none_when_no_block(dd):
    assert dd.extract_frontmatter("body only") is None


def test_extract_frontmatter_returns_none_when_unterminated(dd):
    assert dd.extract_frontmatter("---\nfoo: bar\nno end") is None


def test_extract_frontmatter_returns_none_on_yaml_error(dd):
    # Malformed YAML in body — graceful skip, not raise.
    assert dd.extract_frontmatter("---\n: : :\n---\n") is None


def test_extract_frontmatter_returns_none_on_non_mapping(dd):
    # Frontmatter parses to a list, not a dict.
    assert dd.extract_frontmatter("---\n- one\n- two\n---\n") is None


# --- check_doc --------------------------------------------------------------


def test_check_doc_with_no_frontmatter(dd, tmp_path):
    p = tmp_path / "x.md"
    p.write_text("just body")
    r = dd.check_doc(p)
    assert r["missing_paths"] == []
    assert r["stale"] is False


def test_check_doc_with_no_source_files(dd, tmp_path):
    p = tmp_path / "x.md"
    p.write_text("---\ntitle: T\n---\nbody")
    r = dd.check_doc(p)
    assert r["missing_paths"] == []
    assert r["stale"] is False


def test_check_doc_finds_missing_source_path(dd, tmp_path):
    p = tmp_path / "x.md"
    p.write_text(
        "---\n"
        "title: T\n"
        "source_files:\n"
        "  - some/nonexistent/path.py\n"
        "---\n"
        "body\n"
    )
    r = dd.check_doc(p)
    assert "some/nonexistent/path.py" in r["missing_paths"]


def test_check_doc_real_doc_with_real_sources(dd):
    """Smoke test: a real authored doc with valid source_files reports clean."""
    p = ROOT / "docs" / "SDK-WEB.md"
    if not p.exists():
        pytest.skip("SDK-WEB.md not present")
    r = dd.check_doc(p)
    assert r["missing_paths"] == []


# --- staleness comparison logic -------------------------------------------


def test_check_doc_not_stale_when_no_commits_after_sync(dd, tmp_path, monkeypatch):
    """A freshly-stamped doc whose sources haven't changed since the stamp
    must NOT be flagged stale, even if the stamp doesn't match the
    most-recent commit that ever touched the sources.

    Regression for codex review of PR #70: the equality check
    ``latest == declared`` was incorrect.
    """
    monkeypatch.setattr(dd, "commits_touching_after", lambda declared, paths: [])
    p = tmp_path / "doc.md"
    p.write_text(
        "---\n"
        "title: T\n"
        "source_files:\n"
        "  - README.md\n"
        "last_synced_commit: abc1234\n"
        "---\n"
        "body\n"
    )
    r = dd.check_doc(p)
    assert r["stale"] is False
    assert r["missing_paths"] == []


def test_check_doc_stale_when_commits_after_sync(dd, tmp_path, monkeypatch):
    """Any commit that touched a source AFTER last_synced_commit means
    the doc must be reviewed."""
    monkeypatch.setattr(
        dd,
        "commits_touching_after",
        lambda declared, paths: ["new1234", "new5678"],
    )
    p = tmp_path / "doc.md"
    p.write_text(
        "---\n"
        "title: T\n"
        "source_files:\n"
        "  - README.md\n"
        "last_synced_commit: abc1234\n"
        "---\n"
        "body\n"
    )
    r = dd.check_doc(p)
    assert r["stale"] is True
    assert "new1234" in r["stale_detail"]
    assert "abc1234" in r["stale_detail"]


def test_commits_touching_after_returns_none_for_unknown_sha(dd):
    """An unresolvable declared SHA must be distinguishable from "no drift".

    The previous form of this test pinned the opposite: an unknown stamp
    returned [] and was scored clean, which permanently exempted any doc with
    a vanished (pre-squash) or garbage stamp from drift detection — measured
    at 78 of 368 source-linked docs on this repo. None is the "unverifiable"
    answer the caller turns into a stale finding.
    """
    result = dd.commits_touching_after("zzzzzzz", ["README.md"])
    assert result is None


def test_commits_touching_after_returns_empty_for_no_paths(dd):
    assert dd.commits_touching_after("abc1234", []) == []


# --- stamp_doc / --update mode -------------------------------------------


def test_stamp_doc_adds_last_synced_commit_when_missing(dd, tmp_path):
    p = tmp_path / "doc.md"
    p.write_text(
        "---\n"
        "title: T\n"
        "source_files:\n"
        "  - README.md\n"
        "---\n"
        "body\n"
    )
    changed = dd.stamp_doc(p, "abc1234")
    assert changed is True
    fm = dd.extract_frontmatter(p.read_text())
    assert fm["last_synced_commit"] == "abc1234"


def test_stamp_doc_replaces_existing_last_synced_commit(dd, tmp_path):
    p = tmp_path / "doc.md"
    p.write_text(
        "---\n"
        "title: T\n"
        "source_files:\n"
        "  - README.md\n"
        "last_synced_commit: old1234\n"
        "---\n"
        "body\n"
    )
    changed = dd.stamp_doc(p, "new5678")
    assert changed is True
    fm = dd.extract_frontmatter(p.read_text())
    assert fm["last_synced_commit"] == "new5678"


def test_stamp_doc_is_idempotent_when_sha_matches(dd, tmp_path):
    p = tmp_path / "doc.md"
    p.write_text(
        "---\n"
        "title: T\n"
        "source_files:\n"
        "  - README.md\n"
        "last_synced_commit: abc1234\n"
        "---\n"
        "body\n"
    )
    before = p.read_text()
    changed = dd.stamp_doc(p, "abc1234")
    assert changed is False
    assert p.read_text() == before


def test_stamp_doc_skips_docs_with_no_source_files(dd, tmp_path):
    p = tmp_path / "doc.md"
    p.write_text("---\ntitle: T\n---\nbody\n")
    before = p.read_text()
    changed = dd.stamp_doc(p, "abc1234")
    assert changed is False
    assert p.read_text() == before


def test_stamp_doc_skips_docs_with_no_frontmatter(dd, tmp_path):
    p = tmp_path / "doc.md"
    p.write_text("just body, no fm")
    before = p.read_text()
    changed = dd.stamp_doc(p, "abc1234")
    assert changed is False
    assert p.read_text() == before


def test_stamp_doc_preserves_body_content(dd, tmp_path):
    p = tmp_path / "doc.md"
    body = "\n# Title\n\nSome content here.\n\n## Section\n\nMore.\n"
    p.write_text(
        "---\n"
        "title: T\n"
        "source_files:\n"
        "  - README.md\n"
        "---" + body
    )
    dd.stamp_doc(p, "abc1234")
    assert body in p.read_text()


def test_head_sha_returns_string_in_real_repo(dd):
    sha = dd.head_sha()
    assert sha is not None
    assert len(sha) >= 7
    assert all(c in "0123456789abcdef" for c in sha)


# ── Review backlog registry + restamp-only heuristic ─────────────────────────


def test_restamp_only_commit_is_not_review(dd):
    """A commit that only bumps last_synced_commit must not count as a review.

    This is the hole that hid the 87-doc backlog: any doc edit after the last
    source commit — including a mechanical restamp — cleared staleness.
    """
    import subprocess

    log = subprocess.run(
        ["git", "log", "--format=%H", "-40", "--", "docs"],
        capture_output=True, text=True, cwd=dd.ROOT,
    ).stdout.split()
    # Find a real restamp-only commit on this branch to assert against; the
    # branch's stamp commits are docs-only stamp bumps.
    found_restamp = None
    found_content = None
    for sha in log:
        names = subprocess.run(
            ["git", "show", sha, "--format=", "--name-only"],
            capture_output=True, text=True, cwd=dd.ROOT,
        ).stdout.split()
        for name in names:
            if not name.startswith("docs/") or not name.endswith(".md"):
                continue
            if dd._commit_is_restamp_only(sha, name):
                found_restamp = (sha, name)
            else:
                found_content = (sha, name)
        if found_restamp and found_content:
            break
    assert found_restamp, "expected at least one restamp-only doc commit in history"
    assert found_content, "expected at least one content doc commit in history"
    sha, name = found_restamp
    assert dd._commit_is_restamp_only(sha, name) is True
    sha, name = found_content
    assert dd._commit_is_restamp_only(sha, name) is False


def test_backlog_loader_rejects_anonymous_entries(dd, tmp_path):
    bad = tmp_path / "backlog.yaml"
    bad.write_text("docs:\n  - path: docs/X.md\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        dd.load_review_backlog(bad)


def test_backlog_loader_returns_entries_by_path(dd, tmp_path):
    good = tmp_path / "backlog.yaml"
    good.write_text(
        "docs:\n"
        "  - path: docs/X.md\n"
        "    reason: sources moved\n"
        "    owner: docs@aether\n",
        encoding="utf-8",
    )
    backlog = dd.load_review_backlog(good)
    assert set(backlog) == {"docs/X.md"}
    assert backlog["docs/X.md"]["owner"] == "docs@aether"


def test_real_backlog_registry_loads_and_matches_tracked_docs(dd):
    """Every registered backlog entry must reference a tracked doc."""
    backlog = dd.load_review_backlog()
    tracked = {str(p.relative_to(dd.ROOT)) for p in dd.tracked_docs()}
    unknown = sorted(p for p in backlog if p not in tracked)
    assert unknown == [], f"backlog entries for untracked docs: {unknown}"
