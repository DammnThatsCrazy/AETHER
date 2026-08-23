"""Deterministic evaluation-plane scorers (ADR-008 D7 — Commit 11).

The evaluation plane scores the multi-model harness against canned,
tenant-scoped scenarios: a synthesized :class:`SynthesisResult` is measured
against its :class:`EvaluationCase` and produces one :class:`EvaluationScore`
per metric. This module owns the individual scorers; a caller (e.g. the
orchestrator that aggregates an :class:`EvaluationReport`) decides which
scorers to run per case.

Scoring rules (deterministic, documented, tested):

* **Exact-match** (:class:`ExactMatchScorer`): ``1.0`` when the synthesized
  content and the expected ground truth are equal after strip + lowercase
  normalization, else ``0.0``. Threshold defaults to ``1.0``.
* **Faithfulness** (:class:`FaithfulnessScorer`): claims are extracted from the
  synthesized content with :class:`ClaimExtractor`, checked against the
  result's citation excerpts with :class:`FaithfulnessChecker` (token overlap),
  and the score is the checker's ``supported_ratio``. Threshold defaults to
  ``0.6``. Fail-closed: empty citations yield ``0.0`` (nothing retrieved,
  nothing verified), and a result whose content cannot be parsed into claims
  also scores ``0.0``.
* **Leak-scan** (:class:`LeakScorer`): ``1.0`` only when neither the
  synthesized content nor any citation excerpt carries a credential-shaped
  marker (:class:`SecretLeakDetector`); otherwise ``0.0``. Threshold defaults
  to ``1.0``.
* **Latency** (:class:`LatencyScorer`): the wall-clock ``elapsed_seconds`` the
  caller supplies directly; passes while ``elapsed_seconds <= max_seconds``.
  ``threshold`` is ``max_seconds``, and the default call (``elapsed_seconds =
  0.0``) passes.

Security posture: no scorer logs or stores synthesis content; every scorer is
deterministic and model-free (no LLM calls). Invalid (negative) thresholds are
rejected with :class:`ScorerError` so misconfiguration fails closed.

The ``result`` argument is duck-typed — it only needs ``content: str`` and an
iterable of citation objects exposing ``excerpt: str`` — so this module
imports cleanly while the sibling ``synthesis/models.py`` (Commit 9) is still
landing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from services.model_runtime.evaluation.models import EvaluationScore
from services.model_runtime.verification.claims import (
    ClaimExtractionError,
    ClaimExtractor,
)
from services.model_runtime.verification.faithfulness import FaithfulnessChecker
from services.model_runtime.verification.leaks import SecretLeakDetector

if TYPE_CHECKING:  # pragma: no cover - type hints only
    from services.model_runtime.evaluation.models import EvaluationCase

__all__ = [
    "ScorerError",
    "EvaluationScorer",
    "ExactMatchScorer",
    "FaithfulnessScorer",
    "LeakScorer",
    "LatencyScorer",
]


class ScorerError(Exception):
    """Base error for the evaluation-plane scoring layer."""


def _require_non_negative(threshold: float) -> None:
    """Fail closed on a nonsense (negative) threshold."""
    if threshold < 0:
        raise ScorerError(f"threshold must be non-negative, got {threshold}")


def _normalized(text: str) -> str:
    """Strip + lowercase normalization shared by the string scorers."""
    return text.strip().lower()


class EvaluationScorer(Protocol):
    """Structural contract every scorer satisfies.

    A scorer names itself and produces one :class:`EvaluationScore` per
    ``result`` / ``expected`` pair. ``result`` is the synthesized output;
    ``expected`` is the reference :class:`EvaluationCase`.
    """

    name: str

    def score(self, result: Any, expected: EvaluationCase) -> EvaluationScore:
        """Score ``result`` against ``expected``; return the metric score."""
        ...


class ExactMatchScorer:
    """Normalized-string exact match against ``expected_ground_truth``."""

    name = "exact-match"
    method = "exact-match"

    def __init__(self, threshold: float = 1.0) -> None:
        _require_non_negative(threshold)
        self.threshold = threshold

    def score(self, result: Any, expected: EvaluationCase) -> EvaluationScore:
        value = (
            1.0
            if _normalized(result.content) == _normalized(expected.expected_ground_truth)
            else 0.0
        )
        return EvaluationScore(
            name=self.name,
            value=value,
            passed=value >= self.threshold,
            threshold=self.threshold,
            method=self.method,
        )


class FaithfulnessScorer:
    """Token-overlap faithfulness of claims against cited evidence.

    Score is the fraction of extracted claims that share at least one
    significant token with some citation excerpt. Fail-closed: empty or
    unparseable content and empty citations all score ``0.0``.
    """

    name = "faithfulness"
    method = "token-overlap"

    def __init__(self, threshold: float = 0.6) -> None:
        _require_non_negative(threshold)
        self.threshold = threshold

    def score(self, result: Any, expected: EvaluationCase) -> EvaluationScore:
        checker = FaithfulnessChecker()
        extractor = ClaimExtractor()
        citations = list(result.citations or [])
        try:
            checks = checker.check(extractor.extract(result.content), citations)
        except ClaimExtractionError:
            # A non-empty result with no claim-shaped content cannot be
            # faithful; fail closed to 0.0 rather than raising mid-scoring.
            checks = []
        value = checker.supported_ratio(checks)
        return EvaluationScore(
            name=self.name,
            value=value,
            passed=value >= self.threshold,
            threshold=self.threshold,
            method=self.method,
        )


class LeakScorer:
    """Fail-closed credential-leak sweep over content and citation excerpts."""

    name = "leak-scan"
    method = "leak-scan"

    def __init__(self, threshold: float = 1.0) -> None:
        _require_non_negative(threshold)
        self.threshold = threshold

    def score(self, result: Any, expected: EvaluationCase) -> EvaluationScore:
        detector = SecretLeakDetector()
        clean_content = detector.is_clean(result.content)
        clean_excerpts = all(
            detector.is_clean(citation.excerpt) for citation in (result.citations or [])
        )
        value = 1.0 if clean_content and clean_excerpts else 0.0
        return EvaluationScore(
            name=self.name,
            value=value,
            passed=value >= self.threshold,
            threshold=self.threshold,
            method=self.method,
        )


class LatencyScorer:
    """Wall-clock latency gate.

    The caller supplies ``elapsed_seconds`` directly (the scorer never
    measures time itself); the run passes while ``elapsed_seconds`` is at or
    under ``max_seconds``. The default call (``elapsed_seconds=0.0``) passes.
    """

    name = "latency"
    method = "wall-clock"

    def __init__(self, max_seconds: float = 0.0) -> None:
        _require_non_negative(max_seconds)
        self.threshold = max_seconds

    def score(
        self,
        result: Any,
        expected: EvaluationCase,
        elapsed_seconds: float = 0.0,
    ) -> EvaluationScore:
        value = float(elapsed_seconds)
        return EvaluationScore(
            name=self.name,
            value=value,
            passed=value <= self.threshold,
            threshold=self.threshold,
            method=self.method,
        )
