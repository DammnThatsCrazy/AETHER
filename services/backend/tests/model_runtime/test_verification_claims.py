"""Claim-extraction tests (ADR-008 D7, Commit 10-B).

Plain asserts only: no ``pytest.raises``, no fixture/mock libraries.
``_raises`` is the single tiny helper, so this suite runs identically under
the minimal test runtime used by some CI environments.

Concurrency / gating: the sibling ``verification/models.py`` (Commit 10-A)
lands in parallel. It is importor-skipped so this suite passes (as a skip)
until it is importable; once ``models.py`` is importable, ``claims.py`` — which
imports ``ClaimStatement`` from it — is importable too and the whole suite runs
against the real model contract.
"""

from __future__ import annotations

import pytest

# The sibling models module (Commit 10-A) may land concurrently with this
# suite; until it is importable the whole suite skips.
pytest.importorskip("services.model_runtime.verification.models")

import services.model_runtime.verification.claims as claims_module  # noqa: E402 - after importorskip guard
from services.model_runtime.verification.claims import (  # noqa: E402
    ClaimExtractionError,
    ClaimExtractor,
    MIN_CLAIM_CHARS,
)
from services.model_runtime.verification.models import (  # noqa: E402
    ClaimStatement,
    VerificationUnsafe,
)


def _raises(exc_type, func):
    """Assert that calling func() raises exc_type (no pytest imports needed)."""
    try:
        func()
    except exc_type:
        return
    except Exception as err:
        raise AssertionError(
            f"expected {exc_type.__name__} but got {type(err).__name__}: {err}"
        ) from err
    raise AssertionError(f"expected {exc_type.__name__} to be raised")


def _texts(claims):
    return [claim.text for claim in claims]


def test_splits_on_period_space_boundary():
    claims = ClaimExtractor().extract(
        "Aether settles every payment atomically. It records every ledger entry."
    )
    # The '. ' boundary is consumed, so the first sentence loses its period;
    # the trailing sentence keeps its period.
    assert _texts(claims) == [
        "Aether settles every payment atomically",
        "It records every ledger entry.",
    ]


def test_splits_on_exclamation_and_question_boundaries():
    claims = ClaimExtractor().extract(
        "The escrow released on time! Did the merchant confirm? Yes, the receipt was recorded."
    )
    # '! ' and '? ' boundaries are consumed; the trailing sentence is not
    # followed by a boundary and keeps its punctuation.
    assert _texts(claims) == [
        "The escrow released on time",
        "Did the merchant confirm",
        "Yes, the receipt was recorded.",
    ]


def test_splits_multi_sentence_content_on_all_boundaries():
    claims = ClaimExtractor().extract(
        "First claim has enough words. Second claim is also long! Third query here? Fourth claim kept."
    )
    assert _texts(claims) == [
        "First claim has enough words",
        "Second claim is also long",
        "Third query here",
        "Fourth claim kept.",
    ]


def test_skips_headers_citations_numbered_and_blank_lines():
    content = (
        "# Executive summary\n"
        "\n"
        "The withdrawal settled in full.\n"
        "[ref:tx-1234]\n"
        "1. The first finding is listed here.\n"
        "2. The second finding is listed here.\n"
        "   \n"
        "The final balance matches the ledger.\n"
    )
    claims = ClaimExtractor().extract(content)
    assert _texts(claims) == [
        "The withdrawal settled in full.",
        "The final balance matches the ledger.",
    ]


def test_short_fragments_dropped_below_min_claim_chars():
    claims = ClaimExtractor().extract("The settled value was exact. ok! fine?")
    assert _texts(claims) == ["The settled value was exact"]


def test_claim_length_boundary_uses_min_claim_chars():
    assert MIN_CLAIM_CHARS == 8
    exact = "a" * 8  # exactly MIN_CLAIM_CHARS -> kept
    short = "b" * 6  # below MIN_CLAIM_CHARS -> dropped
    claims = ClaimExtractor().extract(f"{exact}. {short}.")
    assert _texts(claims) == [exact]


def test_single_long_sentence_is_one_claim():
    content = (
        "Aether completes the entire settlement lifecycle end to end without "
        "any interruption."
    )
    claims = ClaimExtractor().extract(content)
    assert len(claims) == 1
    assert claims[0].text == content


def test_empty_content_returns_no_claims():
    extractor = ClaimExtractor()
    assert extractor.extract("") == []
    assert extractor.extract("   \n \t  \n") == []


def test_only_skippable_lines_return_no_claims():
    content = "# Heading\n\n[ref:tx-1]\n1. an item\n## Sub heading\n2. another item\n"
    assert ClaimExtractor().extract(content) == []


def test_all_claims_too_short_raises_fail_closed():
    # Non-empty content with claim-shaped text but every candidate sentence
    # below MIN_CLAIM_CHARS is an unparseable synthesis result: fail closed.
    _raises(ClaimExtractionError, lambda: ClaimExtractor().extract("Hi! No. Go?"))


def test_secret_shaped_sentence_propagates_verification_unsafe():
    extractor = ClaimExtractor()
    _raises(
        VerificationUnsafe,
        lambda: extractor.extract("The rotated API key is sk-1234567890abcdef."),
    )
    _raises(
        VerificationUnsafe,
        lambda: extractor.extract("The cert material is -----BEGIN CERTIFICATE----- here."),
    )
    _raises(
        VerificationUnsafe,
        lambda: extractor.extract("The response used a Bearer token in transport."),
    )


def test_returned_claims_are_claim_statements():
    claims = ClaimExtractor().extract("Aether settled the withdrawal in full.")
    assert len(claims) == 1
    claim = claims[0]
    assert isinstance(claim, ClaimStatement)
    assert claim.text == "Aether settled the withdrawal in full."
    assert claim.evidence_refs == ()


def test_claims_module_exports_complete():
    expected = {"ClaimExtractionError", "MIN_CLAIM_CHARS", "ClaimExtractor"}
    assert set(claims_module.__all__) == expected
    for name in expected:
        assert hasattr(claims_module, name), name
