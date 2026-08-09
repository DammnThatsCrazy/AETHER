"""Tests for the credential-leak sweep (ADR-008 D7/D8) — fail-closed D8 sweep.

The leak detector is the final gate over synthesis content and citation
excerpts: a synthesis result must never carry credential-shaped material into
downstream consumers. All scans are deterministic substring/position matches
(no model calls), and ``[]`` means clean.
"""

from __future__ import annotations

from services.model_runtime.verification.leaks import (
    LEAK_MARKERS,
    LeakHit,
    SecretLeakDetector,
)


def _detector() -> SecretLeakDetector:
    return SecretLeakDetector()


def _raises(exc_type, call):
    """Assert that ``call()`` raises ``exc_type``, using only plain asserts."""
    try:
        call()
    except exc_type:
        return
    raise AssertionError(f"expected {exc_type.__name__} to be raised")


# ---------------------------------------------------------------------------
# Clean text
# ---------------------------------------------------------------------------


def test_clean_text_returns_no_hits():
    assert _detector().detect("the synthesis result is fully grounded") == []


def test_empty_string_returns_no_hits():
    assert _detector().detect("") == []
    assert _detector().is_clean("") is True


# ---------------------------------------------------------------------------
# Single marker detection
# ---------------------------------------------------------------------------


def test_each_marker_detected_once():
    detector = _detector()
    for marker in LEAK_MARKERS:
        text = f"prefix {marker} suffix"
        hits = detector.detect(text)
        assert hits == [LeakHit(marker=marker, position=7)]


def test_sk_marker_at_position_zero():
    assert _detector().detect("sk-abc123") == [LeakHit(marker="sk-", position=0)]


def test_marker_in_citation_excerpt_body():
    text = "the retrieved record references Authorization: Bearer token."
    hits = _detector().detect(text)
    markers = {hit.marker for hit in hits}
    assert "Authorization:" in markers
    assert "Bearer " in markers


# ---------------------------------------------------------------------------
# Multiple different markers
# ---------------------------------------------------------------------------


def test_multiple_different_markers_all_reported():
    text = "key=value and sk-live-99 plus AKIAABCDEF and eyJheader"
    hits = _detector().detect(text)
    markers = {hit.marker for hit in hits}
    assert markers == {"key=", "sk-", "AKIA", "eyJ"}
    # Marker order follows LEAK_MARKERS declaration order — deterministic.
    assert [hit.marker for hit in hits] == ["sk-", "AKIA", "key=", "eyJ"]


# ---------------------------------------------------------------------------
# Same marker repeated
# ---------------------------------------------------------------------------


def test_same_marker_twice_reports_only_first():
    text = "sk-first and sk-second"
    hits = _detector().detect(text)
    assert hits == [LeakHit(marker="sk-", position=0)]


def test_same_marker_ignored_after_other_marker():
    text = "AKIA hits, then AKIA again, then sk-one"
    hits = _detector().detect(text)
    markers = {hit.marker for hit in hits}
    assert markers == {"AKIA", "sk-"}
    # AKIA reported once, at its first occurrence.
    akia = next(hit for hit in hits if hit.marker == "AKIA")
    assert akia.position == 0


# ---------------------------------------------------------------------------
# Case insensitivity
# ---------------------------------------------------------------------------


def test_akia_detected_lowercased():
    assert _detector().detect("akiaAQID...and more") == [LeakHit(marker="AKIA", position=0)]


def test_bearer_detected_uppercased():
    assert _detector().detect("call with BEARER abc123") == [LeakHit(marker="Bearer ", position=10)]


def test_mixed_case_detected():
    text = "SK-live + bEaReR + EyJ header"
    markers = {hit.marker for hit in _detector().detect(text)}
    assert markers == {"sk-", "Bearer ", "eyJ"}


# ---------------------------------------------------------------------------
# No false positives on benign text
# ---------------------------------------------------------------------------


def test_no_false_positive_on_keychain():
    # "keychain" contains "key" but not "key=" — must stay clean.
    assert _detector().detect("the mac keychain unlock happened") == []


def test_no_false_positive_on_secretly():
    # "secretly" contains "secret" but not "secret=" — must stay clean.
    assert _detector().detect("they secretly updated the playbook") == []


def test_no_false_positive_on_benign_paragraph():
    text = (
        "Synthesis grounded in retrieved evidence. The stakeholder's "
        "keychain note and the secret keeper were both mentioned, and "
        "authorization flows were discussed in general terms."
    )
    assert _detector().detect(text) == []
    assert _detector().is_clean(text) is True


# ---------------------------------------------------------------------------
# is_clean mirror
# ---------------------------------------------------------------------------


def test_is_clean_mirrors_detect():
    detector = _detector()
    assert detector.is_clean("clean grounded text") is True
    assert detector.is_clean("sk-leaked") is False
    assert detector.is_clean("-----BEGIN PRIVATE KEY-----") is False
    assert detector.is_clean("X-Api-Key: abc") is False
    assert detector.is_clean("password=hunter2") is False


# ---------------------------------------------------------------------------
# Position correctness
# ---------------------------------------------------------------------------


def test_position_accounts_for_prefix():
    text = "the caller typed sk-live before anything else"
    hits = _detector().detect(text)
    assert hits == [LeakHit(marker="sk-", position=17)]
    assert text[17:20] == "sk-"


def test_position_points_at_original_case_not_lowered():
    # "BEARER" is uppercase at index 5; the reported position is from the
    # ORIGINAL string, not a lowercased copy.
    text = "call BEARER now"
    hits = _detector().detect(text)
    assert hits == [LeakHit(marker="Bearer ", position=5)]
    assert text[5 : 5 + len("Bearer ")] == "BEARER "


def test_positions_reported_for_each_distinct_marker():
    text = "sk-one | -----BEGIN block | key=opaque | eyJj"
    hits = _detector().detect(text)
    assert text[0:3] == "sk-"
    by_marker = {hit.marker: hit.position for hit in hits}
    assert by_marker["sk-"] == text.find("sk-")
    assert by_marker["-----BEGIN"] == text.find("-----BEGIN")
    assert by_marker["key="] == text.find("key=")
    assert by_marker["eyJ"] == text.find("eyJ")


# ---------------------------------------------------------------------------
# Contract shape
# ---------------------------------------------------------------------------


def test_public_exports_exact():
    import services.model_runtime.verification.leaks as leaks_module

    assert leaks_module.__all__ == [
        "LEAK_MARKERS",
        "LeakHit",
        "SecretLeakDetector",
    ]


def test_markers_declaration_order():
    assert LEAK_MARKERS == (
        "sk-",
        "AKIA",
        "Bearer ",
        "-----BEGIN",
        "Authorization:",
        "X-Api-Key:",
        "password=",
        "secret=",
        "key=",
        "eyJ",
    )
    # Every declared marker must actually be detectable.
    detector = _detector()
    for marker in LEAK_MARKERS:
        assert detector.detect(marker) == [LeakHit(marker=marker, position=0)]


def test_leak_hit_is_plain_frozen_dataclass():
    import dataclasses

    assert dataclasses.is_dataclass(LeakHit)
    hit = LeakHit(marker="sk-", position=0)
    _raises(dataclasses.FrozenInstanceError, lambda: setattr(hit, "marker", "AKIA"))
