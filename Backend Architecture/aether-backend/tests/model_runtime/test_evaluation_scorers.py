"""Tests for deterministic evaluation-plane scorers (ADR-008 D7, Commit 11-B).

Plain asserts only: no ``pytest.raises``, no fixture/mock libraries.
``_raises`` is the single tiny helper, so this suite runs identically under
the minimal test runtime used by some CI environments.

Concurrency / gating: the suite consumes sibling ``evaluation/models.py``
(Commit 11-A), the synthesis layer's ``synthesis/models.py`` (Commit 9), and
the verification layer's ``faithfulness``/``leaks``/``claims`` modules
(Commit 10). Each sibling is importor-skipped so this suite passes (as a
skip) until every contract is importable; once ``synthesis/models.py`` lands,
the whole suite runs against the real ``SynthesisResult`` and
``EvidenceCitation`` types. The ``sk-`` shaped LeakScorer case is built via
``SynthesisResult.model_construct`` to bypass ``SynthesisUnsafe``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

import pytest

# Sibling contracts land in parallel with this suite; each is guarded so the
# whole module skips until everything this suite constructs is importable.
pytest.importorskip("services.model_runtime.evaluation.models")
pytest.importorskip("services.model_runtime.synthesis.models")
pytest.importorskip("services.model_runtime.verification.faithfulness")
pytest.importorskip("services.model_runtime.verification.claims")
pytest.importorskip("services.model_runtime.verification.leaks")

from services.model_runtime.evaluation.models import (  # noqa: E402 - after importorskip guards
    EvaluationCase,
    EvaluationScore,
)
from services.model_runtime.evaluation.scorers import (  # noqa: E402
    ExactMatchScorer,
    EvaluationScorer,
    FaithfulnessScorer,
    LatencyScorer,
    LeakScorer,
    ScorerError,
)
from services.model_runtime.synthesis.models import (  # noqa: E402
    EvidenceCitation,
    SynthesisResult,
)


def _raises(exc_type, func):
    """Assert that calling func() raises exc_type, plain-assert style."""
    try:
        func()
    except exc_type:
        return
    except Exception as err:
        raise AssertionError(
            f"expected {exc_type.__name__} but got {type(err).__name__}: {err}"
        ) from err
    raise AssertionError(f"expected {exc_type.__name__} to be raised")


def _case(ground_truth):
    """A real, validated EvaluationCase (required fields only)."""
    return EvaluationCase(
        tenant_id="t1",
        case_id="c1",
        query="describe what happened",
        expected_ground_truth=ground_truth,
    )


def _citation(reference_id, excerpt):
    """A real EvidenceCitation with a known reference id and excerpt."""
    return EvidenceCitation(
        reference_id=reference_id,
        source="aether.records.ledger.tx-1",
        tenant_id="t1",
        excerpt=excerpt,
    )


def _result(content, citations=()):
    """A real SynthesisResult built via model_construct.

    ``model_construct`` bypasses ``SynthesisUnsafe`` so credential-shaped
    content is representable for the LeakScorer cases; it also means the
    helper keeps working regardless of which validation rules the Commit-9
    model layer applies to ``content``.
    """
    return SynthesisResult.model_construct(
        request_id="req-1",
        plan_kind="summarize",
        content=content,
        citations=citations,
        created_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# ExactMatchScorer
# ---------------------------------------------------------------------------


def test_exact_match_hit_scores_one_and_passes():
    scorer = ExactMatchScorer()
    score = scorer.score(
        _result("The escrow released on time."),
        _case("The escrow released on time."),
    )
    assert isinstance(score, EvaluationScore)
    assert score.name == "exact-match"
    assert score.method == "exact-match"
    assert score.value == 1.0
    assert score.threshold == 1.0
    assert score.passed is True


def test_exact_match_ignores_case_and_whitespace():
    scorer = ExactMatchScorer()
    score = scorer.score(
        _result("  THE ESCROW RELEASED ON TIME.  "),
        _case("the escrow released on time."),
    )
    assert score.value == 1.0
    assert score.passed is True


def test_exact_match_mismatch_scores_zero_and_fails():
    scorer = ExactMatchScorer()
    score = scorer.score(
        _result("The escrow released late."),
        _case("The escrow released on time."),
    )
    assert score.value == 0.0
    assert score.passed is False


def test_exact_match_ignores_empty_citations():
    # ExactMatchScorer never reads citations; an empty citation list must not
    # change the outcome.
    scorer = ExactMatchScorer()
    score = scorer.score(_result("exact answer", ()), _case("exact answer"))
    assert score.value == 1.0
    assert score.passed is True


def test_exact_match_threshold_wiring():
    # A threshold of 0.0 lets even a mismatch pass (0.0 >= 0.0).
    scorer = ExactMatchScorer(threshold=0.0)
    score = scorer.score(_result("wrong answer"), _case("right answer"))
    assert score.value == 0.0
    assert score.threshold == 0.0
    assert score.passed is True


# ---------------------------------------------------------------------------
# FaithfulnessScorer
# ---------------------------------------------------------------------------


def test_faithfulness_supported_claim_passes():
    scorer = FaithfulnessScorer()
    # The claim cites ref:r1 inline, so it is checked ONLY against r1's excerpt
    # (cite-aware grounding) and shares significant tokens with it.
    result = _result(
        "Revenue grew strongly [ref:r1].",
        (_citation("r1", "revenue grew 20%"),),
    )
    score = scorer.score(result, _case("Revenue grew strongly."))
    assert isinstance(score, EvaluationScore)
    assert score.name == "faithfulness"
    assert score.method == "token-overlap"
    # The only extracted claim shares significant tokens with the excerpt, so
    # the supported ratio is 1.0, comfortably above the default 0.6 threshold.
    assert score.value == 1.0
    assert score.threshold == 0.6
    assert score.value >= score.threshold
    assert score.passed is True


def test_faithfulness_unsupported_claim_below_threshold():
    scorer = FaithfulnessScorer()
    # The claim cites ref:r1 but r1's excerpt shares no significant token with
    # it -> unsupported even though the claim named the row (cite-aware).
    result = _result(
        "Profit margins expanded [ref:r1].",
        (_citation("r1", "revenue grew 20%"),),
    )
    score = scorer.score(result, _case("Profit margins expanded."))
    # No significant token shared with the excerpt -> unsupported -> ratio 0.0.
    assert score.value == 0.0
    assert score.value < score.threshold
    assert score.passed is False


def test_faithfulness_empty_citations_fails_closed():
    scorer = FaithfulnessScorer()
    # The claim cites ref:r1, but no citation with that id is available, so its
    # scoped set is empty: nothing retrieved, nothing verified -> 0.0.
    result = _result("Revenue grew strongly [ref:r1].", ())
    score = scorer.score(result, _case("Revenue grew strongly."))
    assert score.value == 0.0
    assert score.passed is False


def test_faithfulness_unparseable_content_fails_closed():
    # Content below MIN_CLAIM_CHARS yields no claim and raises
    # ClaimExtractionError; the scorer converts that into a fail-closed 0.0.
    scorer = FaithfulnessScorer()
    result = _result("tldr", (_citation("r1", "revenue grew 20%"),))
    score = scorer.score(result, _case("tldr"))
    assert score.value == 0.0
    assert score.passed is False


def test_faithfulness_threshold_wiring():
    scorer = FaithfulnessScorer(threshold=0.0)
    # The claim cites ref:r1 but r1's excerpt shares no significant token with
    # it; the cited row does not support the claim -> unsupported -> 0.0.
    result = _result(
        "Profit margins expanded [ref:r1].",
        (_citation("r1", "revenue grew 20%"),),
    )
    score = scorer.score(result, _case("Profit margins expanded."))
    assert score.value == 0.0
    assert score.threshold == 0.0
    # 0.0 >= 0.0, so a threshold of 0.0 turns the unsupported run into a pass.
    assert score.passed is True


def test_faithfulness_claim_cannot_pass_on_uncited_citation():
    # Cite-aware regression (Codex): a claim citing ref:r1 is verified ONLY
    # against r1's excerpt. ref:r2 would support it under full-citation
    # matching, but it is ignored because the claim never cited it — exactly
    # what VerificationEngine._check_cited rejects, so the eval plane cannot
    # promote a miscited claim.
    scorer = FaithfulnessScorer()
    result = _result(
        "Gold reserves increased [ref:r1].",
        (
            _citation("r1", "Marketing spend declined sharply."),  # cited, no overlap
            _citation("r2", "Gold reserves increased markedly."),  # uncited, would match
        ),
    )
    score = scorer.score(result, _case("Gold reserves increased."))
    assert score.value == 0.0
    assert score.value < score.threshold
    assert score.passed is False


def test_faithfulness_claim_citing_its_row_passes():
    # Cite-aware positive: the claim cites ref:r2 and r2's excerpt matches, so
    # it is supported even though another (uncited) citation would also match.
    scorer = FaithfulnessScorer()
    result = _result(
        "Gold reserves increased [ref:r2].",
        (
            _citation("r1", "Marketing spend declined sharply."),
            _citation("r2", "Gold reserves increased markedly."),
        ),
    )
    score = scorer.score(result, _case("Gold reserves increased."))
    assert score.value == 1.0
    assert score.passed is True


# ---------------------------------------------------------------------------
# LeakScorer
# ---------------------------------------------------------------------------


def test_leak_scorer_clean_content_passes():
    scorer = LeakScorer()
    result = _result(
        "The escrow released on time.",
        (_citation("r1", "The ledger recorded the escrow."),),
    )
    score = scorer.score(result, _case("The escrow released on time."))
    assert isinstance(score, EvaluationScore)
    assert score.name == "leak-scan"
    assert score.method == "leak-scan"
    assert score.value == 1.0
    assert score.threshold == 1.0
    assert score.passed is True


def test_leak_scorer_clean_content_empty_citations_passes():
    scorer = LeakScorer()
    score = scorer.score(_result("The escrow released on time.", ()), _case("x"))
    assert score.value == 1.0
    assert score.passed is True


def test_leak_scorer_sk_shaped_content_fails():
    # model_construct bypasses SynthesisUnsafe so sk- shaped content is
    # representable; the leak scan must still fail it closed.
    scorer = LeakScorer()
    result = _result("The key sk-live-abc123 is never emitted.", ())
    score = scorer.score(result, _case("irrelevant"))
    assert score.value == 0.0
    assert score.passed is False


def test_leak_scorer_citation_excerpt_leak_fails():
    # The Commit-9 model layer rejects secret markers in an excerpt at
    # construction, so the leaky citation is built via model_construct to
    # represent the (invalid but observable) state the scorer must still
    # catch — mirroring the sk- shaped content case.
    scorer = LeakScorer()
    leaky_citation = EvidenceCitation.model_construct(
        reference_id="r1",
        source="aether.records.ledger.tx-1",
        tenant_id="t1",
        excerpt="reference AKIAIOSFODNN7EXAMPLE archived",
    )
    result = _result("The escrow released on time.", (leaky_citation,))
    score = scorer.score(result, _case("The escrow released on time."))
    # Content is clean but the excerpt carries an AWS access key id: fail.
    assert score.value == 0.0
    assert score.passed is False


def test_leak_scorer_threshold_wiring():
    scorer = LeakScorer(threshold=0.0)
    result = _result("The key sk-live-abc123 is never emitted.", ())
    score = scorer.score(result, _case("irrelevant"))
    assert score.value == 0.0
    assert score.threshold == 0.0
    assert score.passed is True


# ---------------------------------------------------------------------------
# LatencyScorer
# ---------------------------------------------------------------------------


def test_latency_under_max_seconds_passes():
    scorer = LatencyScorer(max_seconds=5.0)
    score = scorer.score(_result("answer"), _case("x"), elapsed_seconds=2.0)
    assert isinstance(score, EvaluationScore)
    assert score.name == "latency"
    assert score.method == "wall-clock"
    assert score.value == 2.0
    assert score.threshold == 5.0
    assert score.passed is True


def test_latency_over_max_seconds_fails():
    scorer = LatencyScorer(max_seconds=5.0)
    score = scorer.score(_result("answer"), _case("x"), elapsed_seconds=7.0)
    assert score.value == 7.0
    assert score.threshold == 5.0
    assert score.passed is False


def test_latency_at_exact_max_seconds_passes():
    scorer = LatencyScorer(max_seconds=5.0)
    score = scorer.score(_result("answer"), _case("x"), elapsed_seconds=5.0)
    assert score.value == 5.0
    assert score.passed is True


def test_latency_default_call_passes_at_zero():
    # The default call supplies elapsed_seconds=0.0, which is never over budget.
    scorer = LatencyScorer()
    score = scorer.score(_result("answer"), _case("x"))
    assert score.value == 0.0
    assert score.passed is True


def test_latency_default_budget_is_nonzero_and_accepts_real_duration():
    # Regression (Codex): the default scorer must carry a NONZERO budget — a
    # real run always measures a positive wall-clock duration, and a
    # zero-duration default would fail every otherwise-faithful report (and
    # reject the default regression suite).
    from services.model_runtime.evaluation.scorers import (
        DEFAULT_MAX_LATENCY_SECONDS,
    )

    scorer = LatencyScorer()
    assert scorer.threshold == DEFAULT_MAX_LATENCY_SECONDS
    assert scorer.threshold > 0.0

    score = scorer.score(_result("answer"), _case("x"), elapsed_seconds=0.5)
    assert score.value == 0.5
    assert score.passed is True


# ---------------------------------------------------------------------------
# Threshold wiring / error posture
# ---------------------------------------------------------------------------


def test_negative_threshold_raises_scorer_error():
    _raises(ScorerError, lambda: ExactMatchScorer(threshold=-0.1))
    _raises(ScorerError, lambda: FaithfulnessScorer(threshold=-0.1))
    _raises(ScorerError, lambda: LeakScorer(threshold=-0.1))
    _raises(ScorerError, lambda: LatencyScorer(max_seconds=-1.0))


def test_zero_thresholds_are_valid():
    # Zero is a legal (if permissive) threshold on every scorer.
    assert ExactMatchScorer(threshold=0.0).threshold == 0.0
    assert FaithfulnessScorer(threshold=0.0).threshold == 0.0
    assert LeakScorer(threshold=0.0).threshold == 0.0
    assert LatencyScorer(max_seconds=0.0).threshold == 0.0


# ---------------------------------------------------------------------------
# Public contract
# ---------------------------------------------------------------------------


def test_public_exports_exact():
    import services.model_runtime.evaluation.scorers as scorers_module

    assert scorers_module.__all__ == [
        "ScorerError",
        "EvaluationScorer",
        "ExactMatchScorer",
        "FaithfulnessScorer",
        "LeakScorer",
        "LatencyScorer",
    ]
    for name in scorers_module.__all__:
        assert hasattr(scorers_module, name), name


def test_evaluation_scorer_is_a_protocol():
    # EvaluationScorer is a structural Protocol (typing.Protocol), not a class
    # to subclass — scorers conform by shape, not inheritance.
    assert issubclass(EvaluationScorer, Protocol)


def test_each_scorer_satisfies_the_evaluation_scorer_protocol():
    # Structural check: every concrete scorer exposes a .name and a .score
    # callable, so the harness can drive them through the protocol uniformly.
    for scorer in (
        ExactMatchScorer(),
        FaithfulnessScorer(),
        LeakScorer(),
        LatencyScorer(),
    ):
        assert isinstance(scorer.name, str)
        assert callable(scorer.score)
