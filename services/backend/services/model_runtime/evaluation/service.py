"""EvaluationService — provider-neutral facade for the evaluation plane.

ADR-008 D7/D8 (Commit 11): the evaluation plane scores the multi-model harness
against canned, tenant-scoped scenarios and fails closed at the regression gate
before a model or provider change is promoted. ``EvaluationService`` is the
one-call entry point for evaluation runs: it owns the scenario catalog, the
runner, and the gate, and it exposes a safe, content-free summary surface.

Callers supply a :class:`Synthesizer`; Aether executes the model calls through
the injected runner's engine. The facade:

* ``run_case`` — run one :class:`EvaluationCase` and return its
  :class:`EvaluationReport`, wrapping ``EvaluationRunnerError`` into a short,
  content-free :class:`EvaluationServiceError`.
* ``run_suite`` — run every catalog case and require the regression gate,
  returning the :class:`GateResult`; a failed gate raises
  :class:`EvaluationServiceError` naming only the failing ``case_id`` values
  (never content).
* ``summarize`` — a safe aggregate over reports (counts + failing case ids +
  leak-free flag) with no report content.

Security posture: the facade never surfaces synthesis content or credentials in
an exception or a summary; failures carry failure class names and case ids only.
"""

from __future__ import annotations

from collections.abc import Sequence

from services.model_runtime.evaluation.gate import (
    GateResult,
    RegressionGate,
    RegressionGateError,
)
from services.model_runtime.evaluation.models import (
    EvaluationCase,
    EvaluationReport,
)
from services.model_runtime.evaluation.runner import (
    EvaluationRunner,
    EvaluationRunnerError,
)
from services.model_runtime.evaluation.scenarios import (
    DEFAULT_TENANT_ID,
    ScenarioCatalog,
)

__all__ = ["EvaluationServiceError", "EvaluationService"]


class EvaluationServiceError(Exception):
    """Raised when an evaluation run fails the service-level gate.

    The message is intentionally short and content-free: the facade never
    surfaces synthesis content or credentials in an exception.
    """


class EvaluationService:
    """Provider-neutral facade for evaluation runs.

    Callers supply a Synthesizer; Aether executes model calls through the
    injected runner's engine. All components are injectable for testing;
    defaults compose the canonical runner (grounded-synthesis engine + the four
    documented scorers), the fail-closed regression gate, and the default
    scenario catalog (tenant-scoped per ``run_suite`` call).
    """

    def __init__(
        self,
        *,
        runner: EvaluationRunner | None = None,
        gate: RegressionGate | None = None,
        catalog: ScenarioCatalog | None = None,
    ) -> None:
        self._runner = runner if runner is not None else EvaluationRunner()
        self._gate = gate if gate is not None else RegressionGate()
        # ``None`` means "default catalog, tenant-scoped per run_suite call".
        self._catalog = catalog

    async def run_case(self, case: EvaluationCase, synthesizer) -> EvaluationReport:
        """Run one evaluation case through the runner and return its report.

        The runner fails closed on engine/scorer errors (a ``passed=False``
        report); this wrapper only converts an unrecoverable
        ``EvaluationRunnerError`` (e.g. a case with no allowed plan kinds) into
        a ``EvaluationServiceError`` whose message carries the failure class
        name — never content.

        Raises:
            EvaluationServiceError: the runner could not produce a report for
                the case.
        """
        try:
            return await self._runner.run_case(case, synthesizer)
        except EvaluationRunnerError as err:
            raise EvaluationServiceError(
                f"evaluation run_case failed: {type(err).__name__}"
            ) from err

    async def run_suite(
        self,
        synthesizer,
        *,
        tenant_id: str = DEFAULT_TENANT_ID,
    ) -> GateResult:
        """Run every catalog case and require the regression gate.

        The default catalog is tenant-scoped to ``tenant_id``; an injected
        catalog is used as-is (its tenant scope is the caller's choice). A
        suite that fails the gate raises ``EvaluationServiceError`` naming only
        the failing ``case_id`` values — never content or credentials.

        Raises:
            EvaluationServiceError: the regression gate did not pass.
        """
        catalog = self._catalog
        if catalog is None:
            catalog = ScenarioCatalog.default(tenant_id=tenant_id)
        cases = catalog.all_cases()
        reports = await self._runner.run_suite(cases, synthesizer)
        try:
            return self._gate.require(reports)
        except RegressionGateError as err:
            # Re-evaluate without raising so only the failing case ids are
            # named; report content never crosses this boundary.
            result = self._gate.evaluate(reports)
            failing = ", ".join(result.failed_case_ids) or "<empty-suite>"
            raise EvaluationServiceError(
                f"evaluation regression gate failed for case_ids: {failing}"
            ) from err

    def summarize(self, reports: Sequence[EvaluationReport]) -> dict:
        """Safe aggregate over a suite of reports — no content, no scores.

        Returns ``{'total': n, 'passed': n, 'failed_case_ids': [...],
        'leak_free': bool}``. ``leak_free`` is True only when every report has
        ``leak_detected`` False.
        """
        reports = list(reports)
        return {
            "total": len(reports),
            "passed": sum(1 for report in reports if report.passed),
            "failed_case_ids": [
                report.case_id for report in reports if not report.passed
            ],
            "leak_free": all(not report.leak_detected for report in reports),
        }
