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
