"""Persistence tests (M7) — consume-only over the Computation Substrate.

Fidelity vectors persist through ``services/computation/repositories.py``
(``ComputedResultsRepository``): one immutable ``CanonicalResult`` per
materialized dimension + a run record carrying the assembled vector document.
No new DDL/table is introduced. Under ``AETHER_ENV=local`` the repository uses
its in-memory backend, so these tests require no database.
"""

from __future__ import annotations

import asyncio

import pytest

from services.computation.repositories import (
    ComputationConflictError,
    get_computation_repository,
)
from services.relationship_fidelity.engine import RelationshipFidelityEngine
from shared.relationship_fidelity.evidence import Observation

engine = RelationshipFidelityEngine()


def _obs(oid: str, src: str = "src-a") -> Observation:
    return Observation(
        observation_id=oid,
        predicate="FOLLOWS",
        direction="outgoing",
        source_key=src,
        observed_at="2026-08-01T00:00:00Z",
    )


def test_persist_writes_run_and_materialized_dimension_results():
    relationship_ref = "rel:p1"
    vec = engine.compute_fidelity(
        relationship_ref=relationship_ref,
        observations=[_obs("o1"), _obs("o2", "src-b")],
        window_seconds=86400 * 30,
        measured={"identity_confidence": 0.6},
    )
    assert vec.materialized_dimension_count >= 1

    async def _run():
        repo = get_computation_repository()
        rec = await engine.persist_fidelity(tenant_id="tenant-p", vector=vec)
        run = await repo.get_run("tenant-p", rec["run_id"])
        rows = await repo.list_for_tenant("tenant-p")
        return rec, run, rows

    rec, run, rows = asyncio.run(_run())
    assert rec["run_id"]
    assert run is not None
    assert run["data"]["kind"] == "fidelity_vector_surface"
    assert run["data"]["relationship_ref"] == relationship_ref
    materialized_defs = {
        f"relationship_fidelity.{dim}" for dim, v in vec.dimension_values().items() if v is not None
    }
    assert set(rec["inserted_definition_ids"]) == materialized_defs
    # the materialized dimension results are present as active computed_results rows
    assert materialized_defs <= {r.get("definition_id") for r in rows}


def test_persist_without_supersede_rejects_duplicate_active_result():
    relationship_ref = "rel:p2"
    vec = engine.compute_fidelity(
        relationship_ref=relationship_ref,
        observations=[_obs("o1"), _obs("o2", "src-b")],
        window_seconds=86400 * 30,
    )

    async def _run():
        await engine.persist_fidelity(tenant_id="tenant-p2", vector=vec)
        with pytest.raises(ComputationConflictError):
            # same active key (tenant/definition/version/context_hash) without
            # supersession must be rejected — immutable append-only substrate.
            await engine.persist_fidelity(tenant_id="tenant-p2", vector=vec)

    asyncio.run(_run())
