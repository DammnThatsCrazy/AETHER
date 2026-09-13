"""Mutation-state tests for the Computation Substrate (task §26.4).

Start from ONE healthy baseline campaign whose canonical results are all
``available``, then apply a single, targeted mutation to the inputs and assert
that the result STATUS changes TRUTHFULLY — the substrate downgrades to the
honest state instead of emitting a plausible-but-wrong number:

  * remove an input                -> missing_inputs (value None)
  * make a numerator unpriced       -> gross_roas missing_inputs / revenue unavailable
  * drop a denominator to zero      -> missing_inputs (value None)
  * reduce the sample below minimum -> insufficient_data (value None, sample_size kept)
  * break allocation conservation   -> AllocationError
  * supersede a stored result       -> superseded_by set + restatement chain recorded

Determinism: fixed ISO timestamps in the ComputationContext; no wall clock, no
randomness. Every assertion checks the enum status, not just the scalar.
"""

from __future__ import annotations

import dataclasses

import pytest

from services.computation.campaign import CampaignAggregates, canonical_campaign_metrics
from services.computation.repositories import (
    ComputationConflictError,
    ComputedResultsRepository,
)
from shared.computation.allocation import (
    AllocationPolicy,
    AllocationResult,
    AllocationTarget,
)
from shared.computation.context import ComputationContext
from shared.computation.errors import AllocationError
from shared.computation.registry import get_definition
from shared.computation.result import ResultStatus, forbids_value
from shared.computation.runtime import money_result, new_run_id

_START = "2026-01-01T00:00:00+00:00"
_END = "2026-01-02T00:00:00+00:00"
_AS_OF = "2026-01-03T00:00:00+00:00"

# A healthy baseline: every canonical metric below is ``available``.
_BASELINE = CampaignAggregates(
    impressions=100000, clicks=1000, media_spend="500.00", total_cost="550.00",
    currency="USD", attributed_conversions="40",
    attributed_gross_revenue="2000.00", attributed_net_revenue="1600.00",
)


@pytest.fixture()
def ctx() -> ComputationContext:
    return ComputationContext(
        tenant_id="t_mut",
        grain="campaign_day",
        event_time_start=_START,
        event_time_end=_END,
        as_of=_AS_OF,
        native_currency="USD",
        reporting_currency="USD",
    )


def _baseline(ctx: ComputationContext):
    return canonical_campaign_metrics(ctx, _BASELINE)


def _mutate(ctx: ComputationContext, **changes):
    return canonical_campaign_metrics(ctx, dataclasses.replace(_BASELINE, **changes))


def _assert_absent(res, expected_status: ResultStatus) -> None:
    assert res.status == expected_status, (res.definition_id, res.status)
    assert forbids_value(res.status), res.status
    assert res.value is None, res.definition_id
    assert res.value != 0  # an honest absence, never a fake zero


# --------------------------------------------------------------------------- #
# Baseline sanity — all green before we mutate.
# --------------------------------------------------------------------------- #
def test_baseline_is_all_available(ctx):
    base = _baseline(ctx)
    for key in (
        "campaign.media_spend", "campaign.attributed_gross_revenue",
        "campaign.ctr", "campaign.cpc", "campaign.conversion_rate",
        "campaign.cpa", "campaign.gross_roas", "campaign.net_roas",
    ):
        assert base[key].status == ResultStatus.AVAILABLE, key
        assert base[key].value is not None, key


# --------------------------------------------------------------------------- #
# Mutation 1 — remove an input -> missing_inputs
# --------------------------------------------------------------------------- #
def test_mutation_remove_input_makes_missing(ctx):
    base = _baseline(ctx)
    assert base["campaign.ctr"].status == ResultStatus.AVAILABLE

    # Remove the impressions input (the CTR denominator signal).
    mutated = _mutate(ctx, impressions=0)
    _assert_absent(mutated["campaign.ctr"], ResultStatus.MISSING_INPUTS)


# --------------------------------------------------------------------------- #
# Mutation 2 — make a numerator unpriced -> missing_inputs / unavailable, never 0
# --------------------------------------------------------------------------- #
def test_mutation_unpriced_numerator_never_zero(ctx):
    base = _baseline(ctx)
    assert base["campaign.gross_roas"].status == ResultStatus.AVAILABLE
    assert base["campaign.gross_roas"].value == pytest.approx(4.0)

    mutated = _mutate(ctx, attributed_gross_revenue=None)  # revenue no longer priced

    # The rate cannot be honestly computed with an unpriced numerator: it becomes
    # missing_inputs with value None — crucially NOT a 0 ROAS.
    _assert_absent(mutated["campaign.gross_roas"], ResultStatus.MISSING_INPUTS)
    # The underlying revenue money is UNAVAILABLE (unpriced), also never 0.
    _assert_absent(
        mutated["campaign.attributed_gross_revenue"], ResultStatus.UNAVAILABLE
    )


