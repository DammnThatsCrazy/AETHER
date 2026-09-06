"""Profile360 financial-normalization regression tests (unknown never 0).

Covers the domain-lane invariants:
  * A record whose amount fails to parse (non-numeric / absent) contributes
    nothing to a profile aggregate — the rollup never fabricates a 0.
  * An explicit ``"0"`` amount is preserved (a real zero, not an unknown).
  * The aggregator's financial rollup can carry an additive
    ``reporting_totals`` block keyed by the tenant's reporting asset while
    ``total_usd`` (and the USD-first summary) stays intact.
"""

from __future__ import annotations

import asyncio
import os
import sys
from decimal import Decimal

os.environ.setdefault("AETHER_ENV", "local")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from services.profile.aggregator import Profile360Aggregator  # noqa: E402
from services.profile.economic import AgentProfile360EconomicComposer  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


# ── In-memory stub repositories (no DB) ──────────────────────────────


class _Repo:
    """Minimal BaseRepository surface used by the aggregator's financial reads."""

    def __init__(self, rows=None):
        self._rows = list(rows or [])

    async def find_many(self, filters=None, limit=50, **_):
        f = filters or {}

        def _matches(row):
            for k, v in f.items():
                if k == "tenant_id" and v in (None, ""):
                    if row.get("tenant_id") not in (None, ""):
                        return False
                    continue
                if row.get(k) != v:
                    return False
            return True

        return [r for r in self._rows if _matches(r)][:limit]


class _NoRows:
    async def find_many(self, *a, **k):
        return []

    async def list_for_agent(self, *a, **k):
        return []

    async def active_for(self, *a, **k):
        return []

    async def find_for_agent(self, *a, **k):
        return None

    async def find_by_id(self, *a, **k):
        return None


def _intents_repo(rows):
    class _Intents:
        def __init__(self):
            self._rows = list(rows)

        async def list_for_agent(self, agent_id, tenant_id, limit=100):
            return [
                r for r in self._rows
                if r.get("agent_id") == agent_id and r.get("tenant_id") == tenant_id
            ][:limit]

    return _Intents()


def _economic_composer(intent_rows):
    return AgentProfile360EconomicComposer(
        payment_intents=_intents_repo(intent_rows),
        settlements=_NoRows(),
        economic_identities=_NoRows(),
        executions=_NoRows(),
        delegations=_NoRows(),
        behavior_profiles=_NoRows(),
    )


# ── Unknown/unparseable amount never fabricates a zero ───────────────


def test_economic_composer_unparseable_settled_amount_contributes_nothing():
    """An invalid-parse settled intent yields no spend_by_currency entry at all.

    Regression for the old ``_decimal()`` -> ``Decimal("0")`` coercion, which
    used to fabricate ``{"USD": "0"}`` from an unparseable amount.
    """
    composer = _economic_composer([
        {
            "intent_id": "p-bad",
            "tenant_id": "t-a",
            "agent_id": "a1",
            "settlement_status": "settled",
            "currency": "USD",
            "amount": "not-a-number",
        },
    ])
    profile = _run(composer.compose("a1", "t-a"))
    assert profile["economic"]["spend_by_currency"] == {}


def test_economic_composer_unparseable_amount_skipped_valid_kept():
    """Valid settled amounts still sum; the unparseable one is simply skipped."""
    composer = _economic_composer([
        {
            "intent_id": "p-ok",
            "tenant_id": "t-a",
            "agent_id": "a1",
            "settlement_status": "settled",
            "currency": "USD",
            "amount": "5.50",
        },
        {
            "intent_id": "p-bad",
            "tenant_id": "t-a",
            "agent_id": "a1",
            "settlement_status": "settled",
            "currency": "USD",
            "amount": "garbage",
        },
    ])
    profile = _run(composer.compose("a1", "t-a"))
    assert profile["economic"]["spend_by_currency"] == {"USD": "5.50"}


def test_economic_composer_explicit_zero_is_preserved():
    """A parseable ``"0"`` is an explicit zero and still appears (not an unknown)."""
    composer = _economic_composer([
        {
            "intent_id": "p-zero",
            "tenant_id": "t-a",
            "agent_id": "a1",
            "settlement_status": "settled",
            "currency": "USD",
            "amount": "0",
        },
    ])
    profile = _run(composer.compose("a1", "t-a"))
    assert profile["economic"]["spend_by_currency"] == {"USD": "0"}


def test_economic_composer_unparseable_abandoned_amount_contributes_nothing():
    """Invalid-parse abandoned value never fabricates a zero either."""
    composer = _economic_composer([
        {
            "intent_id": "p-ab",
            "tenant_id": "t-a",
            "agent_id": "a1",
            "settlement_status": "abandoned",
            "abandoned_reason": "price_above_threshold",
            "currency": "USD",
            "amount": "n/a",
        },
    ])
    profile = _run(composer.compose("a1", "t-a"))
    assert profile["economic"]["abandoned_value_by_currency"] == {}


