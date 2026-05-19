"""Unit tests for scripts/docs_extract/extract_env.py.

Covers the env-file parser: section detection, var capture (with and
without descriptions), required-in-production marker, blank values,
and idempotent output ordering.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "docs_extract" / "extract_env.py"


@pytest.fixture(scope="module")
def ee():
    spec = importlib.util.spec_from_file_location("extract_env", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["extract_env"] = module
    spec.loader.exec_module(module)
    return module


def test_parses_single_section_with_single_var(ee):
    text = "# === Foo ===\nBAR=baz\n"
    categories = ee.parse_env_example(text)
    assert categories == [{
        "name": "Foo",
        "vars": [{
            "name": "BAR",
            "default": "baz",
            "description": "",
            "required_in_production": False,
        }],
    }]


def test_captures_inline_description(ee):
    text = "# === Foo ===\nBAR=baz  # describes BAR\n"
    categories = ee.parse_env_example(text)
    assert categories[0]["vars"][0]["description"] == "describes BAR"


def test_required_in_production_marker(ee):
    text = "# === Auth ===\nSECRET=  # [REQUIRED IN PRODUCTION]\n"
    var = ee.parse_env_example(text)[0]["vars"][0]
    assert var["required_in_production"] is True
    assert var["description"] == ""  # marker stripped out


def test_required_marker_with_extra_description(ee):
    text = (
        "# === Auth ===\n"
        "TOKEN=  # [REQUIRED IN PRODUCTION] used by gateway\n"
    )
    var = ee.parse_env_example(text)[0]["vars"][0]
    assert var["required_in_production"] is True
    assert var["description"] == "used by gateway"


def test_blank_default_is_empty_string(ee):
    text = "# === Foo ===\nEMPTY=\n"
    var = ee.parse_env_example(text)[0]["vars"][0]
    assert var["default"] == ""


def test_multiple_sections_in_order(ee):
    text = (
        "# === First ===\n"
        "A=1\n"
        "# === Second ===\n"
        "B=2\n"
        "# === Third ===\n"
        "C=3\n"
    )
    categories = ee.parse_env_example(text)
    assert [c["name"] for c in categories] == ["First", "Second", "Third"]


def test_comment_block_between_sections_ignored(ee):
    text = (
        "# === Foo ===\n"
        "# this is a long explanatory comment\n"
        "# spanning multiple lines\n"
        "FOO=bar\n"
    )
    categories = ee.parse_env_example(text)
    assert categories[0]["vars"] == [{
        "name": "FOO",
        "default": "bar",
        "description": "",
        "required_in_production": False,
    }]


def test_malformed_line_skipped(ee):
    text = (
        "# === Foo ===\n"
        "not a var\n"
        "FOO=bar\n"
    )
    var = ee.parse_env_example(text)[0]["vars"][0]
    assert var["name"] == "FOO"


def test_header_section_used_before_first_marker(ee):
    text = "PRE=value\n# === Foo ===\nFOO=bar\n"
    categories = ee.parse_env_example(text)
    assert categories[0]["name"] == "Header"
    assert categories[0]["vars"][0]["name"] == "PRE"


def test_real_env_example_is_parseable(ee):
    """End-to-end smoke: the actual repo .env.example produces categories."""
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    categories = ee.parse_env_example(text)
    assert len(categories) > 5
    # At least one required-in-production var declared
    assert any(
        v["required_in_production"]
        for c in categories
        for v in c["vars"]
    )
