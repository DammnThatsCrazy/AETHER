"""Unit tests for scripts/docs_extract/extract_events.py.

Covers the events.ts parser: union extraction with section comments,
record parsing, cross-validation (every event has a family + consent
purpose), and end-to-end correctness against the live source file.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "docs_extract" / "extract_events.py"
EVENTS_TS = ROOT / "packages" / "shared" / "events.ts"


@pytest.fixture(scope="module")
def ee():
    spec = importlib.util.spec_from_file_location("extract_events", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["extract_events"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def live_text():
    return EVENTS_TS.read_text(encoding="utf-8")


# --- Union parsing ----------------------------------------------------------


def test_parse_union_returns_members_in_order(ee):
    text = "export type Foo =\n  | 'a'\n  | 'b'\n  | 'c';\n"
    assert ee.parse_union(text, "Foo") == ["a", "b", "c"]


def test_parse_union_raises_on_missing_type(ee):
    with pytest.raises(ValueError, match="Bar"):
        ee.parse_union("export type Foo = | 'a';", "Bar")


def test_parse_union_with_section_comments_associates_groups(ee):
    text = (
        "export type Foo =\n"
        "  // Section A\n"
        "  | 'a1'\n"
        "  | 'a2'\n"
        "  // Section B\n"
        "  | 'b1';\n"
    )
    pairs = ee.parse_union_with_section_comments(text, "Foo")
    assert pairs == [
        ("a1", "Section A"),
        ("a2", "Section A"),
        ("b1", "Section B"),
    ]


def test_parse_union_with_no_comments(ee):
    text = "export type Foo =\n  | 'x'\n  | 'y';\n"
    pairs = ee.parse_union_with_section_comments(text, "Foo")
    assert pairs == [("x", ""), ("y", "")]


# --- Record parsing ---------------------------------------------------------


def test_parse_record_basic(ee):
    text = (
        "export const FOO: Record<string, string> = {\n"
        "  a: 'one',\n"
        "  b: 'two',\n"
        "};\n"
    )
    assert ee.parse_record(text, "FOO") == {"a": "one", "b": "two"}


def test_parse_record_with_quoted_keys(ee):
    text = (
        "export const FOO: Record<EventType, string> = {\n"
        "  'payment_initiated': 'commerce',\n"
        "  'agent_task': 'agent',\n"
        "};\n"
    )
    result = ee.parse_record(text, "FOO")
    assert result == {"payment_initiated": "commerce", "agent_task": "agent"}


def test_parse_record_raises_on_missing(ee):
    text = "export const FOO: Record<string, string> = { a: 'x' };"
    with pytest.raises(ValueError, match="BAR"):
        ee.parse_record(text, "BAR")


# --- End-to-end against the live source -----------------------------------


def test_live_extract_has_canonical_families(ee, live_text):
    payload = ee.build_payload(live_text)
    assert payload["families"] == [
        "core", "identity", "consent", "commerce", "wallet", "agent", "x402",
    ]


def test_live_extract_every_event_has_family_and_consent(ee, live_text):
    payload = ee.build_payload(live_text)
    for ev in payload["events"]:
        assert ev["family"], f"event {ev['name']} missing family"
        assert ev["consent_purpose"], f"event {ev['name']} missing consent_purpose"


def test_live_extract_includes_known_events(ee, live_text):
    payload = ee.build_payload(live_text)
    names = {ev["name"] for ev in payload["events"]}
    # Sample of canonical events that must always be present.
    for required in [
        "track", "page", "identify", "consent", "conversion",
        "payment_initiated", "wallet", "agent_task", "x402_payment",
    ]:
        assert required in names, f"canonical event {required!r} missing"


def test_live_extract_consent_purposes_subset_of_canonical(ee, live_text):
    payload = ee.build_payload(live_text)
    canonical = {"analytics", "marketing", "commerce", "web3", "agent"}
    actual = set(payload["consent_purposes"])
    assert actual <= canonical, f"unexpected consent purposes: {actual - canonical}"


def test_build_payload_rejects_missing_event_family(ee):
    """If a future events.ts forgets to map an event type, raise loudly."""
    bad = (
        "export type EventType =\n  | 'a'\n  | 'b';\n"
        "export type EventFamily = | 'core';\n"
        "export const EVENT_FAMILY: Record<EventType, EventFamily> = {\n"
        "  a: 'core',\n"
        "};\n"
        "export const EVENT_CONSENT_PURPOSE: Record<EventType, string> = {\n"
        "  a: 'analytics', b: 'analytics',\n"
        "};\n"
    )
    with pytest.raises(ValueError, match="EVENT_FAMILY missing"):
        ee.build_payload(bad)
