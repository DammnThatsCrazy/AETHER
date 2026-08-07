"""Explainability tests: the explain payload answers 'what is this number?' and
reflects observed vs allocated vs estimated, staleness, and supersession."""

from __future__ import annotations

import pytest

from services.computation.campaign import canonical_journey_allocated_cost
from services.computation.explain import build_explain
from services.computation.repositories import ComputedResultsRepository
from shared.computation.context import ComputationContext
from shared.computation.registry import get_definition
from shared.computation.runtime import money_result, rate_result


@pytest.fixture()
def ctx():
    return ComputationContext(tenant_id="t1", grain="campaign_day",
                             event_time_start="2026-01-01T00:00:00+00:00")


def test_explain_observed_money(ctx):
    d = get_definition("campaign.media_spend")
    r = money_result(d, ctx, amount="500.00", currency="USD").model_dump(mode="json")
    ex = build_explain(r)
    assert ex["definition_id"] == "campaign.media_spend"
    assert ex["is_observed"] is True
    assert ex["is_allocated"] is False
    assert ex["currency"] == "USD"
    assert ex["status"] == "available"


def test_explain_rate_exposes_formula(ctx):
    d = get_definition("campaign.ctr")
    r = rate_result(d, ctx, numerator=50, denominator=1000).model_dump(mode="json")
    ex = build_explain(r)
    assert ex["formula"]["numerator"] == "50"
    assert ex["formula"]["denominator"] == "1000"
    assert ex["formula"]["aggregation"] == "ratio_of_sums"
    assert ex["uncertainty"] is not None


def test_explain_allocated_is_flagged_not_observed(ctx):
    _, per_journey = canonical_journey_allocated_cost(
        ctx, campaign_cost="1000.00", currency="USD",
        journey_weights={"j1": "1", "j2": "1"},
    )
    r = per_journey["j1"].model_dump(mode="json")
    ex = build_explain(r)
    assert ex["is_allocated"] is True
    assert ex["is_observed"] is False
    assert "allocated" in ex["nature"]
    assert ex["status"] == "estimated"


async def test_explain_reflects_supersession(ctx):
    repo = ComputedResultsRepository()
    d = get_definition("campaign.media_spend")
    prior = money_result(d, ctx, amount="100.00", currency="USD").model_dump(mode="json")
    p = await repo.insert_result(prior)
    new = money_result(d, ctx, amount="150.00", currency="USD").model_dump(mode="json")
    n = await repo.supersede("t1", p["result_id"], new, reason="provider correction")

    prior_row = await repo.get("t1", p["result_id"])
    ex_prior = build_explain(prior_row)
    assert ex_prior["superseded_by"] == n["result_id"]

    chain = await repo.restatement_chain("t1", n["result_id"])
    ex_new = build_explain(await repo.get("t1", n["result_id"]), chain=chain)
    assert ex_new["restatement_reason"] == "provider correction"
    assert any(c["reason"] == "provider correction" for c in ex_new["restatement_chain"])
