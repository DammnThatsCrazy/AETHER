"""GraphMutationGateway rights-decision-ref seam (backward compatible).

The gateway write path gained an additive, optional ``MutationIntent
.rights_decision_ref`` that surfaces a governing Rights Authority decision ref
on the versioned fact payload annotation — never on the projected edge/vertex.
These tests pin two properties:

1. **Backward compatibility** — existing writes that leave the field ``None``
   produce a fact payload byte-identical to before (no ``rights_decision_ref``
   key), in every mode.
2. **Propagation** — when the field IS set, the ref rides the durable fact
   payload while graph topology stays untouched and the typed MutationRecord /
   ledger columns are unchanged (promoting the ref onto MutationRecord + the
   ledger DDL is the spine producer program's boundary).
"""

from __future__ import annotations

import dataclasses

import pytest

from config.settings import settings
from repositories.graph_mutation_ledger import (
    GraphMutationLedgerRepository,
    reset_graph_ledger_memory,
)
from shared.graph.edge_properties import build_edge_properties
from shared.graph.graph import Edge, GraphClient
from shared.graph.mutation_gateway import GraphMutationGateway, MutationIntent

TENANT = "tenant_rights_ref"
VALID_FROM = "2026-07-01T00:00:00+00:00"


@pytest.fixture(autouse=True)
def _reset_ledger():
    """Every test starts against an empty in-memory ledger."""
    reset_graph_ledger_memory()
    yield
    reset_graph_ledger_memory()


@pytest.fixture()
def mode(monkeypatch):
    """Pin the gateway mode ladder for the duration of a test."""

    def _set(mode_name: str) -> str:
        monkeypatch.setattr(
            settings,
            "temporal_observatory",
            dataclasses.replace(
                settings.temporal_observatory, mutation_gateway_mode=mode_name
            ),
        )
        return mode_name

    return _set


def _edge(*, source_event_id: str = "evt-gw") -> Edge:
    props = build_edge_properties(
        tenant_id=TENANT,
        edge_type="SAME_AS",
        from_vertex_id="entity_a",
        to_vertex_id="entity_b",
        actor_kind="system",
        actor_id="identity_resolver",
        provenance="test",
        valid_from=VALID_FROM,
        confidence=0.9,
        source_event_id=source_event_id,
    )
    return Edge(
        edge_type="SAME_AS",
        from_vertex_id="entity_a",
        to_vertex_id="entity_b",
        properties=props,
    )


def _gateway() -> tuple[GraphMutationGateway, GraphClient, GraphMutationLedgerRepository]:
    client = GraphClient()
    ledger = GraphMutationLedgerRepository()
    return GraphMutationGateway(graph_client=client, ledger=ledger), client, ledger


# ── Backward compatibility: no ref → fact payload identical to before ─────────


@pytest.mark.asyncio
async def test_write_without_rights_ref_is_unchanged(mode) -> None:
    mode("shadow")
    gateway, client, ledger = _gateway()
    await gateway.apply(
        MutationIntent(operation="edge_created", tenant_id=TENANT, edge=_edge())
    )

    rows = await ledger.list_records(TENANT)
    assert len(rows) == 1
    payload = rows[0]["payload"]
    # No rights_decision_ref key is injected when the caller did not set it.
    assert "rights_decision_ref" not in payload
    assert payload["kind"] == "edge"
    assert payload["edge_type"] == "SAME_AS"
    assert len(await client.get_edges("entity_a")) == 1


@pytest.mark.asyncio
async def test_off_mode_with_new_field_defaults_to_prior_behavior(mode) -> None:
    """Even a caller that passes the field explicitly is unaffected in off
    mode: zero ledger, projection exactly as a direct write."""
    mode("off")
    gateway, client, ledger = _gateway()
    bare = Edge(
        edge_type="SAME_AS",
        from_vertex_id="entity_a",
        to_vertex_id="entity_b",
        properties={"tenant_id": TENANT},
    )
    await gateway.apply(
        MutationIntent(
            operation="edge_created",
            tenant_id=TENANT,
            edge=bare,
            rights_decision_ref="rdec_governs",
        )
    )
    assert await ledger.list_records(TENANT) == []
    edges = await client.get_edges("entity_a")
    assert len(edges) == 1
    assert edges[0].properties == {"tenant_id": TENANT}  # off = byte-identical


# ── Propagation: a governing rights ref can ride the mutation ─────────────────


@pytest.mark.asyncio
async def test_rights_decision_ref_rides_fact_payload_annotation(mode) -> None:
    mode("shadow")
    gateway, client, ledger = _gateway()
    outcome = await gateway.apply(
        MutationIntent(
            operation="edge_created",
            tenant_id=TENANT,
            edge=_edge(),
            rights_decision_ref="rdec_governs_1",
        )
    )
    assert outcome.applied and outcome.ledger_recorded

    rows = await ledger.list_records(TENANT)
    assert len(rows) == 1
    assert rows[0]["payload"]["rights_decision_ref"] == "rdec_governs_1"

    # Graph topology is untouched: the ref is governance metadata on the
    # mutation, never a property on the projected edge or the ledger fact props.
    edges = await client.get_edges("entity_a")
    assert len(edges) == 1
    assert "rights_decision_ref" not in edges[0].properties
    assert "rights_decision_ref" not in rows[0]["payload"]["properties"]


@pytest.mark.asyncio
async def test_enforce_mode_records_the_rights_ref(mode) -> None:
    mode("enforce")
    gateway, _client, ledger = _gateway()
    outcome = await gateway.apply(
        MutationIntent(
            operation="edge_created",
            tenant_id=TENANT,
            edge=_edge(),
            rights_decision_ref="rdec_governs_2",
        )
    )
    assert outcome.applied and outcome.ledger_recorded
    rows = await ledger.list_records(TENANT)
    assert rows[0]["payload"]["rights_decision_ref"] == "rdec_governs_2"


@pytest.mark.asyncio
async def test_different_writes_carry_their_own_refs(mode) -> None:
    """Two writes in one tenant keep distinct governing refs; a write with no
    ref stays indistinguishable from a pre-seam write even alongside one."""
    mode("shadow")
    gateway, _client, ledger = _gateway()
    await gateway.apply(
        MutationIntent(
            operation="edge_created",
            tenant_id=TENANT,
            edge=_edge(source_event_id="evt-1"),
            rights_decision_ref="rdec_a",
        )
    )
    await gateway.apply(
        MutationIntent(
            operation="edge_created",
            tenant_id=TENANT,
            edge=_edge(source_event_id="evt-2"),
        )
    )
    rows = await ledger.list_records(TENANT)
    refs = [row["payload"].get("rights_decision_ref") for row in rows]
    assert refs == ["rdec_a", None]


# ── Default value: the field exists, defaults to None, never required ─────────


def test_intent_field_is_additive_and_defaults_to_none() -> None:
    intent = MutationIntent(operation="edge_created", tenant_id=TENANT, edge=_edge())
    assert intent.rights_decision_ref is None
    with_ref = MutationIntent(
        operation="edge_created",
        tenant_id=TENANT,
        edge=_edge(),
        rights_decision_ref="rdec_default",
    )
    assert with_ref.rights_decision_ref == "rdec_default"
    assert intent.rights_decision_ref is None  # existing callers unaffected
