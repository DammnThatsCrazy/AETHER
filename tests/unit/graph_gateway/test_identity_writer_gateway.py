"""Pattern proof: the identity graph writer routes its graph mirror through
the canonical mutation gateway (WP2.5) with proper MutationRecord metadata,
while keeping repo-backed behavior identical in off/shadow modes."""

from __future__ import annotations

import pytest

from repositories.graph_mutation_ledger import (
    GraphMutationLedgerRepository,
    reset_graph_ledger_memory,
)
from repositories.repos import reset_in_memory_stores
from services.identity.graph_writer import IdentityGraphWriter
from services.identity.metrics import IdentityMetrics
from services.identity.models import (
    ConfidenceTier,
    IdentityResolutionDecision,
    MergeDecision,
)
from services.identity.repository import IdentityResolutionRepository
from shared.graph.graph import GraphClient
from shared.graph.mutation_gateway import GraphMutationGateway

TENANT = "tenant_identity_gw"


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()
    reset_graph_ledger_memory()
    yield
    reset_in_memory_stores()
    reset_graph_ledger_memory()


@pytest.fixture
def set_mode(monkeypatch):
    def _set(mode: str) -> None:
        import config.settings as settings_module

        monkeypatch.setattr(
            settings_module.settings,
            "temporal_observatory",
            settings_module.TemporalObservatoryConfig(mutation_gateway_mode=mode),
        )

    return _set


def _writer() -> tuple[IdentityGraphWriter, GraphClient, GraphMutationLedgerRepository]:
    repo = IdentityResolutionRepository()
    client = GraphClient()
    ledger = GraphMutationLedgerRepository()
    writer = IdentityGraphWriter(
        repo,
        IdentityMetrics(),
        graph_client=client,
        mutation_gateway=GraphMutationGateway(graph_client=client, ledger=ledger),
    )
    return writer, client, ledger


def _merge_decision() -> IdentityResolutionDecision:
    return IdentityResolutionDecision(
        tenant_id=TENANT,
        canonical_entity_id="entity_canonical",
        decision=MergeDecision.MERGE,
        confidence=0.97,
        confidence_tier=ConfidenceTier.DETERMINISTIC,
        reason_codes=["same_user_id"],
        candidate_entity_ids=["entity_fragment"],
    )


@pytest.mark.asyncio
async def test_merge_mirror_is_ledgered_as_identity_merged(set_mode):
    set_mode("shadow")
    writer, client, ledger = _writer()
    written = await writer.write_decision(_merge_decision(), source_event_ids=["evt-9"])
    assert len(written) == 1

    # Projection (unchanged behavior): the SAME_AS mirror edge exists.
    edges = await client.get_edges("entity_fragment")
    assert [e.edge_type for e in edges] == ["same_as"]
    props = edges[0].properties
    # The mirror now carries the full required property set.
    assert props["idempotency_key"] and props["actor_kind"] == "system"
    assert props["source_event_id"] == "evt-9"

    # Ledger: one identity_merged record with identity evidence metadata.
    rows = await ledger.list_records(TENANT)
    assert len(rows) == 1
    row = rows[0]
    assert row["operation"] == "identity_merged"
    assert row["aggregate_id"] == "same_as:entity_fragment:entity_canonical"
    assert row["causality_class"] == "observed_sequence"
    assert row["reason_code"] == "same_user_id"
    assert row["evidence_refs"] == ["evt-9"]
    assert row["confidence"] == pytest.approx(0.97)


@pytest.mark.asyncio
async def test_split_mirror_is_ledgered_as_identity_split(set_mode):
    set_mode("shadow")
    writer, client, ledger = _writer()
    await writer.write_decision(_merge_decision(), source_event_ids=["evt-9"])

    revoked = await writer.revoke_edges_after_split(TENANT, "entity_fragment")
    assert len(revoked) == 1
    # Graph mirror: the SAME_AS edge is soft-revoked (hidden by default).
    assert await client.get_edges("entity_fragment") == []
    rows = await ledger.list_records(TENANT)
    assert [r["operation"] for r in rows] == ["identity_merged", "identity_split"]
    assert rows[1]["reason_code"] == "fragment_split"
    assert rows[1]["payload"]["kind"] == "edge_revocation"


@pytest.mark.asyncio
async def test_off_mode_keeps_writer_behavior_with_zero_ledger(set_mode):
    set_mode("off")
    writer, client, ledger = _writer()
    written = await writer.write_decision(_merge_decision(), source_event_ids=["evt-9"])
    assert len(written) == 1
    assert len(await client.get_edges("entity_fragment")) == 1
    assert await ledger.list_records(TENANT) == []  # off = zero ledger writes


@pytest.mark.asyncio
async def test_writer_without_graph_client_never_touches_gateway(set_mode):
    set_mode("shadow")
    repo = IdentityResolutionRepository()
    writer = IdentityGraphWriter(repo, IdentityMetrics())  # no graph client
    written = await writer.write_decision(_merge_decision(), source_event_ids=["evt-9"])
    assert len(written) == 1  # repo write still happens
    ledger = GraphMutationLedgerRepository()
    assert await ledger.list_records(TENANT) == []