def test_aggregator_financials_unparseable_transfer_is_not_a_fabricated_zero():
    """An amount that fails to parse is excluded — total_usd stays None, not "0"."""
    tenant = "t-a"
    entity = "user-1"
    transfers = _Repo([
        {
            "id": "tr-bad", "transfer_id": "tr-bad", "tenant_id": tenant,
            "from_entity_id": "other", "to_entity_id": entity,
            "amount": "not-a-number", "asset_id": "GBP", "amount_usd": "999",
            "occurred_at": "2026-03-01T00:00:00Z",
        },
    ])
    agg = Profile360Aggregator(
        transfer_repo=transfers,
        agent_config_repo=_Repo([]),
        payment_intent_repo=_Repo([]),
        settlement_repo=_Repo([]),
    )
    out = _run(agg.financials(entity, tenant))
    val = out["summary"]["valuation"]
    assert out["summary"]["inflow_usd"] is None
    assert val["inflow"]["total_usd"] is None
    assert val["inflow"]["total_usd"] != "0"
    assert val["inflow"]["excluded_count"] == 1


# ── Reporting-asset-keyed rollups over the profile financial path ────


def _gbp_amount(record):
    """Faithful resolver: a native-GBP record's amount is already GBP (no FX guess).

    Records not denominated in the reporting asset return None (unpriced-for-
    reporting), mirroring the W4a resolver contract.
    """
    cur = record.get("asset_id") or record.get("currency")
    if cur == "GBP":
        return Decimal(record["amount"])
    return None


def _gbp_financials_aggregator(tenant="t-a", entity="user-1"):
    transfers = _Repo([
        {
            "id": "tg-in", "transfer_id": "tg-in", "tenant_id": tenant,
            "from_entity_id": "other", "to_entity_id": entity,
            "amount": "150", "asset_id": "GBP", "amount_usd": "195",
            "occurred_at": "2026-03-01T00:00:00Z",
        },
        {
            "id": "tg-out", "transfer_id": "tg-out", "tenant_id": tenant,
            "from_entity_id": entity, "to_entity_id": "other",
            "amount": "40", "asset_id": "GBP", "amount_usd": "52",
            "occurred_at": "2026-03-02T00:00:00Z",
        },
    ])
    return Profile360Aggregator(
        transfer_repo=transfers,
        agent_config_repo=_Repo([]),
        payment_intent_repo=_Repo([]),
        settlement_repo=_Repo([]),
    )


def test_financials_default_rollup_is_byte_identical_usd_first():
    """No reporting context => no additive reporting_totals block."""
    agg = _gbp_financials_aggregator()
    out = _run(agg.financials("user-1", "t-a"))
    val = out["summary"]["valuation"]
    assert val["inflow"]["total_usd"] == "195"
    assert val["outflow"]["total_usd"] == "52"
    assert "reporting_totals" not in val["inflow"]
    assert "reporting_totals" not in val["outflow"]
    assert "reporting_totals" not in val["settled"]


def test_financials_gbp_reporting_context_keys_totals_and_keeps_usd():
    """With a GBP tenant reporting asset the rollup carries a
    ``reporting_totals["fiat:GBP"]`` block while total_usd / *_usd stay intact."""
    agg = _gbp_financials_aggregator()
    out = _run(agg.financials(
        "user-1", "t-a",
        reporting_asset_id="fiat:GBP",
        amount_in_reporting_asset=_gbp_amount,
    ))
    summary = out["summary"]
    # Trusted USD totals remain the source of truth.
    assert summary["inflow_usd"] == "195"
    assert summary["outflow_usd"] == "52"
    assert summary["net_usd"] == "143"
    val = summary["valuation"]
    assert val["inflow"]["total_usd"] == "195"
    assert val["outflow"]["total_usd"] == "52"
    assert val["inflow"]["native_currency"] == "GBP"

    # Additive reporting block, keyed by the tenant's reporting asset.
    rt_in = val["inflow"]["reporting_totals"]["fiat:GBP"]
    assert rt_in["total"] == "150"
    assert rt_in["priced_count"] == 1
    assert rt_in["unpriced_count"] == 0
    assert rt_in["rollup_status"] == "complete"

    rt_out = val["outflow"]["reporting_totals"]["fiat:GBP"]
    assert rt_out["total"] == "40"
    assert rt_out["priced_count"] == 1

    # The USD-first top-level keys are all still present.
    for key in ("inflow_total", "outflow_total", "net", "rollup_status", "by_native_currency"):
        assert key in summary


def test_financials_gbp_context_unparseable_never_reports_fabricated_reporting_zero():
    """In the reporting context, unparseable amounts still contribute nothing."""
    tenant = "t-a"
    entity = "user-1"
    transfers = _Repo([
        {
            "id": "tg-in", "transfer_id": "tg-in", "tenant_id": tenant,
            "from_entity_id": "other", "to_entity_id": entity,
            "amount": "150", "asset_id": "GBP", "amount_usd": "195",
            "occurred_at": "2026-03-01T00:00:00Z",
        },
        {
            "id": "tr-bad", "transfer_id": "tr-bad", "tenant_id": tenant,
            "from_entity_id": "other", "to_entity_id": entity,
            "amount": "oops", "asset_id": "GBP", "amount_usd": "999",
            "occurred_at": "2026-03-03T00:00:00Z",
        },
    ])
    agg = Profile360Aggregator(
        transfer_repo=transfers,
        agent_config_repo=_Repo([]),
        payment_intent_repo=_Repo([]),
        settlement_repo=_Repo([]),
    )
    out = _run(agg.financials(
        entity, tenant,
        reporting_asset_id="fiat:GBP",
        amount_in_reporting_asset=_gbp_amount,
    ))
    val = out["summary"]["valuation"]
    assert val["inflow"]["total_usd"] == "195"
    rt = val["inflow"]["reporting_totals"]["fiat:GBP"]
    assert rt["total"] == "150"
    assert rt["priced_count"] == 1
    assert rt["total"] != "0"
