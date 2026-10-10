"""apps/public-site/src/site/plans.json mirrors the backend plan catalog.

The unified site's pricing page and /app signup read plan prices and limits
from plans.json. The backend catalog (shared/plans/catalog.py) is the source of
truth and matches the Stripe product catalog, so any drift fails here.
"""

from __future__ import annotations

import json
import sys
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "services" / "backend"
PLANS_JSON = ROOT / "apps" / "public-site" / "src" / "site" / "plans.json"

SELF_SERVE = ("alpha", "beta", "gamma", "delta")
CONTRACT = ("epsilon", "omicron", "omega")


@contextmanager
def backend_path():
    original = list(sys.path)
    original_mods = set(sys.modules.keys())
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original
        for name in list(sys.modules):
            if name not in original_mods:
                sys.modules.pop(name, None)


def _catalog():
    with backend_path():
        from shared.plans.catalog import PLAN_CATALOG

        return {plan.plan_id: plan for plan in PLAN_CATALOG.values()}


def test_plan_ids_and_order_match_the_catalog():
    site = json.loads(PLANS_JSON.read_text())
    assert [p["id"] for p in site["self_serve"]] == list(SELF_SERVE)
    assert [p["id"] for p in site["contract"]] == list(CONTRACT)
    assert set(_catalog()) == set(SELF_SERVE) | set(CONTRACT)


def test_self_serve_prices_and_limits_match_the_catalog():
    catalog = _catalog()
    for row in json.loads(PLANS_JSON.read_text())["self_serve"]:
        plan = catalog[row["id"]]
        assert row["name"] == plan.display_name
        assert Decimal(row["monthly"]) == plan.pricing.monthly, row["id"]
        assert Decimal(row["annual"]) == plan.pricing.annual, row["id"]
        assert row["monthly_quota"] == plan.monthly_quota, row["id"]
        assert row["member_cap"] == plan.member_cap, row["id"]
        assert row["burst_rpm"] == plan.burst_rpm, row["id"]
        assert row["service_count"] == plan.service_count, row["id"]
        assert Decimal(row["event_overage_per_1k"]) == plan.event_overage_per_1k, row["id"]


def test_contract_plans_match_the_catalog():
    catalog = _catalog()
    for row in json.loads(PLANS_JSON.read_text())["contract"]:
        plan = catalog[row["id"]]
        assert row["name"] == plan.display_name
        assert row["monthly_quota"] == plan.monthly_quota, row["id"]
