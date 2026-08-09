"""Tests for the seeded evaluation scenario catalog (ADR-008 Commit 11, D6/D9).

The catalog is a pure-data seed: every scenario is a benign, tenant-scoped,
plain-language summarize task. The models layer fails closed on credential-
shaped content, so a leaked scenario can never reach an evaluation run.
"""

from __future__ import annotations

from services.model_runtime.evaluation.models import (
    EvaluationCase,
    EvaluationUnsafe,
)
from services.model_runtime.evaluation.scenarios import (
    DEFAULT_TENANT_ID,
    ScenarioCatalog,
    ScenarioCatalogError,
    ScenarioDefinition,
)


def _raises(exc_type, call):
    """Assert that ``call()`` raises ``exc_type``, using only plain asserts."""
    try:
        call()
    except exc_type:
        return
    raise AssertionError(f"expected {exc_type.__name__} to be raised")


def _default() -> ScenarioCatalog:
    return ScenarioCatalog.default()


def _definition(case_id: str = "custom") -> ScenarioDefinition:
    return ScenarioDefinition(
        case_id=case_id,
        query="Summarize the sample trend.",
        expected_ground_truth="The sample trend was steady.",
        scenario="summarize",
    )


# ---------------------------------------------------------------------------
# Default seed
# ---------------------------------------------------------------------------


def test_default_seed_has_at_least_five_cases():
    cases = _default().all_cases()
    assert len(cases) >= 5
    assert all(isinstance(case, EvaluationCase) for case in cases)


def test_default_cases_have_non_empty_content():
    for case in _default().all_cases():
        assert case.case_id
        assert case.query
        assert case.expected_ground_truth
        assert case.scenario


def test_default_cases_are_tenant_scoped():
    catalog = _default()
    assert all(case.tenant_id == DEFAULT_TENANT_ID for case in catalog.all_cases())


def test_default_cases_have_non_empty_plan_kinds():
    assert all(case.allowed_plan_kinds for case in _default().all_cases())


def test_custom_tenant_propagates_to_cases():
    catalog = ScenarioCatalog.default(tenant_id="acme-eval")
    assert all(case.tenant_id == "acme-eval" for case in catalog.all_cases())


def test_default_case_ids_unique():
    cases = _default().all_cases()
    assert len({case.case_id for case in cases}) == len(cases)


# ---------------------------------------------------------------------------
# Case lookup
# ---------------------------------------------------------------------------


def test_case_returns_matching_case():
    catalog = _default()
    cases = catalog.all_cases()
    target = cases[0]
    found = catalog.case(target.case_id)
    assert found.case_id == target.case_id
    assert found.query == target.query
    assert found.expected_ground_truth == target.expected_ground_truth


def test_case_unknown_raises():
    _raises(ScenarioCatalogError, lambda: _default().case("no-such-case"))


# ---------------------------------------------------------------------------
# Fail-closed: secret-shaped content raises EvaluationUnsafe
# ---------------------------------------------------------------------------


def test_secret_shaped_query_fails_closed():
    catalog = ScenarioCatalog(
        definitions=[
            ScenarioDefinition(
                case_id="leaked",
                query="sk-live-abc123",
                expected_ground_truth="Revenue grew over the quarter.",
                scenario="summarize",
            )
        ]
    )
    _raises(EvaluationUnsafe, catalog.all_cases)


def test_secret_shaped_ground_truth_fails_closed():
    catalog = ScenarioCatalog(
        definitions=[
            ScenarioDefinition(
                case_id="leaked",
                query="Summarize the quarterly revenue trend.",
                expected_ground_truth="password=hunter2",
                scenario="summarize",
            )
        ]
    )
    _raises(EvaluationUnsafe, catalog.all_cases)


def test_secret_shaped_case_lookup_fails_closed():
    catalog = ScenarioCatalog(
        definitions=[
            ScenarioDefinition(
                case_id="leaked",
                query="Summarize the trend.",
                expected_ground_truth="X-Api-Key: abc",
                scenario="summarize",
            )
        ]
    )
    _raises(EvaluationUnsafe, lambda: catalog.case("leaked"))


# ---------------------------------------------------------------------------
# Ordering and custom definitions
# ---------------------------------------------------------------------------


def test_all_cases_order_matches_definitions():
    definitions = [
        _definition("a"),
        _definition("b"),
        _definition("c"),
    ]
    catalog = ScenarioCatalog(definitions=definitions)
    assert [case.case_id for case in catalog.all_cases()] == ["a", "b", "c"]


def test_custom_definitions_override_seed():
    custom = [_definition("custom-1")]
    catalog = ScenarioCatalog(definitions=custom)
    cases = catalog.all_cases()
    assert len(cases) == 1
    assert cases[0].case_id == "custom-1"


def test_empty_constructor_has_no_cases():
    assert ScenarioCatalog().all_cases() == []


def test_public_exports_exact():
    import services.model_runtime.evaluation.scenarios as scenarios_module

    assert scenarios_module.__all__ == [
        "ScenarioCatalogError",
        "DEFAULT_TENANT_ID",
        "ScenarioDefinition",
        "ScenarioCatalog",
    ]
