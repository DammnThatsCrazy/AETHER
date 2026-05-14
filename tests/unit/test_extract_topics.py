"""Unit tests for scripts/docs_extract/extract_topics.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "docs_extract" / "extract_topics.py"
EVENTS_PY = (
    ROOT
    / "Backend Architecture"
    / "aether-backend"
    / "shared"
    / "events"
    / "events.py"
)


@pytest.fixture(scope="module")
def et():
    spec = importlib.util.spec_from_file_location("extract_topics", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["extract_topics"] = module
    spec.loader.exec_module(module)
    return module


# --- synthetic input ------------------------------------------------------


def _wrap_topic_class(body: str) -> str:
    return (
        "from enum import Enum\n"
        "class Topic(str, Enum):\n"
        f"{body}"
    )


def test_basic_section_capture(et):
    src = _wrap_topic_class(
        "    # Foo\n"
        '    A = "a"\n'
        '    B = "b"\n'
        "    # Bar\n"
        '    C = "c"\n'
    )
    payload = et.build_payload(src)
    assert [s["name"] for s in payload["sections"]] == ["Foo", "Bar"]
    assert payload["sections"][0]["topics"] == [
        {"member": "A", "value": "a"},
        {"member": "B", "value": "b"},
    ]
    assert payload["sections"][1]["topics"] == [{"member": "C", "value": "c"}]


def test_inline_trailing_comment_does_not_start_new_section(et):
    """Regression: trailing inline comments must not be detected as
    section headers — only pure-comment lines qualify."""
    src = _wrap_topic_class(
        "    # Foo\n"
        '    A = "a"  # Reserved — not yet published\n'
        '    B = "b"  # Reserved — not yet published\n'
    )
    payload = et.build_payload(src)
    assert [s["name"] for s in payload["sections"]] == ["Foo"]
    assert len(payload["sections"][0]["topics"]) == 2


def test_multiline_comment_block_uses_topmost(et):
    """When several comment lines stack above an assignment, the topmost
    one is the section header — subordinate notes are skipped."""
    src = _wrap_topic_class(
        "    # ── Profile 360 (additive) ─\n"
        "    # All new topics; no existing topic is renamed.\n"
        '    A = "a"\n'
    )
    payload = et.build_payload(src)
    assert payload["sections"][0]["name"].startswith("── Profile 360")


def test_blank_lines_between_members_do_not_break_section(et):
    src = _wrap_topic_class(
        "    # Foo\n"
        '    A = "a"\n'
        "\n"
        '    B = "b"\n'
    )
    payload = et.build_payload(src)
    assert len(payload["sections"]) == 1
    assert [t["member"] for t in payload["sections"][0]["topics"]] == ["A", "B"]


def test_duplicate_values_raise(et):
    src = _wrap_topic_class(
        "    # Foo\n"
        '    A = "x"\n'
        '    B = "x"\n'
    )
    with pytest.raises(et.ParseError, match="duplicate"):
        et.build_payload(src)


def test_missing_topic_class_raises(et):
    with pytest.raises(et.ParseError, match="Topic"):
        et.build_payload("class Other: pass")


def test_empty_topic_class_raises(et):
    src = (
        "from enum import Enum\n"
        "class Topic(str, Enum):\n"
        "    pass\n"
    )
    with pytest.raises(et.ParseError, match="empty"):
        et.build_payload(src)


# --- end-to-end against the real source ---------------------------------


def test_real_source_emits_many_topics(et):
    text = EVENTS_PY.read_text(encoding="utf-8")
    payload = et.build_payload(text)
    # README claims 40+; the real number is ~94 across 17 sections.
    assert len(payload["all_topics"]) > 40
    assert len(payload["sections"]) >= 10


def test_real_source_includes_canonical_topics(et):
    text = EVENTS_PY.read_text(encoding="utf-8")
    payload = et.build_payload(text)
    members = {t["member"] for t in payload["all_topics"]}
    for required in [
        "SDK_EVENTS_RAW",
        "IDENTITY_RESOLVED",
        "CONSENT_UPDATED",
        "DATA_SUBJECT_REQUEST",
        "AGENT_DISCOVERY",
        "PAYMENT_SENT",
        "X402_PAYMENT_CAPTURED",
    ]:
        assert required in members, f"canonical topic {required} missing"


def test_real_source_topic_values_use_aether_namespace(et):
    text = EVENTS_PY.read_text(encoding="utf-8")
    payload = et.build_payload(text)
    for t in payload["all_topics"]:
        assert t["value"].startswith("aether."), (
            f"topic {t['member']} value {t['value']!r} not in aether.* namespace"
        )


def test_real_source_no_duplicate_values(et):
    text = EVENTS_PY.read_text(encoding="utf-8")
    payload = et.build_payload(text)
    values = [t["value"] for t in payload["all_topics"]]
    assert len(values) == len(set(values))
