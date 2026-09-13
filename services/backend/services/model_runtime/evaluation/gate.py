"""ADR-008 D7/D9 evaluation regression gate — fail-closed quality gate (Commit 11-E).

The regression gate is the last stop before the harness promotes a model or
provider change. A suite PASSES only when every report passed AND no report
carried a detected leak. An empty suite FAILS (fail-closed: no evidence of
quality means the change does not ship). Every report is also required to carry
the full set of configured required score names — a report that is missing a
required metric fails the gate even when its ``passed`` flag is True, because a
suite that stops measuring a dimension cannot claim the dimension still holds.

Contract with sibling ``evaluation/models.py`` (Commit 11-A): a report must
expose ``case_id``, ``passed``, ``leak_detected`` and ``scores`` (a sequence of
``EvaluationScore`` objects, each exposing its metric name as ``.name``). The
gate reads only these members and never imports the sibling model module, so it
stays importable while sibling modules are still landing.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # sibling Commit 11-A lands concurrently; duck-typed at runtime
    from services.model_runtime.evaluation.models import EvaluationReport

__all__ = [
    "RegressionGateError",
    "GateResult",
    "RegressionGate",
]

_DEFAULT_REQUIRED_SCORES: tuple[str, ...] = (
    "exact-match",
    "faithfulness",
    "leak-scan",
    "latency",
)


class RegressionGateError(Exception):
    """Raised by ``RegressionGate.require`` when a suite fails the gate (fail-closed)."""


@dataclass(frozen=True)
class GateResult:
    """Outcome of a regression-gate evaluation over a suite of reports."""

    passed: bool
    total_cases: int
    passed_cases: int
    failed_cases: int
    failed_case_ids: tuple[str, ...] = ()


def _score_name(score: object) -> str:
    """Return the metric name of an ``EvaluationScore`` (contract: ``.name``).

    The gate fails loud instead of silently skipping a required score when the
    score model drifts from the documented contract — fail-closed by design.
    """
    name = getattr(score, "name", None)
    if name is None:
        raise RegressionGateError(
            "gate contract requires every EvaluationScore to expose its metric "
            f"name as '.name'; got {type(score).__name__!r}"
        )
    return name


def _report_fails(report: EvaluationReport, required: frozenset[str]) -> bool:
    """True when a report must fail the gate: leak, not-passed, or a missing required score."""
    if report.leak_detected or not report.passed:
        return True
    present = {_score_name(score) for score in report.scores}
    return not required.issubset(present)


class RegressionGate:
    """Fail-closed quality gate over the eval plane (ADR-008 D7/D9).

    A suite PASSES only when every report passed AND every report has
    ``leak_detected`` False. No reports -> FAIL (fail-closed). Configurable
    required score names: a report with a missing required score fails the gate
    even when its ``passed`` flag is True.
    """

    def __init__(
        self,
        *,
        required_scores: Sequence[str] = _DEFAULT_REQUIRED_SCORES,
    ):
        self._required_scores: tuple[str, ...] = tuple(required_scores)

    def evaluate(self, reports: Sequence[EvaluationReport]) -> GateResult:
        """Evaluate a suite and return a ``GateResult`` without raising."""
        required = frozenset(self._required_scores)
        failed_case_ids = tuple(
            report.case_id for report in reports if _report_fails(report, required)
        )
        total_cases = len(reports)
        failed_cases = len(failed_case_ids)
        passed_cases = total_cases - failed_cases
        passed = total_cases > 0 and passed_cases == total_cases
        return GateResult(
            passed=passed,
            total_cases=total_cases,
            passed_cases=passed_cases,
            failed_cases=failed_cases,
            failed_case_ids=failed_case_ids,
        )

    def require(self, reports: Sequence[EvaluationReport]) -> GateResult:
        """evaluate() then raise ``RegressionGateError`` when not passed.

        Returns the ``GateResult`` when the suite passes.
        """
        result = self.evaluate(reports)
        if not result.passed:
            failing = ", ".join(result.failed_case_ids) or "<empty-suite>"
            raise RegressionGateError(
                f"regression gate FAILED: {result.passed_cases}/{result.total_cases} "
                f"cases passed; failing case_ids: {failing}"
            )
        return result
