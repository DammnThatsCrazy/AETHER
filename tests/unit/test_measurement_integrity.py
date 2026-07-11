"""Measurement Integrity Plane — end-to-end through package + repo + routes.

Proves the immutable-result contract: a result carries a value_state (never a
bare 0 on missing data), supersession is the only mutation and records a
restatement, and the /v1/measurement routes surface definitions, results, and
a full explain (lineage + sufficiency + uncertainty + restatement chain).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import os  # noqa: E402

os.environ.setdefault("AETHER_ENV", "local")

from shared.measurement import (  # noqa: E402
    MeasurementResult,
    ValueState,
)

TENANT = "tenant-measure"


@pytest.fixture()
def repo():
    """Return the process singleton the route handlers use, cleared per test.

    The handlers fetch the repo via a runtime ``get_measurement_results_repository()``
    import, so the test must use that SAME accessor (not a monkeypatched
    top-level module reference, which can resolve to a different module identity
    under the full suite's sys.modules churn). Clearing every in-memory dict on
    the instance isolates each test.
    """
    from repositories.measurement_results_repo import get_measurement_results_repository

    r = get_measurement_results_repository()
    for name in list(vars(r)):
        value = getattr(r, name)
        if isinstance(value, dict):
            value.clear()
    return r


def _result(**over) -> dict:
    base = dict(
        tenant_id=TENANT,
        metric_name="conversion_rate",
        metric_version="1",
        context_hash="ctx-abc",
        value=0.25,
        value_state=ValueState.OBSERVED,
        unit="ratio",
        lineage={"inputs": ["conversions", "sessions"]},
        sufficiency={"sample_size": 40, "min_required": 30, "met": True},
    )
    base.update(over)
    return MeasurementResult(**base).model_dump(mode="json")


class _Tenant:
    def __init__(self, tid=TENANT):
        self.tenant_id = tid

    def require_permission(self, _perm):  # noqa: ANN001
        return True


class _Req:
    def __init__(self, tid=TENANT):
        self.state = type("S", (), {})()
        self.state.tenant = _Tenant(tid)


# ── repo-level immutability + supersession ───────────────────────────────────


async def test_insert_and_get_active(repo):
    rec = await repo.insert_result(_result())
    got = await repo.get(TENANT, rec["id"])
    assert got is not None and got["value_state"] == "observed"
    active = await repo.get_active(TENANT, "conversion_rate", "1", "ctx-abc")
    assert active["id"] == rec["id"]


async def test_supersede_is_the_only_mutation(repo):
    prior = await repo.insert_result(_result(value=0.25))
    new = await repo.supersede(
        TENANT, prior["id"], _result(value=0.31), reason="late-arriving conversions",
    )
    # Prior is now superseded; the new row is the active one.
    prior_now = await repo.get(TENANT, prior["id"])
    assert prior_now["superseded_by"] == new["id"]
    active = await repo.get_active(TENANT, "conversion_rate", "1", "ctx-abc")
    assert active["id"] == new["id"]
    chain = await repo.restatement_chain(TENANT, prior["id"])
    assert len(chain) >= 2


async def test_tenant_isolation(repo):
    rec = await repo.insert_result(_result())
    assert await repo.get("tenant-other", rec["id"]) is None


async def test_insufficient_data_has_no_value(repo):
    # value_state that forbids a value must round-trip with value None.
    rec = await repo.insert_result(_result(
        value=None, value_state=ValueState.INSUFFICIENT_DATA,
        sufficiency={"sample_size": 3, "min_required": 30, "met": False},
    ))
    got = await repo.get(TENANT, rec["id"])
    assert got["value"] is None
    assert got["value_state"] == "insufficient_data"


# ── route handlers ───────────────────────────────────────────────────────────


async def test_definitions_route(repo):
    from services.measurement.routes.integrity import get_measurement_definitions

    body = await get_measurement_definitions(_Req())
    data = body["data"]
    assert data["registry_version"]
    names = {d["name"] for d in data["definitions"]}
    assert "conversion_rate" in names


async def test_results_route_lists_active(repo):
    from services.measurement.routes.integrity import list_measurement_results

    await repo.insert_result(_result())
    # Pass query params explicitly: called directly (not via FastAPI), the
    # Query(...) defaults would otherwise leak as FieldInfo markers.
    body = await list_measurement_results(
        _Req(), metric_name="conversion_rate", include_superseded=False, limit=200,
    )
    assert body["data"]["count"] == 1
    assert body["data"]["results"][0]["metric_name"] == "conversion_rate"


async def test_explain_route_returns_chain(repo):
    from services.measurement.routes.integrity import explain_measurement_result

    prior = await repo.insert_result(_result(value=0.25))
    await repo.supersede(TENANT, prior["id"], _result(value=0.31), reason="restated")
    body = await explain_measurement_result(prior["id"], _Req())
    data = body["data"]
    assert data["value_state"] == "observed"
    assert "lineage" in data and "sufficiency" in data
    assert len(data["restatement_chain"]) >= 2
    assert data["superseded"] is True


async def test_explain_missing_result_404(repo):
    from services.measurement.routes.integrity import explain_measurement_result
    from shared.common.common import NotFoundError

    with pytest.raises(Exception) as exc_info:
        await explain_measurement_result("nope", _Req())
    assert type(exc_info.value).__name__ == "NotFoundError"
    _ = NotFoundError  # imported for clarity
