"""ADR-008 D7/D8 evaluation plane — public API barrel.

The evaluation plane scores the multi-model harness: canned, tenant-scoped
scenarios (:class:`EvaluationCase`) are run through a synthesis engine and
scored for exact-match / faithfulness / leak-safety / latency, then gated for
regression before a model or provider change is promoted. This barrel is the
single import surface the harness consumes.

Ownership (same commit, ADR-008 D7/D8):

* ``models`` — frozen, secret-checked data models (:class:`EvaluationUnsafe`,
  :data:`EVALUATION_SECRET_MARKERS`, :class:`EvaluationCase`,
  :class:`EvaluationScore`, :class:`EvaluationReport`);
* ``scorers`` — deterministic per-metric scorers (:class:`ScorerError`,
  :class:`EvaluationScorer`, :class:`ExactMatchScorer`,
  :class:`FaithfulnessScorer`, :class:`LeakScorer`, :class:`LatencyScorer`);
* ``runner`` — case/suite orchestration through a synthesis engine
  (:class:`EvaluationRunnerError`, :class:`EvaluationRunner`);
* ``scenarios`` — the seeded scenario catalog
  (:class:`ScenarioCatalogError`, :data:`DEFAULT_TENANT_ID`,
  :class:`ScenarioDefinition`, :class:`ScenarioCatalog`);
* ``gate`` — the fail-closed regression gate (:class:`RegressionGateError`,
  :class:`GateResult`, :class:`RegressionGate`);
* ``service`` — the public facade (:class:`EvaluationService`,
  :class:`EvaluationServiceError`).

Security posture: evaluation content is swept for secret markers before it
enters a case or a report, the regression gate fails closed on leaks and
mismatches, and the service surface never exposes synthesis content or
credentials.
"""

from __future__ import annotations

from services.model_runtime.evaluation.gate import (
    GateResult,
    RegressionGate,
    RegressionGateError,
)
from services.model_runtime.evaluation.models import (
    EVALUATION_SECRET_MARKERS,
    EvaluationCase,
    EvaluationReport,
    EvaluationScore,
    EvaluationUnsafe,
)
from services.model_runtime.evaluation.runner import (
    EvaluationRunner,
    EvaluationRunnerError,
)
from services.model_runtime.evaluation.scenarios import (
    DEFAULT_TENANT_ID,
    ScenarioCatalog,
    ScenarioCatalogError,
    ScenarioDefinition,
)
from services.model_runtime.evaluation.scorers import (
    EvaluationScorer,
    ExactMatchScorer,
    FaithfulnessScorer,
    LatencyScorer,
    LeakScorer,
    ScorerError,
)
from services.model_runtime.evaluation.service import (
    EvaluationService,
    EvaluationServiceError,
)

__all__ = [
    # evaluation/models.py — frozen, secret-checked data models
    "EvaluationUnsafe",
    "EVALUATION_SECRET_MARKERS",
    "EvaluationCase",
    "EvaluationScore",
    "EvaluationReport",
    # evaluation/scorers.py — deterministic per-metric scorers
    "ScorerError",
    "EvaluationScorer",
    "ExactMatchScorer",
    "FaithfulnessScorer",
    "LeakScorer",
    "LatencyScorer",
    # evaluation/runner.py — case/suite orchestration
    "EvaluationRunnerError",
    "EvaluationRunner",
    # evaluation/scenarios.py — seeded scenario catalog
    "ScenarioCatalogError",
    "DEFAULT_TENANT_ID",
    "ScenarioDefinition",
    "ScenarioCatalog",
    # evaluation/gate.py — fail-closed regression gate
    "RegressionGateError",
    "GateResult",
    "RegressionGate",
    # evaluation/service.py — the public facade
    "EvaluationServiceError",
    "EvaluationService",
]
