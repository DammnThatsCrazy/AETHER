"""AI money fields are Decimal in memory (program sec19); the wire/JSON shape
stays float for backward compat.

Under test:
- ``AIInvocationObserved`` cost fields are ``Decimal`` in memory, accept
  float/str/Decimal inputs, and serialize to float in JSON.
- ``AIExecutionFact.selected_cost`` and ``AIWorkflowEconomics`` money fields are
  Decimal in memory, float on the wire.
- ai_aggregation internal arithmetic is exact Decimal (0.1 + 0.2 = 0.3), with
  float only at the public output boundary.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from services.economic import ai_aggregation
from services.economic.ai_models import (
    AIExecutionFact,
    AIInvocationObserved,
    AIWorkflowEconomics,
)


def _payload(**overrides) -> dict:
    payload = {
        "invocation_id": f"inv-{uuid.uuid4().hex[:12]}",
        "tenant_id": f"t-{uuid.uuid4().hex[:8]}",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "task_type": "unit_test",
        "provider": "prov",
        "model": "model",
        "status": "succeeded",
        "currency": "USD",
        "provenance": {
            "source": "unit_test",
            "raw_event_hash": uuid.uuid4().hex,
            "schema_version": "ai.execution.v1",
        },
    }
    payload.update(overrides)
    return payload


class TestInvocationCostFieldsAreDecimal:
    def test_billed_cost_is_decimal_in_memory(self):
        observed = AIInvocationObserved.model_validate(_payload(billed_cost=9.99))
        assert isinstance(observed.billed_cost, Decimal)
        assert observed.billed_cost == Decimal("9.99")

    def test_cost_fields_accept_float_str_and_decimal_inputs(self):
        for raw in (9.99, "9.99", Decimal("9.99")):
            observed = AIInvocationObserved.model_validate(_payload(billed_cost=raw))
            assert observed.billed_cost == Decimal("9.99")

    def test_cost_fields_serialize_to_float_in_json(self):
        observed = AIInvocationObserved.model_validate(
            _payload(estimated_cost="0.42", actual_cost="5.50", billed_cost=9.99)
        )
        dumped = observed.model_dump(mode="json")
        assert dumped["estimated_cost"] == 0.42
        assert dumped["actual_cost"] == 5.5
        assert dumped["billed_cost"] == 9.99
        # python-mode dump keeps the exact Decimal.
        assert observed.model_dump()["billed_cost"] == Decimal("9.99")

    def test_cost_fields_never_coerce_unknown_to_zero(self):
        observed = AIInvocationObserved.model_validate(_payload())
        assert observed.billed_cost is None
        assert observed.estimated_cost is None


class TestExecutionFactAndWorkflowMoney:
    def _fact(self, **overrides) -> AIExecutionFact:
        now = datetime.now(timezone.utc).isoformat()
        return AIExecutionFact.model_validate({
            **_payload(),
            "selected_cost": Decimal("1.25"),
            "cost_basis": "billed",
            "received_at": now,
            "computed_at": now,
            "data_quality_status": "complete",
            **overrides,
        })

    def test_selected_cost_is_decimal_in_memory(self):
        fact = self._fact()
        assert isinstance(fact.selected_cost, Decimal)
        assert fact.selected_cost == Decimal("1.25")

    def test_selected_cost_serializes_to_float_in_json(self):
        fact = self._fact()
        assert fact.model_dump(mode="json")["selected_cost"] == 1.25

    def test_workflow_economics_money_fields_decimal(self):
        economics = AIWorkflowEconomics(
            tenant_id="t1",
            workflow_run_id="wf-1",
            total_invocations=1,
            successful_invocations=1,
            failed_invocations=0,
            total_retries=0,
            total_latency_ms=1.0,
            total_model_cost=Decimal("3.10"),
            tool_cost=None,
            retrieval_cost=None,
            fully_loaded_cost=Decimal("3.10"),
            currency="USD",
            cost_coverage=1.0,
            qualified_outcome_count=0,
            first_observed_at="2026-08-01T00:00:00Z",
            last_observed_at="2026-08-01T00:00:00Z",
            computed_at="2026-08-01T00:00:00Z",
        )
        assert isinstance(economics.total_model_cost, Decimal)
        assert economics.total_model_cost == Decimal("3.10")
        assert economics.model_dump(mode="json")["total_model_cost"] == 3.1


class TestAggregationExactDecimalArithmetic:
    def test_total_cost_by_currency_exact_decimal_sum(self):
        facts = [
            {"selected_cost": "0.1", "currency": "USD", "cost_basis": "billed"},
            {"selected_cost": "0.2", "currency": "USD", "cost_basis": "billed"},
        ]
        # Exact Decimal arithmetic: 0.1 + 0.2 == 0.3 (never 0.30000000000000004).
        assert ai_aggregation._total_cost_by_currency(facts) == {"USD": Decimal("0.3")}
        assert ai_aggregation.total_cost_by_currency(facts) == {"USD": 0.3}

    def test_known_cost_accepts_float_str_decimal_and_unknown(self):
        assert ai_aggregation._known_cost({"selected_cost": "0.1"}) == Decimal("0.1")
        assert ai_aggregation._known_cost({"selected_cost": 0.1}) == Decimal("0.1")
        assert ai_aggregation._known_cost({"selected_cost": Decimal("0.1")}) == Decimal("0.1")
        assert ai_aggregation._known_cost({"cost_basis": "unknown"}) is None
        assert ai_aggregation._known_cost({"selected_cost": None}) is None

    def test_retry_waste_cost_uses_decimal_arithmetic(self):
        facts = [
            {"selected_cost": "3.0", "currency": "USD", "retry_count": 2},
            {"selected_cost": "5.0", "currency": "USD", "retry_count": 0},
        ]
        # 3.0 * 2/3 = 2.0 (exact) — second fact contributes nothing.
        assert ai_aggregation.retry_waste_cost(facts) == {"USD": 2.0}

    def test_cost_per_invocation_uses_decimal_division(self):
        facts = [
            {"selected_cost": "0.1", "currency": "USD", "cost_basis": "billed"},
            {"selected_cost": "0.2", "currency": "USD", "cost_basis": "billed"},
        ]
        assert ai_aggregation.cost_per_invocation(facts) == {"USD": 0.15}
