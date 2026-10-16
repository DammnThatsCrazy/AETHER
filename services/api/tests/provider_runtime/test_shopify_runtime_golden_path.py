"""Golden path through the production-backed Shopify provider runtime.

The Shopify pull capability is represented by a provider response fixture, and
the outbound event bus transport is captured at its boundary. The runtime
registry, scheduler, Bronze stores, Shopify normalizer, sync-run lifecycle,
evidence capture, and identity candidate adapter are the real implementations.

Tenant raw-rights admission is the single gate for this path. A record without
an allowed tenant grant is never retained and produces no normalized commerce
events or candidate-visible identity evidence; with an allowed grant the same
record is retained, normalized, and published.
"""

from __future__ import annotations

import pytest

import repositories.repos as repos
from config.settings import Environment, settings
from connectors.integrations.data_rights.models import DataRightsGrant, GrantStatus
from connectors.integrations.data_rights.service import data_rights_service
from repositories.lake import BronzeRepository
from repositories.repos import reset_in_memory_stores
from journeys.comms.sync_runs import SyncRunRepository, SyncRunService
from identity.identity.import_candidate_adapter import ImportIdentityCandidateAdapter
from identity.identity.repository import IdentityResolutionRepository
from identity.identity.source_identity_registry import SourceIdentityRegistry
from connectors.provider_runtime.connection import ProviderConnection, ProviderConnectionRepository
from connectors.provider_runtime.connector_graph_writer import ConnectorGraphWriter
from connectors.provider_runtime.errors import ProviderPullFailed
from connectors.provider_runtime.raw_store import RawProviderRecordStore
from connectors.provider_runtime.rights_admission import (
    PROVIDER_RAW_RIGHTS_METADATA_KEY,
)
from connectors.provider_runtime.registry import ProviderRegistry
from connectors.provider_runtime.scheduler import PullScheduler
from connectors.provider_runtime.tenant_route_repository import (
    RouteDecision,
    RouteScope,
    TenantRouteRepository,
    reset_tenant_route_local_stores,
)
from connectors.providers.shopify.plugin import ShopifyOrdersPlugin
from repositories.graph_mutation_ledger import (
    GraphMutationLedgerRepository,
    reset_graph_ledger_memory,
)
from shared.graph.graph import GraphClient, Vertex, VertexType
from shared.graph.mutation_gateway import GraphMutationGateway, MutationIntent
from shared.integration_contracts.lifecycle import ConnectionState
from shared.integration_contracts.events import ReadBatch, make_raw_record
from shared.integration_contracts.results import AdapterResult
from tenancy.rights_authority.resolver import effective_rights_resolver


class _PullFixture:
    """Provider response fixture at the remote API boundary."""

    async def fetch(self, context, *, cursor, limit=None):
        record = make_raw_record(
            provider_identity=context.provider_identity,
            provider_record_id="771",
            provider_record_type="order",
            tenant_id=context.tenant_id,
            connection_id=context.connection_id,
            account_id=context.account_id,
            payload={
                "id": 771,
                "name": "#771",
                "created_at": "2026-10-01T10:00:00Z",
                "updated_at": "2026-10-01T10:05:00Z",
                "financial_status": "paid",
                "currency": "USD",
                "subtotal_price": "24.50",
                "total_price": "24.50",
                "customer": {
                    "id": 991,
                    "email": "Customer@Example.com",
                    "phone": "+1 415 555 0771",
                },
                "line_items": [{
                    "id": 1,
                    "title": "Notebook",
                    "quantity": 1,
                    "price": "24.50",
                }],
            },
        )
        return AdapterResult.ok(ReadBatch(records=[record]))


@pytest.fixture(autouse=True)
def _isolated_stores():
    reset_in_memory_stores()
    reset_graph_ledger_memory()
    reset_tenant_route_local_stores()
    yield
    reset_in_memory_stores()
    reset_graph_ledger_memory()
    reset_tenant_route_local_stores()


class _CapturingBridge:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def ingest_events(self, tenant_id, events) -> int:
        self.events.extend(events)
        return len(events)


class _GoldenPlugin(ShopifyOrdersPlugin):
    """Keep the real Shopify normalizer while fixing remote API output."""

    def pull(self):
        return _PullFixture()


async def _scheduler(*, raw_store, bridge):
    plugin = _GoldenPlugin()
    identity = plugin.identity().key
    registry = ProviderRegistry(auto_install_legacy=False)
    assert registry.register(plugin, source="golden-path-test") == identity
    connection = ProviderConnection(
        connection_id="conn-golden",
        tenant_id="tenant-golden",
        provider_identity=identity,
        state=ConnectionState.CONNECTED,
        selected_accounts=["shop-golden"],
        config={},
    )
    connections = ProviderConnectionRepository()
    await connections.upsert(connection)

    async def no_op_meter(*_args):
        return None

    scheduler = PullScheduler(
        registry=registry,
        connections=connections,
        raw_store=raw_store,
        bridge=bridge,
        sync_runs=SyncRunService(),
        meters=no_op_meter,
    )
    return scheduler, connection, identity


