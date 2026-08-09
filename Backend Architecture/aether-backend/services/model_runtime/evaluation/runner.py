"""Evaluation runner (ADR-008 D7/D8, Commit 11) — run cases through an engine and score.

The evaluation plane scores the multi-model harness: canned, tenant-scoped
scenarios (:class:`EvaluationCase`) are run through a synthesis engine and
scored on exact-match / faithfulness / leak-safety / latency, producing one
:class:`EvaluationReport` per case. This module owns the orchestrator,
:class:`EvaluationRunner`.

The engine is duck-typed — any object exposing
``async run(request, synthesizer) -> SynthesisResult`` works (for example the
synthesis :class:`GroundedSynthesisEngine`); the runner never imports the
engine hard, so this module stays importable while the synthesis sibling is
still landing.

Fail-closed posture:

* The evaluation request is built with ``evidence=None``, so the synthesis
  grounding gate fails closed (:class:`InsufficientEvidence`). Evaluating an
  ungrounded scenario is itself a signal: the run yields a fail-closed report
  (``passed=False``, ``request_id='eval:ungrounded'``) rather than raising.
* Any unexpected engine/scorer failure becomes a fail-closed report
  (``passed=False``) whose failure reason is the exception class name only —
  short and content-free. The runner never logs or surfaces synthesis content.
* :meth:`run_suite` isolates failures per case so one bad case never aborts
  the suite.

Scorer contract: content scorers (exact-match / faithfulness / leak-scan)
implement ``score(result, expected)``; the latency scorer additionally accepts
``elapsed_seconds=`` and is invoked with the wall-clock time measured around
the engine call. The latency scorer is identified by ``name == 'latency'``.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from services.model_runtime.evaluation.models import (
    EvaluationCase,
    EvaluationReport,
    EvaluationScore,
)
from services.model_runtime.evaluation.scorers import (
    EvaluationScorer,
    ExactMatchScorer,
    FaithfulnessScorer,
    LatencyScorer,
    LeakScorer,
)
from services.model_runtime.synthesis.grounding import InsufficientEvidence

if TYPE_CHECKING:  # pragma: no cover - type-only, resolved at type-check time
    from services.model_runtime.synthesis.models import (
        SynthesisRequest,
        SynthesisResult,
    )

__all__ = [
    "EvaluationRunnerError",
    "EvaluationRunner",
]

#: Score name produced by the leak scorer (see evaluation/scorers.py). The
#: runner detects a detected leak by this name so ``EvaluationReport``'s
#: fail-closed invariant (passed only when no leak) holds by construction.
_LEAK_SCORE_NAME = "leak-scan"


class EvaluationRunnerError(Exception):
    """Raised when a run cannot be converted into a fail-closed report.

    The message is intentionally short and content-free: the runner never
    surfaces synthesis content or credentials in an exception.
    """


class EvaluationRunner:
    """Runs an evaluation case through a synthesis engine and scores the result.

    Fail-closed: any engine/scorer error produces a report with ``passed=False``
    rather than propagating raw content.
    """

    def __init__(
        self,
        *,
        engine=None,
        scorers: Sequence[EvaluationScorer] | None = None,
    ) -> None:
        # The engine is duck-typed (``async run(request, synthesizer)``); the
        # concrete default is imported lazily so this module loads even while
        # the synthesis engine sibling is landing.
        if engine is not None:
            self._engine = engine
        else:
            from services.model_runtime.synthesis.engine import GroundedSynthesisEngine

            self._engine = GroundedSynthesisEngine()
        self._scorers: tuple[EvaluationScorer, ...] = (
            tuple(scorers)
            if scorers is not None
            else (
                ExactMatchScorer(),
                FaithfulnessScorer(),
                LeakScorer(),
                LatencyScorer(),
            )
        )

    async def run_case(self, case: EvaluationCase, synthesizer) -> EvaluationReport:
        """Run one evaluation case and score the result, failing closed.

        1. Build a :class:`SynthesisRequest` for the case with ``evidence=None``
           (``profile_id='eval'``, ``plan_kind=case.allowed_plan_kinds[0]``,
           ``synthesis_instructions=case.scenario``).
        2. Time the engine call; run the engine and let the grounding gate do
           its job — ``evidence=None`` raises ``InsufficientEvidence``, and
           evaluating an ungrounded scenario is itself a signal, so that
           outcome becomes a fail-closed report (``passed=False``,
           ``request_id='eval:ungrounded'``) rather than an exception.
        3. On success, score the result with every scorer (content scorers with
           the result + case; latency with the measured elapsed seconds).
        4. Build the report: ``passed`` is the conjunction of all scores and
           ``leak_detected`` is set when the leak score failed.
        """
        try:
            request = self._build_request(case)
            start = time.perf_counter()
            try:
                result = await self._engine.run(request, synthesizer)
            except InsufficientEvidence:
                return self._ungrounded_report(case)
            except Exception as err:
                # Unexpected engine failure: fail closed to a passed=False
                # report carrying only the exception class name (no content).
                return self._failure_report(case, reason=type(err).__name__)
            elapsed = time.perf_counter() - start

            scores: list[EvaluationScore] = []
            for scorer in self._scorers:
                try:
                    scores.append(
                        self._score_one(
                            scorer,
                            result=result,
                            case=case,
                            elapsed_seconds=elapsed,
                        )
                    )
                except Exception as err:
                    # Scorer failure: fail closed to a passed=False report.
                    return self._failure_report(case, reason=type(err).__name__)
            return self._build_report(case, result, tuple(scores))
        except EvaluationRunnerError:
            raise
        except Exception as err:
            raise EvaluationRunnerError(f"evaluation run failed: {type(err).__name__}") from err

    async def run_suite(
        self,
        cases: Sequence[EvaluationCase],
        synthesizer,
    ) -> list[EvaluationReport]:
        """Run ``cases`` sequentially (deterministic order), scoring each.

        A failure in one case does not abort the suite: any report-less failure
        is converted into a fail-closed ``passed=False`` report so callers
        always receive one report per input case, in order.
        """
        reports: list[EvaluationReport] = []
        for case in cases:
            try:
                reports.append(await self.run_case(case, synthesizer))
            except Exception as err:
                reports.append(self._failure_report(case, reason=type(err).__name__))
        return reports

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _build_request(self, case: EvaluationCase) -> SynthesisRequest:
        """Assemble the evaluation ``SynthesisRequest`` (evidence-less)."""
        if not case.allowed_plan_kinds:
            raise EvaluationRunnerError("evaluation case has no allowed plan kinds")
        from services.model_runtime.synthesis.models import SynthesisRequest

        return SynthesisRequest(
            tenant_id=case.tenant_id,
            profile_id="eval",
            query=case.query,
            plan_kind=case.allowed_plan_kinds[0],
            evidence=None,
            synthesis_instructions=case.scenario,
        )

    @staticmethod
    def _score_one(
        scorer: EvaluationScorer,
        *,
        result: SynthesisResult,
        case: EvaluationCase,
        elapsed_seconds: float,
    ) -> EvaluationScore:
        """Invoke one scorer, passing the measured latency only to latency."""
        if getattr(scorer, "name", None) == "latency":
            return scorer.score(result, case, elapsed_seconds=elapsed_seconds)
        return scorer.score(result, case)

    @staticmethod
    def _build_report(
        case: EvaluationCase,
        result: SynthesisResult,
        scores: tuple[EvaluationScore, ...],
    ) -> EvaluationReport:
        """Assemble the scored report, computing ``passed`` and ``leak_detected``.

        ``leak_detected`` is True exactly when a leak-scan score failed. The
        ``EvaluationReport`` model then enforces the fail-closed invariant
        (``passed`` only when every score passed and no leak was detected) at
        construction.
        """
        leak_detected = any(score.name == _LEAK_SCORE_NAME and not score.passed for score in scores)
        return EvaluationReport(
            case_id=case.case_id,
            request_id=result.request_id,
            scores=scores,
            passed=all(score.passed for score in scores),
            leak_detected=leak_detected,
            created_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _ungrounded_report(case: EvaluationCase) -> EvaluationReport:
        """Fail-closed report for a run rejected by the grounding gate.

        ``request_id='eval:ungrounded'`` marks the outcome. A single failing
        ``grounding`` score carries the reason so the report is a valid
        ``EvaluationReport`` (``passed=False`` requires a failing score given
        ``leak_detected=False``) and consumers can see exactly which dimension
        failed.
        """
        grounding_score = EvaluationScore(
            name="grounding",
            value=0.0,
            passed=False,
            threshold=1.0,
            method="grounding-gate",
        )
        return EvaluationReport(
            case_id=case.case_id,
            request_id="eval:ungrounded",
            scores=(grounding_score,),
            passed=False,
            leak_detected=False,
            created_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _failure_report(case: EvaluationCase, *, reason: str) -> EvaluationReport:
        """Fail-closed report for an engine/scorer run that produced no scores.

        ``reason`` is the exception class name only (short, content-free). A
        single failing ``run`` score keeps the report valid under the
        ``EvaluationReport`` fail-closed invariant.
        """
        run_score = EvaluationScore(
            name="run",
            value=0.0,
            passed=False,
            threshold=0.0,
            method=f"fail-closed:{reason}",
        )
        return EvaluationReport(
            case_id=case.case_id,
            request_id="eval:failed",
            scores=(run_score,),
            passed=False,
            leak_detected=False,
            created_at=datetime.now(timezone.utc),
        )
