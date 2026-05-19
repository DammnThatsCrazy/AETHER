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


def test_commits_touching_after_returns_empty_for_unknown_sha(dd):
    """If the declared SHA isn't in git history, drift check should
    skip rather than crash (graceful degradation)."""
    result = dd.commits_touching_after("zzzzzzz", ["README.md"])
    assert result == []


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