@pytest.mark.asyncio
async def test_shopify_sync_without_tenant_rights_retains_and_promotes_nothing(monkeypatch):
    async def no_pool():
        return None

    monkeypatch.setattr(repos, "get_pool", no_pool)
    bridge = _CapturingBridge()
    scheduler, connection, identity = await _scheduler(
        raw_store=RawProviderRecordStore(), bridge=bridge,
    )

    with pytest.raises(ProviderPullFailed) as exc_info:
        await scheduler.run_sync(connection)

    assert exc_info.value.details["error_code"] == "provider_raw_persist_failed"
    assert exc_info.value.details["detail"] == "ProviderRawRightsDenied"
    assert bridge.events == []
    assert await BronzeRepository("provider_records").find_many(
        filters={"tenant_id": "tenant-golden"}, limit=20,
    ) == []
    assert await scheduler.cursors.get_cursor(
        "tenant-golden", "conn-golden", identity,
    ) is None

    run_rows = await SyncRunRepository().list_for_connector(
        "tenant-golden", "conn-golden", limit=10,
    )
    assert len(run_rows) == 1 and run_rows[0]["status"] == "failed"

    identity_repo = IdentityResolutionRepository()
    assert await SourceIdentityRegistry(identity_repo).find_existing_source_identity(
        "tenant-golden", "shopify:shop-golden:conn-golden", external_id="991",
    ) is None
    candidates = ImportIdentityCandidateAdapter(identity_repo)
    same_tenant = await candidates.evaluate(
        tenant_id="tenant-golden", claims={"email": "customer@example.com"},
    )
    assert same_tenant.outcome == "no_match"
    assert same_tenant.candidate_source_identity_ids == []


