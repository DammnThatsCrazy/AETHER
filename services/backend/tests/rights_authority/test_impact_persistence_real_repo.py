"""Regression: impact/decision persistence survives the REAL repository boundary.

``impact.persist_impact_items`` and the revocation pipeline emit row *dicts*,
while the durable repositories are model-typed. The repositories normalize
model-or-dict so the live path (now reachable via the mounted /v1/rights router)
never crashes with ``'dict' object has no attribute 'model_dump'``.
"""
from __future__ import annotations

import pytest

from services.rights_authority import impact
from services.rights_authority.repositories import (
    rights_decision_repository,
    rights_impact_repository,
)


@pytest.mark.asyncio
async def test_persist_impact_items_records_through_real_repo():
    items = impact.compute_rights_impact("t1", grant_id="g_1")
    assert items, "cascade should produce impact items"

    ids = await impact.persist_impact_items(items)
    assert len(ids) == len(items)

    row = await rights_impact_repository.get(ids[0])
    assert row is not None
    assert row.get("tenant_id") == "t1"
    assert row.get("grant_id") == "g_1"


@pytest.mark.asyncio
async def test_revocation_deny_decision_dict_records_through_real_repo():
    # Mirrors the revocation pipeline's deny-decision row (a dict, not a model).
    from shared.common.common import utc_now

    now_iso = utc_now().isoformat()
    row = {
        "decision_id": "rdec_regression_1",
        "tenant_id": "t1",
        "allowed": False,
        "disposition": "deny",
        "reason_codes": ["grant_revoked:test"],
        "evaluated_at": now_iso,
        "effective_as_of": now_iso,
        "policy_version": "irrl-2",
    }
    await rights_decision_repository.record(row)
    got = await rights_decision_repository.get("rdec_regression_1")
    assert got is not None
    assert got.get("tenant_id") == "t1"
    assert got.get("allowed") is False