# --------------------------------------------------------------------------- #
# Mutation 3 — drop a denominator to zero -> missing_inputs
# --------------------------------------------------------------------------- #
def test_mutation_zero_denominator_is_missing(ctx):
    base = _baseline(ctx)
    assert base["campaign.cpc"].status == ResultStatus.AVAILABLE
    assert base["campaign.conversion_rate"].status == ResultStatus.AVAILABLE

    mutated = _mutate(ctx, clicks=0)  # zero the clicks denominator

    _assert_absent(mutated["campaign.cpc"], ResultStatus.MISSING_INPUTS)
    _assert_absent(mutated["campaign.conversion_rate"], ResultStatus.MISSING_INPUTS)


# --------------------------------------------------------------------------- #
# Mutation 4 — reduce the sample below minimum -> insufficient_data
# --------------------------------------------------------------------------- #
def test_mutation_below_min_sample_is_insufficient(ctx):
    base = _baseline(ctx)
    assert base["campaign.conversion_rate"].status == ResultStatus.AVAILABLE

    # conversion_rate requires >= 30 clicks; 10 is below the minimum.
    mutated = _mutate(ctx, clicks=10, attributed_conversions="4")
    cr = mutated["campaign.conversion_rate"]

    _assert_absent(cr, ResultStatus.INSUFFICIENT_DATA)
    # The honest state still records HOW insufficient the sample was.
    assert cr.sample_size == 10


# --------------------------------------------------------------------------- #
# Mutation 5 — break allocation conservation -> AllocationError
# --------------------------------------------------------------------------- #
def test_mutation_broken_allocation_conservation_raises():
    # A tampered allocation: two 400.00 slices of a 1000.00 source with no
    # residual sums to 800 != 1000. Conservation is enforced, not assumed.
    tampered = AllocationResult(
        policy=AllocationPolicy.PROPORTIONAL,
        source_amount="1000.00",
        currency="USD",
        targets=[
            AllocationTarget(target_id="jA", weight="1", allocated_amount="400.00"),
            AllocationTarget(target_id="jB", weight="1", allocated_amount="400.00"),
        ],
        residual="0",
    )
    with pytest.raises(AllocationError):
        tampered.assert_conserved()

    # For contrast: the honest allocation of the same source DOES conserve.
    honest = AllocationResult(
        policy=AllocationPolicy.PROPORTIONAL,
        source_amount="1000.00",
        currency="USD",
        targets=[
            AllocationTarget(target_id="jA", weight="1", allocated_amount="500.00"),
            AllocationTarget(target_id="jB", weight="1", allocated_amount="500.00"),
        ],
        residual="0",
    )
    honest.assert_conserved()  # does not raise


# --------------------------------------------------------------------------- #
# Mutation 6 — supersede a stored result -> superseded_by set + restatement chain
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_mutation_supersede_sets_chain(ctx):
    repo = ComputedResultsRepository()
    definition = get_definition("campaign.media_spend")

    prior = money_result(definition, ctx, amount="500.00", currency="USD", run_id=new_run_id())
    prior_row = await repo.insert_result(prior.model_dump(mode="json"))

    # An active result is immutable: a second active insert for the same scope is
    # rejected — the ONLY sanctioned mutation is supersession.
    with pytest.raises(ComputationConflictError):
        await repo.insert_result(prior.model_dump(mode="json"))

    # Supersede with a corrected value (a provider restatement of spend).
    corrected = money_result(
        definition, ctx, amount="480.00", currency="USD", run_id=new_run_id()
    )
    new_row = await repo.supersede(
        "t_mut", prior_row["result_id"], corrected.model_dump(mode="json"),
        reason="provider correction",
    )

    # The prior result is retained and stamped superseded_by (historical truth is
    # never overwritten); the new result points back at what it supersedes.
    prior_now = await repo.get("t_mut", prior_row["result_id"])
    assert prior_now["superseded_by"] == new_row["result_id"]
    assert new_row["supersedes_result_id"] == prior_row["result_id"]
    assert new_row["restatement_reason"] == "provider correction"

    # The active result for the scope is now the corrected one.
    active = await repo.get_active(
        "t_mut", "campaign.media_spend", "1", ctx.context_hash()
    )
    assert active["result_id"] == new_row["result_id"]
    assert active["value"] == pytest.approx(480.0)

    # The restatement chain records the correction with its reason.
    chain = await repo.restatement_chain("t_mut", new_row["result_id"])
    assert any(c["reason"] == "provider correction" for c in chain)
    assert any(c["prior_result_id"] == prior_row["result_id"] for c in chain)