@pytest.mark.asyncio
async def test_shopify_sync_with_canonical_tenant_rights_retains_normalizes_and_publishes(
    monkeypatch,
):
    """Exercise the real resolver, grant service, raw store, and Shopify runtime.

    The only fixture is the provider's remote response and outbound bus edge.
    Rights evidence is minted and durably recorded by the same canonical
    EffectiveRightsResolver used by the production raw-store default.
    """
    monkeypatch.setattr(settings, "env", Environment.LOCAL)
    grant = DataRightsGrant(
        data_rights_grant_id="drg_golden",
        tenant_id="tenant-golden",
        source_id="provider-account:conn-golden:shop-golden",
        connector_id=ShopifyOrdersPlugin().identity().key,
        connector_class="tenant_byod_data",
        source_relationship="organization_system",
        data_category="customer",
        data_sensitivity="sensitive_pii",
        raw_data_owner="tenant",
        tenant_lake_allowed=True,
        tenant_graph_allowed=True,
        tenant_insights_allowed=True,
        legal_basis="contract",
        granted_by_user_id="tenant-admin",
        granted_at="2026-01-01T00:00:00+00:00",
        status=GrantStatus.ACTIVE,
        audit_event_id="audit-golden",
    )
    monkeypatch.setattr(
        data_rights_service._repository,
        "_local_grants",
        {grant.data_rights_grant_id: grant},
    )

    bridge = _CapturingBridge()
    scheduler, connection, identity = await _scheduler(
        raw_store=RawProviderRecordStore(repository=BronzeRepository("provider_records")),
        bridge=bridge,
    )

    result = await scheduler.run_sync(connection)

    assert result["status"] == "completed"
    run_rows = await SyncRunRepository().list_for_connector(
        "tenant-golden", "conn-golden", limit=10,
    )
    assert len(run_rows) == 1 and run_rows[0]["status"] == "completed"
    assert run_rows[0]["records_received"] == 1
    assert run_rows[0]["facts_written"] == len(bridge.events) >= 1
    raw_rows = await BronzeRepository("provider_records").find_many(
        filters={"tenant_id": "tenant-golden"}, limit=20,
    )
    assert len(raw_rows) == 1
    raw = raw_rows[0]["payload"]
    assert raw["provider_identity"] == identity
    assert raw["provider_record_id"] == "771"
    assert raw["tenant_id"] == "tenant-golden"
    assert raw["connection_id"] == "conn-golden"
    assert raw["account_id"] == "shop-golden"
    rights_evidence = raw["metadata"][PROVIDER_RAW_RIGHTS_METADATA_KEY]
    assert rights_evidence["source_grant_ref"] == grant.data_rights_grant_id
    assert rights_evidence["rights_decision_ref"].startswith("rdec_")
    from tenancy.rights_authority.repositories import rights_decision_repository

    decision = await rights_decision_repository.get_for_tenant(
        rights_evidence["rights_decision_ref"], tenant_id="tenant-golden",
    )
    assert decision is not None and decision["allowed"] is True
    assert decision["source_grant_refs"] == [grant.data_rights_grant_id]

    # This is a local adapter-contract composition, not evidence that the
    # production Shopify runtime is wired to a graph writer. The graph-use
    # decision is resolved separately from the raw-store tenant_lake decision.
    # The test-only mapping creates an order vertex and deliberately does not
    # infer or project customer identity from provider-supplied identifiers.
    event = bridge.events[0]
    graph_decision = await effective_rights_resolver.resolve(
        tenant="tenant-golden",
        source=rights_evidence["source_id"],
        artifact=str(event.event_id),
        actor="provider_runtime",
        requested_use="tenant_graph",
        purpose="provider_graph_projection",
        destination="tenant",
    )
    assert graph_decision.allowed is True
    assert graph_decision.tenant_id == "tenant-golden"
    assert graph_decision.source_grant_refs == [grant.data_rights_grant_id]

    # A graph write is governed by its own decision, never the raw tenant_lake one.
    assert graph_decision.decision_id != rights_evidence["rights_decision_ref"]
    assert rights_evidence["source_relationship"] == "organization_system"

    from tenancy.rights_authority.source_lineage import trace_source_authority

    trace = await trace_source_authority(graph_decision.decision_id, tenant_id="tenant-golden")
    assert trace is not None
    assert trace.source_relationship == "organization_system"
    assert trace.source_id == rights_evidence["source_id"]
    assert trace.source_grant_ref == rights_evidence["source_grant_ref"]

    # Route fields below are local test fixtures. Production route provisioning
    # remains an explicit integration/cutover decision.
    route_scope = RouteScope(
        tenant_id="tenant-golden",
        environment_id="local",
        managed_integration_id="mi-shopify-golden",
        provider_identity=identity,
        account_id="shop-golden",
        stream_id="orders",
        fact_family="commerce.order",
    )
    routes = TenantRouteRepository()
    await routes.create_legacy(
        route_scope,
        legacy_connection_ref=connection.connection_id,
        decision=RouteDecision(
            actor_ref="test:provider-graph-proof",
            decision_ref="test-route-decision-shopify-golden",
            reason="local provider graph adapter contract proof",
        ),
    )

    graph = GraphClient()
    ledger = GraphMutationLedgerRepository()
    writer = ConnectorGraphWriter(
        routes=routes,
        gateway=GraphMutationGateway(graph_client=graph, ledger=ledger),
    )
    order_id = str(event.data["order_id"])
    graph_vertex_id = f"tenant-golden:shopify:order:{order_id}"
    intent = MutationIntent(
        operation="node_created",
        tenant_id="tenant-golden",
        vertex=Vertex(
            vertex_type=VertexType.ORDER,
            vertex_id=graph_vertex_id,
            properties={
                "tenant_id": "tenant-golden",
                "source_event_id": str(event.event_id),
                "provider_identity": identity,
                "account_id": "shop-golden",
                "order_id": order_id,
            },
        ),
        actor_kind="system",
        actor_id="provider_runtime",
        subject_kind="commerce_order",
        subject_id=graph_vertex_id,
        source_event_id=str(event.event_id),
        idempotency_key=(
            f"tenant-golden:shopify:order:{order_id}:{event.event_id}"
        ),
        rights_decision_ref=graph_decision.decision_id,
    )
    outcome = await writer.apply(
        intent,
        scope=route_scope,
        writer="legacy",
        writer_generation=1,
        connection_ref=connection.connection_id,
    )

    assert outcome.applied is True
    assert outcome.ledger_recorded is True
    ledger_rows = await ledger.list_records("tenant-golden")
    assert len(ledger_rows) == 1
    assert ledger_rows[0]["rights_decision_ref"] == graph_decision.decision_id
    assert ledger_rows[0]["payload"]["rights_decision_ref"] == graph_decision.decision_id

    tenant_read = await graph.get_vertex_for_tenant("tenant-golden", graph_vertex_id)
    assert tenant_read is not None
    assert tenant_read.properties["tenant_id"] == "tenant-golden"
    assert await graph.get_vertex_for_tenant("tenant-other", graph_vertex_id) is None
    assert [
        row.vertex_id
        for row in await graph.get_vertices_for_tenant("tenant-golden", vertex_type=VertexType.ORDER)
    ] == [graph_vertex_id]
    assert await graph.get_vertices_for_tenant("tenant-other", vertex_type=VertexType.ORDER) == []
