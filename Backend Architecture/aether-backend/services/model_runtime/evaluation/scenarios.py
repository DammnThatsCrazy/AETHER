"""Seeded evaluation scenarios for the Aether model-runtime evaluation plane.

ADR-008 Commit 11 (D6/D9) — the scenario catalog is a pure-data seed that the
evaluation runner executes. Each scenario is a plain-language summarize task
paired with a short, neutral expected ground truth; content is generic, holds
no real company or tenant data, and is deliberately secret-free.

Security: scenarios must never contain credentials. The models layer
(``evaluation.models``) fails closed when an ``EvaluationCase`` is built from
secret-shaped material, so a leaked scenario can never reach an evaluation run.
The catalog itself holds no logic beyond construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from services.model_runtime.evaluation.models import EvaluationCase

__all__ = [
    "ScenarioCatalogError",
    "DEFAULT_TENANT_ID",
    "ScenarioDefinition",
    "ScenarioCatalog",
]

DEFAULT_TENANT_ID: str = "eval-tenant"


class ScenarioCatalogError(Exception):
    """Raised when a scenario case is requested that the catalog does not seed."""


@dataclass(frozen=True)
class ScenarioDefinition:
    """One seeded evaluation scenario: query, expected ground truth, and scope.

    ``plan_kinds`` lists the output plan kinds the case permits; defaults to
    the summarize plan that every seeded scenario exercises.
    """

    case_id: str
    query: str
    expected_ground_truth: str
    scenario: str
    plan_kinds: tuple[str, ...] = ("summarize",)


#: The default seed — generic summarize tasks, tenant-scoped and secret-free.
#: Each expected ground truth is a short neutral sentence a faithful summary
#: should match; queries vary so the evaluation plane exercises diverse input.
_DEFAULT_SCENARIOS: tuple[ScenarioDefinition, ...] = (
    ScenarioDefinition(
        case_id="revenue-trend",
        query="Summarize the quarterly revenue trend.",
        expected_ground_truth="Revenue grew over the quarter.",
        scenario="summarize",
    ),
    ScenarioDefinition(
        case_id="churn-drivers",
        query="Summarize the top churn drivers from the retention report.",
        expected_ground_truth="Churn is driven mostly by onboarding friction.",
        scenario="summarize",
    ),
    ScenarioDefinition(
        case_id="cloud-cost-forecast",
        query="Summarize the cloud spend forecast for the next fiscal year.",
        expected_ground_truth="Cloud spend is projected to rise next fiscal year.",
        scenario="summarize",
    ),
    ScenarioDefinition(
        case_id="support-volume",
        query="Summarize how support ticket volume changed this month.",
        expected_ground_truth="Support ticket volume declined month over month.",
        scenario="summarize",
    ),
    ScenarioDefinition(
        case_id="feature-adoption",
        query="Summarize the adoption trend for the latest release.",
        expected_ground_truth="Adoption of the latest release climbed steadily.",
        scenario="summarize",
    ),
    ScenarioDefinition(
        case_id="headcount-mix",
        query="Summarize the headcount mix across engineering and sales.",
        expected_ground_truth="Engineering and sales headcount both grew.",
        scenario="summarize",
    ),
)


class ScenarioCatalog:
    """Owns the seeded evaluation scenarios. All content is benign,
    tenant-scoped, and secret-free. Scenarios must never contain credentials —
    the models layer fails closed if one does."""

    def __init__(
        self,
        tenant_id: str = DEFAULT_TENANT_ID,
        definitions: Sequence[ScenarioDefinition] | None = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._definitions = tuple(definitions or ())

    def all_cases(self) -> list[EvaluationCase]:
        """One :class:`EvaluationCase` per definition, in seed order."""
        return [
            EvaluationCase(
                tenant_id=self._tenant_id,
                case_id=definition.case_id,
                query=definition.query,
                expected_ground_truth=definition.expected_ground_truth,
                scenario=definition.scenario,
                allowed_plan_kinds=definition.plan_kinds,
            )
            for definition in self._definitions
        ]

    def case(self, case_id: str) -> EvaluationCase:
        """Return the case for ``case_id``, or raise when not seeded."""
        for case in self.all_cases():
            if case.case_id == case_id:
                return case
        raise ScenarioCatalogError(f"unknown scenario case_id: {case_id!r}")

    @classmethod
    def default(cls, tenant_id: str = DEFAULT_TENANT_ID) -> "ScenarioCatalog":
        """A catalog seeded with the default evaluation scenarios."""
        return cls(tenant_id=tenant_id, definitions=_DEFAULT_SCENARIOS)
