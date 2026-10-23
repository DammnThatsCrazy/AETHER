"""Computation repository behavior (in-memory backend): immutable insert,
supersession, restatement chain, tenant scoping."""

from __future__ import annotations

from datetime import datetime

import pytest

from intelligence.computation.repositories import (
    ComputationConflictError,
    ComputedResultsRepository,
)
from shared.computation.context import ComputationContext
from shared.computation.registry import get_definition
from shared.computation.runtime import money_result, new_run_id


@pytest.fixture()
def repo():
    return ComputedResultsRepository()


@pytest.fixture()
def ctx():
    return ComputationContext(tenant_id="t1", grain="campaign_day",
                             event_time_start="2026-01-01T00:00:00+00:00")


def _result(ctx, amount="100.00"):
    d = get_definition("campaign.media_spend")
    r = money_result(d, ctx, amount=amount, currency="USD", run_id=new_run_id())
    return r.model_dump(mode="json")


async def test_insert_and_get(repo, ctx):
    rec = await repo.insert_result(_result(ctx))
    got = await repo.get("t1", rec["result_id"])
    assert got is not None
    assert got["value"] == 100.0
    # tenant scoping
    assert await repo.get("other", rec["result_id"]) is None


async def test_active_duplicate_rejected(repo, ctx):
    await repo.insert_result(_result(ctx))
    with pytest.raises(ComputationConflictError):
        await repo.insert_result(_result(ctx, amount="200.00"))


async def test_supersede_preserves_prior_and_chains(repo, ctx):
    prior = await repo.insert_result(_result(ctx, amount="100.00"))
    new = await repo.supersede(
        "t1", prior["result_id"], _result(ctx, amount="150.00"),
        reason="provider correction",
    )
    # prior is retained, stamped superseded_by; new is active.
    prior_now = await repo.get("t1", prior["result_id"])
    assert prior_now["superseded_by"] == new["result_id"]
    active = await repo.get_active(
        "t1", "campaign.media_spend", "1", ctx.context_hash()
    )
    assert active["result_id"] == new["result_id"]
    assert active["value"] == 150.0
    # a fresh active insert is now allowed (the old one is superseded).
    chain = await repo.restatement_chain("t1", new["result_id"])
    assert any(c["reason"] == "provider correction" for c in chain)


async def test_list_excludes_superseded_by_default(repo, ctx):
    prior = await repo.insert_result(_result(ctx, amount="100.00"))
    await repo.supersede("t1", prior["result_id"], _result(ctx, amount="150.00"),
                         reason="fix")
    active = await repo.list_for_tenant("t1", definition_id="campaign.media_spend")
    assert len(active) == 1
    allrows = await repo.list_for_tenant(
        "t1", definition_id="campaign.media_spend", include_superseded=True
    )
    assert len(allrows) == 2


async def test_list_for_subject_filters_exact_tenant_kind_and_id_before_limit(repo):
    rows = [
        {
            "result_id": "journey-a", "definition_id": "campaign.attributed_gross_revenue",
            "definition_version": "1", "tenant_id": "t1", "status": "available",
            "context_hash": "ctx-journey-a", "computed_at": "2026-10-18T11:00:00Z",
            "dimensions": {"subject_type": "journey", "subject_id": "journey-a"}, "value": 1,
        },
        {
            "result_id": "same-id-campaign", "definition_id": "campaign.attributed_gross_revenue",
            "definition_version": "1", "tenant_id": "t1", "status": "available",
            "context_hash": "ctx-campaign", "computed_at": "2026-10-18T12:00:00Z",
            "dimensions": {"subject_type": "campaign", "subject_id": "journey-a"}, "value": 2,
        },
        {
            "result_id": "foreign-tenant-journey",
            "definition_id": "campaign.attributed_gross_revenue",
            "definition_version": "1", "tenant_id": "t2", "status": "available",
            "context_hash": "ctx-foreign", "computed_at": "2026-10-18T13:00:00Z",
            "dimensions": {"subject_type": "journey", "subject_id": "journey-a"}, "value": 3,
        },
        {
            "result_id": "other-journey", "definition_id": "campaign.attributed_gross_revenue",
            "definition_version": "1", "tenant_id": "t1", "status": "available",
            "context_hash": "ctx-other", "computed_at": "2026-10-18T14:00:00Z",
            "dimensions": {"subject_type": "journey", "subject_id": "journey-b"}, "value": 4,
        },
    ]
    for row in rows:
        await repo.insert_result(row)

    exact = await repo.list_for_subject("t1", "journey", "journey-a", limit=1)

    assert [row["result_id"] for row in exact] == ["journey-a"]


