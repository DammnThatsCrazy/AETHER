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
  ``0.6``. **Cite-aware grounding**: each claim is checked ONLY against the
  citations it references (inline ``[ref:...]`` markers and/or
  ``claim.evidence_refs``), mirroring ``VerificationEngine._check_cited`` — a
  claim cannot borrow token overlap from an unrelated citation it never cited.
  Fail-closed: empty citations yield ``0.0`` (nothing retrieved, nothing
  verified), a claim that cites nothing is unsupported, and a result whose
  content cannot be parsed into claims also scores ``0.0``.
* **Leak-scan** (:class:`LeakScorer`): ``1.0`` only when neither the
  synthesized content nor any citation excerpt carries a credential-shaped
  marker (:class:`SecretLeakDetector`); otherwise ``0.0``. Threshold defaults
  to ``1.0``.
* **Latency** (:class:`LatencyScorer`): the wall-clock ``elapsed_seconds`` the
  caller supplies directly; passes while ``elapsed_seconds <= max_seconds``.
  ``threshold`` is ``max_seconds``. The default scorer carries a NONZERO budget
  (:data:`DEFAULT_MAX_LATENCY_SECONDS`) so a real synthesis run — which always
  measures a positive ``perf_counter`` duration — passes the default regression
  suite instead of being rejected by a zero-duration gate; the default call
  (``elapsed_seconds = 0.0``) also passes.

Security posture: no scorer logs or stores synthesis content; every scorer is
deterministic and model-free (no LLM calls). Invalid (negative) thresholds are
rejected with :class:`ScorerError` so misconfiguration fails closed.

The ``result`` argument is duck-typed — it only needs ``content: str`` and an
iterable of citation objects exposing ``excerpt: str`` — so this module
imports cleanly while the sibling ``synthesis/models.py`` (Commit 9) is still
landing.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
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

#: Inline citation marker in synthesized prose, e.g. ``[ref:tx-1234]``. A claim
#: may only borrow token overlap from the citations it names. Mirrors the
#: verifier's ``_REF_MARKER`` (``verification/verifier.py``) so the evaluation
#: scorer applies the SAME cite-aware scoping as ``VerificationEngine._check_cited``.
_REF_MARKER = re.compile(r"\[ref:([^\]]+)\]")

#: Default wall-clock latency budget (seconds) for the evaluation latency gate.
#: A real grounded-synthesis run always measures a positive ``perf_counter``
#: duration, so the default scorer MUST carry a nonzero budget: a zero-duration
#: default would fail every otherwise-faithful evaluation report and reject the
#: default regression suite. 30s is sane headroom for a single model call.
DEFAULT_MAX_LATENCY_SECONDS: float = 30.0


class ScorerError(Exception):
    """Base error for the evaluation-plane scoring layer."""


def _require_non_negative(threshold: float) -> None:
    """Fail closed on a nonsense (negative) threshold."""
    if threshold < 0:
        raise ScorerError(f"threshold must be non-negative, got {threshold}")


def _normalized(text: str) -> str:
    """Strip + lowercase normalization shared by the string scorers."""
    return text.strip().lower()


def _cited_reference_ids(claim: Any) -> set[str]:
    """Reference ids a claim cites: inline markers plus ``evidence_refs``.

    Mirrors ``VerificationEngine._cited_reference_ids`` so the evaluation
    scorer and the verification gate agree on which citations a claim may use.
    """
    refs: set[str] = set(getattr(claim, "evidence_refs", ()) or ())
    for raw in _REF_MARKER.findall(getattr(claim, "text", "")):
        ref = raw.strip()
        if ref:
            refs.add(ref)
    return refs


def _scoped_checks(
    checker: FaithfulnessChecker,
    claims: Sequence[Any],
    citations: Sequence[Any],
) -> list[Any]:
    """Check each claim ONLY against the citations it references (cite-aware).

    Mirrors ``VerificationEngine._check_cited``: claims are grouped by their
    scoped citation set (the reference ids they cite that are present among
    ``citations``) and each group is checked against exactly those citations,
    producing one :class:`CitationCheck` per claim in deterministic order. A
    claim that cites nothing — or only reference ids absent from ``citations``
    — is checked against NO citations and is therefore unsupported
    (fail-closed). This prevents a response from passing faithfulness by
    borrowing token overlap from an unrelated citation it never cited, matching
    the verification gate so promotion results cannot accept miscited claims.
    """
    by_ref = {citation.reference_id: citation for citation in citations}
    buckets: dict[tuple[str, ...], list[Any]] = {}
    for claim in claims:
        refs = _cited_reference_ids(claim)
        scoped_ids = tuple(sorted(ref for ref in refs if ref in by_ref))
        buckets.setdefault(scoped_ids, []).append(claim)

    checks: list[Any] = []
    for scoped_ids, bucket in buckets.items():
        scoped = [by_ref[ref_id] for ref_id in scoped_ids]
        checks.extend(checker.check(bucket, scoped))
    return checks


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
    """Token-overlap faithfulness of claims against CITED evidence.

    Score is the fraction of extracted claims that share at least one
    significant token with a citation the claim itself references
    (cite-aware grounding — a claim cannot borrow overlap from an unrelated
    citation, matching ``VerificationEngine._check_cited``). Fail-closed:
    empty or unparseable content, empty citations, and claims that cite nothing
    all score ``0.0``.
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
            claims = extractor.extract(result.content)
        except ClaimExtractionError:
            # A non-empty result with no claim-shaped content cannot be
            # faithful; fail closed to 0.0 rather than raising mid-scoring.
            claims = []
        checks = _scoped_checks(checker, claims, citations)
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
    under ``max_seconds``. The default budget is NONZERO
    (:data:`DEFAULT_MAX_LATENCY_SECONDS`) so the default scorer accepts a real
    (positive) measured duration instead of failing every otherwise-faithful
    evaluation report; the default call (``elapsed_seconds=0.0``) passes too.
    """

    name = "latency"
    method = "wall-clock"

    def __init__(
        self,
        max_seconds: float = DEFAULT_MAX_LATENCY_SECONDS,
    ) -> None:
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
