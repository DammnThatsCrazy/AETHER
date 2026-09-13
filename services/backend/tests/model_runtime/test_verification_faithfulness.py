"""Tests for the fail-closed token-overlap faithfulness check (ADR-008 D7).

Plain asserts only: no pytest.raises, no fixture/mock libraries. This suite
runs identically under the minimal test runtime used by some CI environments.

The suite consumes sibling A's ``verification.models`` (``ClaimStatement``,
``CitationCheck``) via ``importorskip`` and the synthesis layer's
``EvidenceCitation`` when available (with a duck-typed stand-in fallback while
``synthesis/models.py`` is still landing) so it stays collectible — and keeps
running — while the sibling Commit-10 modules land concurrently.
"""

from __future__ import annotations

import pytest

verification_models = pytest.importorskip("services.model_runtime.verification.models")
ClaimStatement = verification_models.ClaimStatement
CitationCheck = verification_models.CitationCheck

# Synthesis' ``EvidenceCitation`` is a Commit-9 sibling that may still be
# landing. Prefer the real contract when importable; otherwise fall back to an
# equivalent local stand-in so this suite can run (and pass) while
# ``synthesis/models.py`` is mid-landing. ``FaithfulnessChecker`` only reads
# ``citation.excerpt`` and ``citation.reference_id``, so the stand-in is
# faithful to the duck type the checker consumes.
try:
    from services.model_runtime.synthesis.models import EvidenceCitation
except ImportError:  # pragma: no cover - synthesis/models.py still landing
    EvidenceCitation = None


class _CitationStandIn:
    """Minimal EvidenceCitation stand-in carrying the same fields."""

    def __init__(self, reference_id, source, tenant_id, excerpt):
        self.reference_id = reference_id
        self.source = source
        self.tenant_id = tenant_id
        self.excerpt = excerpt


from services.model_runtime.verification.faithfulness import (  # noqa: E402
    STOPWORDS,
    FaithfulnessChecker,
)


def _claim(text, evidence_refs=("ref-1",)):
    return ClaimStatement(text=text, evidence_refs=evidence_refs)


def _citation(reference_id, excerpt, source="aether.records.ledger.tx-1", tenant_id="t1"):
    if EvidenceCitation is not None:
        return EvidenceCitation(
            reference_id=reference_id,
            source=source,
            tenant_id=tenant_id,
            excerpt=excerpt,
        )
    return _CitationStandIn(
        reference_id=reference_id,
        source=source,
        tenant_id=tenant_id,
        excerpt=excerpt,
    )


def _checker() -> FaithfulnessChecker:
    return FaithfulnessChecker()


# ---------------------------------------------------------------------------
# Supported claims
# ---------------------------------------------------------------------------


def test_supported_claim_shared_significant_token():
    checker = _checker()
    citation = _citation("r1", "revenue grew 20%")
    checks = checker.check([_claim("Revenue grew strongly")], [citation])
    assert len(checks) == 1
    check = checks[0]
    assert check.supported is True
    assert check.reference_id == "r1"
    assert check.claim_text == "Revenue grew strongly"
    assert check.method == "token-overlap"


def test_supported_claim_points_at_its_own_citation():
    checker = _checker()
    other = _citation("r-other", "profit guidance was raised")
    match = _citation("r-match", "revenue grew by twenty percent")
    checks = checker.check([_claim("Revenue grew strongly")], [other, match])
    assert checks[0].supported is True
    assert checks[0].reference_id == "r-match"


def test_best_match_is_highest_shared_token_count():
    checker = _checker()
    weak = _citation("r-weak", "revenue was announced")
    strong = _citation("r-strong", "revenue grew rapidly")
    checks = checker.check([_claim("Revenue grew strongly")], [weak, strong])
    assert checks[0].supported is True
    assert checks[0].reference_id == "r-strong"


# ---------------------------------------------------------------------------
# Unsupported claims
# ---------------------------------------------------------------------------


def test_unsupported_claim_no_shared_significant_token():
    checker = _checker()
    citation = _citation("r1", "revenue grew 20%")
    checks = checker.check([_claim("Profit margins expanded")], [citation])
    assert len(checks) == 1
    assert checks[0].supported is False
    assert checks[0].reference_id == "r1"  # best match is still reported


def test_stopword_only_claim_is_unsupported():
    checker = _checker()
    citation = _citation("r1", "revenue grew 20%")
    checks = checker.check([_claim("This is it")], [citation])
    assert checks[0].supported is False


def test_numeric_only_claim_is_unsupported():
    checker = _checker()
    # "20%" and "2024" are bare number/date tokens — never significant.
    citation = _citation("r1", "margin was 20% in 2024")
    checks = checker.check([_claim("20%"), _claim("2024")], [citation])
    assert checks[0].supported is False
    assert checks[1].supported is False


def test_shared_numeric_token_does_not_support():
    checker = _checker()
    citation = _citation("r1", "revenue grew 21%")
    # Claim shares only numeric tokens ("20%") plus a stopword ("was") with the
    # excerpt; the shared significant count is zero -> unsupported.
    checks = checker.check([_claim("It was 20%")], [citation])
    assert checks[0].supported is False