async def test_postgres_list_for_subject_scopes_before_limit(monkeypatch):
    import json

    from intelligence.computation import repositories

    class FakePool:
        query = ""
        args = ()

        async def execute(self, _query):
            return "OK"

        async def fetch(self, query, *args):
            self.query = query
            self.args = args
            return [{"data": json.dumps({"result_id": "exact"})}]

    pool = FakePool()

    async def get_pool():
        return pool

    monkeypatch.setattr(repositories, "get_pool", get_pool)
    got = await ComputedResultsRepository().list_for_subject(
        "t1", "journey", "journey-a", limit=201
    )

    assert [row["result_id"] for row in got] == ["exact"]
    assert "tenant_id=$1" in pool.query
    assert "data->'dimensions'->>'subject_type'=$2" in pool.query
    assert "data->'dimensions'->>'subject_id'=$3" in pool.query
    assert pool.query.index("subject_id'=$3") < pool.query.index("LIMIT $4")
    assert pool.args == ("t1", "journey", "journey-a", 201)


async def test_run_roundtrip(repo):
    run = await repo.insert_run(
        {"tenant_id": "t1", "definition_id": "campaign.ctr", "definition_version": "1",
         "status": "completed"}
    )
    got = await repo.get_run("t1", run["run_id"])
    assert got["status"] == "completed"
    assert await repo.get_run("other", run["run_id"]) is None


async def test_list_runs_for_subject_scopes_before_limit_and_as_of(repo):
    base = {
        "definition_version": "1",
        "status": "completed",
        "data": {
            "subject_kind": "entity",
            "subject_id": "entity-a",
            "assessment_id": "assessment-a",
        },
    }
    await repo.insert_run(
        {
            **base,
            "tenant_id": "t1",
            "definition_id": "risk360.standard",
            "started_at": "2026-10-20T12:00:00+00:00",
        }
    )
    await repo.insert_run(
        {
            **base,
            "tenant_id": "t1",
            "definition_id": "campaign.ctr",
            "started_at": "2026-10-20T11:00:00+00:00",
        }
    )
    await repo.insert_run(
        {
            **base,
            "tenant_id": "t2",
            "definition_id": "risk360.standard",
            "started_at": "2026-10-20T10:00:00+00:00",
        }
    )
    await repo.insert_run(
        {
            **base,
            "tenant_id": "t1",
            "definition_id": "risk360.standard",
            "started_at": "2026-10-22T12:00:00+00:00",
        }
    )

    rows = await repo.list_runs_for_subject(
        "t1",
        "entity",
        "entity-a",
        definition_prefix="risk360.",
        limit=10,
        as_of=datetime.fromisoformat("2026-10-21T00:00:00+00:00"),
    )

    assert len(rows) == 1
    assert rows[0]["tenant_id"] == "t1"
    assert rows[0]["definition_id"] == "risk360.standard"
    assert rows[0]["data"]["subject_id"] == "entity-a"


async def test_postgres_list_runs_for_subject_scopes_before_limit(monkeypatch):
    import json

    from intelligence.computation import repositories

    class FakePool:
        query = ""
        args = ()

        async def execute(self, _query):
            return "OK"

        async def fetch(self, query, *args):
            self.query = query
            self.args = args
            return [{"data": json.dumps({"run_id": "run-a"})}]

    pool = FakePool()

    async def get_pool():
        return pool

    monkeypatch.setattr(repositories, "get_pool", get_pool)
    as_of = datetime.fromisoformat("2026-10-21T00:00:00+00:00")
    rows = await ComputedResultsRepository().list_runs_for_subject(
        "t1", "entity", "entity-a", definition_prefix="risk360.", limit=101, as_of=as_of
    )

    assert rows == [{"run_id": "run-a"}]
    assert "tenant_id=$1" in pool.query
    assert "definition_id LIKE $2" in pool.query
    assert "data->'data'->>'subject_kind'=$3" in pool.query
    assert "data->'data'->>'subject_id'=$4" in pool.query
    assert "started_at <= $5" in pool.query
    assert pool.query.index("subject_id'=$4") < pool.query.index("LIMIT $6")
    assert pool.args == ("t1", "risk360.%", "entity", "entity-a", as_of, 101)
