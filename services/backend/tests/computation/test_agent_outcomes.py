"""Section 23 — agent & operational computation honesty.

Proves three honesty properties:

1. Expected-utility exposes every component *separately* (never one opaque
   number), keeps money as Decimal, and never coerces an unknown input to 0.
2. Outcome provenance is classified: a *claimed* success (HTTP 200 / success
   flag) is NOT a *verified* business outcome; only a reconciled/verified one is.
3. Queue health with no workload/coverage reads as "unknown" / "no_coverage" —
   never "healthy" merely because no errors were seen.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from repositories.repos import reset_in_memory_stores
from services.agent.economic import (
    AgentEconomicViews,
    classify_outcome,
    compute_expected_utility,
)
from services.reliability.service import evaluate_queue_health, queue_service


@pytest.fixture(autouse=True)
def clean():
    reset_in_memory_stores()


# ── 1. Expected-utility: components separately visible ──────────────────────

_EU_COMPONENT_KEYS = (
    "value_of_success",
    "probability_of_success",
    "probability_of_failure",
    "expected_value_of_success",
    "execution_cost",
    "expected_failure_cost",
    "review_cost",
    "risk_penalty",
    "expected_utility",
)


def test_expected_utility_returns_each_component_separately():
    result = compute_expected_utility(
        value_of_success="100",
        probability_of_success="0.5",
        execution_cost="5",
        failure_cost="20",
        review_cost="2",
        risk_penalty="3",
        currency="USD",
    )

    # Every component is individually present — not collapsed into one number.
    for key in _EU_COMPONENT_KEYS:
        assert key in result, f"missing component {key}"
        assert result[key] is not None, f"component {key} should be computable"

    assert result["computable"] is True
    assert result["missing_inputs"] == []
    assert result["components_visible"] is True

    # expected_value_of_success = 100 * 0.5 = 50
    assert Decimal(result["expected_value_of_success"]) == Decimal("50")
    # expected_failure_cost = 20 * (1 - 0.5) = 10
    assert Decimal(result["probability_of_failure"]) == Decimal("0.5")
    assert Decimal(result["expected_failure_cost"]) == Decimal("10")
    # EU = 50 - 5 - 10 - 2 - 3 = 30
    assert Decimal(result["expected_utility"]) == Decimal("30")

    # The aggregate is genuinely distinct from any single component (not aliased).
    assert result["expected_utility"] != result["expected_value_of_success"]
    assert result["execution_cost"] != result["expected_failure_cost"]

    # Money is carried as Decimal strings, never floats.
    for key in _EU_COMPONENT_KEYS:
        assert isinstance(result[key], str)
        assert not isinstance(result[key], float)


def test_expected_utility_unknown_input_is_not_zero():
    # review_cost omitted → unknown, must NOT be silently treated as 0.
    result = compute_expected_utility(
        value_of_success="100",
        probability_of_success="0.5",
        execution_cost="5",
        failure_cost="20",
        risk_penalty="3",
    )
    assert result["computable"] is False
    assert "review_cost" in result["missing_inputs"]
    assert result["review_cost"] is None
    assert result["expected_utility"] is None
    # Components that ARE known stay visible even when the total is not computable.
    assert Decimal(result["expected_value_of_success"]) == Decimal("50")


def test_expected_utility_exposed_on_aggregator():
    # The pure helper is reachable via the service aggregator too.
    assert AgentEconomicViews.compute_expected_utility is compute_expected_utility
    assert AgentEconomicViews.classify_outcome is classify_outcome


# ── 2. Outcome classification: claimed != verified ──────────────────────────

def test_claimed_success_is_not_a_verified_outcome():
    claimed = classify_outcome(http_status=200, self_reported_success=True)
    verified = classify_outcome(reconciliation_state="matched")

    assert claimed["classification"] == "claimed"
    assert verified["classification"] == "verified"
    assert claimed["classification"] != verified["classification"]

    # The load-bearing guarantee: an HTTP 200 is not a business outcome.
    assert claimed["is_verified_business_outcome"] is False
    assert verified["is_verified_business_outcome"] is True


def test_outcome_provenance_ladder():
    # A settlement record exists but is unreconciled → observed, not verified.
    observed = classify_outcome(settlement_status="success")
    assert observed["classification"] == "observed"
    assert observed["is_verified_business_outcome"] is False

    # Modeled/projected → estimated; baseline → counterfactual. Neither is real.
    estimated = classify_outcome(is_estimate=True)
    counterfactual = classify_outcome(is_counterfactual=True)
    assert estimated["classification"] == "estimated"
    assert counterfactual["classification"] == "counterfactual"
    assert estimated["is_verified_business_outcome"] is False
    assert counterfactual["is_verified_business_outcome"] is False

    # No signal at all → unknown (never a default "success").
    assert classify_outcome()["classification"] == "unknown"

    # An explicit verifying authority also promotes to verified.
    assert classify_outcome(verified_by="provider_reconciliation")["classification"] == "verified"


# ── 3. Queue health: no coverage is "unknown"/"no_coverage", not "healthy" ──

def test_evaluate_queue_health_no_coverage_is_not_healthy():
    # Caller self-reports "healthy" but there is no workload and no workers.
    verdict = evaluate_queue_health({"status": "healthy", "depth": 0})
    assert verdict["status"] != "healthy"
    assert verdict["status"] == "unknown"
    assert verdict["coverage"] == "no_coverage"
    assert verdict["reported_status"] == "healthy"
    assert verdict["unverified"] is True
    assert verdict["verification"] == "self_reported"


def test_evaluate_queue_health_self_report_never_certifies_healthy():
    # Even with real workload, a self-reported "healthy" is not certified.
    verdict = evaluate_queue_health(
        {"status": "healthy", "depth": 500, "active_worker_count": 4}
    )
    assert verdict["status"] == "unknown"
    assert verdict["coverage"] == "covered"
    assert verdict["unverified"] is True

    # A self-reported *problem* is honoured (fail toward the worse status).
    problem = evaluate_queue_health({"status": "degraded", "depth": 500})
    assert problem["status"] == "degraded"
    assert problem["unverified"] is True


@pytest.mark.asyncio
async def test_queue_service_report_healthy_without_coverage_reads_unknown():
    # Seed and report a queue that claims healthy with no workload/coverage.
    updated = await queue_service.report("graph_mutations", {"status": "healthy", "depth": 0})
    assert updated["status"] == "unknown"
    assert updated["coverage"] == "no_coverage"
    assert updated["reported_status"] == "healthy"
    assert updated["unverified"] is True


@pytest.mark.asyncio
async def test_queue_service_list_never_reported_is_no_coverage():
    rows = await queue_service.list()
    assert rows, "expected seeded queue rows"
    for row in rows:
        # Nothing was ever observed → nothing may read as healthy.
        assert row["status"] != "healthy"
        assert row["status"] == "unknown"
        assert row["coverage"] == "no_coverage"
        assert row["unverified"] is True