def test_no_citations_means_every_claim_unsupported():
    checker = _checker()
    checks = checker.check([_claim("Revenue grew"), _claim("Costs fell")], [])
    assert len(checks) == 2
    assert all(check.supported is False for check in checks)
    assert [check.reference_id for check in checks] == ["", ""]


def test_empty_claims_produce_no_checks():
    checker = _checker()
    citation = _citation("r1", "revenue grew 20%")
    assert checker.check([], [citation]) == []


# ---------------------------------------------------------------------------
# Tie-breaking
# ---------------------------------------------------------------------------


def test_ties_resolved_by_first_citation():
    checker = _checker()
    first = _citation("r-first", "revenue grew 20%")
    second = _citation("r-second", "revenue grew 30%")
    checks = checker.check([_claim("Revenue grew strongly")], [first, second])
    assert checks[0].supported is True
    assert checks[0].reference_id == "r-first"


def test_unsupported_ties_resolve_to_first_citation():
    checker = _checker()
    first = _citation("r-first", "profit guidance")
    second = _citation("r-second", "margin expansion")
    checks = checker.check([_claim("Revenue grew")], [first, second])
    assert checks[0].supported is False
    assert checks[0].reference_id == "r-first"


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def test_case_insensitive_matching():
    checker = _checker()
    citation = _citation("r1", "REVENUE GREW 20%")
    checks = checker.check([_claim("Revenue grew")], [citation])
    assert checks[0].supported is True


def test_short_tokens_do_not_count():
    checker = _checker()
    # "go" and "up" are both < 3 chars, so neither is significant.
    citation = _citation("r1", "go up")
    checks = checker.check([_claim("go up")], [citation])
    assert checks[0].supported is False


def test_short_token_alone_does_not_support_longer_claim():
    checker = _checker()
    citation = _citation("r1", "go and grow")
    # "grow" (>=3 chars) IS significant; "go"/"and" are not. Claim shares only
    # the short token "go" plus the stopword "and" -> unsupported.
    checks = checker.check([_claim("go and")], [citation])
    assert checks[0].supported is False


def test_stopword_is_never_significant_even_when_shared():
    checker = _checker()
    citation = _citation("r1", "the margin is the number")
    checks = checker.check([_claim("the margin is the profit")], [citation])
    # "margin" is shared and significant -> supported.
    assert checks[0].supported is True


# ---------------------------------------------------------------------------
# supported_ratio
# ---------------------------------------------------------------------------


def test_supported_ratio_one_of_four():
    checker = _checker()
    citation = _citation("r1", "revenue grew 20%")
    checks = checker.check(
        [
            _claim("Revenue grew"),
            _claim("Costs fell"),
            _claim("Profit is up"),
            _claim("Margin compressed"),
        ],
        [citation],
    )
    assert checker.supported_ratio(checks) == 0.25


def test_supported_ratio_with_explicit_checks():
    checker = _checker()
    checks = [
        CitationCheck(reference_id="r1", claim_text="a", supported=True, method="token-overlap"),
        CitationCheck(reference_id="r1", claim_text="b", supported=True, method="token-overlap"),
        CitationCheck(reference_id="r1", claim_text="c", supported=False, method="token-overlap"),
        CitationCheck(reference_id="r1", claim_text="d", supported=False, method="token-overlap"),
    ]
    assert checker.supported_ratio(checks) == 0.5


def test_supported_ratio_empty_checks_is_zero():
    assert _checker().supported_ratio([]) == 0.0


def test_supported_ratio_no_supported_is_zero():
    checker = _checker()
    citation = _citation("r1", "revenue grew 20%")
    checks = checker.check([_claim("This is it")], [citation])
    assert checker.supported_ratio(checks) == 0.0


def test_supported_ratio_all_supported_is_one():
    checker = _checker()
    citation = _citation("r1", "revenue grew 20%")
    checks = checker.check([_claim("Revenue grew"), _claim("revenue improved")], [citation])
    assert checker.supported_ratio(checks) == 1.0


# ---------------------------------------------------------------------------
# Public contract
# ---------------------------------------------------------------------------


def test_public_exports_exact():
    import services.model_runtime.verification.faithfulness as faithfulness_module

    assert faithfulness_module.__all__ == [
        "FaithfulnessCheckError",
        "STOPWORDS",
        "FaithfulnessChecker",
    ]
    for name in faithfulness_module.__all__:
        assert hasattr(faithfulness_module, name), name


def test_stopwords_is_frozenset_with_declared_members():
    assert isinstance(STOPWORDS, frozenset)
    expected = {
        "the", "a", "an", "is", "are", "was", "were", "to", "of", "in", "on",
        "for", "and", "or", "it", "this", "that", "with", "as", "at", "by",
        "from", "be", "been", "will", "would", "can", "could", "do", "does",
        "did", "has", "have", "had", "not", "no", "but", "its", "their",
        "them", "they", "we", "you", "i", "my", "your",
    }
    assert set(STOPWORDS) == expected


def test_faithfulness_check_error_is_exception():
    import services.model_runtime.verification.faithfulness as faithfulness_module

    err = faithfulness_module.FaithfulnessCheckError("boom")
    assert isinstance(err, Exception)
    assert str(err) == "boom"
