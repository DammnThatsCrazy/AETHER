"""gold_materializer journey rounding: a campaign shared by several journeys is
allocated ONCE across all of its journeys, so the persisted journey totals sum
EXACTLY to the campaign spend (program sec19 — Decimal money, never float drift).

Previously each journey ran its own two-target allocation against an artificial
``other_journeys`` bucket and rounded independently to cents: two equal journeys
over $10.01 each persisted $5.01, so the journey totals became $10.02. The fix
allocates across the real journey targets and assigns the rounding residual
deterministically to the lexicographically-first positive-weight journey.

Under test (all seed data is Decimal/string money — the engine never sees floats):
- two equal journeys over $10.01 → $5.00 + $5.01 (never two $5.01 → $10.02)
- three equal journeys over $10.01 → $3.33 + $3.34 + $3.34 (never $10.02+)
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from services.measurement import repositories as measurement_repos  # noqa: E402
from services.measurement.engine import gold_materializer  # noqa: E402
from services.measurement.repositories.attribution_run_repo import AttributionRunRepository  # noqa: E402
from services.measurement.repositories.journey_repo import JourneyRepository  # noqa: E402
from services.measurement.repositories.spend_repo import SpendRepository  # noqa: E402


@pytest.fixture(autouse=True)
async def _isolate():
    measurement_repos.spend_repo._local_store.clear()
    measurement_repos.attribution_run_repo._local_credits.clear()
    measurement_repos.attribution_run_repo._local_runs.clear()
    measurement_repos.journey_repo._local_store.clear()
    if gold_materializer._ch_client is not None:
        await gold_materializer._ch_client.close()
        gold_materializer._ch_client = None
    import services.computation.repositories as comp_repos
    comp_repos._repo_singleton = None
    yield
    measurement_repos.spend_repo._local_store.clear()
    measurement_repos.attribution_run_repo._local_credits.clear()
    measurement_repos.attribution_run_repo._local_runs.clear()
    measurement_repos.journey_repo._local_store.clear()
    if gold_materializer._ch_client is not None:
        await gold_materializer._ch_client.close()
        gold_materializer._ch_client = None
    comp_repos._repo_singleton = None


TENANT = "t-journey-round"
CAMPAIGN = "c-shared"


def _start() -> datetime:
    return datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def _end() -> datetime:
    return _start().replace(hour=23, minute=59, second=59)


async def _seed_spend(total: str) -> None:
    await SpendRepository().upsert({
        "tenant_id": TENANT,
        "campaign_id": CAMPAIGN,
        "platform": "meta",
        "period_start": _start().isoformat(),
        "period_end": _end().isoformat(),
        "billing_currency": "USD",
        "normalized_currency": "USD",
        "exchange_rate": "1.0",
        "total_cost": total,
        "idempotency_key": f"spend-{CAMPAIGN}-{total}",
    })


async def _seed_journey(journey_id: str, conversion_id: str) -> None:
    await JourneyRepository().create_version({
        "tenant_id": TENANT,
        "journey_id": journey_id,
        "profile_id": f"profile-{journey_id}",
        "campaign_ids": [CAMPAIGN],
        "conversion_ids": [conversion_id],
        "started_at": _start().isoformat(),
        "ended_at": _end().isoformat(),
        "journey_version": "v1",
    })


async def _seed_conversion(conversion_id: str, conversions: str) -> None:
    run_repo = AttributionRunRepository()
    run = await run_repo.create_run({
        "tenant_id": TENANT,
        "conversion_id": conversion_id,
        "is_active": True,
        "status": "completed",
    })
    await run_repo.insert_credits([{
        "tenant_id": TENANT,
        "attribution_run_id": run["attribution_run_id"],
        "conversion_id": conversion_id,
        "campaign_id": CAMPAIGN,
        "attributed_conversions": conversions,
        "attributed_conversion_count": conversions,
        "attributed_net_revenue": "100",
        "conversion_occurred_at": _start().replace(hour=12).isoformat(),
    }])


async def _seed_journeys_equal_weights(journey_ids: list[str]) -> None:
    await _seed_spend("10.01")
    for jid in journey_ids:
        conv = str(uuid.uuid4())
        await _seed_journey(jid, conv)
        await _seed_conversion(conv, "0.5")


async def _materialized_spend() -> dict[str, Decimal]:
    """Materialize every seeded journey and return journey_id -> ad_spend_usd
    as exact Decimal (round-tripped through the float wire column via str)."""
    ch = await gold_materializer._ch()
    # Materialize all current journeys (their ids are seeded directly).
    journey_ids = sorted({
        v["journey_id"] for v in measurement_repos.journey_repo._local_store.values()
    })
    for jid in journey_ids:
        await gold_materializer.materialize_journey_economics(TENANT, jid)
    gold = ch.get_table("gold_journey_economics")
    return {
        r["journey_id"]: Decimal(str(r["ad_spend_usd"]))
        for r in gold
    }


async def test_two_equal_journeys_conserve_10_01_exactly():
    """The Codex repro: two equal journeys over $10.01 must persist $5.00 +
    $5.01, summing EXACTLY to the campaign spend — never two $5.01 = $10.02."""
    await _seed_journeys_equal_weights(["j-a", "j-b"])
    spend = await _materialized_spend()
    assert spend == {
        "j-a": Decimal("5.00"),  # lexicographically-first receives the residual
        "j-b": Decimal("5.01"),
    }
    assert sum(spend.values(), Decimal("0")) == Decimal("10.01")


async def test_three_equal_journeys_conserve_10_01_exactly():
    """Three equal journeys: residual assigned once, sum still exactly $10.01."""
    await _seed_journeys_equal_weights(["j-a", "j-b", "j-c"])
    spend = await _materialized_spend()
    assert spend == {
        "j-a": Decimal("3.33"),  # residual receiver
        "j-b": Decimal("3.34"),
        "j-c": Decimal("3.34"),
    }
    assert sum(spend.values(), Decimal("0")) == Decimal("10.01")
