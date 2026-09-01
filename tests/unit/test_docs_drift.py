"""Unit tests for scripts/docs_drift.py.

Covers frontmatter extraction (positive, negative, malformed) and the
per-doc check that surfaces missing source paths.
"""

from __future__ import annotations

import importlib.util
import os
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


def test_check_doc_accepts_explicit_review_receipts(dd, tmp_path, monkeypatch):
    """A reviewed but intentionally unchanged page may record its receipt."""
    monkeypatch.setattr(dd, "commits_touching_after", lambda declared, paths: ["source123"])
    monkeypatch.setattr(dd, "doc_reviewed_after_sources", lambda *args: False)
    monkeypatch.setattr(dd, "reviewed_source_commits_cover", lambda *args: True)
    p = tmp_path / "doc.md"
    p.write_text(
        "---\n"
        "title: T\n"
        "source_files:\n"
        "  - README.md\n"
        "last_synced_commit: abc1234\n"
        "reviewed_source_commits:\n"
        "  - commit: source123\n"
        "    reason: source change is orthogonal\n"
        "---\n"
        "body\n"
    )
    r = dd.check_doc(p)
    assert r["stale"] is False


def test_reviewed_source_receipts_require_resolved_source_commit(dd, monkeypatch):
    """Receipt validation is fail-closed when a marker cannot be resolved."""
    monkeypatch.setattr(dd, "resolve_commit", lambda sha: None if sha == "missing1" else "a" * 40)
    monkeypatch.setattr(dd, "is_ancestor", lambda *args: True)
    monkeypatch.setattr(dd, "commit_touches_paths", lambda *args: True)
    assert dd.reviewed_source_commits_cover(
        "b" * 7,
        [{"commit": "missing1", "reason": "reviewed"}],
        ["README.md"],
        ["source123"],
    ) is False


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


def test_check_doc_accepts_unresolvable_stamp_when_squash_tip_reviews_source_and_doc(
    dd, tmp_path, monkeypatch
):
    """A squash merge may erase the stamped branch SHA, but the final tip can
    still contain the source change and the reviewed doc change together."""
    monkeypatch.setattr(dd, "commits_touching_after", lambda declared, paths: None)
    monkeypatch.setattr(dd, "squash_merge_reviewed_at_tip", lambda doc, sources: True)
    p = tmp_path / "doc.md"
    p.write_text(
        "---\n"
        "title: T\n"
        "source_files:\n"
        "  - README.md\n"
        "last_synced_commit: vanished123\n"
        "---\n"
        "body\n"
    )
    r = dd.check_doc(p)
    assert r["stale"] is False


def test_commit_touches_paths_supports_merge_commit_boundaries(dd, tmp_path, monkeypatch):
    """The final PR merge commit must be inspectable as a review boundary."""
    calls = []

    class Result:
        returncode = 0
        stdout = "docs/CICD.md\n.github/workflows/repo-health.yml\n"

    def fake_run(args, **kwargs):
        calls.append(args)
        return Result()

    monkeypatch.setattr(dd.subprocess, "run", fake_run)
    assert dd.commit_touches_paths("merge-sha", [".github/workflows/repo-health.yml"])
    assert "-m" in calls[0]


def test_unresolvable_stamp_uses_latest_first_parent_source_boundary(dd, monkeypatch):
    """A synthetic PR merge can point back to its squash merge ancestor."""
    calls = []

    class Result:
        returncode = 0
        stdout = "squash-boundary\n"

    def fake_run(args, **kwargs):
        calls.append(args)
        return Result()

    monkeypatch.setattr(dd.subprocess, "run", fake_run)
    monkeypatch.setattr(dd, "commit_touches_paths", lambda sha, paths: True)
    assert dd.squash_merge_reviewed_at_tip("docs/CICD.md", [".github/workflows/"])
    assert calls[0][:5] == ["git", "log", "--first-parent", "-1", "--format=%H"]


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


def test_restamp_only_commit_is_not_review(dd, tmp_path, monkeypatch):
    """A commit that only bumps last_synced_commit must not count as a review.

    This is the hole that hid the 87-doc backlog: any doc edit after the last
    source commit — including a mechanical restamp — cleared staleness.
    Constructed in a temp repo so the assertion never depends on how much of
    the real repo's history a CI checkout happens to include.
    """
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        subprocess.run(
            ["git", *args], cwd=repo, check=True, capture_output=True,
            env={
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
                "PATH": os.environ["PATH"],
            },
        )

    def head():
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
            capture_output=True, text=True,
        ).stdout.strip()

    doc = repo / "doc.md"
    git("init", "-q")
    doc.write_text('---\nlast_synced_commit: "aaa"\n---\nbody\n', encoding="utf-8")
    git("add", "doc.md")
    git("commit", "-qm", "initial")

    doc.write_text('---\nlast_synced_commit: "bbb"\n---\nbody\n', encoding="utf-8")
    git("commit", "-aqm", "restamp only")
    restamp_sha = head()

    doc.write_text('---\nlast_synced_commit: "bbb"\n---\nnew body\n', encoding="utf-8")
    git("commit", "-aqm", "content change")
    content_sha = head()

    monkeypatch.setattr(dd, "ROOT", repo)
    assert dd._commit_is_restamp_only(restamp_sha, "doc.md") is True
    assert dd._commit_is_restamp_only(content_sha, "doc.md") is False


def test_doc_content_mentioning_stamp_field_is_not_restamp_only(dd, tmp_path, monkeypatch):
    """A prose/table edit mentioning the stamp field is still a review."""
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
        "PATH": os.environ["PATH"],
    }
    def git(*args):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)
    git("init", "-q")
    doc = repo / "doc.md"
    doc.write_text("---\nlast_synced_commit: \"aaa\"\n---\nold\n")
    git("add", "doc.md")
    git("commit", "-qm", "initial")
    doc.write_text("---\nlast_synced_commit: \"aaa\"\n---\nTable mentions last_synced_commit: as metadata.\n")
    git("commit", "-aqm", "document stamp behavior")
    monkeypatch.setattr(dd, "ROOT", repo)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
        capture_output=True, text=True, env=env,
    ).stdout.strip()
    assert dd._commit_is_restamp_only(sha, "doc.md") is False


def test_receipt_only_commit_is_not_treated_as_content_review(dd, tmp_path, monkeypatch):
    """A metadata-only review receipt must go through receipt validation."""
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
        "PATH": os.environ["PATH"],
    }
    def git(*args):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)
    git("init", "-q")
    doc = repo / "doc.md"
    doc.write_text(
        "---\ntitle: T\nreviewed_source_commits:\n  - commit: abc1234\n    reason: old\n---\nbody\n",
        encoding="utf-8",
    )
    git("add", "doc.md")
    git("commit", "-qm", "initial")
    doc.write_text(
        "---\ntitle: T\nreviewed_source_commits:\n  - commit: def5678\n    reason: new\n---\nbody\n",
        encoding="utf-8",
    )
    git("commit", "-aqm", "receipt only")
    monkeypatch.setattr(dd, "ROOT", repo)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
        capture_output=True, text=True, env=env,
    ).stdout.strip()
    assert dd._commit_is_receipt_only(sha, "doc.md") is True


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
